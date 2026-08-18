"""TUI 冒烟测试：使用 Textual 的 pilot 驱动交互。"""

import pytest
from textual.widgets import DataTable, Static

from pip_upgrade.environment import detect_environment
from pip_upgrade.packages import InstalledPackage, PyPIInfo
from pip_upgrade.resolver import UpgradeCandidate, UpgradeOption
from pip_upgrade.ui.app import PipUpgradeApp
from pip_upgrade.ui.version_list import VersionModal


def make_candidates() -> list[UpgradeCandidate]:
    pkg = InstalledPackage(name="demo", version="1.0.0")
    info = PyPIInfo(
        name="demo",
        latest="1.3.0",
        releases={
            "1.0.1": [{"requires_python": None, "yanked": False}],
            "1.1.0": [{"requires_python": None, "yanked": False}],
            "1.2.0": [{"requires_python": None, "yanked": False}],
            "1.3.0": [{"requires_python": None, "yanked": False}],
        },
    )
    cand = UpgradeCandidate(
        package=pkg,
        info=info,
        options=[UpgradeOption(version=v) for v in ["1.3.0", "1.2.0", "1.1.0", "1.0.1"]],
    )
    return [cand]


@pytest.mark.asyncio
async def test_select_package_and_version_flow():
    app = PipUpgradeApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.screen.query_one(DataTable)
        assert len(table.rows) == 1

        # Space 选中包，默认选最新兼容版本
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}
        assert "demo==1.3.0" in str(app.screen.query_one("#summary", Static).content)

        # 取消勾选后再 Enter 打开弹窗（首次进入，自动跟随模式）
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, VersionModal)

        # 高亮下移 -> 自动跟随为 1.2.0，Enter 确认
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected == {"demo": "1.2.0"}
        assert "demo==1.2.0" in str(app.screen.query_one("#summary", Static).content)

        # q 退出
        await pilot.press("q")
    assert app.return_value is None


@pytest.mark.asyncio
async def test_remembers_selected_version_on_reopen():
    app = PipUpgradeApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}

        # 再次进入弹窗：应定位并选中当前已选版本 1.3.0
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, VersionModal)
        assert modal._selected == "1.3.0"
        await pilot.press("escape")
        await pilot.pause()

        # 已选模式下改选 1.2.0：需用 Space 手动圈选（高亮移动不再自动跟随）
        await pilot.press("enter")
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("space")
        await pilot.press("enter")
        await pilot.pause()
        assert app.selected == {"demo": "1.2.0"}

        # 再次进入：定位并选中已选的 1.2.0
        await pilot.press("enter")
        await pilot.pause()
        assert app.screen._selected == "1.2.0"  # type: ignore[attr-defined]
        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_execute_shows_confirm_modal():
    app = PipUpgradeApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}

        # 按 e 应弹出确认框（而不是 NoActiveWorker 崩溃）
        from pip_upgrade.ui.dialog import ConfirmModal

        await pilot.press("e")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmModal)

        # 按 n 取消：不执行、不退出
        await pilot.press("n")
        await pilot.pause()
        assert not isinstance(app.screen, ConfirmModal)
        assert app.return_value is None
        await pilot.press("q")


@pytest.mark.asyncio
async def test_space_toggle_unselects():
    app = PipUpgradeApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}
        await pilot.press("space")
        assert app.selected == {}
        await pilot.press("q")
