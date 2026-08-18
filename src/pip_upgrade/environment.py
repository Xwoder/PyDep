"""检测当前 Python 环境信息。

这个工具最终操作的是「当前 Python environment」而不是系统 Python，
所以第一步必须搞清楚：我到底在哪个环境里？
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass

from .packages import PROBE_SCRIPT, InstalledPackage


@dataclass(frozen=True)
class Environment:
    """描述当前运行所在的 Python 环境。"""

    python_version: str
    python_executable: str
    pip_executable: str
    is_venv: bool
    venv_name: str | None

    @property
    def python_version_short(self) -> str:
        """形如 3.12 的短版本号，用于 Requires-Python 匹配。"""
        parts = self.python_version.split(".")
        if len(parts) > 2:
            return ".".join(parts[:2])
        return self.python_version

    @property
    def pip_command(self) -> list[str]:
        """推荐的 pip 调用方式：始终走当前解释器的 `-m pip`。"""
        return [self.python_executable, "-m", "pip"]

    def describe(self) -> str:
        parts = [f"Python {self.python_version}"]
        if self.is_venv and self.venv_name:
            parts.append(f"venv: {self.venv_name}")
        else:
            parts.append("系统环境")
        return " · ".join(parts)


def _find_pip_in_bin(bin_dir: str) -> str:
    """在可执行文件目录中寻找 pip（用于展示；执行时仍走 -m pip）。"""
    for candidate in ("pip", "pip3"):
        path = os.path.join(bin_dir, candidate)
        if os.path.isfile(path):
            return path
    return os.path.join(bin_dir, "pip")


def detect_environment() -> Environment:
    """基于运行时信息推断当前环境。"""
    exe = sys.executable
    prefix = sys.prefix
    base_prefix = getattr(sys, "base_prefix", prefix)
    is_venv = prefix != base_prefix
    venv_name = os.path.basename(prefix) if is_venv else None

    return Environment(
        python_version=platform.python_version(),
        python_executable=exe,
        pip_executable=_find_pip_in_bin(os.path.dirname(exe)),
        is_venv=is_venv,
        venv_name=venv_name,
    )


@dataclass(frozen=True)
class ProbeResult:
    """目标解释器的探测结果：环境信息 + 已安装包。"""

    env: Environment
    packages: list[InstalledPackage]


def probe_interpreter(python_executable: str) -> ProbeResult:
    """在另一个 Python 解释器中探测其环境与已安装包。

    用于「检查别的项目」：例如指向该项目虚拟环境里的 python。
    """
    proc = subprocess.run(
        [python_executable, "-c", PROBE_SCRIPT],
        capture_output=True,
        text=True,
        timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"无法探测目标解释器 {python_executable}:\n{proc.stderr.strip()}"
        )
    data = json.loads(proc.stdout)

    prefix = data["prefix"]
    base_prefix = data["base_prefix"]
    is_venv = prefix != base_prefix
    env = Environment(
        python_version=data["python_version"],
        python_executable=data["python_executable"],
        pip_executable=_find_pip_in_bin(os.path.dirname(data["python_executable"])),
        is_venv=is_venv,
        venv_name=os.path.basename(prefix) if is_venv else None,
    )
    packages = [InstalledPackage(**p) for p in data["packages"]]
    return ProbeResult(env=env, packages=packages)
