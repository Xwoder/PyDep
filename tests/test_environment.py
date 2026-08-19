"""uv 管理环境识别与安装命令分支的测试。"""

import os

from pydep.environment import Environment, _is_uv_managed


def _make_venv_with_cfg(tmp_path, name, cfg_lines=None):
    """创建伪 venv 目录（含 pyvenv.cfg），返回其 python 路径。"""
    if os.name == "nt":
        bin_rel = "Scripts"
    else:
        bin_rel = "bin"
    venv_root = os.path.join(str(tmp_path), name)
    os.makedirs(os.path.join(venv_root, bin_rel), exist_ok=True)
    cfg_path = os.path.join(venv_root, "pyvenv.cfg")
    with open(cfg_path, "w", encoding="utf-8") as f:
        f.write("\n".join(cfg_lines or []) + "\n")
    python = os.path.join(venv_root, bin_rel, "python")
    with open(python, "w", encoding="utf-8") as f:
        f.write("")
    return python


def test_is_uv_managed_with_pyvenv_cfg_marker(tmp_path):
    """pyvenv.cfg 含 uv 键（uv>=0.2 创建环境时写入）→ 判定为 uv 管理。"""
    python = _make_venv_with_cfg(
        tmp_path,
        ".venv",
        ['home = /usr/bin', 'include-system-site-packages = false', 'version = 3.12.3', 'uv = "0.5.0"'],
    )
    assert _is_uv_managed(python) is True


def test_is_uv_managed_without_marker(tmp_path):
    """普通 venv（pyvenv.cfg 无 uv 键、无 UV_ACTIVE）→ 不是 uv 管理。"""
    python = _make_venv_with_cfg(
        tmp_path,
        ".venv",
        ['home = /usr/bin', 'include-system-site-packages = false', 'version = 3.12.3'],
    )
    assert _is_uv_managed(python) is False


def test_is_uv_managed_false_when_no_cfg(tmp_path):
    """没有 pyvenv.cfg（如系统解释器）→ 不是 uv 管理。"""
    python = _make_venv_with_cfg(tmp_path, "plain")
    os.remove(os.path.join(os.path.dirname(os.path.dirname(python)), "pyvenv.cfg"))
    assert _is_uv_managed(python) is False


def test_is_uv_managed_via_uv_active_env(monkeypatch, tmp_path):
    """无 uv 标记但进程由 uv 启动（UV_ACTIVE=1）→ 判定为 uv 管理。"""
    python = _make_venv_with_cfg(tmp_path, ".venv")
    monkeypatch.setenv("UV_ACTIVE", "1")
    assert _is_uv_managed(python) is True


def test_environment_pip_command_uv():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
        is_uv=True,
    )
    assert env.pip_command == ["uv", "pip"]


def test_environment_pip_command_regular():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
        is_uv=False,
    )
    assert env.pip_command == ["/path/.venv/bin/python", "-m", "pip"]


def test_environment_describe_uv():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
        is_uv=True,
    )
    assert "uv 管理" in env.describe()


MIRROR = {"name": "tuna", "url": "https://pypi.tuna.tsinghua.edu.cn/simple"}


def test_install_command_regular_pip():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
    )
    assert env.install_command(["demo==2.0.0"]) == [
        "/path/.venv/bin/python",
        "-m",
        "pip",
        "install",
        "demo==2.0.0",
    ]
    # 普通环境：镜像参数用 -i
    assert env.install_command(["demo==2.0.0"], mirror=MIRROR) == [
        "/path/.venv/bin/python",
        "-m",
        "pip",
        "install",
        "demo==2.0.0",
        "-i",
        MIRROR["url"],
    ]


def test_install_command_uv_pip():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
        is_uv=True,
    )
    # 默认模式：uv pip install（仅改环境）
    assert env.install_command(["demo==2.0.0"]) == ["uv", "pip", "install", "demo==2.0.0"]
    assert env.install_command(["demo==2.0.0"], mode="pip") == [
        "uv",
        "pip",
        "install",
        "demo==2.0.0",
    ]
    # uv：镜像参数用 --index-url
    assert env.install_command(["demo==2.0.0"], mode="pip", mirror=MIRROR) == [
        "uv",
        "pip",
        "install",
        "demo==2.0.0",
        "--index-url",
        MIRROR["url"],
    ]


def test_install_command_uv_add():
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
        is_uv=True,
    )
    # add 模式：uv add（写入 pyproject.toml / uv.lock），无 install 子命令
    assert env.install_command(["demo==2.0.0"], mode="add") == ["uv", "add", "demo==2.0.0"]
    assert env.install_command(["demo==2.0.0"], mode="add", mirror=MIRROR) == [
        "uv",
        "add",
        "demo==2.0.0",
        "--index-url",
        MIRROR["url"],
    ]


def test_install_command_regular_ignores_mode():
    """普通环境忽略 mode：即使传 add 也走 python -m pip install。"""
    env = Environment(
        python_version="3.12.3",
        python_executable="/path/.venv/bin/python",
        pip_executable="/path/.venv/bin/pip",
        is_venv=True,
        venv_name=".venv",
    )
    assert env.install_command(["demo==2.0.0"], mode="add") == [
        "/path/.venv/bin/python",
        "-m",
        "pip",
        "install",
        "demo==2.0.0",
    ]
