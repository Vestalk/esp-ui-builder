# PyInstaller spec: one folder per platform (``pyinstaller packaging/espui.spec``).
#
# Bundled resources (read at run time, so they must be files, not compiled code):
#   espui/assets/fonts/*            - TTF fonts and their licences
#   espui/displays/*.yaml           - display profiles
#   espui/generators/micropython/templates/*.j2
#   espui/generators/micropython/runtime/*  - copied verbatim into every generated project
# PyAV (video import) is optional and left out to keep the build small.

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

datas = collect_data_files("espui")
datas += collect_data_files(
    "espui", subdir="generators/micropython/runtime", include_py_files=True
)
datas += collect_data_files("freetype")
binaries = collect_dynamic_libs("freetype")

a = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=["espui.gui.app"],
    excludes=["av", "tkinter", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="espui",
    console=True,  # the same file is also the command line tool
)
coll = COLLECT(exe, a.binaries, a.datas, name="espui")
app = BUNDLE(  # macOS only; ignored elsewhere
    coll,
    name="ESP UI Builder.app",
    bundle_identifier="dev.espui.builder",
    info_plist={"NSHighResolutionCapable": True, "CFBundleShortVersionString": "0.1.0"},
)
