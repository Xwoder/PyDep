"""升级候选解析。

「支持升级的版本」不能简单理解为「PyPI 上存在」，而要结合：
    PyPI 版本 -> Requires-Python -> 当前 Python -> 当前已安装版本 -> 预发布策略
最终给出当前环境下真正可安装的版本列表。
"""

from __future__ import annotations

from dataclasses import dataclass, field

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


def build_candidates(
    packages: list[InstalledPackage],
    infos: dict[str, PyPIInfo],
    python_version: str,
    *,
    allow_prerelease: bool = False,
    max_options: int | None = 15,
) -> list[UpgradeCandidate]:
    """为每个已安装包生成升级候选列表。

    过滤规则（按顺序）：
    1. Requires-Python 必须兼容当前解释器；
    2. 版本必须严格高于当前已安装版本；
    3. 默认过滤预发布版本（除非当前装的就是预发布版，或显式 --all）；
    4. 默认隐藏 yanked 版本（除非没有其它可选版本）。
    """
    candidates: list[UpgradeCandidate] = []
    for pkg in packages:
        info = infos.get(pkg.name)
        if info is None:
            candidates.append(UpgradeCandidate(package=pkg))
            continue

        installed = pkg.version
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

        visible = [o for o in options if not o.yanked] or options
        if max_options is not None:
            visible = visible[:max_options]

        candidates.append(UpgradeCandidate(package=pkg, info=info, options=visible))

    return candidates
