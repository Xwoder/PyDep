# CODEBUDDY.md

This file provides guidance to CodeBuddy Code when working with code in this repository.

## 项目概览

`pydep` 是一个基于 [Textual](https://github.com/Textualize/textual) 的交互式终端工具，用于检查并升级 Python 环境的依赖包。它并发查询 PyPI、按当前环境的 Python 版本与已装版本筛选可升级候选，并在 TUI 内直接执行 `pip install`。

技术栈：Textual（TUI）、Typer（CLI 入口）、packaging（PEP 440 版本解析）、httpx（PyPI 并发请求）。源码布局为 `src/` 布局，包名 `pydep`。

## 常用命令

Python 虚拟环境位于项目根目录的 `.venv`（激活后使用，或直接用 `.venv/bin/` 前缀）。

```bash
# 安装（含开发依赖，含 pytest / pytest-asyncio）
pip install -e ".[dev]"

# 运行全部测试
pytest

# 运行单个测试文件
pytest tests/test_tui.py

# 运行单个测试函数（按名称 / -k 表达式）
pytest tests/test_tui.py::test_select_package_and_version_flow
pytest -k "yanked"

# 启动工具本身（检查当前环境）
pydep
python -m pydep
```

注意：`pyproject.toml` 配置了 `asyncio_mode = "auto"`，异步测试无需 `@pytest.mark.asyncio` 也能运行（现有测试仍保留该标记，新增可省略）。

## 架构

### 端到端数据流（cli.py 的 `main`）

1. **确定环境** `_resolve_environment` → `environment.py`：`detect_environment()`（推断当前环境）/ `find_project_venv()`（向父目录回溯发现 `.venv` 等）/ `--target` 时 `probe_interpreter()`（用 `subprocess` 在目标解释器内跑 `packages.PROBE_SCRIPT` 枚举其已装包）。返回 `Environment` + `list[InstalledPackage]`。`--requirements` 经 `parse_dependency_file()` 只保留文件声明的包，`-p` 进一步过滤。
2. **查询 PyPI** `_query_pypi` → `packages.fetch_pypi_info_many`：用 `httpx.AsyncClient` 以 `Semaphore(concurrency)` 并发请求 PyPI JSON API（`https://pypi.org/pypi/{name}/json`）。带磁盘缓存、单次重试、整体超时（超时后保留已完成结果）。
3. **计算升级候选** `resolver.build_candidates`：对每个包生成 `UpgradeCandidate`，过滤规则见下文。
4. **启动 TUI** `_launch_tui` → `ui.app.PydepApp`：无可升级时退出，否则进入 `PackageListScreen`。

### 核心数据模型（贯穿各模块）

- `InstalledPackage`（packages.py）：`name, version(可 None 表示未装但被依赖文件声明), summary, requires`（`requires` 是 `Requires-Dist` 字符串列表）。
- `PyPIInfo`（packages.py）：`name, latest, releases`（`releases[version]` = 该版本各文件的 `[{requires_python, yanked}]`）。
- `UpgradeCandidate`（resolver.py）：`package, info, options`；关键属性 `upgradable`（`len(options)>0`）、`on_pypi`、`latest`。`UpgradeOption`：`version, requires_python, yanked`。
- `Environment` / `ProbeResult`（environment.py）：描述目标解释器（路径、版本、是否 venv、pip 调用方式 `python -m pip`）。

### 升级候选过滤规则（resolver._build_options）

顺序过滤：① Requires-Python 必须兼容当前解释器；② 版本严格高于已装版本（未装的包所有版本皆候选）；③ 默认跳过预发布（除非已装版或 `--all` 放行）；④ yanked 版本保留但排到末尾。结果按 `max_options`（`--limit`，默认 15）截断。版本比较一律走 `versions.py` 的 `packaging.Version`，切勿手写字符串比较。

### 反向依赖冲突检查（resolver.py）

升级前通过已装包的 `Requires-Dist`（其正向依赖）反向匹配目标包，用 `SpecifierSet.contains` 校验新版本是否满足约束。`build_reverse_dep_index` 一次性建索引供多个候选版本复用；`check_reverse_dep_conflicts_index` 返回告警列表（pip 本身不做此保护，工具只是超前提醒）。

### TUI 模块结构（src/pydep/ui/）

屏幕流转由 `app.PydepApp` 管理（持有 `candidates`、`selected`、`mirror`、安装状态）：

- `package_list.PackageListScreen` — 主界面：包列表、勾选、底部摘要与最终 `pip install` 命令。按键：`Space` 勾选、`Enter` 开版本弹窗、`f` 过滤、`c` 复制、`e` 执行、`k` 清缓存、`m` 镜像、`q` 退出。
- `version_list.VersionModal` — 选具体版本，标红冲突版本、标黄 yanked 版本（带悬停详情）。
- `dialog.ConfirmModal` — Y/N 确认（执行/清缓存），并展示冲突警告。
- `mirror.MirrorModal` — 临时选镜像源（BFSU/TUNA/Aliyun），仅本次生效不持久化。
- `install.InstallScreen` — 在 TUI 内直接跑 `python -m pip install` 并实时显示日志，成功后再探测环境刷新版本（`app.refresh_versions` → `refresh_candidate_options` 重算候选）。

TUI 测试用 Textual 的 `pilot` 驱动：`async with app.run_test() as pilot: ... await pilot.press(...)`。注意 `push_screen_wait` 必须在 worker 内调用（`run_worker`），否则崩溃——这是现有测试的坑点。

### 缓存

PyPI 结果磁盘缓存位于 `~/.cache/pydep/pypi`（受 `XDG_CACHE_HOME` / `LOCALAPPDATA` 影响），`--clear-cache` 或 TUI 内 `k` 可清理，`--no-cache` 关闭。缓存文件按包名 `{name}.json` 存储。
