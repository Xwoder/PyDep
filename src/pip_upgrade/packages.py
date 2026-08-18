"""包信息获取：当前环境已安装的包 + PyPI 上的可用版本。

本地信息来自 importlib.metadata（而非解析 pip 命令输出）；
远程信息来自 PyPI JSON API。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Callable

import httpx

try:
    from packaging.requirements import InvalidRequirement, Requirement
except ImportError:  # pragma: no cover - packaging 是硬依赖，此处仅为类型安全
    Requirement = None  # type: ignore[assignment]
    InvalidRequirement = ValueError  # type: ignore[assignment,misc]

PYPI_JSON_URL = "https://pypi.org/pypi/{name}/json"

# 由 pip 自身管理、一般不建议在工具里主动升级的包
SKIP_NAMES = {"pip", "setuptools", "wheel", "distribute"}


@dataclass
class InstalledPackage:
    """环境中已安装（或声明）的一个包。

    version 为 None 表示「未安装但被项目依赖文件声明」，此时所有 PyPI 版本都是候选。
    """

    name: str
    version: str | None
    summary: str = ""
    # 该包声明的所有依赖条目（Requires-Dist，形如 "websockets<16,>=14"）
    requires: list[str] = field(default_factory=list)


@dataclass
class PyPIInfo:
    """从 PyPI JSON API 拉取到的包信息。"""

    name: str
    latest: str | None
    releases: dict[str, list[dict]] = field(default_factory=dict)

    def versions(self) -> list[str]:
        return list(self.releases.keys())


def list_installed(skip: set[str] | None = None) -> list[InstalledPackage]:
    """列出当前环境中已安装的包（按名称排序）。"""
    skip = skip or SKIP_NAMES
    packages: list[InstalledPackage] = []
    for dist in metadata.distributions():
        name = _normalize_name(dist.metadata.get("Name") or "")
        if not name or name in skip:
            continue
        packages.append(
            InstalledPackage(
                name=name,
                version=dist.version,
                summary=(dist.metadata.get("Summary") or "").strip(),
                requires=list(dist.requires or []),
            )
        )
    packages.sort(key=lambda p: p.name)
    return packages


def default_cache_dir() -> Path:
    """PyPI 结果缓存目录（磁盘缓存，避免每次重复下载大 JSON）。"""
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        root = Path(base)
    elif sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path.home() / ".cache"
    return root / "pip-upgrade" / "pypi"


def _info_from_payload(name: str, data: dict) -> PyPIInfo:
    info = data.get("info") or {}
    releases_raw = data.get("releases") or {}
    releases: dict[str, list[dict]] = {}
    for ver, files in releases_raw.items():
        cleaned = []
        for f in files or []:
            cleaned.append(
                {
                    "requires_python": f.get("requires_python"),
                    "yanked": bool(f.get("yanked", False)),
                }
            )
        releases[ver] = cleaned
    return PyPIInfo(
        name=name,
        latest=(info.get("version") or None),
        releases=releases,
    )


def _cache_path(cache_dir: Path, name: str) -> Path:
    return cache_dir / f"{name}.json"


def _cache_read(cache_dir: Path, name: str, ttl: float) -> tuple[PyPIInfo | None, bool]:
    """读取缓存，返回 (info, fresh)。fresh=False 表示缓存过期（网络失败时可兜底）。"""
    try:
        path = _cache_path(cache_dir, name)
        if not path.is_file():
            return None, False
        age = time.time() - path.stat().st_mtime
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        info = PyPIInfo(
            name=name,
            latest=data.get("latest"),
            releases=data.get("releases") or {},
        )
        return info, age <= ttl
    except (OSError, ValueError, TypeError):
        return None, False


def _cache_write(cache_dir: Path, name: str, info: PyPIInfo) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        with open(_cache_path(cache_dir, name), "w", encoding="utf-8") as f:
            json.dump({"latest": info.latest, "releases": info.releases}, f)
    except OSError:
        pass


async def _get_json(client: httpx.AsyncClient, url: str) -> dict | None:
    """GET + 解析 JSON，带一次重试；网络错误返回 None。"""
    for _ in range(2):
        try:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            return None  # 404 等确定性错误不重试
        except httpx.HTTPError:
            continue
    return None


async def fetch_pypi_info(
    name: str,
    client: httpx.AsyncClient,
    *,
    use_cache: bool = True,
    ttl: float = 86400.0,
    cache_dir: Path | None = None,
) -> tuple[PyPIInfo | None, str]:
    """拉取单个包的 PyPI 信息。

    返回 (info, status)，status 为：
    - "cache"   缓存命中（TTL 内），未联网
    - "network" 从 PyPI 实时获取成功
    - "stale"   网络失败，用过期缓存兜底（数据可能过时）
    - "missing" 包不存在或获取失败且无缓存
    """
    cache_dir = cache_dir or default_cache_dir()
    cached, fresh = (None, False)
    if use_cache:
        cached, fresh = _cache_read(cache_dir, name, ttl)
        if fresh and cached is not None:
            return cached, "cache"

    data = await _get_json(client, PYPI_JSON_URL.format(name=name))
    if data is not None:
        info = _info_from_payload(name, data)
        if use_cache:
            _cache_write(cache_dir, name, info)
        return info, "network"

    if use_cache and cached is not None:
        return cached, "stale"
    return None, "missing"


async def fetch_pypi_info_many(
    names: list[str],
    concurrency: int = 24,
    *,
    use_cache: bool = True,
    ttl: float = 86400.0,
    cache_dir: Path | None = None,
    on_progress: Callable[[str, str], None] | None = None,
    timeout: float | None = None,
) -> dict[str, PyPIInfo]:
    """并发拉取多个包的 PyPI 信息。

    on_progress(name, status) 在每完成一个包时被调用（status 见 fetch_pypi_info；
    整体超时时未完成的包会以 status="timeout" 回调一次）。
    timeout 为整体超时秒数；超时后取消剩余任务，但已完成的（含缓存命中）结果
    仍保留在返回值中，不会整体丢弃。
    """
    http_timeout = httpx.Timeout(30.0, connect=8.0)
    async with httpx.AsyncClient(follow_redirects=True, timeout=http_timeout) as client:
        semaphore = asyncio.Semaphore(concurrency)

        async def one(name: str) -> tuple[str, PyPIInfo | None]:
            async with semaphore:
                info, status = await fetch_pypi_info(
                    name,
                    client,
                    use_cache=use_cache,
                    ttl=ttl,
                    cache_dir=cache_dir,
                )
                if on_progress is not None:
                    on_progress(name, status)
                return name, info

        tasks = [asyncio.create_task(one(n)) for n in names]
        name_by_task = dict(zip(tasks, names))
        done, pending = await asyncio.wait(tasks, timeout=timeout)

        results: list[tuple[str, PyPIInfo | None]] = []
        for t in done:
            try:
                results.append(t.result())
            except BaseException:
                pass

        if pending:
            # 整体超时：取消未完成任务，并报告为 timeout（进度条仍能走完）
            for t in pending:
                t.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if on_progress is not None:
                for t in pending:
                    on_progress(name_by_task[t], "timeout")
    return {name: info for name, info in results if info is not None}


# ---- 依赖文件解析（检查其它项目用） ----

# 让目标解释器枚举自身环境与已安装包的脚本
PROBE_SCRIPT = """
import json, platform, sys
from importlib import metadata

skip = {"pip", "setuptools", "wheel", "distribute"}
packages = []
for dist in metadata.distributions():
    name = (dist.metadata.get("Name") or "").strip().lower().replace("_", "-")
    if not name or name in skip:
        continue
    packages.append({
        "name": name,
        "version": dist.version,
        "summary": (dist.metadata.get("Summary") or "").strip(),
        "requires": dist.requires or [],
    })
packages.sort(key=lambda p: p["name"])
print(json.dumps({
    "python_version": platform.python_version(),
    "python_executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": getattr(sys, "base_prefix", sys.prefix),
    "packages": packages,
}))
"""


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _spec_names(specs: list[str]) -> list[str]:
    """从 PEP 508 依赖条目列表提取规范化包名。"""
    names: list[str] = []
    for spec in specs:
        if not spec:
            continue
        try:
            names.append(_normalize_name(Requirement(spec).name))
        except (InvalidRequirement, TypeError):
            continue
    return names


def parse_requirements_file(path: str | Path) -> list[str]:
    """解析 requirements.txt，返回包名列表。

    支持 -r/--requirement/-c/--constraint 递归引用（相对路径基于所在文件），
    跳过注释、空行及其它 pip 选项行；无法解析的行（如直接 URL）被忽略。
    """
    seen: set[str] = set()
    stack = [Path(path)]
    while stack:
        cur = stack.pop()
        try:
            lines = cur.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            included: str | None = None
            for prefix in ("-r", "--requirement", "-c", "--constraint"):
                if line == prefix:
                    included = ""
                    break
                if line.startswith(prefix + " "):
                    included = line[len(prefix) :].strip()
                    break
                if line.startswith(prefix + "="):
                    included = line[len(prefix) + 1 :].strip()
                    break
            if included is not None:
                ref = Path(included)
                if not ref.is_absolute():
                    ref = cur.parent / ref
                stack.append(ref)
                continue

            if line.startswith("-") or line.startswith("--"):
                continue

            try:
                name = _normalize_name(Requirement(line.split(None, 1)[0]).name)
            except (InvalidRequirement, TypeError):
                continue
            if name not in seen:
                seen.add(name)
    return sorted(seen)


def parse_pyproject(path: str | Path) -> list[str]:
    """解析 pyproject.toml 的 [project] 依赖（含所有 optional-dependencies extras）。"""
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10 fallback
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            raise RuntimeError("解析 pyproject.toml 需要 Python 3.11+ 或安装 tomli") from None

    with open(path, "rb") as f:
        data = tomllib.load(f)
    project = data.get("project") or {}
    specs: list[str] = list(project.get("dependencies") or [])
    for extra in (project.get("optional-dependencies") or {}).values():
        specs.extend(extra)
    return sorted(set(_spec_names(specs)))


def parse_dependency_file(path: str | Path) -> list[str]:
    """按文件类型自动识别 requirements.txt / pyproject.toml 并返回包名列表。"""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"依赖文件不存在: {p}")
    if p.suffix == ".toml" or p.name == "pyproject.toml":
        return parse_pyproject(p)
    return parse_requirements_file(p)
