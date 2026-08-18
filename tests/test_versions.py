"""versions 模块的单元测试。"""

from pip_upgrade.versions import (
    compatible_with_python,
    is_prerelease,
    sort_versions,
    version_gt,
)


def test_sort_versions_follows_pep440():
    # 2.0a1 是 2.0 的预发布，仍大于所有 1.x
    versions = ["2.10", "2.9", "1.0rc1", "2.0a1", "1.0.post1"]
    assert sort_versions(versions) == ["2.10", "2.9", "2.0a1", "1.0.post1", "1.0rc1"]


def test_sort_versions_ignores_invalid():
    versions = ["2.0", "not-a-version", "1.0"]
    assert sort_versions(versions) == ["2.0", "1.0"]


def test_is_prerelease():
    assert is_prerelease("2.0rc1")
    assert is_prerelease("2.0b1")
    assert is_prerelease("2.0.dev1")
    assert not is_prerelease("2.0.1")
    assert not is_prerelease("garbage")  # 解析失败按非预发布处理


def test_version_gt():
    assert version_gt("2.10", "2.9")
    assert version_gt("1.0.post1", "1.0")
    assert not version_gt("1.0", "1.0")
    assert not version_gt("1.0", "garbage")


def test_compatible_with_python():
    assert compatible_with_python(None, "3.10")
    assert compatible_with_python(">=3.8", "3.10")
    assert not compatible_with_python(">=3.11", "3.10")
    assert compatible_with_python("", "3.10")
    assert compatible_with_python(">=3.11,<4", "3.12")
    # 无法解析的声明不拦截
    assert compatible_with_python("~~~~", "3.10")
