"""Player-side installer for mods made with the FX Reborn Toolkit.

Driven entirely by game.json next to this file. For each target file (the game
exe and/or DLLs) it:
  1. finds the game through Steam (or takes a path),
  2. checks the CPU has the features the game needs,
  3. keeps the untouched original as <file>.fxkit-original; when Steam has
     replaced the file (a game update), saves the new one instead,
  4. picks the instructions to translate: a known build's frozen list, else a
     scan of the player's own file (marked UNVERIFIED), plus anything
     fxcompat.dll logged as missed in fxreborn-missed.log,
  5. builds the converted file and puts it, plus fxcompat.dll, in place.

  installer.py install [game folder] [--rebuild]
  installer.py restore [game folder]
  installer.py status  [game folder]
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import fxkit  # noqa: E402

BACKUP = ".fxkit-original"
STATE = ".fxkit-state.json"
MISSED_LOG = "fxreborn-missed.log"
RUNTIME = "fxcompat.dll"

# CPUID locations: (leaf, register index eax=0 ebx=1 ecx=2 edx=3, bit). Names are iced-x86's.
CPUID_BITS = {
    "SSE3": (1, 2, 0), "PCLMULQDQ": (1, 2, 1), "SSSE3": (1, 2, 9), "FMA": (1, 2, 12),
    "SSE4_1": (1, 2, 19), "SSE4_2": (1, 2, 20), "MOVBE": (1, 2, 22), "POPCNT": (1, 2, 23),
    "AES": (1, 2, 25), "AVX": (1, 2, 28), "F16C": (1, 2, 29), "RDRAND": (1, 2, 30),
    "BMI1": (7, 1, 3), "AVX2": (7, 1, 5), "BMI2": (7, 1, 8), "AVX512F": (7, 1, 16),
    "RDSEED": (7, 1, 18), "ADX": (7, 1, 19), "SHA": (7, 1, 29),
    "LZCNT": (0x80000001, 2, 5), "SSE4A": (0x80000001, 2, 6), "XOP": (0x80000001, 2, 11),
    "FMA4": (0x80000001, 2, 16),
}


class Stop(Exception):
    pass


def cpuid_reader():
    code = bytes.fromhex("53 4989d0 89c8 31c9 0fa2 418900 41895804 41894808 4189500c 5b c3".replace(" ", ""))
    k32 = ctypes.windll.kernel32
    k32.VirtualAlloc.restype = ctypes.c_void_p
    k32.VirtualAlloc.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_uint32]
    mem = k32.VirtualAlloc(None, len(code), 0x3000, 0x40)
    ctypes.memmove(mem, code, len(code))
    fn = ctypes.CFUNCTYPE(None, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32 * 4))(mem)

    def cpuid(leaf):
        out = (ctypes.c_uint32 * 4)()
        fn(leaf, ctypes.byref(out))
        return list(out)
    return cpuid


def check_cpu(required: list[str]):
    cpuid = cpuid_reader()
    cache = {}
    have = {}
    for name, (leaf, reg, bit) in CPUID_BITS.items():
        if leaf not in cache:
            cache[leaf] = cpuid(leaf)
        have[name] = bool(cache[leaf][reg] >> bit & 1)
    missing = [f for f in required if f in have and not have[f]]
    if missing:
        raise Stop("This CPU lacks " + ", ".join(missing) + ", which this game needs even after conversion.")
    if have["AVX2"] and have["BMI2"]:
        print("Note: this CPU already has AVX2 and BMI2; the game runs without this mod.")
    if not have["AVX"]:
        raise Stop("This CPU lacks AVX, which the converted code needs.")


def steam_libraries() -> list[Path]:
    roots = []
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.append(Path(winreg.QueryValueEx(k, name)[0]))
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass
    libs = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            libs += [Path(p.replace("\\\\", "\\")) for p in
                     re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore"))]
        libs.append(root)
    out, seen = [], set()
    for lib in libs:
        if str(lib).lower() not in seen:
            seen.add(str(lib).lower())
            out.append(lib)
    return out


def find_game(cfg: dict, explicit: str | None) -> Path:
    first = cfg["targets"][0]
    if explicit:
        root = Path(explicit)
        if (root / first).exists():
            return root
        raise Stop(f"{first} not found under {root}")
    found = [lib / "steamapps" / "common" / cfg["steam_folder"] for lib in steam_libraries()]
    found = [p for p in found if (p / first).exists()]
    if not found:
        raise Stop(f"Could not find {cfg['game_title']} in your Steam libraries. "
                   "Drag the game folder onto the Install launcher, or pass it as an argument.")
    if len(found) > 1:
        raise Stop("More than one installation found; pass the one to use:\n  " + "\n  ".join(map(str, found)))
    return found[0]


def running(process: str) -> bool:
    out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {process}", "/NH"], capture_output=True, text=True).stdout
    return process.lower() in out.lower()


def is_converted(path: Path) -> bool:
    import pefile
    with path.open("rb") as f:
        head = f.read(0x2000)
    return any(s.Name.rstrip(b"\0") == b".fxcpt" for s in pefile.PE(data=head, fast_load=True).sections)


def state_path(t: Path) -> Path:
    return t.with_name(t.name + STATE)


def install_target(cfg: dict, target: Path, rebuild: bool, game_root: Path):
    backup = target.with_name(target.name + BACKUP)
    st = json.loads(state_path(target).read_text()) if state_path(target).exists() else {}
    current = fxkit.sha256(target)
    log = target.parent / MISSED_LOG
    if is_converted(target):
        if not backup.exists() or is_converted(backup):
            raise Stop(f"{target.name} is converted but no clean backup exists. Verify the game files in Steam "
                       "and run this again.")
        original_sha = fxkit.sha256(backup)
        learned = sorted(set(int(x, 16) for x in st.get("learned_sites", []))
                         | set(fxkit.learned_from_log(log, target.name)))
        new = set(learned) - set(int(x, 16) for x in st.get("learned_sites", []))
        if st.get("converted_sha256") == current and not rebuild and not new:
            print(f"{target.name}: already installed for this game version ({st.get('site_kind')}).")
            return
    else:
        original_sha = current
        if backup.exists() and fxkit.sha256(backup) != current:
            print(f"{target.name} changed since the last install (game update?). Saving the new original.")
            st = {}
        tmp = backup.with_name(backup.name + ".tmp")
        shutil.copy2(target, tmp)
        if fxkit.sha256(tmp) != current:
            raise Stop("Backup copy failed verification. Nothing was changed.")
        os.replace(tmp, backup)
        learned = fxkit.learned_from_log(log, target.name) if st.get("original_sha256") == original_sha else []

    sites, kind, report = fxkit.choose_sites(backup, cfg, ROOT, learned)
    specs = [p for p in cfg.get("patches", []) if p.get("target", target.name).lower() == target.name.lower()]
    print(f"{target.name}: {len(sites)} sites, list {kind}", flush=True)
    with tempfile.TemporaryDirectory(prefix="fxkit-", dir=target.parent) as tmpdir:
        work = Path(tmpdir)
        local = work / "in" / target.name
        local.parent.mkdir()
        shutil.copy2(backup, local)
        patches = fxkit.locate_patches(local, specs)
        manifest = fxkit.build(local, work / "out", sites, patches)
        if manifest["unwind_refusals"]:
            raise Stop(f"{len(manifest['unwind_refusals'])} unwind refusals in {target.name}; not installing.")
        if manifest["skipped"]:
            print(f"Warning: {len(manifest['skipped'])} instructions in {target.name} could not be translated.")
        converted = work / "out" / target.name
        converted_sha = fxkit.sha256(converted)
        shutil.copy2(ROOT / RUNTIME, target.with_name(RUNTIME))
        os.replace(converted, target)
    tmp = state_path(target).with_name(state_path(target).name + ".tmp")
    tmp.write_text(json.dumps({"mod": cfg["mod_name"], "original_sha256": original_sha,
                               "converted_sha256": converted_sha, "site_kind": kind, "sites": len(sites),
                               "learned_sites": [hex(x) for x in learned], "methods": manifest["methods"],
                               "skipped": len(manifest["skipped"]), "patches": manifest.get("patches", []),
                               "scan_report": report, "built": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
    os.replace(tmp, state_path(target))
    if not kind.startswith("verified"):
        print(f"{target.name}: this game version is UNVERIFIED (scanned on this PC, not play-tested).")


def install(cfg, root: Path, rebuild: bool):
    check_cpu(cfg.get("cpu_features", []))
    if running(cfg.get("process", Path(cfg["targets"][0]).name)):
        raise Stop("The game is running. Close it first.")
    if not (ROOT / RUNTIME).exists():
        raise Stop(f"{RUNTIME} is missing from the mod folder.")
    started = time.time()
    for rel in cfg["targets"]:
        install_target(cfg, root / rel, rebuild, root)
    log = (root / cfg["targets"][0]).parent / MISSED_LOG
    if log.exists():
        log.replace(log.with_name(MISSED_LOG + ".processed"))
    print(f"Done in {time.time() - started:.0f}s. If the game ever closes with a missing-instruction error, "
          "run this again: it reads fxreborn-missed.log and adds the address.")


def restore(cfg, root: Path):
    if running(cfg.get("process", Path(cfg["targets"][0]).name)):
        raise Stop("The game is running. Close it first.")
    for rel in cfg["targets"]:
        t = root / rel
        b = t.with_name(t.name + BACKUP)
        if not is_converted(t):
            print(f"{t.name}: not converted.")
            continue
        if not b.exists() or is_converted(b):
            raise Stop(f"No clean backup for {t.name}. Use Steam's Verify integrity of game files.")
        tmp = t.with_name(t.name + ".restore.tmp")
        shutil.copy2(b, tmp)
        os.replace(tmp, t)
        if state_path(t).exists():
            state_path(t).unlink()
        print(f"{t.name}: original restored.")
    rt = (root / cfg["targets"][0]).with_name(RUNTIME)
    if rt.exists() and not any(is_converted(root / r) for r in cfg["targets"]):
        rt.unlink()


def status(cfg, root: Path):
    print(f"{cfg['mod_name']} for {cfg['game_title']}: {root}")
    for rel in cfg["targets"]:
        t = root / rel
        st = json.loads(state_path(t).read_text()) if state_path(t).exists() else {}
        print(f"  {t.name}: converted={is_converted(t)} {st.get('site_kind', '')} {st.get('built', '')}")
        if st and st.get("converted_sha256") != fxkit.sha256(t):
            print("    changed since install (game update?): run Install or Update again.")
    if ((root / cfg["targets"][0]).parent / MISSED_LOG).exists():
        print(f"  {MISSED_LOG} has entries: run Install or Update again to add them.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["install", "restore", "status"])
    ap.add_argument("game", nargs="?", help="game folder (default: find it through Steam)")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--config", default=str(ROOT / "game.json"))
    a = ap.parse_args()
    cfg = json.loads(Path(a.config).read_text())
    print(f"{cfg['mod_name']} (FX Reborn Toolkit {fxkit.VERSION})")
    try:
        root = find_game(cfg, a.game)
        {"install": lambda: install(cfg, root, a.rebuild), "restore": lambda: restore(cfg, root),
         "status": lambda: status(cfg, root)}[a.command]()
    except Stop as e:
        print("Stopped:", e)
        return 1
    except Exception as e:  # noqa: BLE001 - show players a readable error, keep details
        import traceback
        traceback.print_exc()
        print("Stopped by an unexpected error. Nothing was replaced unless a message above says so.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
