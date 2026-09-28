"""The phone path end to end, on a normal folder registered as a phone storage: the Shell
(Namespace/Items) and IFileOperation behave the same on file-system folders and on MTP devices."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from cleaner import app, deleter, grouping, mtp, rules

APP = Path(__file__).resolve().parents[1]
ROOT = rules.PHONE + "TestPhone\\Memoria interna"


@pytest.fixture
def phone():
    base = Path(tempfile.mkdtemp(dir=APP))
    files = {
        "DCIM/Camera/IMG_0001.jpg": 3,
        "DCIM/.thumbnails/t1.jpg": 2,
        "Android/data/com.example/cache/c.bin": 2,
        "Android/data/com.example/files/save.dat": 2,
        "Download/app-release.apk": 1,
        "LOST.DIR/frag1": 1,
    }
    for rel, mb in files.items():
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"0" * mb * rules.MB)
    mtp.register(ROOT, str(base))
    yield base
    shutil.rmtree(base, ignore_errors=True)


def scan(base):
    scanner = mtp.PhoneScanner(ROOT, big_file=100 * rules.MB)
    tree = scanner.run()
    return tree, grouping.build(tree, scanner.loose, min_item=int(0.5 * rules.MB))


def test_phone_scan_reads_everything(phone):
    tree, items = scan(phone)
    assert tree.size == 11 * rules.MB
    assert sum(i.size for i in items) == tree.size
    by_rule = {i.rule.id: i for i in items if i.rule}
    assert by_rule["phone-thumbs"].rule.precheck
    assert by_rule["phone-app-cache"].rule.precheck  # found inside the protected Android/data
    assert "phone-lost" in by_rule
    assert any(i.kind == "files" and i.path.lower().endswith(".apk") for i in items)
    app_data = [i for i in items if i.kind == "protected"]
    assert app_data and all(i.locked for i in app_data)


@pytest.mark.parametrize("rel", ["", "DCIM", "DCIM\\Camera", "Download", "Android", "Android\\data\\x"])
def test_phone_guard_refuses_main_folders(phone, rel):
    with pytest.raises(deleter.Refused):
        deleter.guard(ROOT + ("\\" + rel if rel else ""), APP)


def test_phone_delete_is_permanent_only(phone, tmp_path):
    tree, items = scan(phone)
    thumbs = next(i for i in items if i.rule and i.rule.id == "phone-thumbs")

    report = deleter.Report()
    deleter.run([thumbs], False, report, APP, tmp_path)
    assert (phone / "DCIM" / ".thumbnails").exists()
    assert report.errors and "Cestino" in report.errors[0]["error"]

    report = deleter.Report()
    deleter.run([thumbs], True, report, APP, tmp_path)
    assert not report.errors, report.errors
    assert not (phone / "DCIM" / ".thumbnails").exists()
    assert report.freed == 2 * rules.MB
    assert (phone / "DCIM" / "Camera" / "IMG_0001.jpg").exists()


def test_thresholds_shrink_on_small_drives():
    assert app.thresholds(2 * 1024**4)["min_item"] == 64 * rules.MB
    stick = app.thresholds(32 * 1024**3)
    assert 4 * rules.MB <= stick["min_item"] < 64 * rules.MB
    assert stick["big_file"] < 512 * rules.MB


def test_no_recycle_bin_detection(tmp_path):
    assert deleter.has_recycle_bin(str(tmp_path))  # fixed drive
    assert not deleter.has_recycle_bin(ROOT)
    assert os.path.splitdrive(str(tmp_path))[0]
