"""安装模式选择弹窗：仅对 uv 管理环境有意义（普通环境固定为 python -m pip）。"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

#: uv 环境可选的安装模式："pip" = uv pip install；"add" = uv add
UV_INSTALL_MODES: tuple[str, ...] = ("pip", "add")

MODE_LABELS: dict[str, str] = {
    "pip": "uv pip install",
    "add": "uv add",
}

MODE_DESCRIPTIONS: dict[str, str] = {
    "pip": "仅安装到当前环境，不修改任何项目文件",
    "add": "安装并写入 pyproject.toml，更新 uv.lock",
}


class InstallModeModal(ModalScreen[str | None]):
    """单选一个安装模式，Enter 确认返回模式名，Esc 取消（保持现状）。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(self, current: str = "pip") -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        items: list[ListItem] = []
        for mode in UV_INSTALL_MODES:
            text = Text()
            text.append(
                "● " if mode == self._current else "○ ",
                style="bold green" if mode == self._current else "dim",
            )
            text.append(MODE_LABELS[mode], style="bold")
            text.append("  ", style="dim")
            text.append(MODE_DESCRIPTIONS[mode], style="dim")
            items.append(ListItem(Label(text)))
        with Vertical(id="install-mode-dialog"):
            yield Static(
                "[bold]选择安装模式[/bold]\n[dim]仅对 uv 管理环境生效，本次会话有效[/dim]",
                id="install-mode-header",
            )
            yield ListView(*items, id="install-mode-list")
            yield Static(
                "[dim]↑↓ 移动 · Enter 选择 · Esc 取消（保持现状）[/dim]",
                id="install-mode-hint",
            )

    def on_mount(self) -> None:
        lv = self.query_one("#install-mode-list", ListView)
        if self._current in UV_INSTALL_MODES:
            lv.index = UV_INSTALL_MODES.index(self._current)
        else:
            lv.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None:
            self.dismiss(None)
            return
        self.dismiss(UV_INSTALL_MODES[event.list_view.index])

    def action_cancel(self) -> None:
        self.dismiss(None)
