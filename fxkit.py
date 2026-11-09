"""FX Reborn Toolkit: make AVX2 games run on CPUs that only have AVX.

Rewrites AVX2/BMI2 instructions in a game's exe or DLL into equivalent AVX/SSE
code, adds a tiny runtime DLL (fxcompat.dll) for sites too short to jump from,
and can patch the game's "CPU not supported" check. Built from FX Reborn, the
FF7 Rebirth mod that took an AMD FX-8350 from 1 FPS (emulated) to 30-85 FPS.

Commands (modder side):
  scan    <exe|dll>                     Can this game be converted? Counts AVX2/BMI2
                                        instructions, checks which ones the engine can
                                        translate, and lists other CPU features it needs.
  gate    <exe|dll>                     Finds "requires AVX2" CPU checks and suggests a
                                        patch spec for game.json.
  build   <exe|dll> -o DIR [--config game.json] [--learned LOG]
                                        Writes the converted file + manifest + fxcompat.dll.
  package --config game.json -o DIR     Makes a player-ready mod folder and zip: launchers,
                                        your config, the engine, fxcompat.dll and a private
                                        Python, so players install nothing.

Players then run "Install or Update.cmd", which builds the patch on their own PC
for whatever game version they have (see installer.py).
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENGINE = ROOT / "engine"
sys.path[:0] = [str(ENGINE / "pylibs"), str(ENGINE)]

VERSION = "0.1.0"
# Features every x86-64 CPU has; never worth reporting as requirements.
BASELINE = {"X64", "SSE", "SSE2", "CMOV", "CX8", "FPU", "MMX", "FXSR", "INTEL8086", "INTEL186",
            "INTEL286", "INTEL386", "INTEL486", "INTEL8086_ONLY", "CPUID", "SYSCALL", "TSC",
            "MULTIBYTENOP", "PAUSE", "CLFSH", "MSR", "RDTSCP", "XSAVE", "OSXSAVE", "SSE3",
            "CX16", "LAHF_SAHF", "PREFETCHW", "D3NOW_PREFETCH", "PREFETCH"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def feature_names():
    import iced_x86 as ix
    return {v: k for k, v in vars(ix.CpuidFeature).items() if isinstance(v, int)}


def load_pe(path: Path):
    import pefile
    data = path.read_bytes()
    pe = pefile.PE(data=data, fast_load=True)
    pe.parse_data_directories(directories=[3])
    return pe, data


# ------------------------------------------------------------------- sites
def find_sites(path: Path) -> tuple[list[int], dict]:
    import find_sites as fs
    print("Scanning for AVX2/BMI2 code (follows the program's control flow; large games take minutes)...",
          flush=True)
    discovery = fs.discover(path)
    pe, _ = load_pe(path)
    return fs.select(pe, discovery)


def learned_from_log(log: Path, module: str | None = None) -> list[int]:
    """Addresses fxcompat.dll logged as untranslated (fxreborn-missed.log).

    module: the file name of the converted exe/dll. Without it, only entries for
    the main exe are used."""
    out = set()
    if log and log.exists():
        for line in log.read_text(errors="ignore").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not e.get("rva"):
                continue
            if module and e.get("module"):
                match = e["module"].lower() == module.lower()
            else:
                match = bool(int(e.get("main_module", "0x0"), 16))
            if match:
                out.add(int(e["rva"], 16))
    return sorted(out)


def choose_sites(path: Path, config: dict, config_dir: Path, extra=(), force_scan=False):
    """Known build -> its frozen list; otherwise scan. Returns (sites, kind, report)."""
    digest = sha256(path)
    known = config.get("known_builds", {}).get(digest)
    if known and not force_scan:
        data = json.loads((config_dir / known["sites"]).read_text())
        sites = [int(x, 16) for x in data["sites"]]
        kind, report = f"verified ({known.get('label', digest[:12])})", {}
    else:
        cache = ENGINE / "code_cache" / f"{digest}.sites.json"
        if cache.exists():
            data = json.loads(cache.read_text())
        else:
            sites, report = find_sites(path)
            data = {"sites": [hex(s) for s in sites], "report": report}
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps(data))
        sites, kind, report = [int(x, 16) for x in data["sites"]], "UNVERIFIED (scanned)", data["report"]
    added = sorted(set(extra) - set(sites))
    return sorted(set(sites) | set(extra)), kind, {**report, "learned_added": [hex(a) for a in added]}


# ------------------------------------------------------------------- build
def build(path: Path, out_dir: Path, sites: list[int], patches: list[dict]) -> dict:
    """Patch a copy of path into out_dir. Returns the manifest."""
    import build_static_mod as engine
    out_dir.mkdir(parents=True, exist_ok=True)
    engine.STAGING = out_dir
    engine.Builder(path, [{"rva": hex(r)} for r in sites], patches).finish()
    return json.loads((out_dir / (path.name + ".manifest.json")).read_text())


def locate_patches(path: Path, specs: list[dict]) -> list[dict]:
    import patterns
    pe, data = load_pe(path)
    return patterns.locate_all(pe, data, specs)


# -------------------------------------------------------------- commands
def cmd_scan(a):
    import iced_x86 as ix
    import avx2_lower
    import bmi2_lower
    path = Path(a.file)
    pe, data = load_pe(path)
    names = feature_names()
    is_dll = bool(pe.FILE_HEADER.Characteristics & 0x2000)
    patched = any(s.Name.rstrip(b"\0") == b".fxcpt" for s in pe.sections)
    print(f"{path.name}: {'DLL' if is_dll else 'EXE'}, {len(data) / 1e6:.1f} MB, sha256 {sha256(path)[:16]}...")
    if patched:
        print("This file is already converted (.fxcpt section present). Scan the original instead.")
        return 1

    # Other instruction-set features the game uses (linear sweep of code sections).
    used = collections.Counter()
    base = pe.OPTIONAL_HEADER.ImageBase
    t = time.time()
    for sec in pe.sections:
        if sec.Characteristics & 0x20000000:
            for ins in ix.Decoder(64, sec.get_data()[:sec.Misc_VirtualSize], ip=base + sec.VirtualAddress):
                for f in ins.cpuid_features():
                    used[names.get(f, str(f))] += 1
    print(f"(feature sweep {time.time() - t:.0f}s)")

    sites, report = find_sites(path)
    by_mnemonic = collections.Counter()
    unsupported = collections.Counter()
    stub_features = set()
    fmt = ix.Formatter(ix.FormatterSyntax.INTEL)
    for rva in sites:
        ins = ix.Decoder(64, pe.get_data(rva, 15), ip=base + rva).decode()
        mnem = fmt.format_mnemonic(ins)
        by_mnemonic[mnem] += 1
        fs = ins.cpuid_features()
        try:
            body = (bmi2_lower.lower(ins, ins.ip) if ix.CpuidFeature.BMI2 in fs
                    else avx2_lower.lower(ins, ins.ip) if ix.CpuidFeature.AVX2 in fs else None)
        except Exception as err:
            body, why = None, str(err)
        else:
            why = "no lowering"
        if body is None:
            unsupported[f"{mnem} ({why[:60]})"] += 1
        else:
            for sub in ix.Decoder(64, body, ip=ins.ip):
                stub_features.update(names.get(f, str(f)) for f in sub.cpuid_features())

    needs = sorted(k for k in used if k not in BASELINE | {"AVX2", "BMI2"})
    stub_needs = sorted(stub_features - BASELINE)
    ok = len(sites) - sum(unsupported.values())
    lines = [f"# FX Reborn Toolkit scan: {path.name}", "",
             f"- AVX2/BMI2 instructions found (control flow + reviewed pointer targets): **{len(sites)}**",
             f"- Translatable by the engine: **{ok}**; not yet supported: **{sum(unsupported.values())}**",
             f"- Byte-sweep-only candidates ignored (may be data): {report.get('linear_candidates_ignored', 0)}",
             f"- Pointer-reached groups rejected by the automatic review: {len(report.get('address_reference_rejected', []))}",
             "", "## Other CPU features this program uses (players' CPUs must have these)", "",
             ", ".join(f"{k} ({used[k]})" for k in needs) or "none beyond baseline x86-64",
             "", f"Translated code itself uses: {', '.join(stub_needs) or 'baseline only'}",
             "", "## AVX2/BMI2 instructions by type", "", "| instruction | count |", "|---|---:|"]
    lines += [f"| {m} | {c} |" for m, c in by_mnemonic.most_common()]
    if unsupported:
        lines += ["", "## Not yet supported (left as-is; the game closes if it reaches them)", "",
                  "| instruction | count |", "|---|---:|"]
        lines += [f"| {m} | {c} |" for m, c in unsupported.most_common()]
    verdict = ("Looks convertible." if not unsupported else
               "Partly convertible: unsupported instructions need engine work (avx2_lower.py) or must "
               "be unreachable in practice.")
    if any(k in needs for k in ("AVX512F", "AVX512BW", "AVX512VL", "AVX512DQ")):
        verdict += " The program also uses AVX-512, which this toolkit does not translate."
    lines += ["", f"**Verdict:** {verdict}"]
    text = "\n".join(lines)
    print(text)
    if a.report:
        Path(a.report).write_text(text + "\n", encoding="utf-8")
        print(f"\nSaved {a.report}")
    return 0


def cmd_gate(a):
    import bisect
    import iced_x86 as ix
    import patterns
    path = Path(a.file)
    pe, data = load_pe(path)
    base = pe.OPTIONAL_HEADER.ImageBase
    fmt = ix.Formatter(ix.FormatterSyntax.INTEL)
    found = False
    texts = set()
    for needle in (b"AVX2", "AVX2".encode("utf-16-le")):
        pos = data.find(needle)
        while pos >= 0 and len(texts) < 50:
            unit = 2 if needle[1:2] == b"\0" else 1
            s = pos
            while s >= unit and data[s - unit:s] != b"\0" * unit and data[s - unit] >= 0x20:
                s -= unit
            e = pos
            while e + unit <= len(data) and data[e:e + unit] != b"\0" * unit:
                e += unit
            raw = data[s:e]
            try:
                txt = raw.decode("utf-16-le" if unit == 2 else "latin-1")
            except UnicodeDecodeError:
                txt = ""
            if 6 <= len(txt) <= 300 and txt.isprintable():
                texts.add(txt)
            pos = data.find(needle, pos + unit)
    funcs, starts = patterns._functions(pe)
    for txt in sorted(texts):
        try:
            regions = patterns._regions_near(pe, data, txt)
        except patterns.PatchError:
            continue
        print(f'\nString: "{txt}"')
        for begin, end in regions:
            print(f"  referenced in function {begin:#x}-{end:#x}. Feature tests in it:")
            prev = None
            for ins in ix.Decoder(64, pe.get_data(begin, end - begin), ip=base + begin):
                is_test = (ins.mnemonic in (ix.Mnemonic.BT, ix.Mnemonic.TEST)
                           and ins.op_count == 2 and ins.op1_kind in (ix.OpKind.IMMEDIATE8, ix.OpKind.IMMEDIATE32)
                           and (ins.immediate(1) in (5, 8, 0x20, 0x100)))
                if prev is not None and prev[0] and ins.flow_control == ix.FlowControl.CONDITIONAL_BRANCH:
                    p = prev[1]
                    rva = p.ip - base
                    raw = pe.get_data(rva, p.len + ins.len).hex(" ")
                    print(f"    {rva:#x}: {fmt.format(p)} ; {fmt.format(ins)}    bytes: {raw}")
                    found = True
                prev = (is_test, ins)
    if not found:
        print("No AVX2 check found next to an AVX2 message. The game may check CPUID elsewhere "
              "or not at all; try running the converted game and see whether it complains.")
        return 0
    print('\nTo skip a check, add a patch to game.json, e.g. for "bt eax,8 ; jb":\n'
          '  {"name": "Skip AVX2 check", "find": "0f ba e0 08 72 ??", "replace": "0f ba e0 08 eb ??",\n'
          '   "near_string": "<the message above>", "expect": 1}\n'
          "Turn the conditional jump that skips the error into an unconditional one (72/73/74/75 -> eb\n"
          "for short jumps), or NOP the jump that leads to the error. Check your choice in a disassembler.")
    return 0


def load_config(path: str | None) -> tuple[dict, Path]:
    if not path:
        return {}, Path.cwd()
    p = Path(path)
    return json.loads(p.read_text()), p.parent


def cmd_build(a):
    path = Path(a.file)
    out = Path(a.out)
    config, cdir = load_config(a.config)
    learned = learned_from_log(Path(a.learned), path.name) if a.learned else []
    sites, kind, report = choose_sites(path, config, cdir, learned, a.scan)
    patches = locate_patches(path, [p for p in config.get("patches", [])
                                    if p.get("target", path.name).lower() == path.name.lower()])
    for p in patches:
        print(f"Patch '{p['name']}' at {p['rva']:#x}: {p['old']} -> {p['new']}")
    print(f"{len(sites)} sites ({kind}). Building...", flush=True)
    manifest = build(path, out, sites, patches)
    runtime = Path(a.runtime) if a.runtime else ROOT / "runtime" / "fxcompat.dll"
    if runtime.exists():
        shutil.copy2(runtime, out / "fxcompat.dll")
    else:
        print("Note: runtime/fxcompat.dll not found; compile runtime/fxcompat_static.cpp (see README).")
    print(f"Done: {out / path.name}  methods {manifest['methods']}  skipped {len(manifest['skipped'])}"
          f"  unwind refusals {len(manifest['unwind_refusals'])}")
    print("Put the converted file AND fxcompat.dll next to each other in the game folder.")
    return 0


def cmd_package(a):
    import package_mod
    return package_mod.package(Path(a.config), Path(a.out), Path(a.runtime) if a.runtime else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("scan", help="report how convertible an exe/dll is")
    s.add_argument("file")
    s.add_argument("--report", help="also save the report as Markdown")
    g = sub.add_parser("gate", help="find AVX2 CPU checks and suggest patches")
    g.add_argument("file")
    b = sub.add_parser("build", help="convert an exe/dll")
    b.add_argument("file")
    b.add_argument("-o", "--out", required=True, help="output folder (never the game folder)")
    b.add_argument("--config", help="game.json with patches and known builds")
    b.add_argument("--learned", help="fxreborn-missed.log from a test run, to add missed sites")
    b.add_argument("--scan", action="store_true", help="scan even if the build is in known_builds")
    b.add_argument("--runtime", help="fxcompat.dll to copy (default runtime/fxcompat.dll)")
    p = sub.add_parser("package", help="make a player-ready mod folder + zip")
    p.add_argument("--config", required=True)
    p.add_argument("-o", "--out", required=True)
    p.add_argument("--runtime", help="fxcompat.dll to include (default runtime/fxcompat.dll)")
    a = ap.parse_args()
    print(f"FX Reborn Toolkit {VERSION}")
    return {"scan": cmd_scan, "gate": cmd_gate, "build": cmd_build, "package": cmd_package}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
