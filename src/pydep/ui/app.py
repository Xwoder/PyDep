"""Textual 应用：装配两级选择的完整流程。"""

from __future__ import annotations

from textual.app import App
from textual.binding import Binding

from ..environment import Environment
from ..resolver import UpgradeCandidate
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

VersionModal, ConfirmModal, MirrorModal {
    align: center middle;
}

#version-dialog, #confirm-dialog, #mirror-dialog {
    width: 62;
    height: auto;
    max-height: 80%;
    border: round $accent;
    background: $surface;
    padding: 1 2;
}

#version-list, #mirror-list {
    height: auto;
    max-height: 25;
}

#version-hint, #confirm-hint, #mirror-hint {
    margin-top: 1;
    color: $text-muted;
}

#confirm-warnings {
    margin-top: 1;
    color: $error;
}

#version-header, #mirror-header {
    margin-bottom: 1;
}
"""


class PydepApp(App[dict | None]):
    """pydep 主应用。

    退出时通过 exit() 返回 {execute, pins, mirror}：
    - execute=True 表示用户确认要在 CLI 中直接执行 pip install
    - pins 形如 ["numpy==2.2.2", "pandas==2.3.1"]
    - mirror 为本次升级临时选择的镜像源（{"name", "url"}）或 None
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
    ) -> None:
        super().__init__()
        self.candidates = candidates
        self.candidates_by_name = {c.package.name: c for c in candidates}
        self.env = env
        self.selected: dict[str, str] = {}
        # 本次升级临时选用的镜像源（不持久化）：{"name": ..., "url": ...}，None 表示官方源
        self.mirror: dict[str, str] | None = None
        self.sub_title = env.describe()

    def on_mount(self) -> None:
        self.push_screen(PackageListScreen(self.candidates, self.env))
