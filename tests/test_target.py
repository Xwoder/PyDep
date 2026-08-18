"""检查其它项目：依赖文件解析 + 目标解释器探测 + 未安装包处理。"""

import os
import sys

from pip_upgrader.environment import find_project_venv, probe_interpreter
from pip_upgrader.packages import (
    InstalledPackage,
    PyPIInfo,
    parse_dependency_file,
    parse_pyproject,
    parse_requirements_file,
)
from pip_upgrader.resolver import build_candidates


def test_parse_requirements_file(tmp_path):
    sub = tmp_path / "base.txt"
    sub.write_text(
        "# comment\n"
        "numpy==2.2.0\n"
        "pandas>=2.0\n"
        "requests\n"
        "git+https://github.com/psf/requests.git\n"
        "--index-url https://pypi.org/simple\n"
        "-r extra.txt\n"
    )
    extra = tmp_path / "extra.txt"
    extra.write_text("httpx==0.28\n# another comment\n")

    names = parse_requirements_file(sub)
    assert names == ["httpx", "numpy", "pandas", "requests"]


def test_parse_requirements_skips_options(tmp_path):
    f = tmp_path / "r.txt"
    f.write_text("-c constraints.txt\n--no-binary :all:\nbeautifulsoup4\n")
    assert parse_requirements_file(f) == ["beautifulsoup4"]


def test_parse_pyproject(tmp_path):
    f = tmp_path / "pyproject.toml"
    f.write_text(
        "[project]\n"
        'name = "demo"\n'
        'dependencies = [\n'
        '  "fastapi>=0.115",\n'
        '  "uvicorn[standard]>=0.30",\n'
        "]\n"
        "[project.optional-dependencies]\n"
        'dev = ["pytest>=8"]\n'
    )
    names = parse_pyproject(f)
    assert names == ["fastapi", "pytest", "uvicorn"]


def test_parse_dependency_file_auto_detect(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("pandas\n")
    assert parse_dependency_file(req) == ["pandas"]

    toml = tmp_path / "pyproject.toml"
    toml.write_text('[project]\ndependencies = ["numpy"]\n')
    assert parse_dependency_file(toml) == ["numpy"]


def _make_venv(root, name, exe="python"):
    """在 root 下创建名为 name 的伪虚拟环境目录，返回其 python 路径。"""
    if os.name == "nt":
        exe = "python.exe"
        bin_dir = os.path.join(root, name, "Scripts")
    else:
        bin_dir = os.path.join(root, name, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    python = os.path.join(bin_dir, exe)
    with open(python, "w", encoding="utf-8") as f:
        f.write("")
    return python


def test_find_project_venv_in_current_dir(tmp_path):
    _make_venv(str(tmp_path), ".venv2")
    python = find_project_venv(start_dir=str(tmp_path))
    assert python == os.path.join(str(tmp_path), ".venv2", "bin", "python")


def test_find_project_venv_prefers_dot_venv(tmp_path):
    _make_venv(str(tmp_path), "venv")
    _make_venv(str(tmp_path), ".venv")
    python = find_project_venv(start_dir=str(tmp_path))
    assert python.endswith(os.path.join(".venv", "bin", "python"))


def test_find_project_venv_walks_up_parents(tmp_path):
    _make_venv(str(tmp_path), ".venv")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    python = find_project_venv(start_dir=str(nested))
    assert python.endswith(os.path.join(".venv", "bin", "python"))


def test_find_project_venv_none_when_missing(tmp_path):
    assert find_project_venv(start_dir=str(tmp_path)) is None


def test_probe_interpreter_current():
    result = probe_interpreter(sys.executable)
    assert result.env.python_version.startswith(("3.", "2."))
    assert result.env.python_executable == sys.executable
    assert any(p.name == "pip-upgrader" for p in result.packages)


def test_resolver_uninstalled_package_all_versions_are_candidates():
    info = PyPIInfo(
        name="demo",
        latest="2.0.0",
        releases={
            "1.0.0": [{"requires_python": None, "yanked": False}],
            "1.5.0": [{"requires_python": None, "yanked": False}],
            "2.0.0": [{"requires_python": None, "yanked": False}],
        },
    )
    pkg = InstalledPackage(name="demo", version=None)
    cand = build_candidates([pkg], {"demo": info}, "3.10")[0]
    assert cand.upgradable
    assert [o.version for o in cand.options] == ["2.0.0", "1.5.0", "1.0.0"]
