# PyDep

交互式终端工具：检查并升级当前 Python 环境的依赖包。

基于 [Textual](https://github.com/Textualize/textual) 构建的 TUI（终端用户界面），让你可以在终端里直观地浏览可升级的包、选择目标版本并一键执行升级。

## 功能特性

- **环境检测**：默认检查当前 Python 环境；支持通过 `--target` 指定任意解释器（如其它项目的 `.venv/bin/python`），也可以自动发现当前目录及其父目录中的项目虚拟环境
- **依赖文件支持**：通过 `--requirements` 解析 `requirements.txt` 或 `pyproject.toml`，只检查文件声明的包（未安装的包也会列出）
- **并发查询 PyPI**：默认 24 路并发，支持磁盘缓存（`--clear-cache` 清理），避免重复请求；查询超时或失败的包会单独列出并跳过，不阻塞其余结果
- **版本筛选**：默认只展示稳定版，`--all` 可显示预发布版本；基于目标环境的 Python 版本过滤不兼容的版本
- **反向依赖冲突检查**：升级前解析所有已安装包的 `Requires-Dist`，对选中的每个升级提前检查是否会破坏其它包的版本约束并给出警告
- **镜像源支持**：`m` 键可为本次升级临时选择 PyPI 镜像源（BFSU / TUNA / Aliyun），仅本次生效，不写入任何配置
- **交互式 TUI**：`↑↓` 移动、`Space` 勾选包、`Enter` 选择具体版本、`F` 过滤、`c` 复制命令、`e` 执行升级、`k` 清理缓存、`m` 选择镜像、`q` 退出

## 安装

需要 Python 3.10+。

```bash
# 从源码安装（含开发依赖）
pip install -e ".[dev]"
```

或仅安装运行依赖：

```bash
pip install -e .
```

## 使用

```bash
# 检查并升级当前环境的包
pydep

# 只检查指定的包
pydep -p numpy -p pandas

# 检查其它项目虚拟环境
pydep -t /path/to/other/project/.venv/bin/python

# 只检查依赖文件声明的包
pydep -r requirements.txt
pydep -r pyproject.toml

# 显示所有版本（包括预发布版本）
pydep --all

# 清空 PyPI 缓存后退出
pydep --clear-cache

# 也支持以模块方式调用
python -m pydep
```

> 提示：在 TUI 内按 `m` 可临时切换镜像源（仅本次升级生效，不写入任何配置）；若查询 PyPI 超时或失败，相关包会被跳过并在结果中单独提示。

### 完整选项

| 选项 | 说明 |
| --- | --- |
| `-p, --package <name>` | 只检查指定的包，可多次使用 |
| `-t, --target <path>` | 目标 Python 解释器路径 |
| `-r, --requirements <file>` | 依赖文件路径（`requirements.txt` 或 `pyproject.toml`） |
| `--all` | 显示所有版本（包括预发布版本） |
| `--limit <n>` | 每个包最多展示的候选版本数量（默认 15） |
| `--concurrency <n>` | 查询 PyPI 的并发请求数（默认 24） |
| `--no-cache` | 禁用 PyPI 结果磁盘缓存 |
| `--clear-cache` | 清空 PyPI 结果磁盘缓存后退出 |
| `--timeout <sec>` | 整个 PyPI 查询阶段的超时秒数（默认 10） |
| `--help` | 显示帮助信息 |

### TUI 快捷键

| 按键 | 功能 |
| --- | --- |
| `↑` / `↓` | 上下移动 |
| `Space` | 勾选/取消勾选包（默认升级到最新版） |
| `Enter` | 为包选择具体版本 |
| `f` | 切换「仅显示可升级包」过滤 |
| `c` | 复制 pip 升级命令 |
| `e` | 执行升级（使用目标环境的 `python -m pip install`） |
| `k` | 清空 PyPI 结果磁盘缓存 |
| `m` | 为本次升级临时选择镜像源（BFSU / TUNA / Aliyun） |
| `q` | 退出 |

## 开发

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest
```

项目采用 `src` 布局，测试位于 `tests/` 目录。

## 技术栈

- [Textual](https://github.com/Textualize/textual) — TUI 框架
- [Typer](https://github.com/fastapi/typer) — 命令行入口
- [packaging](https://github.com/pypa/packaging) — 版本解析与比较
- [httpx](https://github.com/encode/httpx) — PyPI API 并发请求

## 许可证

[MIT](./LICENSE)
