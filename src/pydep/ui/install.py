"""安装执行屏幕：在 TUI 内部直接运行 pip install，实时显示日志。

替代原先「确认后退出 TUI、回 CLI 用 subprocess 执行」的方式：
安装过程完全发生在应用内部，结束后按 Esc 返回包列表，可继续操作。
"""

from __future__ import annotations

import asyncio
import shlex
import shutil

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, RichLog, Static

from ..environment import Environment

CSS = """
#install-cmd {
    height: auto;
    margin: 1 2;
}

#install-log {
    height: 1fr;
    margin: 0 2;
    border: round $primary;
    padding: 0 1;
}

#install-status {
    height: auto;
    margin: 1 2;
    color: $text-muted;
}
"""


class InstallScreen(Screen[None]):
    """执行 pip 安装并实时展示日志。"""

    CSS = CSS

    BINDINGS = [
        Binding("escape", "back", "返回列表", show=True),
    ]

    def __init__(
        self,
        env: Environment,
        pins: list[str],
        mirror: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self._env = env
        self._cmd = [*env.pip_command, "install", *pins]
        if mirror:
            # uv 的索引参数为 --index-url（等价于 pip 的 -i），语义更明确
            index_flag = "--index-url" if env.is_uv else "-i"
            self._cmd.extend([index_flag, mirror["url"]])

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(
            f"[bold cyan]执行:[/bold cyan] {shlex.join(self._cmd)}\n"
            "[dim]↑↓ 滚动日志 · Esc 返回列表[/dim]",
            id="install-cmd",
        )
        yield RichLog(id="install-log", highlight=False, markup=False, wrap=True)
        yield Static("安装进行中 ...", id="install-status")
        yield Footer()

    def on_mount(self) -> None:
        if self._env.is_uv and shutil.which("uv") is None:
            # uv 管理的环境但本机没有 uv 可执行文件：直接提示，避免子进程报错
            self.app.installing = False  # type: ignore[attr-defined]
            self.query_one("#install-status", Static).update(
                "[bold red]未检测到 uv 可执行文件，请先安装 uv[/bold red]  按 Esc 返回列表"
            )
            return
        self.run_worker(self._run(), exclusive=True)

    async def _run(self) -> None:
        log = self.query_one("#install-log", RichLog)
        status = self.query_one("#install-status", Static)
        log.write(f"$ {shlex.join(self._cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *self._cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (OSError, ValueError) as exc:
            # pip 无法启动（如解释器缺失）时立即恢复 UI，避免「安装中」永久卡死
            self.app.installing = False  # type: ignore[attr-defined]
            status.update(
                f"[bold red]无法启动安装命令：{exc}[/bold red]  按 Esc 返回列表"
            )
            return
        assert proc.stdout is not None and proc.stderr is not None

        async def pump(stream: asyncio.StreamReader) -> None:
            while True:
                line = await stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").rstrip("\r\n")
                if text:
                    log.write(text)

        error: str | None = None
        try:
            await asyncio.gather(pump(proc.stdout), pump(proc.stderr))
            returncode = await proc.wait()
        except Exception as exc:
            error = str(exc)
        finally:
            # 无论成功失败（含异常），都必须恢复 UI 状态
            self.app.installing = False  # type: ignore[attr-defined]

        if error is not None:
            status.update(
                f"[bold red]安装过程出错：{error}[/bold red]  按 Esc 返回列表"
            )
            return
        if returncode == 0:
            status.update("[bold green]安装完成[/bold green]  按 Esc 返回列表")
            # 安装成功后异步刷新包列表中的当前版本
            self.app.refresh_versions()  # type: ignore[attr-defined]
        else:
            status.update(
                f"[bold red]安装失败（返回码 {returncode}）[/bold red]  按 Esc 返回列表"
            )

    def action_back(self) -> None:
        self.app.pop_screen()  # type: ignore[attr-defined]
