"""PyPI 查询缓存与超时/重试逻辑测试（用假客户端，不联网）。"""

import asyncio

import httpx
import pytest

from pydep.packages import (
    PyPIInfo,
    clear_cache,
    fetch_pypi_info,
    fetch_pypi_info_many,
)


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    @property
    def status_code(self):
        return 200 if self._payload is not None else 404

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def make_payload(latest: str) -> dict:
    return {
        "info": {"version": latest},
        "releases": {
            "1.0.0": [{"requires_python": ">=3.8", "yanked": False}],
            latest: [{"requires_python": None, "yanked": False}],
        },
    }


class FakeClient:
    def __init__(self, payload=None, fail=False):
        self.payload = payload
        self.fail = fail
        self.calls = 0

    async def get(self, url):  # noqa: ARG002
        self.calls += 1
        if self.fail:
            raise httpx.ConnectError("network down")
        return FakeResponse(self.payload)


def test_clear_cache_removes_files(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.json").write_text("{}")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "keep.txt").write_text("x")

    assert clear_cache(tmp_path) == 2
    assert not (tmp_path / "a.json").exists()
    assert not (tmp_path / "b.json").exists()
    assert (sub / "keep.txt").exists()  # 子目录不动


def test_clear_cache_missing_dir_is_noop(tmp_path):
    assert clear_cache(tmp_path / "nope") == 0


def test_clear_cache_then_network_again(tmp_path):
    """清空后再次查询会走网络（cache 状态重新变成 network）。"""
    import pydep.packages as pkg

    client = FakeClient(payload=make_payload("2.0.0"))

    async def fake_fetch(name, _client, **kwargs):  # noqa: ANN202
        return await fetch_pypi_info(name, client, **kwargs)

    original = pkg.fetch_pypi_info
    pkg.fetch_pypi_info = fake_fetch  # type: ignore[assignment]
    try:
        assert asyncio.run(
            fetch_pypi_info_many(["demo"], cache_dir=tmp_path)
        )["demo"].latest == "2.0.0"
        clear_cache(tmp_path)
        assert asyncio.run(
            fetch_pypi_info_many(["demo"], cache_dir=tmp_path)
        )["demo"].latest == "2.0.0"
    finally:
        pkg.fetch_pypi_info = original  # type: ignore[assignment]

    assert client.calls == 2  # 清空缓存后重新联网


@pytest.mark.asyncio
async def test_first_fetch_network_then_cache_hit(tmp_path):
    client = FakeClient(payload=make_payload("2.0.0"))
    info, status = await fetch_pypi_info(
        "demo", client, cache_dir=tmp_path, ttl=86400.0
    )
    assert status == "network"
    assert info is not None and info.latest == "2.0.0"

    # 第二次：命中缓存，不再发请求
    info2, status2 = await fetch_pypi_info(
        "demo", client, cache_dir=tmp_path, ttl=86400.0
    )
    assert status2 == "cache"
    assert client.calls == 1  # 只发了一次网络请求


@pytest.mark.asyncio
async def test_stale_cache_fallback_on_network_error(tmp_path):
    client = FakeClient(payload=make_payload("2.0.0"))
    await fetch_pypi_info("demo", client, cache_dir=tmp_path, ttl=86400.0)

    # 缓存过期 + 网络挂掉 -> 用过期缓存兜底
    client.fail = True
    client.payload = None
    info, status = await fetch_pypi_info("demo", client, cache_dir=tmp_path, ttl=0.0)
    assert status == "stale"
    assert info is not None and info.latest == "2.0.0"


@pytest.mark.asyncio
async def test_missing_without_cache(tmp_path):
    client = FakeClient(payload=None)  # 404
    info, status = await fetch_pypi_info("nonexistent", client, cache_dir=tmp_path)
    assert status == "missing"
    assert info is None


@pytest.mark.asyncio
async def test_retries_then_stale(tmp_path):
    # 连续失败两次 -> missing（有缓存时 stale）
    client = FakeClient(payload=make_payload("1.0.0"))
    await fetch_pypi_info("demo", client, cache_dir=tmp_path, ttl=86400.0)

    client.fail = True
    info, status = await fetch_pypi_info("demo", client, cache_dir=tmp_path, ttl=0.0)
    assert status == "stale"
    assert client.calls >= 3  # 首次成功(1) + 本次重试(2)


@pytest.mark.asyncio
async def test_many_progress_and_collection(tmp_path):
    payloads = {n: make_payload(f"{i}.0.0") for i, n in enumerate(["a", "b", "c"])}

    class MultiClient:
        def __init__(self):
            self.calls = 0

        async def get(self, url):
            self.calls += 1
            name = url.rsplit("/", 2)[-2]
            return FakeResponse(payloads[name])

    client = MultiClient()
    # fetch_pypi_info_many 内部自建 client，因此这里测试缓存写入路径
    seen: list[tuple[str, str]] = []

    async def fake_fetch(name, _client, **kwargs):  # noqa: ANN202
        return await fetch_pypi_info(name, client, **kwargs)

    import pydep.packages as pkg

    original = pkg.fetch_pypi_info
    pkg.fetch_pypi_info = fake_fetch  # type: ignore[assignment]
    try:
        infos = await fetch_pypi_info_many(
            ["a", "b", "c"],
            concurrency=3,
            cache_dir=tmp_path,
            on_progress=lambda n, s: seen.append((n, s)),
        )
    finally:
        pkg.fetch_pypi_info = original  # type: ignore[assignment]

    assert set(infos) == {"a", "b", "c"}
    assert len(seen) == 3
    assert all(status == "network" for _, status in seen)


@pytest.mark.asyncio
async def test_many_timeout_keeps_partial_results():
    """整体超时：已完成的保留，未完成的以 timeout 报告，不抛异常、不整体丢弃。"""
    import pydep.packages as pkg

    async def mixed_fetch(name, _client, **kwargs):  # noqa: ANN202
        if name == "fast":
            return PyPIInfo(name="fast", latest="2.0.0"), "network"
        await asyncio.sleep(30)  # 模拟卡住的请求
        return None, "network"

    original = pkg.fetch_pypi_info
    pkg.fetch_pypi_info = mixed_fetch  # type: ignore[assignment]
    seen: list[tuple[str, str]] = []
    try:
        infos = await fetch_pypi_info_many(
            ["fast", "slow"],
            concurrency=2,
            timeout=0.2,
            on_progress=lambda n, s: seen.append((n, s)),
        )
    finally:
        pkg.fetch_pypi_info = original  # type: ignore[assignment]

    assert set(infos) == {"fast"}  # 部分结果未丢失
    assert ("fast", "network") in seen
    assert ("slow", "timeout") in seen
    assert len(seen) == 2  # 进度条能走完


@pytest.mark.asyncio
async def test_many_no_timeout_when_absent():
    """未传 timeout 时行为与 gather 一致：等待全部完成。"""
    import pydep.packages as pkg

    async def quick_fetch(name, _client, **kwargs):  # noqa: ANN202
        return PyPIInfo(name=name, latest="1.0.0"), "network"

    original = pkg.fetch_pypi_info
    pkg.fetch_pypi_info = quick_fetch  # type: ignore[assignment]
    try:
        infos = await fetch_pypi_info_many(["a", "b", "c"], concurrency=3)
    finally:
        pkg.fetch_pypi_info = original  # type: ignore[assignment]

    assert set(infos) == {"a", "b", "c"}
