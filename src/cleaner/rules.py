"""Deterministic knowledge about Windows paths: what is protected, what is known junk.

Everything here is decided without the model. Protection is absolute: no answer from the model
can make a protected path deletable, and `deleter.guard` checks it again right before deleting.
"""

import os
import re
from dataclasses import dataclass

MB = 1024 * 1024


PHONE = "mtp:\\"  # prefix of the paths of phones and other portable devices (MTP)


def is_phone(path: str) -> bool:
    return path[:5].lower() == PHONE


def norm(path: str) -> str:
    """Lowercase absolute path with backslashes, no trailing separator (except on a drive root).
    Phone paths (`mtp:\\Device\\Storage\\...`) are only lowercased."""
    if is_phone(path):
        return path.replace("/", "\\").lower().rstrip("\\")
    path = os.path.normcase(os.path.abspath(path))
    return path if re.fullmatch(r"[a-z]:\\", path) else path.rstrip("\\")


def _env(name: str, fallback: str) -> str:
    return norm(os.environ.get(name) or fallback)


SYSTEM_DRIVE = (os.environ.get("SystemDrive") or "C:")[:2].lower()
WINDIR = _env("WINDIR", SYSTEM_DRIVE + "\\windows")
PROGRAM_FILES = _env("ProgramFiles", SYSTEM_DRIVE + "\\program files")
PROGRAM_FILES_X86 = _env("ProgramFiles(x86)", SYSTEM_DRIVE + "\\program files (x86)")
PROGRAM_DATA = _env("ProgramData", SYSTEM_DRIVE + "\\programdata")
USERS = norm(SYSTEM_DRIVE + "\\users")

PROFILE_RE = re.compile(r"^[a-z]:\\users\\[^\\]+")

# Names that are protected when they sit directly under a drive root.
ROOT_PROTECTED = {
    "windows": "Cartella di sistema di Windows",
    "program files": "Programmi installati",
    "program files (x86)": "Programmi installati",
    "programdata": "Dati condivisi dei programmi installati",
    "windowsapps": "App dello Store installate",
    "system volume information": "Punti di ripristino di Windows",
    "recovery": "Ripristino di Windows",
    "$winreagent": "Ripristino di Windows",
    "$sysreset": "Ripristino di Windows",
    "boot": "Avvio del sistema",
    "efi": "Avvio del sistema",
    "config.msi": "Installazioni in corso",
    "msocache": "Installazione di Office",
    "perflogs": "Registri di sistema",
    "onedrivetemp": "File temporanei di OneDrive in uso",
}
# Protected wherever they appear.
ANYWHERE_PROTECTED = {"windowsapps": "App dello Store installate"}
ROOT_PROTECTED_FILES = {
    "pagefile.sys": "File di paging di Windows",
    "hiberfil.sys": "File di ibernazione di Windows",
    "swapfile.sys": "File di scambio di Windows",
    "dumpstack.log": "Registro di avvio di Windows",
    "dumpstack.log.tmp": "Registro di avvio di Windows",
}
# The folders a user profile is made of: never deleted as a whole, only their contents.
PROFILE_KNOWN = {
    "desktop", "documents", "downloads", "pictures", "music", "videos", "onedrive",
    "appdata", "appdata\\local", "appdata\\roaming", "appdata\\locallow", "favorites",
    "contacts", "links", "saved games", "searches", "3d objects",
}


def split_root(path: str) -> tuple[str, str]:
    """('c:', 'rest\\of\\path') for a normalized path."""
    return path[:2], path[3:]


def protection(path: str) -> str | None:
    """Why a folder must not be touched, or None. `path` is normalized."""
    if is_phone(path):
        return phone_protection(path)
    drive, rest = split_root(path)
    if not rest:
        return "Radice del disco"
    for base, label in (
        (WINDIR, "Cartella di sistema di Windows"),
        (PROGRAM_FILES, "Programmi installati"),
        (PROGRAM_FILES_X86, "Programmi installati"),
        (PROGRAM_DATA, "Dati condivisi dei programmi installati"),
    ):
        if path == base or path.startswith(base + "\\"):
            return label
    profile = PROFILE_RE.match(path)
    if profile:
        inner = path[profile.end():].lstrip("\\")
        if inner == r"appdata\local\programs" or inner.startswith("appdata\\local\\programs\\"):
            return "Programmi installati per questo utente"
    first = rest.split("\\", 1)[0]
    if first in ROOT_PROTECTED:
        return ROOT_PROTECTED[first]
    for part in rest.split("\\"):
        if part in ANYWHERE_PROTECTED:
            return ANYWHERE_PROTECTED[part]
    return None


def protected_file(path: str) -> str | None:
    if is_phone(path):
        return phone_protection(os.path.dirname(path))
    drive, rest = split_root(path)
    if "\\" not in rest and rest in ROOT_PROTECTED_FILES:
        return ROOT_PROTECTED_FILES[rest]
    return protection(os.path.dirname(path)) if os.path.dirname(path)[3:] else None


def critical(path: str) -> str | None:
    """Folders that are never deleted as a whole even though they are not protected:
    drive roots, the Users folder, a profile and its known folders."""
    if is_phone(path):
        return phone_critical(path)
    drive, rest = split_root(path)
    if not rest:
        return "Radice del disco"
    if path == USERS or re.fullmatch(r"[a-z]:\\users", path):
        return "Cartella degli utenti"
    match = PROFILE_RE.match(path)
    if match:
        inner = path[match.end():].lstrip("\\")
        if not inner:
            return "Profilo utente"
        if inner in PROFILE_KNOWN or re.fullmatch(r"onedrive[^\\]*", inner):
            return "Cartella personale di Windows"
    return None


@dataclass(frozen=True)
class Rule:
    id: str
    category: str
    label: str  # shown to the user
    why: str  # shown to the user: why it can (or cannot) go
    hint: str  # given to the model as evidence
    precheck: bool = False
    stale_days: int | None = None  # precheck only when untouched for this long
    contents_only: bool = False  # empty the folder, keep the folder itself
    special: str | None = None  # "recycle": emptied through the shell


def _r(*args, **kwargs):
    return Rule(*args, **kwargs)


TEMP = _r("temp", "cache", "File temporanei", "Windows e i programmi li ricreano quando servono.",
          "Windows temporary files folder.", precheck=True, contents_only=True)

# Paths relative to a user profile.
PROFILE_RULES = {
    "appdata\\local\\temp": TEMP,
    "appdata\\local\\crashdumps": _r(
        "crashdumps", "logs", "Rapporti di arresto anomalo",
        "Servono solo per diagnosticare crash passati.", "Crash dump files of applications.",
        precheck=True, contents_only=True),
    "appdata\\local\\microsoft\\windows\\inetcache": _r(
        "inetcache", "cache", "Cache internet di Windows", "Si ricrea navigando.",
        "Internet cache of Windows.", precheck=True, contents_only=True),
    "appdata\\local\\microsoft\\windows\\wer": _r(
        "wer", "logs", "Segnalazioni errori di Windows", "Rapporti di errori già inviati o vecchi.",
        "Windows Error Reporting archive.", precheck=True, contents_only=True),
    "appdata\\local\\npm-cache": _r(
        "npm-cache", "dev", "Cache di npm", "npm riscarica i pacchetti quando servono.",
        "Package download cache of npm, regenerated automatically.", precheck=True),
    "appdata\\local\\pip\\cache": _r(
        "pip-cache", "dev", "Cache di pip", "pip riscarica i pacchetti quando servono.",
        "Package download cache of pip, regenerated automatically.", precheck=True),
    "appdata\\local\\uv\\cache": _r(
        "uv-cache", "dev", "Cache di uv", "uv riscarica i pacchetti quando servono.",
        "Package cache of the uv Python tool, regenerated automatically.", precheck=True),
    "appdata\\local\\yarn\\cache": _r(
        "yarn-cache", "dev", "Cache di Yarn", "Yarn riscarica i pacchetti quando servono.",
        "Package cache of Yarn, regenerated automatically.", precheck=True),
    "appdata\\local\\nvidia\\dxcache": _r(
        "shader", "cache", "Cache shader della scheda video", "Il driver la ricrea da solo.",
        "GPU driver shader cache.", precheck=True),
    "appdata\\local\\nvidia\\glcache": _r(
        "shader", "cache", "Cache shader della scheda video", "Il driver la ricrea da solo.",
        "GPU driver shader cache.", precheck=True),
    "appdata\\locallow\\nvidia\\perdrivershadercache": _r(
        "shader", "cache", "Cache shader della scheda video", "Il driver la ricrea da solo.",
        "GPU driver shader cache.", precheck=True),
    "appdata\\local\\d3dscache": _r(
        "shader", "cache", "Cache shader di DirectX", "Windows la ricrea da solo.",
        "DirectX shader cache.", precheck=True),
    "appdata\\local\\amd\\dxcache": _r(
        "shader", "cache", "Cache shader della scheda video", "Il driver la ricrea da solo.",
        "GPU driver shader cache.", precheck=True),
    ".nuget\\packages": _r(
        "nuget", "dev", "Pacchetti NuGet", "Si riscaricano, ma serve tempo e connessione.",
        "NuGet package cache for .NET development."),
    ".gradle\\caches": _r(
        "gradle", "dev", "Cache di Gradle", "Si riscarica alla prossima compilazione.",
        "Gradle build cache."),
    ".m2\\repository": _r(
        "maven", "dev", "Pacchetti Maven", "Si riscaricano alla prossima compilazione.",
        "Maven package repository cache."),
    ".cache": _r(
        "dotcache", "cache", "Cache di programmi vari",
        "Può contenere anche modelli AI scaricati: controlla prima.",
        "Generic cache folder of command-line tools; may contain downloaded AI models."),
}

# Absolute paths (normalized).
SYSTEM_RULES = {
    WINDIR + "\\temp": TEMP,
    WINDIR + "\\softwaredistribution\\download": _r(
        "wu-download", "installers", "Aggiornamenti di Windows scaricati",
        "Aggiornamenti già installati; Windows li riscarica se servono.",
        "Downloaded Windows Update packages.", precheck=True, contents_only=True),
    WINDIR + "\\minidump": _r(
        "minidump", "logs", "Rapporti di crash di sistema", "Servono solo per diagnosi passate.",
        "Kernel crash minidumps.", precheck=True, contents_only=True),
    WINDIR + "\\livekernelreports": _r(
        "kernelreports", "logs", "Rapporti di errore del kernel", "Servono solo per diagnosi passate.",
        "Live kernel crash reports.", precheck=True, contents_only=True),
    PROGRAM_DATA + "\\microsoft\\windows\\wer\\reportarchive": _r(
        "wer", "logs", "Segnalazioni errori di Windows", "Rapporti di errori già inviati o vecchi.",
        "Windows Error Reporting archive.", precheck=True, contents_only=True),
    PROGRAM_DATA + "\\microsoft\\windows\\wer\\reportqueue": _r(
        "wer", "logs", "Segnalazioni errori di Windows", "Rapporti di errori in coda.",
        "Windows Error Reporting queue.", precheck=True, contents_only=True),
}

# Names directly under any drive root.
ROOT_RULES = {
    "$recycle.bin": _r(
        "recycle", "backup", "Cestino", "Contiene file che hai già eliminato: svuotarlo è definitivo.",
        "The Recycle Bin: files the user already deleted.", special="recycle"),
    "windows.old": _r(
        "windows-old", "backup", "Installazione precedente di Windows",
        "Serve solo per tornare alla versione precedente. Richiede i permessi di amministratore.",
        "Previous Windows installation kept after an upgrade."),
    "$windows.~bt": _r(
        "upgrade-leftovers", "backup", "Resti di un aggiornamento di Windows",
        "File di un aggiornamento già concluso.", "Leftover files of a Windows upgrade."),
    "$windows.~ws": _r(
        "upgrade-leftovers", "backup", "Resti di un aggiornamento di Windows",
        "File di un aggiornamento già concluso.", "Leftover files of a Windows upgrade."),
    "$getcurrent": _r(
        "upgrade-leftovers", "backup", "Resti di un aggiornamento di Windows",
        "File di un aggiornamento già concluso.", "Leftover files of a Windows upgrade."),
}

NODE_MODULES = _r(
    "node_modules", "dev", "Dipendenze di un progetto JavaScript",
    "Si ricreano con npm install, ma servono se il progetto è in uso: decidi tu.",
    "node_modules: JavaScript project dependencies, regenerated by npm install.")
PY_CACHE = _r(
    "pycache", "dev", "Cache di Python", "Python la ricrea da solo.",
    "Python bytecode or test-tool cache, regenerated automatically.", precheck=True)
VENV = _r(
    "venv", "dev", "Ambiente virtuale Python",
    "Si ricrea dal progetto, ma serve se il progetto è in uso: decidi tu.",
    "Python virtual environment, can be recreated from the project's requirements.")
WEB_BUILD_CACHE = _r(
    "web-cache", "dev", "Cache di compilazione web", "Si ricrea alla prossima compilazione.",
    "Build cache of a web framework, regenerated automatically.", stale_days=30)
BUILD_OUTPUT = _r(
    "build-output", "dev", "Risultato di compilazione",
    "Di solito si ricrea compilando il progetto, ma controlla che non ti serva.",
    "Build output folder of a software project.")
APP_CACHE = _r(
    "app-cache", "cache", "Cache di un programma", "Il programma la ricrea quando serve.",
    "Cache folder inside an application's data, regenerated automatically.", precheck=True)
APP_LOGS = _r(
    "app-logs", "logs", "Registri di un programma", "Servono solo per la diagnosi di problemi.",
    "Log folder inside an application's data.", precheck=True)

NAME_RULES = {
    "node_modules": NODE_MODULES,
    "__pycache__": PY_CACHE,
    ".pytest_cache": PY_CACHE,
    ".mypy_cache": PY_CACHE,
    ".ruff_cache": PY_CACHE,
    ".next": WEB_BUILD_CACHE,
    ".nuxt": WEB_BUILD_CACHE,
    ".parcel-cache": WEB_BUILD_CACHE,
    ".turbo": WEB_BUILD_CACHE,
    ".angular": WEB_BUILD_CACHE,
}
APPDATA_CACHE_NAMES = {
    "cache", "cache2", "code cache", "gpucache", "shadercache", "grshadercache",
    "graphitedawncache", "dawncache", "dawngraphitecache", "dawnwebgpucache", "cachestorage",
    "cacheddata", "cachedextensionvsixs", "cachedprofilesdata", "webcache", "htmlcache",
    "media cache", "component_crx_cache", "crashpad",
}
APPDATA_LOG_NAMES = {"logs", "log", "crashreports", "crash reports"}
BUILD_NAMES = {"bin", "obj", "build", "dist", "target", "out"}
PROJECT_MARKERS = {
    ".git", "package.json", "pyproject.toml", "setup.py", "requirements.txt", "cargo.toml",
    "go.mod", "pom.xml", "build.gradle", "build.gradle.kts", "composer.json", "gemfile",
}
INSTALLER_EXTS = {".exe", ".msi", ".msix", ".msixbundle", ".appx", ".iso", ".img", ".apk", ".xapk"}
DUMP_EXTS = {".dmp", ".mdmp", ".hdmp"}


def is_project(markers) -> bool:
    return bool(markers) and any(m in PROJECT_MARKERS or m.endswith((".sln", ".csproj")) for m in markers)


def match(path: str, name: str, markers=frozenset(), parent_markers=frozenset(),
          system_only=False) -> Rule | None:
    """The junk rule for a folder, or None. `path` and `name` are normalized (lowercase).
    `system_only`: inside protected areas only the exact system locations count."""
    if is_phone(path):
        return phone_match(path, name)
    drive, rest = split_root(path)
    if "\\" not in rest and rest in ROOT_RULES:
        return ROOT_RULES[rest]
    if path in SYSTEM_RULES:
        return SYSTEM_RULES[path]
    if system_only:
        return None
    profile = PROFILE_RE.match(path)
    inner = path[profile.end():].lstrip("\\") if profile else ""
    if inner in PROFILE_RULES:
        return PROFILE_RULES[inner]
    if name == "node_modules" and (
        "package.json" not in parent_markers or inner.startswith("appdata\\")
    ):
        return None  # the internals of an installed tool, not a project's dependencies
    if name in NAME_RULES:
        return NAME_RULES[name]
    if name in ("venv", ".venv", "env", ".env") and "pyvenv.cfg" in markers:
        return VENV
    if name in BUILD_NAMES and is_project(parent_markers):
        return BUILD_OUTPUT
    in_app_data = bool(profile) and inner.startswith("appdata\\") and inner.count("\\") >= 3
    if in_app_data and name in APPDATA_CACHE_NAMES:
        return APP_CACHE
    if in_app_data and name in APPDATA_LOG_NAMES:
        return APP_LOGS
    return None


def unit_kind(path: str, name: str, markers, has_exe: bool) -> str | None:
    """A folder that is one thing (a project, an app, a game) and is not split further.
    `has_exe` means the folder holds both an .exe and a .dll, as program folders do."""
    if critical(path) or is_phone(path):
        return None
    if is_project(markers):
        return "project"
    parts = path.split("\\")
    parent = parts[-2] if len(parts) >= 2 else ""
    if parent == "common" and len(parts) >= 3 and parts[-3] == "steamapps":
        return "game"
    profile = PROFILE_RE.match(path)
    if profile:
        inner = path[profile.end():].lstrip("\\")
        if re.fullmatch(r"appdata\\(local|roaming|locallow)\\[^\\]+", inner):
            return "appdata"
    if has_exe:
        return "app"
    return None


# --- phones (MTP) -------------------------------------------------------------------------
# Paths look like mtp:\\<device>\\<storage>\\<folders...>, normalized to lowercase.

PHONE_KNOWN = {
    "dcim", "pictures", "download", "downloads", "documents", "music", "movies", "podcasts",
    "ringtones", "alarms", "notifications", "audiobooks", "recordings", "android", "whatsapp",
    "telegram",
}


def phone_parts(path: str) -> list[str]:
    """Folders below the storage root."""
    return [p for p in path[len(PHONE):].split("\\")[2:] if p]


def phone_protection(path: str) -> str | None:
    rel = phone_parts(path)
    if rel[:2] in (["android", "data"], ["android", "obb"]):
        return "Dati delle app del telefono"
    return None


def phone_critical(path: str) -> str | None:
    rel = phone_parts(path)
    if not rel:
        return "Memoria del telefono"
    if len(rel) == 1 and rel[0] in PHONE_KNOWN:
        return "Cartella principale del telefono"
    if rel == ["android", "media"] or rel == ["dcim", "camera"]:
        return "Cartella principale del telefono"
    return None


PHONE_THUMBS = Rule(
    "phone-thumbs", "cache", "Miniature della Galleria", "La Galleria le ricrea quando servono.",
    "Thumbnail cache of the phone gallery (.thumbnails), regenerated automatically.",
    precheck=True)
PHONE_APP_CACHE = Rule(
    "phone-app-cache", "cache", "Cache di un'app del telefono", "L'app la ricrea quando serve.",
    "Cache folder of an Android app, regenerated automatically.", precheck=True)
PHONE_LOST = Rule(
    "phone-lost", "backup", "File recuperati dopo errori (LOST.DIR)",
    "Frammenti salvati da Android dopo un errore della memoria: di solito inutili, ma controlla.",
    "LOST.DIR: file fragments recovered by Android after a storage error.")
PHONE_STATUSES = Rule(
    "phone-statuses", "cache", "Stati di WhatsApp visti", "Copie temporanee degli stati visti.",
    "WhatsApp .Statuses folder: temporary copies of viewed statuses.", precheck=True)
PHONE_SENT = Rule(
    "phone-sent", "media", "Copie dei file inviati su WhatsApp",
    "Sono copie di foto e video che hai inviato: gli originali di solito sono nella Galleria.",
    "WhatsApp Sent folder: copies of media the user sent to others.")


def phone_match(path: str, name: str) -> Rule | None:
    rel = phone_parts(path)
    if name == ".thumbnails":
        return PHONE_THUMBS
    if len(rel) == 4 and rel[:2] == ["android", "data"] and rel[3] in ("cache", "code_cache"):
        return PHONE_APP_CACHE
    if rel == ["lost.dir"]:
        return PHONE_LOST
    if name == ".statuses" and "whatsapp" in rel:
        return PHONE_STATUSES
    if name == "sent" and "whatsapp" in rel:
        return PHONE_SENT
    return None
