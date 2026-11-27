# PyInstaller spec for the backend shipped with the Tauri app (one folder, no console window).
#   cd backend && pyinstaller --noconfirm --distpath dist --workpath build packaging/xqc-backend.spec
# Output: backend/dist/xqc-backend/ (xqc-backend[.exe] + _internal/). One folder, not one file: no extraction to
# %TEMP% on every start, nothing left behind if the process is killed. Pikafish is NOT bundled here; Tauri ships
# it as a resource and passes XQC_PIKAFISH_PATH.
import os

from PyInstaller.utils.hooks import collect_submodules

backend = os.path.dirname(SPECPATH)

a = Analysis(
    [os.path.join(backend, "app", "__main__.py")],
    pathex=[backend],
    # db.py reads migrations via importlib.resources.files("app.migrations")
    datas=[(os.path.join(backend, "app", "migrations", "*.sql"), "app/migrations")],
    # uvicorn picks loops/protocols/lifespan by string at runtime; anthropic/httpx2 import lazily.
    hiddenimports=collect_submodules("uvicorn")
    + collect_submodules("anthropic")
    + collect_submodules("httpx2")
    + ["app.migrations"],
    excludes=["tkinter", "pytest", "py7zr", "PyInstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="xqc-backend",
    console=False,
    upx=False,
    strip=False,
    debug=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="xqc-backend", strip=False, upx=False)
