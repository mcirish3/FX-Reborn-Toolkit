"""Build the toolkit download for modders: dist/FX-Reborn-Toolkit-<version>.zip.

Contents: fxkit.py/.cmd, installer.py, package_mod.py, engine/, runtime/ (source +
prebuilt fxcompat.dll), examples/, tests/selftest sources, README, LICENSE and a
private Python 3.13 so modders install nothing either.
"""
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fxkit  # noqa: E402
import package_mod  # noqa: E402

NAME = f"FX-Reborn-Toolkit-{fxkit.VERSION}"
out = ROOT / "dist" / NAME
if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
for f in ("fxkit.py", "fxkit.cmd", "installer.py", "package_mod.py", "README.md", "LICENSE"):
    shutil.copy2(ROOT / f, out / f)
skip = shutil.ignore_patterns("__pycache__", "code_cache", "*.obj", "*.lib", "*.exp", "bin", "*.pyc")
shutil.copytree(ROOT / "engine", out / "engine", ignore=skip)
shutil.copytree(ROOT / "runtime", out / "runtime", ignore=skip)
shutil.copytree(ROOT / "examples", out / "examples", ignore=skip)
shutil.copytree(ROOT / "tests", out / "tests", ignore=skip)
if not (out / "runtime" / "fxcompat.dll").exists():
    sys.exit("runtime/fxcompat.dll missing: run runtime/build_runtime.cmd first")
package_mod.bundle_python(out / "python")
sums = [f"{hashlib.sha256(f.read_bytes()).hexdigest()}  {f.relative_to(out).as_posix()}"
        for f in sorted(out.rglob("*")) if f.is_file()]
(out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
archive = ROOT / "dist" / f"{NAME}.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in sorted(out.rglob("*")):
        if f.is_file():
            z.write(f, (Path(NAME) / f.relative_to(out)).as_posix())
print(f"{archive} ({archive.stat().st_size / 1e6:.1f} MB) sha256 {hashlib.sha256(archive.read_bytes()).hexdigest()}")
