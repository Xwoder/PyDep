"""TUI 冒烟测试：使用 Textual 的 pilot 驱动交互。"""

import pytest
from textual.widgets import DataTable, Label, ListView, Static

from pydep.environment import detect_environment
from pydep.packages import InstalledPackage, PyPIInfo
from pydep.resolver import UpgradeCandidate, UpgradeOption
from pydep.ui.app import PydepApp
from pydep.ui.version_list import VersionModal


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
    app = PydepApp(candidates=make_candidates(), env=detect_environment())
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
    app = PydepApp(candidates=make_candidates(), env=detect_environment())
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


def make_yanked_candidates() -> list[UpgradeCandidate]:
    """demo 的 1.2.0 已被发布者 yanked（撤回），1.3.0 正常。"""
    pkg = InstalledPackage(name="demo", version="1.0.0")
    info = PyPIInfo(
        name="demo",
        latest="1.3.0",
        releases={
            "1.2.0": [{"requires_python": None, "yanked": True}],
            "1.3.0": [{"requires_python": None, "yanked": False}],
        },
    )
    cand = UpgradeCandidate(
        package=pkg,
        info=info,
        options=[
            UpgradeOption(version="1.3.0"),
            UpgradeOption(version="1.2.0", yanked=True),
        ],
    )
    return [cand]


@pytest.mark.asyncio
async def test_version_modal_marks_yanked():
    """版本弹窗中，yanked 版本应标黄标记并带悬停说明。"""
    app = PydepApp(candidates=make_yanked_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, VersionModal)
        assert modal._yanked == {"1.2.0"}

        lv = modal.query_one("#version-list", ListView)
        labels = [child.query_one(Label) for child in lv.children]
        # yanked 版本（1.2.0）带 [yanked] 标记及悬停说明，正常版本（1.3.0）没有
        assert "[yanked]" in str(labels[1].content)
        assert "[yanked]" not in str(labels[0].content)
        assert labels[1].tooltip and "yanked" in str(labels[1].tooltip)
        assert not labels[0].tooltip

        await pilot.press("escape")
        await pilot.press("q")


def make_conflicted_candidates() -> list[UpgradeCandidate]:
    """websockets 升级到 16.0 会与 langgraph-sdk 的约束冲突。"""
    ws = InstalledPackage(name="websockets", version="15.0.1")
    lg = InstalledPackage(
        name="langgraph-sdk",
        version="0.4.2",
        requires=["websockets<16,>=14"],
    )
    info = PyPIInfo(
        name="websockets",
        latest="16.0",
        releases={
            "16.0": [{"requires_python": None, "yanked": False}],
            "15.1.0": [{"requires_python": None, "yanked": False}],
        },
    )
    cand_ws = UpgradeCandidate(
        package=ws,
        info=info,
        options=[UpgradeOption(version=v) for v in ["16.0", "15.1.0"]],
    )
    cand_lg = UpgradeCandidate(
        package=lg,
        info=PyPIInfo(name="langgraph-sdk", latest="0.4.2", releases={}),
        options=[],
    )
    return [cand_ws, cand_lg]


@pytest.mark.asyncio
async def test_version_modal_marks_conflicts():
    """版本弹窗中，与已安装包依赖冲突的版本应标红并带悬停详情。"""
    app = PydepApp(candidates=make_conflicted_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        # 光标默认在第一行（websockets），Enter 打开版本弹窗
        await pilot.press("enter")
        await pilot.pause()
        modal = app.screen
        assert isinstance(modal, VersionModal)
        # 16.0 与 langgraph-sdk 冲突，15.1.0 不冲突
        assert "16.0" in modal._conflicts
        assert "15.1.0" not in modal._conflicts

        lv = modal.query_one("#version-list", ListView)
        labels = [child.query_one(Label) for child in lv.children]
        # 冲突版本标红：内容带 [incompatible] 标记，且设置了悬停详情
        assert "[incompatible]" in str(labels[0].content)  # 16.0
        assert "[incompatible]" not in str(labels[1].content)  # 15.1.0
        assert labels[0].tooltip and "websockets<16,>=14" in str(labels[0].tooltip)
        assert not labels[1].tooltip

        await pilot.press("escape")
        await pilot.press("q")


@pytest.mark.asyncio
async def test_execute_shows_confirm_modal():
    app = PydepApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}

        # 按 e 应弹出确认框（而不是 NoActiveWorker 崩溃）
        from pydep.ui.dialog import ConfirmModal

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
    app = PydepApp(candidates=make_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("space")
        assert app.selected == {"demo": "1.3.0"}
        await pilot.press("space")
        assert app.selected == {}
        await pilot.press("q")


def make_mixed_candidates() -> list[UpgradeCandidate]:
    """demo 可升级；nosel 在 PyPI 但无更高版本；localpkg 不在 PyPI。"""
    demo = make_candidates()[0]
    nosel = UpgradeCandidate(
        package=InstalledPackage(name="nosel", version="1.0.0"),
        info=PyPIInfo(
            name="nosel",
            latest="1.0.0",
            releases={"1.0.0": [{"requires_python": None, "yanked": False}]},
        ),
        options=[],
    )
    local = UpgradeCandidate(
        package=InstalledPackage(name="localpkg", version="0.1.0"),
        info=None,
        options=[],
    )
    return [demo, nosel, local]


@pytest.mark.asyncio
async def test_filter_upgradable_toggle():
    """按 f 仅显示可升级的包；再次按下恢复显示全部。"""
    app = PydepApp(candidates=make_mixed_candidates(), env=detect_environment())
    async with app.run_test() as pilot:
        await pilot.pause()
        screen = app.screen
        table = screen.query_one(DataTable)
        assert len(table.rows) == 3

        # 第一次按 f：只剩可升级的 demo
        await pilot.press("f")
        await pilot.pause()
        assert len(table.rows) == 1
        assert "demo" in screen._row_key_by_name
        assert "nosel" not in screen._row_key_by_name
        assert "localpkg" not in screen._row_key_by_name

        # 再次按 f：恢复全部
        await pilot.press("f")
        await pilot.pause()
        assert len(table.rows) == 3

        await pilot.press("q")
