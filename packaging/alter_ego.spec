# PyInstaller recipe for Alter Ego: one folder with AlterEgo(.exe) and everything it needs.
#
# Build from the project root, inside the project's virtual environment:
#
#     pyinstaller --noconfirm --clean packaging/alter_ego.spec
#
# The result is dist/AlterEgo/. The release workflow (.github/workflows/release.yml)
# wraps it in the Windows installer, the portable zip and the Linux tarball.
#
# ALTER_EGO_LITE=1 leaves out the character voice (PyTorch and the RVC converter):
# a much smaller, faster build for checking the packaging locally. Releases are
# always full builds.

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent  # noqa: F821 (SPECPATH is defined by PyInstaller)
LITE = os.environ.get("ALTER_EGO_LITE") == "1"

datas = [(str(ROOT / "assets"), "assets")]
binaries = []
hiddenimports = collect_submodules("alter_ego")

# Packages that load data files or native libraries in ways PyInstaller cannot see on its own.
PACKAGES = [
    "faster_whisper",   # Silero VAD model and assets
    "ctranslate2",      # Whisper's inference engine (native libraries)
    "kokoro_onnx",      # the text-to-speech model wrapper and its config
    "onnxruntime",
    "espeakng_loader",  # the espeak-ng library and its language data, used for phonemes
    "phonemizer",
    "language_tags",
    "segments",
    "csvw",
    "truststore",
    "certifi",
]
# The character voice: Kokoro speech converted with the RVC model in assets/voice/.
VOICE_PACKAGES = [
    "infer_rvc_python",
    "torchcrepe",
    "parselmouth",
    "pyworld",
    "faiss",
    "soxr",
    "librosa",
]

for package in PACKAGES + ([] if LITE else VOICE_PACKAGES):
    try:
        package_datas, package_binaries, package_hidden = collect_all(package)
    except Exception as error:  # noqa: BLE001 - an optional package that is not installed is skipped
        print(f"Warning: not bundling {package}: {error}")
        continue
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

pathex = [str(ROOT / "src")]
if not LITE:
    # pyworld (part of the character voice) imports pkg_resources, which needs jaraco.text and
    # more_itertools. They live in setuptools/_vendor, which pkg_resources adds to sys.path only
    # while running, so PyInstaller cannot see them; without them the voice converter fails to
    # import in the build. They are copied as plain source next to the program (_internal is on
    # sys.path), the way that was tested on an installed copy. Do NOT put _vendor on pathex: it
    # also holds old copies of typing_extensions, packaging and others that would shadow the real
    # ones (torch then fails with "cannot import name 'Format' from 'typing_extensions'").
    import setuptools

    VENDOR = Path(setuptools.__file__).parent / "_vendor"
    hiddenimports.append("pkg_resources")
    for name in ("jaraco", "more_itertools"):
        datas.append((str(VENDOR / name), name))

    # torchvision (imported by transformers, for the HuBERT model) keeps its operators in
    # _C_stable.so and image_stable.so since 0.29, loaded with torch.ops.load_library rather than
    # imported, so PyInstaller misses them ('Hidden import "torchvision._C" not found!'). Without
    # them: "operator torchvision::nms does not exist", and the voice converter fails to import.
    import importlib.util

    tv_spec = importlib.util.find_spec("torchvision")
    if tv_spec is not None and tv_spec.origin:
        tv_dir = Path(tv_spec.origin).parent
        binaries += [(str(lib), "torchvision") for lib in tv_dir.glob("*.so")]
        binaries += [(str(lib), "torchvision") for lib in tv_dir.glob("*.pyd")]  # Windows
        binaries += [(str(lib), "torchvision") for lib in tv_dir.glob("*.dll")]
        for libs in (tv_dir.parent / "torchvision.libs",):
            if libs.is_dir():
                binaries += [(str(lib), "torchvision.libs") for lib in libs.iterdir()]

excludes = [
    # Big parts of Qt that Alter Ego does not use.
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
    "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtQuick3D", "PySide6.QtDesigner",
    # Development and plotting tools that libraries import only optionally.
    "tkinter", "matplotlib", "IPython", "pytest", "notebook",
]
if LITE:
    excludes += ["torch", "torchaudio", "torchvision", "infer_rvc_python", "transformers", "librosa"]

a = Analysis(  # noqa: F821
    [str(ROOT / "main.py")],
    pathex=pathex,
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AlterEgo",
    console=False,  # A desktop app: no terminal window. Diagnostics go to alter_ego.log (see main.py).
    icon=str(ROOT / "packaging" / "AlterEgo.ico"),
    upx=False,      # UPX-packed DLLs set off antivirus false alarms and save little here.
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    upx=False,
    name="AlterEgo",
)
