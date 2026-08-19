"""升级候选解析。

「支持升级的版本」不能简单理解为「PyPI 上存在」，而要结合：
    PyPI 版本 -> Requires-Python -> 当前 Python -> 当前已安装版本 -> 预发布策略
最终给出当前环境下真正可安装的版本列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name
from packaging.version import Version

from .packages import InstalledPackage, PyPIInfo
from .versions import parse


@dataclass
class UpgradeOption:
    """一个可升级到的候选版本。"""

    version: str
    requires_python: str | None = None
    yanked: bool = False


@dataclass
class UpgradeCandidate:
    """一个包在「当前环境」下的升级画像。"""

    package: InstalledPackage
    info: PyPIInfo | None = None
    options: list[UpgradeOption] = field(default_factory=list)

    @property
    def on_pypi(self) -> bool:
        return self.info is not None

    @property
    def latest(self) -> str | None:
        """PyPI 上的最新版本（不一定兼容当前环境）。"""
        return self.info.latest if self.info else None

    @property
    def upgradable(self) -> bool:
        return len(self.options) > 0

    def find(self, version: str) -> UpgradeOption | None:
        for opt in self.options:
            if opt.version == version:
                return opt
        return None


def _release_requires_python(info: PyPIInfo, version: str) -> str | None:
    for f in info.releases.get(version) or []:
        rp = f.get("requires_python")
        if rp:
            return rp
    return None


def _release_yanked(info: PyPIInfo, version: str) -> bool:
    return any(f.get("yanked") for f in info.releases.get(version) or [])


def _compatible_with_cached(
    requires_python: str | None,
    python_version: str,
    cache: dict[str, SpecifierSet],
) -> bool:
    """等价于 versions.compatible_with_python，但按声明字符串缓存 SpecifierSet。"""
    if not requires_python:
        return True
    spec = cache.get(requires_python)
    if spec is None:
        try:
            spec = SpecifierSet(requires_python)
        except Exception:
            # 无法解析的声明按「未知」处理，不过滤
            return True
        cache[requires_python] = spec
    try:
        return python_version in spec
    except Exception:
        return True


def _build_options(
    info: PyPIInfo,
    installed: str | None,
    python_version: str,
    *,
    allow_prerelease: bool = False,
    max_options: int | None = 15,
) -> list[UpgradeOption]:
    """按「当前已安装版本」为一个包计算候选版本列表。

    过滤规则（按顺序）：
    1. Requires-Python 必须兼容当前解释器；
    2. 版本必须严格高于当前已安装版本；
    3. 默认过滤预发布版本（除非当前装的就是预发布版，或显式放行）；
    4. yanked 版本保留但排在列表末尾（供 UI 标记提示，截断时优先保留非 yanked）。
    """
    # 一次性解析所有版本与当前已装版本，避免循环内重复构建 Version 对象
    installed_v = parse(installed) if installed else None
    installed_pre = installed_v.is_prerelease if installed_v else False

    parsed: list[tuple[Version, str]] = []
    for version in info.versions():
        v = parse(version)
        if v is not None:
            parsed.append((v, version))
    parsed.sort(key=lambda item: item[0], reverse=True)

    # 同一声明字符串只解析一次 Requires-Python
    rp_specs: dict[str, SpecifierSet] = {}

    options: list[UpgradeOption] = []
    for v, version in parsed:
        requires_python = _release_requires_python(info, version)
        if not _compatible_with_cached(requires_python, python_version, rp_specs):
            continue
        # 未安装的包（version 为 None）所有版本都是候选
        if installed_v is not None and v <= installed_v:
            continue
        if v.is_prerelease and not installed_pre and not allow_prerelease:
            continue
        options.append(
            UpgradeOption(
                version=version,
                requires_python=requires_python,
                yanked=_release_yanked(info, version),
            )
        )

    # 稳定排序：非 yanked 版本保持在前面（仍从新到旧），yanked 版本统一排到末尾
    options.sort(key=lambda o: o.yanked)
    if max_options is not None:
        options = options[:max_options]
    return options


def build_candidates(
    packages: list[InstalledPackage],
    infos: dict[str, PyPIInfo],
    python_version: str,
    *,
    allow_prerelease: bool = False,
    max_options: int | None = 15,
) -> list[UpgradeCandidate]:
    """为每个已安装包生成升级候选列表。"""
    candidates: list[UpgradeCandidate] = []
    for pkg in packages:
        info = infos.get(pkg.name)
        if info is None:
            candidates.append(UpgradeCandidate(package=pkg))
            continue
        options = _build_options(
            info,
            pkg.version,
            python_version,
            allow_prerelease=allow_prerelease,
            max_options=max_options,
        )
        candidates.append(UpgradeCandidate(package=pkg, info=info, options=options))
    return candidates


def refresh_candidate_options(
    candidates: list[UpgradeCandidate],
    python_version: str,
    *,
    allow_prerelease: bool = False,
    max_options: int | None = 15,
) -> None:
    """安装完成后按每个包「新的已安装版本」重新计算候选列表。

    已安装到的版本不再严格高于当前版本，会被过滤掉，
    因此 `upgradable`（len(options) > 0）随之自动变为正确状态。
    """
    for cand in candidates:
        if cand.info is None:
            continue
        cand.options = _build_options(
            cand.info,
            cand.package.version,
            python_version,
            allow_prerelease=allow_prerelease,
            max_options=max_options,
        )


@dataclass(frozen=True)
class ReverseDepConstraint:
    """一个已安装包对某个目标包声明的版本约束（预解析结果）。"""

    pkg_name: str
    pkg_version: str | None
    spec: str
    # None 表示无版本限制，不构成约束
    specifier: SpecifierSet | None


def build_reverse_dep_index(
    installed: list[InstalledPackage],
) -> dict[str, list[ReverseDepConstraint]]:
    """一次性解析所有已安装包的依赖约束，按键为规范化的目标包名索引。

    对同一批包检查多个候选版本时（如版本弹窗），预建索引可避免
    每个版本都重复遍历安装包并重新解析 Requirement。
    """
    index: dict[str, list[ReverseDepConstraint]] = {}
    for pkg in installed:
        for spec in pkg.requires or []:
            try:
                req = Requirement(spec)
            except InvalidRequirement:
                continue
            # 忽略目标包对自身的依赖声明（不自构成反向依赖）
            if canonicalize_name(pkg.name) == canonicalize_name(req.name):
                continue
            index.setdefault(canonicalize_name(req.name), []).append(
                ReverseDepConstraint(
                    pkg_name=pkg.name,
                    pkg_version=pkg.version,
                    spec=spec,
                    specifier=req.specifier if req.specifier else None,
                )
            )
    return index


def check_reverse_dep_conflicts_index(
    index: dict[str, list[ReverseDepConstraint]],
    target_name: str,
    new_version: str,
) -> list[str]:
    """基于预建索引检查把 target_name 升级到 new_version 的依赖冲突。

    返回冲突描述列表，空列表表示无冲突。
    """
    target = canonicalize_name(target_name)
    conflicts: list[str] = []
    for c in index.get(target, []):
        # specifier 为空表示不限版本，不构成约束
        if c.specifier and not c.specifier.contains(new_version, prereleases=True):
            conflicts.append(
                f"{c.pkg_name} {c.pkg_version} 要求 {c.spec}，"
                f"但 {target_name}=={new_version} 不满足"
            )
    return conflicts


def check_reverse_dep_conflicts(
    installed: list[InstalledPackage],
    target_name: str,
    new_version: str,
) -> list[str]:
    """检查把 target_name 升级到 new_version 是否会破坏其它已安装包的依赖约束。

    通过其它已安装包的 Requires-Dist 元数据（即它们的正向依赖）反向匹配目标包，
    用 SpecifierSet 校验新版本是否满足约束。返回冲突描述列表，空列表表示无冲突。

    注意：仅能发现「已安装包声明的直接版本约束」。pip 在 pip install 时本身
    也不做这种保护（pip 的已知行为），因此本检查是对用户的超前提醒。
    """
    return check_reverse_dep_conflicts_index(
        build_reverse_dep_index(installed), target_name, new_version
    )
