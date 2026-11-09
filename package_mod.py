"""Turn a game.json into a player-ready mod folder + zip (used by `fxkit.py package`)."""
from __future__ import annotations

import compileall
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE_FILES = ["avx2_lower.py", "bmi2_lower.py", "build_static_mod.py", "unwind_builder.py",
                "discover_code_sites.py", "find_sites.py", "patterns.py"]
STDLIB_SKIP = {"test", "idlelib", "tkinter", "turtledemo", "ensurepip", "venv", "lib2to3", "pydoc_data",
               "site-packages", "__pycache__", "unittest", "sqlite3", "curses", "dbm", "asyncio", "email",
               "http", "xml", "xmlrpc", "wsgiref", "multiprocessing", "concurrent", "html", "urllib",
               "zoneinfo", "tomllib", "_pyrepl"}
DLL_KEEP = {"_ctypes.pyd", "libffi-8.dll"}

LAUNCHER = r"""@echo off
rem {comment}
set "FXK_SELF=%~f0"
set "FXK_ARG=%~1"
net session >nul 2>&1
if not errorlevel 1 goto elevated
powershell -NoProfile -Command "if ($env:FXK_ARG) {{ Start-Process -FilePath $env:FXK_SELF -ArgumentList ('\"' + $env:FXK_ARG + '\"') -Verb RunAs }} else {{ Start-Process -FilePath $env:FXK_SELF -Verb RunAs }}" 2>nul
if errorlevel 1 echo Could not get administrator rights. & pause
exit /b
:elevated
cd /d "%~dp0"
if exist "python\python.exe" goto bundled
py -3.13 -c "" >nul 2>&1
if errorlevel 1 goto nopython
py -3.13 installer.py {command} %*
goto done
:bundled
"python\python.exe" installer.py {command} %*
goto done
:nopython
echo This mod's Python runtime is missing. Re-download the mod.
:done
pause
"""

README = """{mod_name} {mod_version} - {game_title} on CPUs without AVX2
{underline}

Converts the game's AVX2/BMI2 instructions into code that runs on CPUs with AVX
but no AVX2 (for example AMD FX). Made with the FX Reborn Toolkit.

Needs: a CPU with {features}. Nothing else to install: this
download includes its own private copy of Python.

INSTALL: close the game, unzip this folder anywhere, double-click
"Install or Update.cmd" and accept the administrator prompt. It finds the game
through Steam (or drag the game folder onto the launcher), backs up the original
files and builds the patch on your PC.

AFTER A GAME UPDATE: run "Install or Update.cmd" again. Game versions other than
the ones the mod author tested are marked UNVERIFIED. If the game closes with a
missing-instruction error, run the installer again: it reads
fxreborn-missed.log in the game folder and adds the address.

UNINSTALL: "Restore original.cmd", or verify the game files in Steam.

WHAT IT CHANGES: only {targets} (originals kept as *.fxkit-original) plus
fxcompat.dll and small state files next to them. No saves, settings or Steam files.

Includes Python 3.13 (PSF license, python/LICENSE.txt), iced-x86 and pefile (MIT,
engine/pylibs) and the FX Reborn Toolkit (MIT, LICENSE-TOOLKIT.txt).
"""


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bundle_python(dest: Path):
    if sys.version_info[:2] != (3, 13):
        raise SystemExit("Packaging needs Python 3.13 (the bundled iced-x86 build is for 3.13).")
    base = Path(sys.base_prefix)
    dest.mkdir()
    if (base / "python313.zip").exists():  # running from an embeddable/bundled Python: copy it
        for f in base.iterdir():
            if f.is_file() and not f.name.endswith("._pth"):
                shutil.copy2(f, dest / f.name)
    else:
        for name in ("python.exe", "python3.dll", "python313.dll", "vcruntime140.dll",
                     "vcruntime140_1.dll", "LICENSE.txt"):
            shutil.copy2(base / name, dest / name)
        for f in (base / "DLLs").iterdir():
            if f.name.lower() in DLL_KEEP:
                shutil.copy2(f, dest / f.name)
        stage = dest.parent / "_stdlib"
        lib = base / "Lib"
        for path in lib.rglob("*.py"):
            rel = path.relative_to(lib)
            if rel.parts[0] in STDLIB_SKIP or "__pycache__" in rel.parts or "tests" in rel.parts:
                continue
            (stage / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, stage / rel)
        compileall.compile_dir(str(stage), quiet=1, legacy=True)
        with zipfile.ZipFile(dest / "python313.zip", "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for f in stage.rglob("*.pyc"):
                z.write(f, f.relative_to(stage).as_posix())
        shutil.rmtree(stage)
    (dest / "python313._pth").write_text("python313.zip\n.\n..\\engine\\pylibs\n..\\engine\n..\n")


def package(config_path: Path, out_root: Path, runtime: Path | None = None) -> int:
    cfg = json.loads(config_path.read_text())
    cdir = config_path.parent
    runtime = runtime or ROOT / "runtime" / "fxcompat.dll"
    if not runtime.exists():
        raise SystemExit(f"{runtime} not found. Compile runtime/fxcompat_static.cpp first (see README).")
    for key in ("mod_name", "game_title", "steam_folder", "targets"):
        if key not in cfg:
            raise SystemExit(f"game.json is missing '{key}'.")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{cfg['mod_name']}-{cfg.get('mod_version', '1.0.0')}").strip("-")
    out = out_root / slug
    if out.exists():
        shutil.rmtree(out)
    (out / "engine").mkdir(parents=True)
    for name in ("installer.py", "fxkit.py"):
        shutil.copy2(ROOT / name, out / name)
    shutil.copy2(ROOT / "LICENSE", out / "LICENSE-TOOLKIT.txt")
    shutil.copy2(config_path, out / "game.json")
    for build in cfg.get("known_builds", {}).values():
        shutil.copy2(cdir / build["sites"], out / build["sites"])
    for name in ENGINE_FILES:
        shutil.copy2(ROOT / "engine" / name, out / "engine" / name)
    shutil.copytree(ROOT / "engine" / "pylibs", out / "engine" / "pylibs",
                    ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(runtime, out / "fxcompat.dll")
    for title, command, comment in (("Install or Update", "install", "Builds and installs the mod; run again after game updates."),
                                    ("Restore original", "restore", "Puts the original game files back."),
                                    ("Status", "status", "Shows what is installed.")):
        (out / f"{title}.cmd").write_text(LAUNCHER.format(command=command, comment=comment).replace("\n", "\r\n"),
                                          encoding="ascii", newline="")
    title = f"{cfg['mod_name']} {cfg.get('mod_version', '')} - {cfg['game_title']} on CPUs without AVX2"
    (out / "README.txt").write_text(README.format(
        mod_name=cfg["mod_name"], mod_version=cfg.get("mod_version", ""), game_title=cfg["game_title"],
        underline="=" * len(title), features=", ".join(cfg.get("cpu_features", ["AVX"])),
        targets=", ".join(Path(t).name for t in cfg["targets"])))
    bundle_python(out / "python")
    sums = [f"{_sha(f)}  {f.relative_to(out).as_posix()}" for f in sorted(out.rglob("*")) if f.is_file()]
    (out / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    archive = out_root / f"{slug}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for f in sorted(out.rglob("*")):
            if f.is_file():
                z.write(f, (Path(slug) / f.relative_to(out)).as_posix())
    print(f"Player package: {out}\nZip: {archive} ({archive.stat().st_size / 1e6:.1f} MB)")
    return 0
