"""升级候选解析。

「支持升级的版本」不能简单理解为「PyPI 上存在」，而要结合：
    PyPI 版本 -> Requires-Python -> 当前 Python -> 当前已安装版本 -> 预发布策略
最终给出当前环境下真正可安装的版本列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from .packages import InstalledPackage, PyPIInfo
from .versions import compatible_with_python, is_prerelease, sort_versions, version_gt


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
    installed_pre = is_prerelease(installed) if installed else False

    options: list[UpgradeOption] = []
    for version in sort_versions(info.versions()):
        requires_python = _release_requires_python(info, version)
        if not compatible_with_python(requires_python, python_version):
            continue
        # 未安装的包（version 为 None）所有版本都是候选
        if installed is not None and not version_gt(version, installed):
            continue
        if is_prerelease(version) and not installed_pre and not allow_prerelease:
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
    conflicts: list[str] = []
    target = canonicalize_name(target_name)
    for pkg in installed:
        if canonicalize_name(pkg.name) == target:
            continue
        for spec in pkg.requires or []:
            try:
                req = Requirement(spec)
            except InvalidRequirement:
                continue
            if canonicalize_name(req.name) != target:
                continue
            # specifier 为空表示不限版本，不构成约束
            if req.specifier and not req.specifier.contains(
                new_version, prereleases=True
            ):
                conflicts.append(
                    f"{pkg.name} {pkg.version} 要求 {spec}，"
                    f"但 {target_name}=={new_version} 不满足"
                )
    return conflicts
