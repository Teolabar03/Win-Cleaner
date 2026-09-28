"""Window and bridge: the HTML interface calls the methods of `Api` through pywebview."""

import ctypes
import logging
import os
import sys
import threading
import time
import traceback
from pathlib import Path

from . import classifier as clf
from . import deleter, grouping, mtp, rules
from .scanner import Cancelled, Scanner

APP_NAME = "Pulizia disco"


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def ui_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", base_dir())) / "cleaner" / "ui"
    return Path(__file__).resolve().parent / "ui"


def ai_dir() -> Path:
    """Model and llama.cpp runtimes: `ai/` next to the exe; in development, rizzo-flow."""
    override = os.environ.get("CLEANER_AI_DIR")
    if override:
        return Path(override)
    local = base_dir() / "ai"
    if local.is_dir():
        return local
    return base_dir().parent / "rizzo-flow"


def system_theme() -> dict:
    accent, dark = "#0067c0", False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            value = winreg.QueryValueEx(key, "AccentColor")[0] & 0xFFFFFFFF
            r, g, b = value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF
            accent = f"#{r:02x}{g:02x}{b:02x}"
        path = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            dark = winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except OSError:
        pass
    return {"accent": accent, "dark": dark}


def drives(phones: bool = True) -> list[dict]:
    """Fixed and removable drives with a letter, then the storages of connected phones."""
    result = []
    kernel = ctypes.windll.kernel32
    for root in os.listdrives():
        kind = kernel.GetDriveTypeW(root)
        if kind not in (2, 3):  # removable, fixed
            continue
        try:
            import shutil

            usage = shutil.disk_usage(root)
        except OSError:
            continue
        label = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        kernel.GetVolumeInformationW(root, label, 261, None, None, None, fs, 261)
        letter = root[:2]
        system = letter.lower() == rules.SYSTEM_DRIVE
        result.append({
            "root": root,
            "letter": letter,
            "label": label.value or ("Disco locale" if kind == 3 else "Disco rimovibile"),
            "removable": kind == 2,
            "phone": False,
            "system": system,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
        })
    if phones:
        result.extend(mtp.devices())
    for drive in result:
        drive["trash"] = not (drive["removable"] or drive["phone"])
    return result


def thresholds(total: int) -> dict:
    """Smaller items on smaller drives, so a 32 GB stick still gives a useful list:
    1/2000 of the drive for folders (4-64 MB), 1/256 for single big files (32-512 MB)."""
    total = total or 0
    return {
        "min_item": min(64 * rules.MB, max(4 * rules.MB, total // 2000)),
        "big_file": min(512 * rules.MB, max(32 * rules.MB, total // 256)),
    }


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


class Api:
    def __init__(self):
        self._classifier = clf.Classifier(ai_dir())
        self._classifier.start()
        self._lock = threading.Lock()
        self._scanner = None
        self._items = []
        self._by_id = {}
        self._drive = None
        self._phase = "idle"
        self._error = None
        self._classify = {"total": 0, "done": 0, "current": ""}
        self._skip = threading.Event()
        self._report = None

    # --- start-up ---------------------------------------------------------------------------

    def system_info(self):
        found = drives()
        logging.info("drives: %s", [d["root"] for d in found])
        return {
            "theme": system_theme(),
            "drives": found,
            "model": self._classifier.status,
            "admin": is_admin(),
            "app_dir": str(base_dir()),
        }

    def model_status(self):
        return self._classifier.status

    # --- analysis ---------------------------------------------------------------------------

    def start(self, root):
        with self._lock:
            if self._phase in ("scanning", "waiting-model", "classifying", "deleting"):
                return False
            self._drive = next((d for d in drives(phones=rules.is_phone(root))
                                if d["root"] == root), None)
            if self._drive is None:
                return False
            self._limits = thresholds(self._drive["total"])
            scanner = mtp.PhoneScanner if self._drive["phone"] else Scanner
            self._scanner = scanner(root, big_file=self._limits["big_file"])
            self._items, self._by_id, self._error = [], {}, None
            self._skip.clear()
            self._classify = {"total": 0, "done": 0, "current": ""}
            self._phase = "scanning"
        threading.Thread(target=self._analyse, name="analysis", daemon=True).start()
        return True

    def _analyse(self):
        try:
            tree = self._scanner.run()
            items = grouping.build(tree, self._scanner.loose,
                                   min_item=self._limits["min_item"])
            self._phase = "waiting-model"
            deadline = time.time() + 120
            while not self._classifier.wait(0.2) and not self._skip.is_set():
                if time.time() > deadline:
                    break
            self._phase = "classifying"
            engine_ok = self._classifier.engine is not None
            clf.classify_all(items, self._classifier if engine_ok else None, self._classify,
                             self._skip)
            self._items = items
            self._by_id = {i.id: i for i in items}
            self._phase = "done"
        except Cancelled:
            self._phase = "idle"
        except Exception as error:  # noqa: BLE001 - shown to the user
            logging.exception("analysis failed")
            traceback.print_exc()
            self._error = str(error)
            self._phase = "error"

    def status(self):
        progress = self._scanner.progress if self._scanner else None
        elapsed = time.time() - progress.started if progress else 0
        return {
            "phase": self._phase,
            "error": self._error,
            "scan": {
                "files": progress.files,
                "folders": progress.folders,
                "bytes": progress.bytes,
                "denied": progress.denied,
                "current": progress.current,
                "elapsed": elapsed,
                "partial": progress.partial,
            } if progress else None,
            "classify": {k: v for k, v in self._classify.items() if k != "started"},
            "model": self._classifier.status,
        }

    def stop_scan(self):
        """Phase 1: stop mapping and go on with the part already read."""
        if self._scanner and self._phase == "scanning":
            self._scanner.stop()
        return True

    def skip_ai(self):
        """Phase 2: stop classifying; the rest is judged by the rules only."""
        self._skip.set()
        return True

    def cancel(self):
        if self._scanner:
            self._scanner.cancel()
        self._skip.set()
        return True

    def results(self):
        items = self._items
        folders = {rules.norm(i.paths[0]): i.id for i in items
                   if i.kind == "folder" and i.paths}
        payload = []
        for item in items:
            ancestors = []
            if item.paths:
                current = rules.norm(item.paths[0])
                while True:
                    parent = os.path.dirname(current)
                    if parent == current:
                        break
                    current = parent
                    if current in folders and folders[current] != item.id:
                        ancestors.append(folders[current])
            payload.append({
                "id": item.id,
                "kind": item.kind,
                "name": item.name,
                "path": item.path,
                "size": item.size,
                "free": item.free,
                "count": item.count,
                "newest": item.newest,
                "category": item.category,
                "p_category": item.p_category,
                "p_delete": item.p_delete,
                "checked": item.checked,
                "advice": item.advice,
                "source": item.source,
                "locked": item.locked,
                "rule": item.rule.label if item.rule else None,
                "contents_only": bool(item.rule and item.rule.contents_only),
                "special": item.rule.special if item.rule else None,
                "unit": item.unit,
                "paths": item.paths[:500],
                "ancestors": ancestors,
            })
        return {
            "drive": self._drive,
            "items": payload,
            "categories": [{"id": c, "label": label} for c, label, _ in clf.CATEGORIES],
            "model": self._classifier.status,
            "denied": self._scanner.progress.denied if self._scanner else 0,
            "classified": self._classify.get("done", 0),
            "to_classify": self._classify.get("total", 0),
            "ai_stopped": self._skip.is_set(),
            "partial_scan": bool(self._scanner and self._scanner.progress.partial),
            "admin": is_admin(),
        }

    # --- actions ----------------------------------------------------------------------------

    def open_path(self, path):
        deleter.open_in_explorer(path)
        return True

    def open_log_folder(self):
        folder = base_dir() / "registri"
        folder.mkdir(exist_ok=True)
        os.startfile(folder)
        return True

    def delete(self, ids, permanent):
        with self._lock:
            if self._phase != "done" or (self._report and not self._report.finished):
                return 0
            if not permanent and self._drive and not self._drive["trash"]:
                return 0  # no Recycle Bin here: the interface only offers permanent deletion
        chosen = [self._by_id[i] for i in ids if i in self._by_id]
        chosen = [i for i in chosen if i.paths and not i.locked]
        # A selected folder already covers the items inside it.
        roots = {rules.norm(i.paths[0]) for i in chosen if i.kind == "folder"}

        def covered(item):
            if item.kind == "files":
                return False
            key = rules.norm(item.paths[0])
            return any(key.startswith(root + "\\") for root in roots)

        chosen = [i for i in chosen if not covered(i)]
        self._report = deleter.Report()
        threading.Thread(
            target=deleter.run,
            args=(chosen, bool(permanent), self._report, base_dir(), base_dir() / "registri"),
            name="delete", daemon=True,
        ).start()
        return len(chosen)

    def delete_status(self):
        report = self._report
        if report is None:
            return None
        return {
            "total": report.total,
            "done": report.done,
            "freed": report.freed,
            "current": report.current,
            "errors": report.errors[-200:],
            "error_count": len(report.errors),
            "finished": report.finished,
            "log_path": report.log_path,
            "drive": next((d for d in drives(phones=bool(self._drive and self._drive["phone"]))
                           if self._drive and d["root"] == self._drive["root"]), None)
            if report.finished else None,
        }


def main():
    import webview

    if getattr(sys, "frozen", False):
        os.chdir(base_dir())
    logs = base_dir() / "registri"
    try:
        logs.mkdir(exist_ok=True)
        logging.basicConfig(filename=logs / "cleaner.log", level=logging.INFO, encoding="utf-8",
                            format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    except OSError:
        pass
    logging.info("start, ai dir %s", ai_dir())
    theme = system_theme()
    api = Api()
    window = webview.create_window(
        APP_NAME,
        str(ui_dir() / "index.html"),
        js_api=api,
        width=1240,
        height=820,
        min_size=(960, 640),
        background_color="#202020" if theme["dark"] else "#f3f3f3",
        text_select=False,
    )
    webview.start(debug=bool(os.environ.get("CLEANER_DEBUG")), private_mode=True)
    return window


if __name__ == "__main__":
    main()
