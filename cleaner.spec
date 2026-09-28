# PyInstaller spec: one-folder, windowed build. Run through build.ps1.
a = Analysis(
    ["launcher.py"],
    pathex=["src"],
    datas=[("src/cleaner/ui", "cleaner/ui")],
    hiddenimports=[f"rizzo_flow.{m}" for m in (
        "engine", "backend_llama", "llama_cpp", "llama_release", "config", "prompts",
        "decisions", "responses", "schema", "runtime", "calibration")],
    excludes=["mlx", "mlx_lm", "fastapi", "uvicorn", "starlette", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Cleaner",
    console=False,
    icon="assets/cleaner.ico",
    version="version.txt",
    uac_admin=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Cleaner")
