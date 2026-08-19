"""命令行入口（Typer）。

流程：
    1. 确定检查对象：当前环境 / 指定解释器（--target）/ 项目依赖文件（--requirements）
       —— 不带 --target 时，自动在当前目录（及其父目录）发现项目虚拟环境
    2. 列出（或解析出）待检查的包
    3. 并发查询 PyPI
    4. 计算升级候选
    5. 启动 Textual TUI
    6. （可选）退出后用目标环境的 python -m pip 直接执行
"""

from __future__ import annotations

import asyncio
import subprocess

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from .environment import detect_environment, find_project_venv, probe_interpreter
from .packages import (
    InstalledPackage,
    clear_cache,
    fetch_pypi_info_many,
    list_installed,
    parse_dependency_file,
)
from .resolver import build_candidates, check_reverse_dep_conflicts
from .ui.app import PydepApp

app = typer.Typer(add_completion=False, no_args_is_help=True, rich_markup_mode="rich")
console = Console()


@app.command()
def main(
    package: list[str] = typer.Option(
        None, "--package", "-p", help="只检查指定的包，可多次使用（如 -p numpy -p pandas）"
    ),
    target: str = typer.Option(
        None,
        "--target",
        "-t",
        help="目标 Python 解释器路径（如其它项目 .venv/bin/python），检查那个环境的包",
    ),
    requirements: str = typer.Option(
        None,
        "--requirements",
        "-r",
        help="依赖文件路径（requirements.txt 或 pyproject.toml），只检查文件声明的包",
    ),
    all_versions: bool = typer.Option(
        False, "--all", help="显示所有版本（包括预发布版本）"
    ),
    limit: int = typer.Option(
        15, "--limit", help="每个包最多展示的候选版本数量"
    ),
    concurrency: int = typer.Option(
        24, "--concurrency", help="查询 PyPI 的并发请求数（默认 24）"
    ),
    no_cache: bool = typer.Option(
        False, "--no-cache", help="禁用 PyPI 结果磁盘缓存"
    ),
    clear_cache_opt: bool = typer.Option(
        False, "--clear-cache", help="清空 PyPI 结果磁盘缓存后退出，不执行检查"
    ),
    timeout: float = typer.Option(
        10.0, "--timeout", help="整个 PyPI 查询阶段的超时秒数"
    ),
) -> None:
    """交互式升级指定环境或项目的依赖。"""

    if clear_cache_opt:
        removed = clear_cache()
        if removed:
            console.print(f"[green]已清空 {removed} 个缓存文件。[/green]")
        else:
            console.print("[dim]缓存目录不存在或已为空，无需清理。[/dim]")
        raise typer.Exit(0)

    env = detect_environment()

    def probe_target(python: str) -> None:
        nonlocal env, installed
        try:
            probe = probe_interpreter(python)
        except (OSError, RuntimeError) as exc:
            console.print(f"[red]无法探测目标解释器:[/red] {exc}")
            raise typer.Exit(1) from exc
        env = probe.env
        installed = probe.packages

    if target:
        probe_target(target)
        console.print(f"[bold]目标环境:[/bold] {env.describe()}")
        console.print(f"[bold]目标解释器:[/bold] {env.python_executable}")
    else:
        auto_target = find_project_venv()
        if auto_target:
            probe_target(auto_target)
            console.print(f"[bold]自动检测到项目虚拟环境:[/bold] {env.describe()}")
            console.print(f"[bold]解释器:[/bold] {env.python_executable}")
            console.print("[dim]提示: 想检查当前 shell 环境时，可用 --target 显式指定或到其它目录执行[/dim]")
        else:
            installed = list_installed()
            console.print(f"[bold]环境:[/bold] {env.describe()}")
            console.print(f"[bold]解释器:[/bold] {env.python_executable}")

    # 从依赖文件解析，只保留文件声明的包；未安装的以 version=None 占位
    if requirements:
        try:
            declared = parse_dependency_file(requirements)
        except (OSError, RuntimeError) as exc:
            console.print(f"[red]无法解析依赖文件:[/red] {exc}")
            raise typer.Exit(1) from exc
        if not declared:
            console.print("[yellow]未从依赖文件解析到任何包。[/yellow]")
            raise typer.Exit(0)
        console.print(
            f"从 [bold]{requirements}[/bold] 解析到 [bold]{len(declared)}[/bold] 个包"
        )
        declared_set = set(declared)
        installed = [p for p in installed if p.name in declared_set]
        have = {p.name for p in installed}
        installed.extend(
            InstalledPackage(name=n, version=None)
            for n in declared
            if n not in have
        )
        installed.sort(key=lambda p: p.name)

    if package:
        wanted = {p.lower() for p in package}
        installed = [p for p in installed if p.name in wanted]

    if not installed:
        console.print("[yellow]没有可检查的包。[/yellow]")
        raise typer.Exit(0)

    console.print(
        f"发现 [bold]{len(installed)}[/bold] 个包，正在查询 PyPI（需联网，"
        f"[dim]并发 {concurrency}，缓存 {'关' if no_cache else '开'}[/dim]）..."
    )
    failed: list[str] = []
    timed_out: list[str] = []
    cached_hits = 0

    def on_progress(name: str, status: str) -> None:
        nonlocal cached_hits
        if status in ("cache", "stale"):
            cached_hits += 1
        if status == "missing":
            failed.append(name)
        if status == "timeout":
            timed_out.append(name)
        progress.advance(task)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        task = progress.add_task("查询 PyPI ...", total=len(installed))
        infos = asyncio.run(
            fetch_pypi_info_many(
                [p.name for p in installed],
                concurrency=concurrency,
                use_cache=not no_cache,
                on_progress=on_progress,
                timeout=timeout,
            )
        )

    if timed_out:
        console.print(
            f"[yellow]PyPI 查询超过 {timeout:.0f}s，{len(timed_out)} 个包未完成已跳过: "
            f"{', '.join(timed_out[:8])}{'...' if len(timed_out) > 8 else ''}"
            "（已获取的结果继续使用，可重试未完成的包）[/yellow]"
        )
    if cached_hits:
        console.print(f"[dim]其中 {cached_hits} 个来自本地缓存[/dim]")
    if failed:
        console.print(
            f"[yellow]有 {len(failed)} 个包查询失败，已跳过: "
            f"{', '.join(failed[:8])}{'...' if len(failed) > 8 else ''}[/yellow]"
        )
    if infos:
        console.print("[green]PyPI 查询完成。[/green]")
    elif failed or timed_out:
        console.print("[red]没有获取到任何 PyPI 信息，无法继续。请检查网络连接后重试。[/red]")
        raise typer.Exit(1)

    candidates = build_candidates(
        installed,
        infos,
        env.python_version_short,
        allow_prerelease=all_versions,
        max_options=limit,
    )

    upgradable = [c for c in candidates if c.upgradable]
    if not upgradable:
        console.print("[green]所有包都已是最新版本，无需升级。[/green]")
        raise typer.Exit(0)

    console.print(f"有 [bold]{len(upgradable)}[/bold] 个包可以升级，启动交互界面 ...")
    console.print("[dim]提示: ↑↓ 移动 · Space 勾选包(最新版) · Enter 选具体版本 · c 复制 · e 执行 · k 清理缓存 · m 镜像 · q 退出[/dim]")

    ui_app = PydepApp(candidates=candidates, env=env)
    result = ui_app.run()

    if result and result.get("execute"):
        conflicts: list[str] = []
        for pin in result["pins"]:
            name, _, version = pin.partition("==")
            conflicts.extend(check_reverse_dep_conflicts(installed, name, version))
        if conflicts:
            console.print("[bold yellow]依赖冲突警告（pip 不会自动拦截，请确认）：[/bold yellow]")
            for line in conflicts:
                console.print(f"[yellow]  - {line}[/yellow]")
        cmd = [env.python_executable, "-m", "pip", "install", *result["pins"]]
        mirror = result.get("mirror")
        if mirror:
            cmd.extend(["-i", mirror["url"]])
            console.print(f"[bold cyan]镜像源:[/bold cyan] {mirror['name']} · {mirror['url']}")
        console.print(f"\n[bold cyan]执行:[/bold cyan] {' '.join(cmd)}")
        raise SystemExit(subprocess.run(cmd).returncode)


if __name__ == "__main__":
    app()
