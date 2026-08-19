"""第一级界面：包列表 + 勾选 + 底部摘要与最终命令。"""

from __future__ import annotations

import subprocess
import sys

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from ..environment import Environment
from ..packages import clear_cache
from ..resolver import UpgradeCandidate, check_reverse_dep_conflicts
from .dialog import ConfirmModal
from .mirror import MIRRORS, MirrorModal
from .version_list import VersionModal


def copy_to_clipboard(text: str) -> bool:
    """跨平台复制文本到剪贴板。"""
    if sys.platform == "darwin":
        try:
            subprocess.run(["pbcopy"], input=text.encode(), check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            return False
    if sys.platform.startswith("win"):
        try:
            subprocess.run(["clip"], input=text.encode(), check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            return False
    for cmd in (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    ):
        try:
            subprocess.run(cmd, input=text.encode(), check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            continue
    return False


class PackageListScreen(Screen[None]):
    """主界面：第一级选择包，第二级（弹窗）选择版本。"""

    BINDINGS = [
        Binding("space", "toggle", "选中"),
        Binding("c", "copy_command", "复制"),
        Binding("e", "execute", "执行"),
        Binding("f", "filter_upgradable", "过滤"),
        Binding("k", "clear_cache", "清理缓存"),
        Binding("m", "select_mirror", "镜像"),
        Binding("q", "quit", "退出"),
    ]

    def __init__(self, candidates: list[UpgradeCandidate], env: Environment) -> None:
        super().__init__()
        self.candidates = candidates
        self.env = env
        self._filter_upgradable = True
        self._row_key_by_name: dict[str, object] = {}
        self._name_by_row_key: dict[object, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Static(self.env.describe(), id="env-info")
        yield Static(
            "[dim]Space 勾选包（选最新兼容版） · Enter 打开该包的版本列表 · F 切换全部/仅可升级 · m 选本次升级镜像[/dim]",
            id="hint",
        )
        yield DataTable(id="package-table")
        with Horizontal(id="bottom"):
            yield Static("已选择：\n（无）", id="summary")
            yield Static("最终命令：\n（请先选择包）", id="command")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        table.add_column("选择", key="sel")
        table.add_column("包", key="name")
        table.add_column("当前版本", key="current")
        table.add_column("最新", key="latest")
        table.add_column("候选版本", key="options")
        self._rebuild_table()

    # ---- 交互 ----

    def action_toggle(self) -> None:
        table = self.query_one(DataTable)
        coord = table.coordinate_to_cell_key(table.cursor_coordinate)
        name = self._name_by_row_key.get(coord.row_key)
        if name is None:
            return
        selected = self.app.selected  # type: ignore[attr-defined]
        if name in selected:
            del selected[name]
        else:
            cand = self.app.candidates_by_name[name]  # type: ignore[attr-defined]
            if cand.options:
                # 默认选中第一个（最新兼容版本）
                selected[name] = cand.options[0].version
            else:
                self.notify(f"{name} 没有可升级的版本", severity="warning")
                return
        self._update_row(name)
        self._update_summary()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        # Enter 选中一行 -> 打开该包的版本选择
        self.run_worker(self._open_versions(event.row_key.value), exclusive=True)

    async def _open_versions(self, name: str) -> None:
        cand = self.app.candidates_by_name[name]  # type: ignore[attr-defined]
        if not cand.on_pypi:
            self.notify(f"{name} 不在 PyPI 上，无法升级", severity="warning")
            return
        if not cand.options:
            self.notify(f"{name} 没有可升级的版本", severity="warning")
            return
        current = self.app.selected.get(name)  # type: ignore[attr-defined]
        installed = [c.package for c in self.candidates]
        result = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            VersionModal(cand, current_version=current, installed=installed)
        )
        if result:
            self.app.selected[name] = result  # type: ignore[attr-defined]
            self._update_row(name)
            self._update_summary()

    def action_copy_command(self) -> None:
        cmd = self._build_command()
        if not cmd:
            self.notify("还没有选择任何升级", severity="warning")
            return
        if copy_to_clipboard(" ".join(cmd)):
            self.notify("命令已复制到剪贴板")
        else:
            self.notify("复制失败：未找到可用的剪贴板工具", severity="error")

    def action_execute(self) -> None:
        if self.app.installing:  # type: ignore[attr-defined]
            self.notify("安装正在进行中，请稍候", severity="warning")
            return
        cmd = self._build_command()
        if not cmd:
            self.notify("还没有选择任何升级", severity="warning")
            return
        # push_screen_wait 必须在 worker 中调用
        self.run_worker(self._confirm_execute(cmd), exclusive=True)

    def action_clear_cache(self) -> None:
        """按 k 清理 PyPI 结果磁盘缓存（需确认）。"""
        # push_screen_wait 必须在 worker 中调用
        self.run_worker(self._confirm_clear_cache(), exclusive=True)

    def action_select_mirror(self) -> None:
        """按 m 选择本次升级使用的镜像源（仅本次，不写入任何配置）。"""
        # push_screen_wait 必须在 worker 中调用
        self.run_worker(self._open_mirror(), exclusive=True)

    async def _open_mirror(self) -> None:
        current = self.app.mirror  # type: ignore[attr-defined]
        name = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            MirrorModal(current=current["name"] if current else None)
        )
        if name:
            self.app.mirror = {"name": name, "url": MIRRORS[name]}  # type: ignore[attr-defined]
            self._update_summary()
            self.notify(f"本次升级将使用镜像源 [bold]{name}[/bold]")

    def action_filter_upgradable(self) -> None:
        """按 f 切换：仅显示可升级的包；再次按下显示全部。"""
        self._filter_upgradable = not self._filter_upgradable
        self._rebuild_table()
        if self._filter_upgradable:
            self.notify("仅显示可升级的包")
        else:
            self.notify("已显示全部包")

    async def _confirm_execute(self, cmd: list[str]) -> None:
        confirm = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            ConfirmModal(
                f"[bold]执行:[/bold] [cyan]{' '.join(cmd)}[/cyan]\n\n"
                "[bold red]此操作会安装/升级当前环境中的包！[/bold red]",
                warnings=self._collect_conflicts(),
            )
        )
        if confirm:
            # 不退出 TUI：直接在应用内部 push 安装屏幕执行 pip
            self.app.run_install(self._pins())  # type: ignore[attr-defined]

    async def _confirm_clear_cache(self) -> None:
        confirm = await self.app.push_screen_wait(  # type: ignore[attr-defined]
            ConfirmModal("[bold]清空 PyPI 结果磁盘缓存？[/bold]\n\n下次查询将重新从 PyPI 拉取数据。")
        )
        if confirm:
            removed = clear_cache()
            if removed:
                self.notify(f"已清空 {removed} 个缓存文件")
            else:
                self.notify("没有缓存可清理", severity="warning")

    # ---- 内部 ----

    def _rebuild_table(self) -> None:
        """按当前过滤状态重建表格（保留列与选中状态）。"""
        table = self.query_one(DataTable)
        table.clear(columns=False)
        self._row_key_by_name.clear()
        self._name_by_row_key.clear()

        for cand in self.candidates:
            name = cand.package.name
            if name in self._row_key_by_name:
                # 防御：同名包（editable 安装残留等）只展示第一行
                continue
            if self._filter_upgradable and not cand.upgradable:
                continue
            if cand.upgradable:
                cells = [
                    Text("[ ]"),
                    Text(name, style="bold"),
                    Text(cand.package.version or "未安装", style="dim" if cand.package.version is None else ""),
                    Text(cand.latest or "", style="bold green"),
                    Text(f"{len(cand.options)} 个", style="cyan"),
                ]
            elif cand.on_pypi:
                cells = [
                    Text("[ ]"),
                    Text(name),
                    Text(cand.package.version or "未安装", style="dim" if cand.package.version is None else ""),
                    Text("无更高版本", style="dim"),
                    Text("-", style="dim"),
                ]
            else:
                cells = [
                    Text("[ ]"),
                    Text(name),
                    Text(cand.package.version or "未安装", style="dim" if cand.package.version is None else ""),
                    Text("不在 PyPI", style="red"),
                    Text("-", style="dim"),
                ]
            row_key = table.add_row(*cells, key=name)
            self._row_key_by_name[name] = row_key
            self._name_by_row_key[row_key] = name

        table.focus()

    def _collect_conflicts(self) -> list[str]:
        """检查已选的升级是否与环境中其它已安装包的依赖约束冲突。"""
        installed = [c.package for c in self.candidates]
        conflicts: list[str] = []
        for name, version in self.app.selected.items():  # type: ignore[attr-defined]
            conflicts.extend(check_reverse_dep_conflicts(installed, name, version))
        return conflicts

    def _pins(self) -> list[str]:
        return [f"{n}=={v}" for n, v in self.app.selected.items()]  # type: ignore[attr-defined]

    def _build_command(self) -> list[str]:
        pins = self._pins()
        if not pins:
            return []
        cmd = ["pip", "install", *pins]
        mirror = self.app.mirror  # type: ignore[attr-defined]
        if mirror:
            cmd.extend(["-i", mirror["url"]])
        return cmd

    def _update_row(self, name: str) -> None:
        table = self.query_one(DataTable)
        row_key = self._row_key_by_name[name]
        marked = name in self.app.selected  # type: ignore[attr-defined]
        table.update_cell(
            row_key,
            "sel",
            Text("[✓]" if marked else "[ ]", style="bold green" if marked else ""),
            update_width=False,
        )

    def _update_summary(self) -> None:
        pins = self._pins()
        mirror = self.app.mirror  # type: ignore[attr-defined]
        if pins:
            summary = "已选择：\n" + "\n".join(f"[green]{p}[/green]" for p in pins)
            command = "最终命令：\n" + " ".join(["pip", "install", *pins])
        else:
            summary = "已选择：\n（无）"
            command = "最终命令：\n（请先选择包）"
        if mirror:
            command += f"\n[dim]镜像源：{mirror['name']} · {mirror['url']}[/dim]"
        self.query_one("#summary", Static).update(summary)
        self.query_one("#command", Static).update(command)

    def refresh_after_install(self) -> None:
        """安装完成后刷新界面：重建表格并清空已选状态。"""
        self._rebuild_table()
        self._update_summary()

    def on_screen_resume(self) -> None:
        """从安装屏幕返回时，若安装已刷新版本数据，则重建界面。"""
        if self.app._pending_refresh:  # type: ignore[attr-defined]
            self.app._pending_refresh = False  # type: ignore[attr-defined]
            self.refresh_after_install()
