import os
from pathlib import Path

import pytest

from cleaner import deleter, grouping, rules
from cleaner.scanner import Scanner

PROFILE = os.environ["USERPROFILE"]
WINDIR = os.environ.get("WINDIR", r"C:\Windows")
APP = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("path", [
    "C:\\",
    WINDIR,
    WINDIR + r"\System32",
    r"C:\Program Files",
    r"C:\Program Files\Some App",
    r"C:\ProgramData\Microsoft",
    r"C:\Users",
    PROFILE,
    PROFILE + r"\Desktop",
    PROFILE + r"\Documents",
    PROFILE + r"\Downloads",
    PROFILE + r"\AppData",
    PROFILE + r"\AppData\Local",
    PROFILE + r"\AppData\Local\Programs\Some App",
    r"D:\WindowsApps\x",
])
def test_guard_refuses_protected_and_critical(path):
    with pytest.raises((deleter.Refused, FileNotFoundError)) as error:
        deleter.guard(path, APP)
    assert error.type is deleter.Refused


def test_guard_refuses_the_app_itself():
    with pytest.raises(deleter.Refused):
        deleter.guard(str(APP / "src"), APP)
    with pytest.raises(deleter.Refused):
        deleter.guard(str(APP.parent), APP)


def test_rule_opens_only_its_own_system_folder(tmp_path):
    temp = WINDIR + r"\Temp"
    inside = temp + r"\something.log"
    # inside the Windows Temp rule the Windows protection does not apply
    try:
        deleter.guard(inside, APP, temp)
    except FileNotFoundError:
        pass
    # the same rule root does not open another system folder
    with pytest.raises(deleter.Refused):
        deleter.guard(WINDIR + r"\System32\x.dll", APP, temp)
    # a made-up rule root does not open anything
    with pytest.raises(deleter.Refused):
        deleter.guard(WINDIR + r"\System32\x.dll", APP, WINDIR + r"\System32")


def test_rules_match_known_junk():
    assert rules.match(rules.norm(PROFILE + r"\AppData\Local\Temp"), "temp").contents_only
    assert rules.match(rules.norm(PROFILE + r"\AppData\Roaming\App\Cache"), "cache").precheck
    project = frozenset({"package.json"})
    assert rules.match(r"c:\work\site\node_modules", "node_modules", parent_markers=project)
    assert rules.match(r"c:\work\site\node_modules", "node_modules") is None
    tool = rules.norm(PROFILE + r"\AppData\Local\tool\node_modules")
    assert rules.match(tool, "node_modules", parent_markers=project) is None
    # outside AppData a folder called "cache" is not junk by name alone
    assert rules.match(r"c:\photos\cache", "cache") is None
    assert rules.match(WINDIR.lower() + r"\system32\cache", "cache", system_only=True) is None


def test_delete_to_trash_and_permanently(tmp_path):
    keep = tmp_path / "keep.txt"
    keep.write_text("x")
    trash_dir = tmp_path / "old_cache"
    trash_dir.mkdir()
    (trash_dir / "a.bin").write_bytes(b"0" * 1000)
    gone = tmp_path / "build"
    (gone / "sub").mkdir(parents=True)
    ro = gone / "sub" / "readonly.bin"
    ro.write_bytes(b"1" * 500)
    os.chmod(ro, 0o444)

    item_a = grouping.Item(id="0", kind="folder", name="a", path=str(trash_dir),
                           paths=[str(trash_dir)], size=1000, free=1000, count=1, newest=0)
    item_b = grouping.Item(id="1", kind="folder", name="b", path=str(gone), paths=[str(gone)],
                           size=500, free=500, count=1, newest=0)

    report = deleter.Report()
    deleter.run([item_a], False, report, APP, tmp_path / "logs")
    assert not trash_dir.exists() and report.freed == 1000 and not report.errors

    report = deleter.Report()
    deleter.run([item_b], True, report, APP, tmp_path / "logs")
    assert not gone.exists() and report.freed == 500 and not report.errors
    assert keep.exists()
    assert len(list((tmp_path / "logs").glob("pulizia_*.json"))) >= 1


def test_contents_only_keeps_the_folder(tmp_path, monkeypatch):
    folder = tmp_path / "Temp"
    folder.mkdir()
    (folder / "x.tmp").write_bytes(b"0" * 10)
    (folder / "d").mkdir()
    item = grouping.Item(id="0", kind="folder", name="t", path=str(folder), paths=[str(folder)],
                         size=10, free=10, count=1, newest=0, rule=rules.TEMP)
    report = deleter.Report()
    deleter.run([item], True, report, APP, tmp_path / "logs")
    assert folder.is_dir() and not any(folder.iterdir())


@pytest.fixture
def outside_appdata():
    import shutil
    import tempfile

    root = Path(tempfile.mkdtemp(dir=APP))  # pytest's own tmp_path lives inside AppData
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_grouping_accounts_for_every_byte(outside_appdata):
    tmp_path = outside_appdata
    project = tmp_path / "proj"
    (project / "node_modules" / "lib").mkdir(parents=True)
    (project / "package.json").write_text("{}")
    (project / "node_modules" / "lib" / "big.js").write_bytes(b"0" * 3 * rules.MB)
    (project / "src").mkdir()
    (project / "src" / "main.js").write_bytes(b"0" * 2 * rules.MB)
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(b"0" * 5 * rules.MB)
    scanner = Scanner(str(tmp_path))
    tree = scanner.run()
    items = grouping.build(tree, scanner.loose, min_item=4 * rules.MB)
    assert sum(i.size for i in items) == tree.size
    by_name = {i.name: i for i in items}
    assert "Dipendenze di un progetto JavaScript" in by_name
    proj = next(i for i in items if i.unit == "project")
    assert proj.free == tree.children[[c.name for c in tree.children].index("proj")].size


def test_guard_refuses_paths_through_a_junction(outside_appdata):
    import subprocess

    precious = outside_appdata / "documents"
    precious.mkdir()
    (precious / "thesis.docx").write_text("do not delete")
    link = outside_appdata / "cache"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(precious)], check=True,
                   capture_output=True)
    with pytest.raises(deleter.Refused):
        deleter.guard(str(link / "thesis.docx"), APP)
    with pytest.raises(deleter.Refused):
        deleter.guard(str(link), APP)
    item = grouping.Item(id="0", kind="folder", name="c", path=str(link), paths=[str(link)],
                         size=1, free=1, count=1, newest=0, rule=rules.TEMP)
    report = deleter.Report()
    deleter.run([item], True, report, APP, outside_appdata / "logs")
    assert (precious / "thesis.docx").exists()
    assert report.errors


def test_recycle_bin_is_emptied_before_recycling(tmp_path, monkeypatch):
    order = []
    monkeypatch.setattr(deleter, "empty_recycle_bin", lambda drive: order.append("empty"))
    monkeypatch.setattr(deleter, "remove", lambda path, permanent: order.append("remove"))
    victim = tmp_path / "old"
    victim.mkdir()
    normal = grouping.Item(id="0", kind="folder", name="o", path=str(victim), paths=[str(victim)],
                           size=1, free=1, count=1, newest=0)
    recycle = grouping.Item(id="1", kind="folder", name="r", path=r"C:\$Recycle.Bin",
                            paths=[r"C:\$Recycle.Bin"], size=1, free=1, count=1, newest=0,
                            rule=rules.ROOT_RULES["$recycle.bin"])
    deleter.run([normal, recycle], False, deleter.Report(), APP, tmp_path / "logs")
    assert order == ["empty", "remove"]


def test_folders_read_in_part_cannot_be_selected(outside_appdata):
    from cleaner.scanner import finish, walk

    big = outside_appdata / "videos"
    (big / "inner").mkdir(parents=True)
    (big / "a.mp4").write_bytes(b"0" * 5 * rules.MB)
    (big / "inner" / "b.mp4").write_bytes(b"0" * 2 * rules.MB)
    scanner = Scanner(str(outside_appdata))
    tree = scanner.run()
    for node in walk(tree):
        if node.name == "inner":
            node.scanned = False  # as if the user stopped the scan before reading it
    finish(tree)
    items = grouping.build(tree, scanner.loose, min_item=4 * rules.MB)
    videos = next(i for i in items if i.name == "videos")
    assert videos.locked and "interrotta" in videos.locked


def test_stop_keeps_what_was_read(outside_appdata):
    (outside_appdata / "a").mkdir()
    scanner = Scanner(str(outside_appdata))
    scanner.stop()
    tree = scanner.run()
    assert scanner.progress.partial and scanner.progress.done
    assert not tree.complete
