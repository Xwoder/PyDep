"""resolver / packages 模块的单元测试。"""

from pip_upgrade.packages import InstalledPackage, PyPIInfo
from pip_upgrade.resolver import build_candidates


def make_info(name: str, latest: str, releases: dict[str, str | None]) -> PyPIInfo:
    """把 {版本: requires_python} 组装成 PyPIInfo。"""
    return PyPIInfo(
        name=name,
        latest=latest,
        releases={
            ver: [{"requires_python": rp, "yanked": False}] for ver, rp in releases.items()
        },
    )


def test_filters_requires_python():
    info = make_info(
        "numpy",
        "2.3.1",
        {
            "2.2.1": ">=3.10",
            "2.2.2": ">=3.10",
            "2.3.0": ">=3.11",
            "2.3.1": ">=3.11",
        },
    )
    pkg = InstalledPackage(name="numpy", version="2.2.0")
    cands = build_candidates([pkg], {"numpy": info}, "3.10")
    cand = cands[0]
    # 2.3.x 要求 Python >=3.11，当前 3.10 下应被过滤
    assert [o.version for o in cand.options] == ["2.2.2", "2.2.1"]
    assert cand.upgradable


def test_excludes_installed_and_lower_versions():
    info = make_info("demo", "2.0", {"1.0": None, "1.5": None, "2.0": None})
    pkg = InstalledPackage(name="demo", version="1.0")
    cand = build_candidates([pkg], {"demo": info}, "3.10")[0]
    assert [o.version for o in cand.options] == ["2.0", "1.5"]


def test_filters_prerelease_by_default():
    info = make_info("demo", "2.0", {"1.5": None, "2.0b1": None})
    pkg = InstalledPackage(name="demo", version="1.0")
    cand = build_candidates([pkg], {"demo": info}, "3.10")[0]
    assert [o.version for o in cand.options] == ["1.5"]

    cand_all = build_candidates([pkg], {"demo": info}, "3.10", allow_prerelease=True)[0]
    assert [o.version for o in cand_all.options] == ["2.0b1", "1.5"]


def test_allows_prerelease_when_installed_is_prerelease():
    info = make_info("demo", "2.0", {"1.5": None, "2.0rc1": None})
    pkg = InstalledPackage(name="demo", version="1.5b1")
    cand = build_candidates([pkg], {"demo": info}, "3.10")[0]
    assert [o.version for o in cand.options] == ["2.0rc1", "1.5"]


def test_hides_yanked_unless_no_alternative():
    info = PyPIInfo(
        name="demo",
        latest="1.2",
        releases={
            "1.1": [{"requires_python": None, "yanked": True}],
            "1.2": [{"requires_python": None, "yanked": False}],
        },
    )
    pkg = InstalledPackage(name="demo", version="1.0")
    cand = build_candidates([pkg], {"demo": info}, "3.10")[0]
    assert [o.version for o in cand.options] == ["1.2"]

    info2 = PyPIInfo(
        name="demo",
        latest="1.1",
        releases={"1.1": [{"requires_python": None, "yanked": True}]},
    )
    cand2 = build_candidates([pkg], {"demo": info2}, "3.10")[0]
    assert [o.version for o in cand2.options] == ["1.1"]


def test_missing_from_pypi():
    pkg = InstalledPackage(name="private-pkg", version="0.1")
    cands = build_candidates([pkg], {}, "3.10")
    assert not cands[0].on_pypi
    assert not cands[0].upgradable


def test_max_options_limit():
    info = make_info("demo", "9.0", {f"{i}.0": None for i in range(9, 0, -1)})
    pkg = InstalledPackage(name="demo", version="0.1")
    cand = build_candidates([pkg], {"demo": info}, "3.10", max_options=3)[0]
    assert len(cand.options) == 3
    assert cand.options[0].version == "9.0"
