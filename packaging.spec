# PyInstaller spec: one-folder build of the PaperMind server. Build: uv run --with pyinstaller pyinstaller packaging.spec
# The frontend is already built into backend/papermind/static (shipped as data). Models/llama-server are fetched at runtime.
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("papermind") + collect_submodules("uvicorn") + collect_submodules("apscheduler")
a = Analysis(
    ["backend/papermind/cli.py"],
    pathex=["backend"],
    datas=[("backend/papermind/static", "papermind/static")],
    hiddenimports=hidden,
    excludes=["tkinter", "pytest", "playwright"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="papermind", console=True)
coll = COLLECT(exe, a.binaries, a.datas, name="papermind")
