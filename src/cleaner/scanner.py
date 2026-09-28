"""Map a drive into a tree of folders with aggregated sizes.

Only folders are kept in memory (a few hundred thousand on a full system drive). For files we keep
per-folder aggregates: count, bytes by extension, newest change and the few largest ones.
"""

import heapq
import os
import stat
import threading
import time
from dataclasses import dataclass, field

from . import rules

TOP_FILES = 6
# Files that report a size but live in the cloud (OneDrive placeholders) or are offline.
CLOUD_ATTRS = 0x00400000 | 0x00040000 | 0x00001000  # RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN | OFFLINE
REPARSE = stat.FILE_ATTRIBUTE_REPARSE_POINT
MARKER_NAMES = rules.PROJECT_MARKERS | {"pyvenv.cfg"}
DOWNLOAD_NAMES = {"downloads", "download"}


@dataclass(slots=True, eq=False)
class Node:
    path: str  # as found on disk
    name: str
    parent: "Node | None"
    children: list["Node"] = field(default_factory=list)
    files_size: int = 0
    files_count: int = 0
    size: int = 0  # whole subtree, filled by finish()
    count: int = 0
    newest: float = 0.0  # newest file change in the subtree
    ext: dict[str, int] = field(default_factory=dict)  # direct files: bytes by extension
    top: list[tuple[int, str, float]] = field(default_factory=list)  # min-heap of direct files
    markers: frozenset = frozenset()
    has_exe: bool = False  # an .exe and a .dll side by side: a program folder
    _bits: int = 0
    denied: bool = False
    scanned: bool = False  # this folder was read (a stopped scan leaves some unread)
    complete: bool = True  # the whole subtree was read, filled by finish()

    @property
    def key(self) -> str:
        return rules.norm(self.path)


@dataclass(slots=True)
class LooseFile:
    path: str
    size: int
    mtime: float
    kind: str  # "big" | "installer" | "dump"


@dataclass
class Progress:
    files: int = 0
    folders: int = 0
    bytes: int = 0
    denied: int = 0
    current: str = ""
    done: bool = False
    partial: bool = False  # stopped by the user: only part of the drive was read
    started: float = field(default_factory=time.time)


class Cancelled(Exception):
    pass


class Scanner:
    def __init__(self, root: str, big_file=512 * rules.MB):
        self.root = root if root.endswith("\\") else root + "\\"
        self.big_file = big_file
        self.progress = Progress()
        self.loose: list[LooseFile] = []
        self._cancel = threading.Event()
        self._stop = threading.Event()

    def cancel(self):
        """Abort: no results."""
        self._cancel.set()

    def stop(self):
        """Stop early and keep what was read so far."""
        self._stop.set()

    def run(self) -> Node:
        root = Node(self.root, self.root.rstrip("\\"), None)
        stack = [root]
        progress = self.progress
        tick = 0
        while stack:
            if self._cancel.is_set():
                raise Cancelled()
            if self._stop.is_set():
                progress.partial = True
                break
            node = stack.pop()
            node.scanned = True
            progress.folders += 1
            tick += 1
            if tick % 64 == 0:
                progress.current = node.path
            in_downloads = node.name.lower() in DOWNLOAD_NAMES
            try:
                entries = os.scandir(node.path)
            except OSError:
                node.denied = True
                progress.denied += 1
                continue
            markers = set()
            with entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(info, "st_file_attributes", 0)
                    lower = entry.name.lower()
                    if lower in MARKER_NAMES or lower.endswith((".sln", ".csproj")):
                        markers.add(lower)
                    if stat.S_ISDIR(info.st_mode):
                        if attrs & REPARSE:  # junctions and symlinks: counted where they point
                            continue
                        child = Node(entry.path, entry.name, node)
                        node.children.append(child)
                        stack.append(child)
                        continue
                    if attrs & REPARSE and not stat.S_ISREG(info.st_mode):
                        continue
                    size = 0 if attrs & CLOUD_ATTRS else info.st_size
                    self.add_file(node, entry.name, lower, entry.path, size, info.st_mtime,
                                  in_downloads)
            if markers:
                node.markers = frozenset(markers)
            node.has_exe = node._bits == 3
        finish(root)
        progress.current = ""
        progress.done = True
        return root

    def add_file(self, node: Node, name: str, lower: str, path: str, size: int, mtime: float,
                 in_downloads: bool) -> str | None:
        """Account one file in its folder. Returns the kind of loose item it became, if any."""
        node.files_count += 1
        node.files_size += size
        if mtime > node.newest:
            node.newest = mtime
        dot = lower.rfind(".")
        ext = lower[dot:] if dot > 0 and len(lower) - dot <= 12 else ""
        node.ext[ext] = node.ext.get(ext, 0) + size
        if ext == ".exe":
            node._bits |= 1
        elif ext == ".dll":
            node._bits |= 2
        item = (size, name, mtime)
        if len(node.top) < TOP_FILES:
            heapq.heappush(node.top, item)
        elif size > node.top[0][0]:
            heapq.heapreplace(node.top, item)
        self.progress.files += 1
        self.progress.bytes += size
        kind = None
        if size >= self.big_file:
            kind = "big"
        elif in_downloads and ext in rules.INSTALLER_EXTS:
            kind = "installer"
        elif ext in rules.DUMP_EXTS:
            kind = "dump"
        if kind:
            self.loose.append(LooseFile(path, size, mtime, kind))
        return kind


def finish(root: Node) -> None:
    """Aggregate sizes, counts and newest change bottom-up, without recursion."""
    order = []
    stack = [root]
    while stack:
        node = stack.pop()
        order.append(node)
        stack.extend(node.children)
    for node in reversed(order):
        node.size = node.files_size + sum(c.size for c in node.children)
        node.count = node.files_count + sum(c.count for c in node.children)
        node.complete = node.scanned and all(c.complete for c in node.children)
        newest = max((c.newest for c in node.children), default=0.0)
        if newest > node.newest:
            node.newest = newest


def walk(node: Node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


def summary(node: Node, limit_files=8, limit_folders=10) -> dict:
    """Extension mix, largest files and main subfolders of a subtree, for the model and the UI."""
    ext: dict[str, int] = {}
    largest: list[tuple[int, str, float]] = []
    for current in walk(node):
        for key, value in current.ext.items():
            ext[key] = ext.get(key, 0) + value
        for size, name, mtime in current.top:
            if len(largest) < limit_files:
                heapq.heappush(largest, (size, name, mtime))
            elif size > largest[0][0]:
                heapq.heapreplace(largest, (size, name, mtime))
    folders = sorted(node.children, key=lambda c: c.size, reverse=True)[:limit_folders]
    return {
        "ext": sorted(ext.items(), key=lambda kv: kv[1], reverse=True)[:8],
        "largest": sorted(largest, reverse=True),
        "folders": [(c.name, c.size) for c in folders],
    }
