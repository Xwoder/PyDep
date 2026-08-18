"""Y/N 确认对话框。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmModal(ModalScreen[bool]):
    """按 Y 确认 / N 或 Esc 取消的模态对话框。"""

    BINDINGS = [
        Binding("y", "yes", "确认"),
        Binding("n", "no", "取消", show=False),
        Binding("escape", "no", "取消", show=False),
    ]

    def __init__(self, message: str, warnings: list[str] | None = None) -> None:
        super().__init__()
        self._message = message
        self._warnings = warnings or []

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Static(self._message, id="confirm-message")
            if self._warnings:
                lines = ["[bold red]依赖冲突警告（pip 不会自动拦截）：[/bold red]"]
                lines.extend(f"[red]  - {w}[/red]" for w in self._warnings)
                yield Static("\n".join(lines), id="confirm-warnings")
            yield Static("[dim]按 Y 确认 · N 取消[/dim]", id="confirm-hint")

    def on_mount(self) -> None:
        self.focus()

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)
