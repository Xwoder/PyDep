"""镜像选择弹窗：为本次升级临时选择 PyPI 镜像源（仅本次，不持久化）。"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

# 可选镜像源：name -> PyPI simple 完整地址
MIRRORS: dict[str, str] = {
    "bfsu": "https://mirrors.bfsu.edu.cn/pypi/web/simple",
    "tuna": "https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple",
    "aliyun": "http://mirrors.aliyun.com/pypi/simple/",
}


class MirrorModal(ModalScreen[str | None]):
    """单选一个镜像源，Enter 确认返回镜像名，Esc 取消（保持现状/官方源）。"""

    BINDINGS = [
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(self, current: str | None = None) -> None:
        super().__init__()
        self._current = current

    def compose(self) -> ComposeResult:
        names = list(MIRRORS)
        items: list[ListItem] = []
        for name in names:
            text = Text()
            text.append(
                "● " if name == self._current else "○ ",
                style="bold green" if name == self._current else "dim",
            )
            text.append(name, style="bold")
            text.append("  ", style="dim")
            text.append(MIRRORS[name], style="dim")
            items.append(ListItem(Label(text)))
        with Vertical(id="mirror-dialog"):
            yield Static(
                "[bold]选择本次升级使用的镜像源[/bold]\n[dim]仅本次升级生效，不会写入任何配置[/dim]",
                id="mirror-header",
            )
            yield ListView(*items, id="mirror-list")
            yield Static(
                "[dim]↑↓ 移动 · Enter 选择 · Esc 取消（使用官方源）[/dim]",
                id="mirror-hint",
            )

    def on_mount(self) -> None:
        lv = self.query_one("#mirror-list", ListView)
        names = list(MIRRORS)
        if self._current in names:
            lv.index = names.index(self._current)
        else:
            lv.index = 0

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None:
            self.dismiss(None)
            return
        self.dismiss(list(MIRRORS)[event.list_view.index])

    def action_cancel(self) -> None:
        self.dismiss(None)
