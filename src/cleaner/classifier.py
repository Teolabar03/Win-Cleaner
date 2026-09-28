"""Classify items with Rizzo Flow (in-process, llama.cpp) and decide the pre-selection.

The model sees a compact description of each item (path, size, age, file types, names) and
answers two questions in one forward pass over the shared state: which category, and whether
deleting it is safe. Without a model the app still works on rules and file-type heuristics.
"""

import logging
import os
import threading
import time
from pathlib import Path

from . import rules
from .grouping import Item
from .scanner import summary

log = logging.getLogger(__name__)

# id, label shown to the user, description given to the model
CATEGORIES = [
    ("cache", "Cache e file temporanei",
     "Cache or temporary data that a program re-creates automatically (browser cache, shader "
     "cache, thumbnails, temp files)."),
    ("logs", "Registri e rapporti di errore",
     "Log files, crash dumps or diagnostic and error reports."),
    ("installers", "Programmi di installazione",
     "Installer or setup packages already downloaded (.exe, .msi, .iso) or downloaded updates."),
    ("dev", "File di sviluppo rigenerabili",
     "Software development dependencies, package caches or build output that can be "
     "regenerated (node_modules, virtual environments, build folders)."),
    ("backup", "Backup e versioni precedenti",
     "Backups, old versions or leftovers of previous installations and upgrades."),
    ("projects", "Progetti software",
     "A software project or source code the user works on (a repository, a solution, an app "
     "being developed), even if it also contains build files."),
    ("documents", "Documenti",
     "Personal documents and work files: office documents, PDFs, spreadsheets, notes."),
    ("media", "Foto, video e musica", "Personal photos, videos or music."),
    ("games", "Giochi", "Installed video games and their data."),
    ("programs", "Programmi", "Installed applications and their program files."),
    ("appdata", "Dati delle app",
     "Settings, profiles, databases, mailboxes or saved data of applications."),
    ("archives", "Archivi e immagini disco",
     "Compressed archives or disk images (zip, rar, 7z, iso, vhdx) and virtual machines."),
    ("system", "Sistema", "Operating system files."),
    ("other", "Altro", "Something else, or it cannot be told from the evidence."),
]
LABELS = {cid: label for cid, label, _ in CATEGORIES}
JUNK = {"cache", "logs", "installers", "dev", "backup"}

EXT_FAMILIES = {
    "media": {".jpg", ".jpeg", ".png", ".heic", ".gif", ".webp", ".raw", ".cr2", ".nef", ".arw",
              ".mp4", ".mov", ".mkv", ".avi", ".wmv", ".m4v", ".mp3", ".flac", ".wav", ".m4a",
              ".aac", ".ogg"},
    "documents": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
                  ".txt", ".md", ".psd", ".ai", ".dwg"},
    "archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso", ".vhd", ".vhdx", ".vmdk", ".vdi"},
    "installers": {".msi", ".msix", ".appx"},
    "logs": {".log", ".etl", ".dmp", ".mdmp"},
    "cache": {".tmp", ".temp", ".cache"},
}
UNIT_CATEGORY = {"project": "projects", "game": "games", "app": "programs", "appdata": "appdata"}


def human(size: int) -> str:
    value = float(size)
    for unit in ("byte", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "byte" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} byte"


def age(days: float) -> str:
    if days < 1:
        return "today"
    if days < 60:
        return f"{days:.0f} days ago"
    if days < 730:
        return f"{days / 30:.0f} months ago"
    return f"{days / 365:.1f} years ago"


def evidence(item: Item) -> dict:
    """What the model sees about one item."""
    phone = rules.is_phone(item.path)
    state = {
        "path": item.path[len(rules.PHONE):] if phone else item.path,
        "kind": {"folder": "folder", "file": "single file", "files": "group of files",
                 "folders": "group of similar folders"}.get(item.kind, item.kind),
        "total_size": human(item.free or item.size),
        "files": item.count,
        "last_modified": age(item.stale_days) if item.newest else "unknown",
    }
    if item.node is not None:
        info = summary(item.node)
        total = sum(v for _, v in info["ext"]) or 1
        state["file_types_by_size"] = [
            f"{ext or '(no extension)'} {100 * v / total:.0f}%" for ext, v in info["ext"] if v
        ][:6]
        state["largest_files"] = [name for _, name, _ in info["largest"]][:8]
        if info["folders"]:
            state["subfolders"] = [name for name, _ in info["folders"]]
    elif item.files:
        state["files_list"] = [os.path.basename(f.path) for f in item.files[:12]]
    elif item.members:
        state["folders_list"] = [m.path for m in item.members[:10]]
    if phone:
        state["device"] = "internal storage of a smartphone connected by USB"
    if item.unit:
        state["looks_like"] = {"project": "a software project folder", "game": "an installed game",
                               "app": "a folder containing a program (.exe)",
                               "appdata": "the data folder of one application"}[item.unit]
    if item.rule:
        state["known_location"] = item.rule.hint
    return state


QUESTIONS = {
    "category": {
        "type": "choice",
        "instructions": "What kind of data is this, mostly?",
        "options": [{"id": cid, "description": text} for cid, _, text in CATEGORIES],
        "policy": {"allow_abstain": False},
    },
    "deletable": {
        "type": "boolean",
        "instructions": (
            "Can this be deleted safely? Safe means: no personal file or work of the user is lost "
            "and no installed program stops working; at most the content is re-created or "
            "re-downloaded automatically."),
        "true_description": "Yes. It is disposable: cache, temporary, regenerable or leftover data.",
        "false_description": (
            "No. It holds personal data, installed software, settings, or its value is unclear."),
    },
}


def heuristic_category(item: Item) -> str:
    if item.rule:
        return item.rule.category
    if item.category != "other":  # already decided while grouping (protected areas)
        return item.category
    if item.unit:
        return UNIT_CATEGORY[item.unit]
    exts = []
    if item.node is not None:
        exts = summary(item.node)["ext"]
    elif item.kind == "file":
        exts = [(os.path.splitext(item.path)[1].lower(), item.size)]
    total = sum(v for _, v in exts) or 1
    for family, members in EXT_FAMILIES.items():
        share = sum(v for ext, v in exts if ext in members) / total
        if share >= 0.5:
            return family
    return "other"


class Classifier:
    """Owns the Rizzo Flow engine. Loading takes seconds, so it starts in the background."""

    def __init__(self, ai_dir: Path):
        self.ai_dir = ai_dir
        self.engine = None
        self.status = {"state": "loading", "message": "Caricamento del modello AI…", "device": None}
        self._ready = threading.Event()

    def start(self):
        threading.Thread(target=self._load, name="model-loader", daemon=True).start()

    def wait(self, timeout=None) -> bool:
        return self._ready.wait(timeout)

    def _load(self):
        try:
            self.engine = self._open()
            meta = self.engine.backend.metadata
            device = meta.get("device_name") or "processore (CPU)"
            self.status = {
                "state": "ready" if meta.get("device") == "gpu" else "cpu",
                "message": f"Modello AI pronto su {device}",
                "device": device,
            }
        except Exception as error:  # noqa: BLE001 - any failure falls back to rules
            self.engine = None
            self.status = {
                "state": "unavailable",
                "message": "Modello AI non disponibile: analisi con le sole regole",
                "device": None,
                "detail": str(error)[:300],
            }
        finally:
            log.info("model: %s", self.status)
            self._ready.set()

    def _open(self):
        from rizzo_flow import llama_release
        from rizzo_flow.backend_llama import LlamaBackend
        from rizzo_flow.config import GGUF
        from rizzo_flow.engine import Engine

        model = self.ai_dir / GGUF[("4b", "q8_0")].path
        if not model.is_file():
            candidates = sorted((self.ai_dir / "models").rglob("*.gguf"))
            if not candidates:
                raise FileNotFoundError(f"Nessun modello .gguf in {self.ai_dir / 'models'}")
            model = candidates[0]
        runtimes = self.ai_dir / "runtimes"
        preferred = llama_release.pick("auto")
        order = [preferred] + [f for f in ("cuda", "vulkan", "cpu") if f != preferred]
        errors = []
        for family in order:
            directory = runtimes / f"llama-{llama_release.RELEASE}-win32-x64-{family}"
            library = llama_release.find_library(directory)
            if library is None:
                continue
            for device in ("auto", "cpu"):
                try:
                    backend = LlamaBackend.load(model, device=device, ctx=4096, batch_size=2,
                                                runtime_dir=library.parent)
                    return Engine(backend, ctx=4096)
                except Exception as error:  # noqa: BLE001
                    errors.append(f"{family}/{device}: {error}")
        raise RuntimeError("; ".join(errors) or f"Nessun runtime llama.cpp in {runtimes}")

    def classify(self, item: Item) -> tuple[str, float, float]:
        response = self.engine.decide({"state": evidence(item), "questions": QUESTIONS})
        answers = response["answers"]
        category = answers["category"]
        probs = category["probabilities"]
        chosen = max(probs, key=probs.get)
        deletable = answers["deletable"]["probabilities"].get("true", 0.0)
        return chosen, float(probs[chosen]), float(deletable)


def decide(item: Item, with_model: bool) -> None:
    """Pre-selection and the sentence that explains it. Prudent by design."""
    label = LABELS.get(item.category, "Altro")
    if item.locked or not item.paths:
        item.checked = False
        item.advice = item.locked or "Non selezionabile"
        return
    if item.rule:
        rule = item.rule
        ok = rule.precheck or (rule.stale_days is not None and item.stale_days >= rule.stale_days)
        advice = rule.why
        if with_model and item.p_delete is not None and item.p_delete < 0.35 and ok:
            ok = False
            advice += " L'AI ha dei dubbi: controlla prima di eliminare."
        item.checked = ok
        item.advice = advice
        return
    if not with_model:
        item.checked = False
        item.advice = f"Sembra: {label.lower()}. Senza AI non viene pre-selezionato."
        return
    pc, pd = item.p_category or 0, item.p_delete or 0
    # The model alone never selects a whole program, game, project or app-data folder.
    item.checked = (item.unit is None and item.kind != "folders"
                    and item.category in {"cache", "logs"} and pc >= 0.7 and pd >= 0.9)
    if item.category in JUNK and pd >= 0.6:
        item.advice = f"L'AI lo considera {label.lower()} ed eliminabile ({pd:.0%})."
    elif pd >= 0.6:
        item.advice = f"L'AI lo considera {label.lower()}: eliminabile secondo l'AI, ma verifica."
    else:
        item.advice = f"L'AI lo considera {label.lower()}: meglio tenerlo."


def classify_all(items: list[Item], classifier: Classifier | None, progress: dict,
                 stop: threading.Event) -> None:
    for item in items:
        item.category = heuristic_category(item)
    ai = classifier is not None and classifier.engine is not None
    kinds = ("folder", "folders", "file", "files")
    todo = [i for i in items if i.kind in kinds and not i.locked] if ai else []
    todo.sort(key=lambda i: i.free or i.size, reverse=True)
    progress.update(total=len(todo), done=0, current="", started=time.time())
    for item in todo:
        if stop.is_set():
            break
        progress["current"] = item.path
        try:
            category, pc, pd = classifier.classify(item)
            if not item.rule:
                item.category = category
            item.p_category, item.p_delete = pc, pd
            item.source = "regole + AI" if item.rule else "AI"
        except Exception as error:  # noqa: BLE001 - one bad item must not stop the run
            progress["last_error"] = str(error)[:200]
        progress["done"] += 1
    for item in items:
        decide(item, ai and item.p_delete is not None)
