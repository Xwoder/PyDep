"""Textual 应用：装配两级选择的完整流程。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from textual.app import App
from textual.binding import Binding

from ..environment import Environment, probe_interpreter
from ..resolver import UpgradeCandidate, refresh_candidate_options
from .install import InstallScreen
from .package_list import PackageListScreen

CSS = """
Screen {
    layout: vertical;
}

Header {
    dock: top;
}

Footer {
    dock: bottom;
}

#env-info {
    height: auto;
    margin: 1 2 0 2;
    color: $text-muted;
}

#hint {
    height: auto;
    margin: 0 2;
    color: $text-muted;
}

#package-table {
    height: 1fr;
    margin: 1 2;
    border: round $primary;
    padding: 0 1;
}

#bottom {
    height: auto;
    margin: 0 2 1 2;
}

#summary, #command {
    width: 1fr;
    height: auto;
    border: round $secondary;
    padding: 0 1;
}

#summary {
    margin-right: 1;
}

VersionModal, ConfirmModal, MirrorModal, InstallModeModal {
    align: center middle;
}

#version-dialog, #confirm-dialog, #mirror-dialog, #install-mode-dialog {
    width: 62;
    height: auto;
    max-height: 80%;
    border: round $accent;
    background: $surface;
    padding: 1 2;
}

#version-list, #mirror-list, #install-mode-list {
    height: auto;
    max-height: 25;
}

#version-hint, #confirm-hint, #mirror-hint, #install-mode-hint {
    margin-top: 1;
    color: $text-muted;
}

#confirm-warnings {
    margin-top: 1;
    color: $error;
}

#version-header, #mirror-header, #install-mode-header {
    margin-bottom: 1;
}
"""


@dataclass
class UpgradeRecord:
    """一次升级会话中的包记录，用于退出 TUI 后打印摘要。"""

    name: str
    old_version: str | None
    new_version: str
    # "done" = 已执行安装成功；"selected" = 仅勾选未执行
    status: str = "selected"


class PydepApp(App[list[UpgradeRecord]]):
    """pydep 主应用。

    安装（包列表按 e -> 确认 Y）在应用内部直接完成：push 到 InstallScreen
    运行 pip install，无需退出 TUI；安装成功后自动刷新包列表的当前版本。
    """

    CSS = CSS
    TITLE = "pydep"
    BINDINGS = [
        Binding("q", "quit", "退出", show=False),
        Binding("ctrl+c", "quit", "退出", show=False),
    ]

    def __init__(
        self,
        candidates: list[UpgradeCandidate],
        env: Environment,
        *,
        allow_prerelease: bool = False,
        max_options: int | None = 15,
    ) -> None:
        super().__init__()
        self.candidates = candidates
        self.candidates_by_name = {c.package.name: c for c in candidates}
        self.env = env
        self.selected: dict[str, str] = {}
        # 本次升级临时选用的镜像源（不持久化）：{"name": ..., "url": ...}，None 表示官方源
        self.mirror: dict[str, str] | None = None
        # uv 管理环境的安装模式："pip"（uv pip install，默认）/ "add"（uv add，写入依赖清单）
        self.install_mode = "pip"
        self.sub_title = env.describe()
        # 与 CLI 阶段 build_candidates 一致的候选策略，用于安装后重算
        self._allow_prerelease = allow_prerelease
        self._max_options = max_options
        # 是否有 pip 安装正在后台进行（进行中禁止再次触发安装）
        self.installing = False
        # 安装成功后版本数据已刷新，等待返回包列表时重建界面
        self._pending_refresh = False
        # 本次会话的升级记录（name -> 记录），退出 TUI 后由 CLI 打印摘要
        self.upgrade_records: dict[str, UpgradeRecord] = {}

    def action_quit(self) -> None:
        """按 q / Ctrl+C 退出：返回本次会话的升级摘要供 CLI 打印。"""
        records = [self.upgrade_records[name] for name in sorted(self.upgrade_records)]
        self.exit(records)

    # ---- 升级记录 ----

    def record_selection(self, name: str, new_version: str) -> None:
        """勾选或修改目标版本时记录升级信息（old 为当前环境已装版本）。"""
        cand = self.candidates_by_name[name]
        self.upgrade_records[name] = UpgradeRecord(
            name=name,
            old_version=cand.package.version,
            new_version=new_version,
            status="selected",
        )

    def remove_record(self, name: str) -> None:
        """取消勾选时移除对应升级记录。"""
        self.upgrade_records.pop(name, None)

    def mark_installed(self, names: Iterable[str]) -> None:
        """安装命令成功返回后，将本次执行安装的包标记为已升级。"""
        for name in names:
            record = self.upgrade_records.get(name)
            if record is not None:
                record.status = "done"

    def on_mount(self) -> None:
        self.push_screen(PackageListScreen(self.candidates, self.env))

    # ---- 安装与刷新 ----

    def run_install(self, pins: list[str]) -> None:
        """在 TUI 内部执行安装：push 安装屏幕，不退出应用。"""
        self.installing = True
        self.push_screen(InstallScreen(self.env, pins, self.mirror, self.install_mode))

    def refresh_versions(self) -> None:
        """安装成功后重新探测该环境，刷新包列表中的当前版本。"""
        self.run_worker(self._refresh_versions(), exclusive=False)

    async def _refresh_versions(self) -> None:
        try:
            probe = probe_interpreter(self.env.python_executable)
        except (OSError, RuntimeError) as exc:
            self.notify(f"安装完成，但刷新版本信息失败：{exc}", severity="warning")
            return
        versions = {p.name: p.version for p in probe.packages}
        for cand in self.candidates:
            if cand.package.name in versions:
                cand.package.version = versions[cand.package.name]
        # 按新的已安装版本重算候选列表：已装到的版本不再显示为可升级
        refresh_candidate_options(
            self.candidates,
            self.env.python_version_short,
            allow_prerelease=self._allow_prerelease,
            max_options=self._max_options,
        )
        self.selected.clear()
        self._pending_refresh = True
        # 若已返回包列表则立即重建界面；否则等 on_screen_resume 触发
        if isinstance(self.screen, PackageListScreen):
            self.screen.refresh_after_install()
        self.notify("安装完成，包列表已刷新")
