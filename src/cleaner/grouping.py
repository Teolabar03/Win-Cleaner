"""Turn the folder tree into a few hundred items the user can reason about (and the model can
classify in seconds): known junk folders, projects, apps, big files, the largest plain folders.

Every byte of the drive belongs to exactly one item (`size`), so charts add up. `free` is what
deleting the item releases: for a folder, the whole subtree, junk items inside included.
"""

import os
import time
from dataclasses import dataclass, field

from . import rules
from .scanner import LooseFile, Node

MIN_ITEM = 64 * rules.MB
MIN_RULE = 1 * rules.MB
MAX_DEPTH = 8


@dataclass(eq=False)
class Item:
    id: str
    kind: str  # folder | folders | file | files | rest | protected
    name: str
    path: str  # what "open" shows
    paths: list[str]  # what "delete" removes
    size: int
    free: int
    count: int
    newest: float
    node: Node | None = None
    rule: rules.Rule | None = None
    unit: str | None = None
    locked: str | None = None  # why it cannot be selected
    files: list[LooseFile] = field(default_factory=list)
    context: Node | None = None  # the app or project a junk folder belongs to
    members: list[Node] = field(default_factory=list)  # merged folders (kind "folders")
    # filled by the classifier
    category: str = "other"
    p_category: float | None = None
    p_delete: float | None = None
    checked: bool = False
    advice: str = ""
    source: str = "regole"

    @property
    def stale_days(self) -> float:
        return (time.time() - self.newest) / 86400 if self.newest else 0.0


class Builder:
    def __init__(self, loose: list[LooseFile], min_item=MIN_ITEM, max_depth=MAX_DEPTH):
        self.items: list[Item] = []
        self.min_item = min_item
        self.max_depth = max_depth
        self.loose_by_dir: dict[str, list[LooseFile]] = {}
        for entry in loose:
            self.loose_by_dir.setdefault(rules.norm(os.path.dirname(entry.path)), []).append(entry)
        self.installers: list[LooseFile] = []
        self.dumps: list[LooseFile] = []

    def add(self, **fields) -> Item:
        node = fields.get("node")
        if node is not None and not node.complete and fields.get("paths"):
            # Deleting a folder that was read only in part would remove what nobody has seen.
            fields["locked"] = "Mappatura interrotta prima di leggere tutta la cartella"
        item = Item(id=str(len(self.items)), **fields)
        self.items.append(item)
        return item

    # --- emitters -------------------------------------------------------------------------

    def rule_item(self, node: Node, rule: rules.Rule, context: Node | None = None) -> int:
        if node.size < MIN_RULE:
            return 0
        self.add(kind="folder", name=rule.label, path=node.path, paths=[node.path],
                 size=node.size, free=node.size, count=node.count, newest=node.newest,
                 node=node, rule=rule, category=rule.category, context=context)
        return node.size

    def rules_only(self, node: Node, context: Node | None = None, system_only=False) -> int:
        """Claim the junk folders inside a region that is otherwise kept whole."""
        key = node.key
        rule = rules.match(key, key.rsplit("\\", 1)[-1], node.markers,
                           node.parent.markers if node.parent else frozenset(), system_only)
        if rule:
            return self.rule_item(node, rule, context)
        return sum(self.rules_only(c, context, system_only)
                   for c in node.children if c.size >= MIN_RULE)

    def protected(self, node: Node, reason: str) -> int:
        category = ("programs" if reason.startswith("Programmi") or "App dello Store" in reason
                    else "appdata" if reason.startswith("Dati condivisi") else "system")
        claimed = 0
        for child in sorted(node.children, key=lambda c: c.size, reverse=True):
            inside = self.rules_only(child, system_only=True)
            if child.size - inside >= self.min_item:
                self.add(kind="protected", name=child.name, path=child.path, paths=[],
                         size=child.size - inside, free=0, count=child.count,
                         newest=child.newest, node=child, locked=reason, category=category)
                inside = child.size
            claimed += inside
        rest = node.size - claimed
        if rest > 0:
            self.add(kind="protected", name=node.name, path=node.path, paths=[], size=rest,
                     free=0, count=node.count, newest=node.newest, node=node, locked=reason,
                     category=category)
        return node.size

    # --- the walk -------------------------------------------------------------------------

    def visit(self, node: Node, depth: int) -> int:
        """Bytes of `node` claimed by emitted items; the rest is left to the parent."""
        key = node.key
        name = key.rsplit("\\", 1)[-1]
        parent_markers = node.parent.markers if node.parent else frozenset()
        is_root = node.parent is None
        if not is_root:
            rule = rules.match(key, name, node.markers, parent_markers)
            if rule:
                return self.rule_item(node, rule)
            reason = rules.protection(key)
            if reason:
                return self.protected(node, reason)
        if node.size < MIN_RULE:
            return 0
        unit = None if is_root else rules.unit_kind(key, name, node.markers, node.has_exe)
        claimed = 0
        if not unit:
            for loose in self.loose_by_dir.get(key, []):
                claimed += self.loose_file(loose)
        if unit or depth >= self.max_depth:
            context = node if unit else None
            claimed += sum(self.rules_only(c, context) for c in node.children
                           if c.size >= MIN_RULE)
        else:
            claimed += sum(self.visit(c, depth + 1) for c in node.children)
        rest = node.size - claimed
        if is_root:
            if rest > 0:
                self.add(kind="rest", name="File sparsi in cartelle piccole", path=node.path,
                         paths=[], size=rest, free=0, count=0, newest=0, node=None,
                         locked="Insieme di tante cartelle piccole: non si elimina in blocco",
                         category="other")
            return node.size
        whole = claimed == 0 or unit is not None
        if rest >= self.min_item or (unit and rest >= MIN_RULE):
            if whole:
                self.add(kind="folder", name=node.name, path=node.path, paths=[node.path],
                         size=rest, free=node.size, count=node.count, newest=node.newest,
                         node=node, unit=unit, locked=rules.critical(key))
            else:
                self.add(kind="rest", name=f"Altri file in {node.name}", path=node.path,
                         paths=[], size=rest, free=0, count=node.files_count,
                         newest=node.newest, node=node,
                         locked="Contenuto misto della cartella: aprila per scegliere a mano")
            return node.size
        return claimed

    def loose_file(self, loose: LooseFile) -> int:
        key = rules.norm(loose.path)
        if loose.kind == "installer":
            self.installers.append(loose)
            return loose.size
        if loose.kind == "dump":
            self.dumps.append(loose)
            return loose.size
        reason = rules.protected_file(key)
        folder = os.path.basename(os.path.dirname(key))
        installer = (folder in ("downloads", "download")
                     and os.path.splitext(key)[1] in rules.INSTALLER_EXTS)
        self.add(kind="file", name=os.path.basename(loose.path), path=loose.path,
                 paths=[] if reason else [loose.path], size=loose.size,
                 free=0 if reason else loose.size, count=1, newest=loose.mtime, locked=reason,
                 rule=INSTALLERS if installer else None,
                 category="system" if reason else ("installers" if installer else "other"))
        return loose.size

    def groups(self):
        for files, name, category, rule in (
            (self.installers, "Programmi di installazione scaricati", "installers", INSTALLERS),
            (self.dumps, "File di dump di arresti anomali", "logs", DUMPS),
        ):
            total = sum(f.size for f in files)
            if not files or total < MIN_RULE:
                continue
            files.sort(key=lambda f: f.size, reverse=True)
            self.add(kind="files", name=name, path=files[0].path, paths=[f.path for f in files],
                     size=total, free=total, count=len(files),
                     newest=max(f.mtime for f in files), files=list(files), rule=rule,
                     category=category)


INSTALLERS = rules.Rule(
    "installers", "installers", "Programmi di installazione scaricati",
    "Di solito sono setup già usati, ma tra questi possono esserci programmi portatili: "
    "controlla prima di eliminare.",
    "Setup and installer files found in a Downloads folder.")
DUMPS = rules.Rule(
    "dumps", "logs", "File di dump", "Istantanee di memoria di programmi andati in crash.",
    "Crash dump files.", precheck=True)


def merge(items: list[Item]) -> list[Item]:
    """One item per (rule, app or project) instead of dozens of small cache folders."""
    groups: dict[tuple[str, str], list[Item]] = {}
    for item in items:
        if item.rule and item.context is not None and item.kind == "folder":
            groups.setdefault((item.rule.id, item.context.key), []).append(item)
    merged = set()
    result = []
    for members in groups.values():
        if len(members) < 2:
            continue
        first = members[0]
        merged.update(id(m) for m in members)
        result.append(Item(
            id="", kind="folders", name=f"{first.rule.label} · {first.context.name}",
            path=first.context.path, paths=[m.path for m in members],
            size=sum(m.size for m in members), free=sum(m.free for m in members),
            count=sum(m.count for m in members), newest=max(m.newest for m in members),
            rule=first.rule, category=first.category, context=first.context,
            locked=next((m.locked for m in members if m.locked), None),
            members=[m.node for m in members if m.node is not None]))
    result.extend(i for i in items if id(i) not in merged)
    for index, item in enumerate(result):
        item.id = str(index)
    return result


def build(root: Node, loose: list[LooseFile], **options) -> list[Item]:
    builder = Builder(loose, **options)
    builder.visit(root, 0)
    builder.groups()
    return merge(builder.items)
