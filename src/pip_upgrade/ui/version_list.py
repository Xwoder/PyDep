"""版本选择弹窗：展示某个包在当前环境下可升级到的版本。"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, ListItem, ListView, Static

from ..packages import InstalledPackage
from ..resolver import UpgradeCandidate, check_reverse_dep_conflicts


class VersionModal(ModalScreen[str | None]):
    """单选一个目标版本，Enter 确认返回，Esc 取消。

    传入 installed 时，会检查每个版本是否与环境中其它已安装包存在
    反向依赖冲突，冲突版本在列表中标红并附带悬停详情。
    yanked（被发布者撤回）的版本标黄显示，可悬停查看说明。
    """

    BINDINGS = [
        Binding("space", "toggle", "选择"),
        Binding("escape", "cancel", "取消", show=False),
    ]

    def __init__(
        self,
        candidate: UpgradeCandidate,
        current_version: str | None = None,
        installed: list[InstalledPackage] | None = None,
    ) -> None:
        super().__init__()
        self._candidate = candidate
        self._versions = [o.version for o in candidate.options]
        self._current_version = current_version
        self._selected: str | None = None
        # 用户是否手动选择过；未手动选择时高亮移动会自动跟随
        self._manual = False
        # 版本 -> 反向依赖冲突描述（用于标红提示）
        self._conflicts: dict[str, list[str]] = {}
        # 被发布者 yanked（撤回）的版本集合
        self._yanked: set[str] = set()
        for opt in candidate.options:
            cs = check_reverse_dep_conflicts(
                installed or [], candidate.package.name, opt.version
            )
            if cs:
                self._conflicts[opt.version] = cs
            if opt.yanked:
                self._yanked.add(opt.version)

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
        if self._conflicts:
            header.append(
                f"\n{len(self._conflicts)} 个版本与已安装包依赖冲突（标红，可悬停查看详情）",
                style="bold red",
            )
        if self._yanked:
            header.append(
                f"\n{len(self._yanked)} 个版本已被发布者 yanked（撤回），标黄显示，谨慎安装",
                style="bold yellow",
            )
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
            conflicts = self._conflicts.get(version)
            is_yanked = version in self._yanked
            text = Text()
            text.append("● " if selected else "○ ", style="bold green" if selected else "dim")
            if conflicts:
                text.append(version, style="bold red")
                text.append("  !", style="bold red")
                if is_yanked:
                    text.append("  [yanked]", style="bold yellow")
            elif is_yanked:
                text.append(version, style="bold yellow")
                text.append("  [yanked]", style="bold yellow")
            else:
                text.append(version, style="bold green" if selected else "")
            label = item.query_one(Label)
            label.update(text)
            tooltip_parts: list[str] = []
            if conflicts:
                tooltip_parts.append("与已安装包存在依赖冲突：")
                tooltip_parts.extend(conflicts)
            if is_yanked:
                tooltip_parts.append(
                    "该版本已被发布者从 PyPI yanked（撤回），可能存在已知问题，安装前请确认。"
                )
            label.tooltip = "\n".join(tooltip_parts) if tooltip_parts else None
