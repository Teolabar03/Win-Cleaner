"""Phones and other portable devices (MTP), reached through the Windows Shell.

A phone connected in "file transfer" mode has no drive letter: Windows shows it under This PC as a
portable device. Its folders are Shell items with opaque parsing paths, so the app gives them
readable paths (`mtp:\\Device\\Storage\\DCIM\\...`) and keeps a registry from those to the Shell's
parsing paths. Reading is much slower than on a disk (every folder is a round trip over USB) and
there is no Recycle Bin: deletion is always permanent.
"""

import contextlib
import logging
import subprocess

from . import rules
from .scanner import DOWNLOAD_NAMES, MARKER_NAMES, Cancelled, Node, Scanner, finish, walk

log = logging.getLogger(__name__)
THIS_PC = 17  # ssfDRIVES
PORTABLE = "\\\\?\\"  # parsing paths of portable devices contain a device interface path

# normalized readable path -> Shell parsing path, and -> size in bytes (filled by the scanner)
REGISTRY: dict[str, str] = {}
SIZES: dict[str, int] = {}
FILES: set[str] = set()  # registered entries that are files, not folders
ARCHIVE_EXTS = (".zip", ".cab")


@contextlib.contextmanager
def com():
    import pythoncom

    pythoncom.CoInitialize()
    try:
        yield
    finally:
        pythoncom.CoUninitialize()


def _shell():
    import win32com.client

    return win32com.client.Dispatch("Shell.Application")


def _number(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def register(readable: str, parsing: str) -> None:
    REGISTRY[rules.norm(readable)] = parsing


def parsing_path(readable: str) -> str | None:
    return REGISTRY.get(rules.norm(readable))


def devices() -> list[dict]:
    """One entry per storage of every connected portable device (a phone may have two: the
    internal memory and an SD card)."""
    found = []
    try:
        with com():
            computer = _shell().Namespace(THIS_PC)
            for device in computer.Items():
                if device.IsFileSystem or PORTABLE not in (device.Path or ""):
                    continue
                for storage in device.GetFolder.Items():
                    if not storage.IsFolder:
                        continue
                    readable = f"{rules.PHONE}{device.Name}\\{storage.Name}"
                    register(readable, storage.Path)
                    total = _number(storage.ExtendedProperty("System.Capacity"))
                    free = _number(storage.ExtendedProperty("System.FreeSpace"))
                    found.append({
                        "root": readable,
                        "letter": "",
                        "label": f"{device.Name} · {storage.Name}",
                        "device": device.Name,
                        "removable": True,
                        "phone": True,
                        "system": False,
                        "total": total,
                        "used": max(0, total - free),
                        "free": free,
                    })
    except Exception as error:  # noqa: BLE001 - no pywin32, no COM, device unplugged: no phones
        log.warning("portable devices not readable: %s", error)
        return []
    log.info("portable devices: %d storage(s)", len(found))
    return found


class PhoneScanner(Scanner):
    """Same output as the disk scanner (a Node tree plus loose files), read through the Shell."""

    def run(self) -> Node:
        root_path = self.root.rstrip("\\")
        parsing = parsing_path(root_path)
        if parsing is None:
            raise FileNotFoundError("Dispositivo non trovato: ricollegalo e aggiorna l'elenco.")
        name = root_path.rsplit("\\", 1)[-1]
        root = Node(root_path, name, None)
        progress = self.progress
        with com():
            shell = _shell()
            stack = [(root, parsing)]
            while stack:
                if self._cancel.is_set():
                    raise Cancelled()
                if self._stop.is_set():
                    progress.partial = True
                    break
                node, where = stack.pop()
                node.scanned = True
                progress.folders += 1
                progress.current = node.path[len(rules.PHONE):]
                folder = shell.Namespace(where)
                if folder is None:
                    node.denied = True
                    progress.denied += 1
                    continue
                in_downloads = node.name.lower() in DOWNLOAD_NAMES
                markers = set()
                try:
                    entries = list(folder.Items())
                except Exception:  # noqa: BLE001 - device busy or unplugged mid-scan
                    node.denied = True
                    progress.denied += 1
                    continue
                for entry in entries:
                    try:
                        entry_name = entry.Name
                        lower = entry_name.lower()
                        readable = f"{node.path}\\{entry_name}"
                        if lower in MARKER_NAMES:
                            markers.add(lower)
                        if entry.IsFolder and not lower.endswith(ARCHIVE_EXTS):
                            child = Node(readable, entry_name, node)
                            node.children.append(child)
                            register(readable, entry.Path)
                            stack.append((child, entry.Path))
                            continue
                        size = _number(entry.ExtendedProperty("System.Size")) or _number(entry.Size)
                        try:
                            mtime = entry.ModifyDate.timestamp()
                        except Exception:  # noqa: BLE001 - some devices do not report it
                            mtime = 0.0
                        kind = self.add_file(node, entry_name, lower, readable, size, mtime,
                                             in_downloads)
                        if kind:
                            register(readable, entry.Path)
                            SIZES[rules.norm(readable)] = size
                            FILES.add(rules.norm(readable))
                    except Exception:  # noqa: BLE001 - skip one unreadable entry
                        continue
                if markers:
                    node.markers = frozenset(markers)
        finish(root)
        for node in walk(root):
            SIZES[node.key] = node.size
        progress.current = ""
        progress.done = True
        return root


def exists(readable: str) -> bool:
    parsing = parsing_path(readable)
    if parsing is None:
        return False
    try:
        from win32com.shell import shell

        with com():
            shell.SHCreateItemFromParsingName(parsing, None, shell.IID_IShellItem)
        return True
    except Exception:  # noqa: BLE001
        return False


def delete(readable: str) -> None:
    """Permanent deletion through IFileOperation, as Explorer does on a phone."""
    import pythoncom
    from win32com.shell import shell, shellcon

    parsing = parsing_path(readable)
    if parsing is None:
        raise FileNotFoundError(readable)
    with com():
        operation = pythoncom.CoCreateInstance(
            shell.CLSID_FileOperation, None, pythoncom.CLSCTX_ALL, shell.IID_IFileOperation)
        operation.SetOperationFlags(
            shellcon.FOF_NOCONFIRMATION | shellcon.FOF_SILENT | shellcon.FOF_NOERRORUI
            | shellcon.FOF_NOCONFIRMMKDIR)
        item = shell.SHCreateItemFromParsingName(parsing, None, shell.IID_IShellItem)
        operation.DeleteItem(item, None)
        operation.PerformOperations()
        if operation.GetAnyOperationsAborted():
            raise OSError("Il dispositivo ha rifiutato l'eliminazione")
    for key in [k for k in REGISTRY if k == rules.norm(readable)
                or k.startswith(rules.norm(readable) + "\\")]:
        REGISTRY.pop(key, None)


def size(readable: str) -> int:
    return SIZES.get(rules.norm(readable), 0)


def open_in_explorer(readable: str) -> None:
    """Explorer cannot select an item inside a device: for a file, open its folder."""
    target = readable
    if rules.norm(target) in FILES:
        target = target.rsplit(chr(92), 1)[0]
    parsing = parsing_path(target)
    if parsing:
        subprocess.Popen(["explorer.exe", parsing])
