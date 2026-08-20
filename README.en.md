# PyDep

An interactive terminal tool for checking and upgrading the dependencies of your current Python environment.

A TUI (Terminal User Interface) built with [Textual](https://github.com/Textualize/textual) that lets you browse upgradable packages, pick target versions, and run the upgrade with a single keypress — all inside your terminal.

## Features

- **Environment detection**: By default checks the current Python environment; supports pointing at any interpreter via `--target` (e.g. another project's `.venv/bin/python`), and can also auto-discover project virtual environments in the current directory and its parents
- **Dependency file support**: Resolve `requirements.txt` or `pyproject.toml` via `--requirements` to check only the packages declared in the file (uninstalled packages are listed too)
- **Concurrent PyPI queries**: 24-way concurrency by default, with on-disk caching (`--clear-cache` to purge) to avoid repeated requests; packages that time out or fail are listed separately and skipped without blocking the rest of the results
- **Version filtering**: Only stable versions are shown by default; `--all` reveals pre-release versions; versions incompatible with the target environment's Python version are filtered out
- **Reverse-dependency conflict check**: Before upgrading, parses the `Requires-Dist` of every installed package and warns if a selected upgrade would break another package's version constraints
- **Mirror support**: Press `m` to temporarily pick a PyPI mirror (BFSU / TUNA / Aliyun) for the current upgrade only — nothing is written to any config
- **Interactive TUI**: `↑↓` to move, `Space` to select packages, `Enter` to choose a specific version, `F` to filter, `c` to copy the command, `e` to run the upgrade, `k` to clear the cache, `m` to pick a mirror, `q` to quit

## Installation

Requires Python 3.10+.

```bash
# Install from source (with development dependencies)
pip install -e ".[dev]"
```

Or install runtime dependencies only:

```bash
pip install -e .
```

## Usage

```bash
# Check and upgrade packages in the current environment
pydep

# Check only specific packages
pydep -p numpy -p pandas

# Check another project's virtual environment
pydep -t /path/to/other/project/.venv/bin/python

# Check only packages declared in a dependency file
pydep -r requirements.txt
pydep -r pyproject.toml

# Show all versions (including pre-releases)
pydep --all

# Clear the PyPI cache and exit
pydep --clear-cache

# Can also be invoked as a module
python -m pydep
```

> Tip: Press `m` inside the TUI to temporarily switch mirrors (effective for the current upgrade only, nothing is written to any config); if a PyPI query times out or fails, the affected package is skipped and flagged separately in the results.

### Full Options

| Option | Description |
| --- | --- |
| `-p, --package <name>` | Check only the specified package; can be used multiple times |
| `-t, --target <path>` | Path to the target Python interpreter |
| `-r, --requirements <file>` | Dependency file path (`requirements.txt` or `pyproject.toml`) |
| `--all` | Show all versions (including pre-releases) |
| `--limit <n>` | Maximum number of candidate versions shown per package (default 15) |
| `--concurrency <n>` | Number of concurrent PyPI requests (default 24) |
| `--no-cache` | Disable on-disk caching of PyPI results |
| `--clear-cache` | Clear the on-disk cache of PyPI results and exit |
| `--timeout <sec>` | Timeout in seconds for the whole PyPI query phase (default 10) |
| `--help` | Show help information |

### TUI Key Bindings

| Key | Action |
| --- | --- |
| `↑` / `↓` | Move up / down |
| `Space` | Select / deselect a package (defaults to upgrading to the latest version) |
| `Enter` | Choose a specific version for the package |
| `f` | Toggle the "show only upgradable packages" filter |
| `c` | Copy the pip upgrade command |
| `e` | Run the upgrade (using the target environment's `python -m pip install`) |
| `k` | Clear the on-disk cache of PyPI results |
| `m` | Temporarily pick a mirror for this upgrade (BFSU / TUNA / Aliyun) |
| `q` | Quit |

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest
```

The project uses a `src` layout, with tests located in `tests/`.

## Tech Stack

- [Textual](https://github.com/Textualize/textual) — TUI framework
- [Typer](https://github.com/fastapi/typer) — CLI entry point
- [packaging](https://github.com/pypa/packaging) — version parsing and comparison
- [httpx](https://github.com/encode/httpx) — concurrent PyPI API requests

## License

[MIT](./LICENSE)
