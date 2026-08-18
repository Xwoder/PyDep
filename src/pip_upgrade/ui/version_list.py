"""版本选择弹窗：展示某个包在当前环境下可升级到的版本。"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from ..resolver import UpgradeCandidate


class VersionModal(ModalScreen[str | None]):
    """单选一个目标版本，Enter 确认返回，Esc 取消。"""

    BINDINGS = [
        Binding("space", "toggle", "选择"),
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(self, candidate: UpgradeCandidate, current_version: str | None = None) -> None:
        super().__init__()
        self._candidate = candidate
        self._versions = [o.version for o in candidate.options]
        self._current_version = current_version
        self._selected: str | None = None
        # 用户是否手动选择过；未手动选择时高亮移动会自动跟随
        self._manual = False

    def compose(self) -> ComposeResult:
        pkg = self._candidate.package
        header = Text()
        header.append(pkg.name, style="bold")
        header.append(f"  当前: {pkg.version}")
        rp = (
            self._candidate.options[0].requires_python
            if self._candidate.options
            else None
        )
        if rp:
            header.append(f"\nRequires-Python: {rp}", style="dim")
        items = [ListItem(Label(str(v))) for v in self._versions]
        with Vertical(id="version-dialog"):
            yield Static(header, id="version-header")
            yield ListView(*items, id="version-list")
            yield Static(
                "[dim]↑↓ 移动 · Space 选择 · Enter 确认 · Esc 取消[/dim]",
                id="version-hint",
            )

    def on_mount(self) -> None:
        if not self._versions:
            return
        lv = self.query_one("#version-list", ListView)
        # 该包已选过版本时，直接定位并选中它；否则高亮最新版本并自动跟随
        if self._current_version in self._versions:
            index = self._versions.index(self._current_version)
            lv.index = index
            self._selected = self._current_version
            self._manual = True
        else:
            self._selected = self._versions[0]
        self._refresh_labels()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        if self._manual or event.list_view.index is None:
            return
        self._selected = self._versions[event.list_view.index]
        self._refresh_labels()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        # Enter 确认：未手动选择则取当前高亮版本
        self.dismiss(self._selected or self._versions[0])

    def action_toggle(self) -> None:
        lv = self.query_one("#version-list", ListView)
        if lv.index is None:
            return
        version = self._versions[lv.index]
        self._selected = None if self._selected == version else version
        self._manual = True
        self._refresh_labels()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _refresh_labels(self) -> None:
        lv = self.query_one("#version-list", ListView)
        for i, item in enumerate(lv.children):
            version = self._versions[i]
            selected = version == self._selected
            text = Text()
            text.append("● " if selected else "○ ", style="bold green" if selected else "dim")
            text.append(version, style="bold green" if selected else "")
            item.query_one(Label).update(text)
