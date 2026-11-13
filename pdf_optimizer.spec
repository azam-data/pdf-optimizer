# PyInstaller spec: builds "PDF Optimizer.exe" (GUI) and "pdfopt-cli.exe" (console)
# into one portable folder that shares a single _internal directory.
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = (collect_submodules("fontTools.ttLib.tables") + collect_submodules("fontTools.subset")
          + ["fontTools.cffLib", "fontTools.ttLib.ttFont"])
common_excludes = ["matplotlib", "scipy", "pandas", "IPython", "pytest", "setuptools", "pip",
                   "pydoc_data", "lib2to3", "sympy", "lxml", "brotli", "brotlicffi", "zopfli",
                   "unicodedata2", "fs", "numpy.f2py", "numpy.distutils", "PIL.ImageQt",
                   "PIL._avif", "PIL.AvifImagePlugin", "PIL._webp", "PIL.WebPImagePlugin",
                   "PIL._imagingcms", "PIL.ImageCms", "PIL._imagingtk", "PIL.ImageTk",
                   "xmlrpc", "http.server"]
binaries = [("third_party/jbig2/jbig2.exe", "."),
            # Microsoft VC++ runtime (redistributable): MuPDF needs MSVCP140.dll, which is not on every PC
            ("third_party/vcruntime/msvcp140.dll", "."),
            ("third_party/vcruntime/vcruntime140.dll", "."),
            ("third_party/vcruntime/vcruntime140_1.dll", ".")]
datas = ([("assets/icon.ico", "assets"),
          ("third_party/tessdata/eng.traineddata", "tessdata"),
          ("third_party/jbig2/LICENSE-jbig2enc.txt", "licenses"),
          ("third_party/jbig2/LICENSE-leptonica.txt", "licenses"),
          ("third_party/jbig2/BUILD-INFO.txt", "licenses")]
         + collect_data_files("sv_ttk"))


def prune(toc):
    # drop Tcl/Tk extras we never use (time zones, translations, demos, sample images)
    bad = ("tzdata", "demos", "\\msgs\\", "/msgs/", "\\images\\", "/images/", "tcl8\\8.", "tcl8/8.")
    return [t for t in toc if not any(b in t[0] for b in bad)]


a_gui = Analysis(["app_gui.py"], binaries=binaries, datas=datas, hiddenimports=hidden + ["sv_ttk"],
                 excludes=common_excludes, noarchive=False)
a_gui.datas = prune(a_gui.datas)
a_cli = Analysis(["app_cli.py"], binaries=binaries, datas=datas, hiddenimports=hidden,
                 excludes=common_excludes + ["tkinter", "sv_ttk", "_tkinter"], noarchive=False)

pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)

exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="PDF Optimizer",
              icon="assets/icon.ico", console=False, upx=False)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="pdfopt-cli",
              icon="assets/icon.ico", console=True, upx=False)

coll = COLLECT(exe_gui, a_gui.binaries, a_gui.datas,
               exe_cli, a_cli.binaries, a_cli.datas,
               strip=False, upx=False, name="PDF Optimizer")
