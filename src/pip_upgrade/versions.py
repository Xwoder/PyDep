"""版本解析与过滤（基于 packaging，遵循 PEP 440）。

永远不要手写 "2.10" > "2.9" 这类字符串比较，
Python 包版本还涉及 1.0rc1 / 1.0.post1 / 1.0.dev1 等形态。
"""

from __future__ import annotations

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion, Version


def parse(version: str) -> Version | None:
    """解析版本；非法版本返回 None 而不是抛异常。"""
    try:
        return Version(version)
    except InvalidVersion:
        return None


def sort_versions(versions: list[str], reverse: bool = True) -> list[str]:
    """按 PEP 440 语义对版本列表排序（默认从新到旧）。"""
    parsed: list[tuple[Version, str]] = []
    for raw in versions:
        v = parse(raw)
        if v is not None:
            parsed.append((v, raw))
    parsed.sort(key=lambda item: item[0], reverse=reverse)
    return [raw for _, raw in parsed]


def is_prerelease(version: str) -> bool:
    v = parse(version)
    return bool(v and v.is_prerelease)


def version_gt(a: str, b: str) -> bool:
    """a 是否严格大于 b（语义版本比较）。"""
    va, vb = parse(a), parse(b)
    if va is None or vb is None:
        return False
    return va > vb


def compatible_with_python(requires_python: str | None, python_version: str) -> bool:
    """判断某个版本声明的 Requires-Python 是否兼容当前解释器。

    例如 requires_python=">=3.11"，当前 python_version="3.10" 时返回 False。
    """
    if not requires_python:
        return True
    try:
        spec = SpecifierSet(requires_python)
    except Exception:
        # 无法解析的声明按「未知」处理，不过滤
        return True
    try:
        return python_version in spec
    except Exception:
        return True
