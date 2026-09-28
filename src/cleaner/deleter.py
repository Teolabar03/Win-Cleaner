"""Delete what the user confirmed: to the Recycle Bin by default, permanently on request.

`guard` runs on every path right before it is touched, independently of the UI and the model.
"""

import ctypes
import json
import os
import shutil
import stat
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from send2trash import send2trash

from . import mtp, rules


class Refused(Exception):
    pass


def guard(path: str, app_dir: Path, rule_root: str | None = None) -> None:
    """Refuse protected and critical paths. Inside a folder that a junk rule matches (such as
    the Temp folder of Windows) the protection of the surrounding system folder does not apply."""
    key = rules.norm(path)
    inside_rule = False
    if rule_root:
        root = rules.norm(rule_root)
        name = root.rsplit("\\", 1)[-1]
        inside = key == root or key.startswith(root + "\\")
        inside_rule = inside and rules.match(root, name) is not None
    reason = rules.critical(key) or (None if inside_rule else rules.protection(key))
    if reason:
        raise Refused(f"Percorso protetto ({reason})")
    if rules.is_phone(path):
        if not mtp.exists(path):
            raise FileNotFoundError(path)
        return
    # A junction, symlink or SUBST drive anywhere on the way could point somewhere else
    # (Windows, Documents): judge the real location, and refuse any redirection.
    if os.path.lexists(path):
        real = rules.norm(os.path.realpath(path))
        if real != key:
            raise Refused("Il percorso passa per un collegamento (giunzione o unità virtuale)")
    app = rules.norm(str(app_dir))
    if app == key or app.startswith(key + "\\") or key.startswith(app + "\\"):
        raise Refused("Contiene questo programma")
    if not os.path.lexists(path):
        raise FileNotFoundError(path)


@dataclass
class Report:
    total: int = 0
    done: int = 0
    freed: int = 0
    current: str = ""
    errors: list[dict] = field(default_factory=list)
    finished: bool = False
    log_path: str = ""


def has_recycle_bin(path: str) -> bool:
    """USB sticks and memory cards have no Recycle Bin: Windows would delete for good."""
    if rules.is_phone(path):
        return False
    drive = os.path.splitdrive(os.path.abspath(path))[0]
    if not drive or sys.platform != "win32":
        return False
    return ctypes.windll.kernel32.GetDriveTypeW(drive + "\\") == 3  # DRIVE_FIXED


def size_of(path: str) -> int:
    if rules.is_phone(path):
        return mtp.size(path)
    if os.path.isfile(path):
        return os.path.getsize(path)
    total = 0
    for directory, _, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(directory, name)).st_size
            except OSError:
                pass
    return total


def _make_writable_and_retry(function, path, _error):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def remove(path: str, permanent: bool) -> None:
    if not permanent and not has_recycle_bin(path):
        raise Refused("Questa unità non ha un Cestino: serve l'eliminazione definitiva")
    if rules.is_phone(path):
        mtp.delete(path)
    elif not permanent:
        send2trash(path)
    elif os.path.isdir(path) and not os.path.islink(path):
        errors = []

        def onexc(function, target, error):
            try:
                _make_writable_and_retry(function, target, error)
            except OSError as again:
                errors.append(f"{target}: {again.strerror or again}")

        shutil.rmtree(path, onexc=onexc)
        if errors:
            raise OSError(f"{len(errors)} file non eliminati (in uso o senza permessi). "
                          f"Primo: {errors[0]}")
    else:
        try:
            os.remove(path)
        except PermissionError:
            os.chmod(path, stat.S_IWRITE)
            os.remove(path)


def empty_recycle_bin(drive: str) -> None:
    # SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
    result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, drive[:2] + "\\", 0x1 | 0x2 | 0x4)
    if result not in (0, -2147418113):  # S_OK, E_UNEXPECTED when already empty
        raise OSError(f"Svuotamento del Cestino non riuscito (codice {result})")


def targets(item) -> list[tuple[str, str | None]]:
    """(path, junk-rule folder it lies in) for one item: the folders themselves, or their
    children when only the contents go."""
    folder_rule = item.rule is not None and item.kind in ("folder", "folders")
    result = []
    for folder in item.paths:
        root = folder if folder_rule else None
        if item.rule and item.rule.contents_only:
            try:
                result.extend((os.path.join(folder, n), root) for n in os.listdir(folder))
            except OSError:
                pass
        else:
            result.append((folder, root))
    return result


def run(items, permanent: bool, report: Report, app_dir: Path, log_dir: Path) -> None:
    plan = []
    # The Recycle Bin is emptied first, so what this run moves there is not purged with it.
    for item in items:
        if item.rule and item.rule.special == "recycle":
            plan.append((item, None, None))
    for item in items:
        if not (item.rule and item.rule.special == "recycle"):
            plan.extend((item, path, root) for path, root in targets(item))
    report.total = len(plan)
    log = []
    for item, path, root in plan:
        report.current = path or item.name
        entry = {"item": item.name, "path": path or item.path, "mode":
                 "definitiva" if permanent else "cestino"}
        try:
            if path is None:
                before = item.free
                empty_recycle_bin(item.path)
                report.freed += before
            else:
                guard(path, app_dir, root)
                before = size_of(path)
                remove(path, permanent)
                report.freed += before
            entry["result"] = "ok"
        except FileNotFoundError:
            entry["result"] = "già assente"
        except (OSError, Refused) as error:
            message = str(error) if isinstance(error, Refused) else (
                error.strerror or str(error))
            report.errors.append({"path": path or item.path, "error": message})
            entry["result"] = f"errore: {message}"
        log.append(entry)
        report.done += 1
    report.current = ""
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / time.strftime("pulizia_%Y%m%d_%H%M%S.json")
        log_file.write_text(json.dumps({"freed_bytes": report.freed, "operations": log},
                                       ensure_ascii=False, indent=1), encoding="utf-8")
        report.log_path = str(log_file)
    except OSError:
        pass
    report.finished = True


def open_in_explorer(path: str) -> None:
    import subprocess

    if sys.platform != "win32":
        return
    if rules.is_phone(path):
        mtp.open_in_explorer(path)
    elif os.path.exists(path):
        subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    else:
        parent = os.path.dirname(path)
        if os.path.isdir(parent):
            os.startfile(parent)
