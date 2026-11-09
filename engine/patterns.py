"""Config-driven byte patches that survive game updates.

Games that require AVX2 often refuse to start on older CPUs with a message like
"This CPU does not support a required feature (AVX2)". Skipping that check is a
small byte patch, but a fixed address breaks on every game update. Here a patch
is described by its bytes and, optionally, by a string the surrounding code
refers to:

    {
      "name": "Skip the AVX2 startup check",
      "find":    "0f ba e0 08 72 ??",      # bt eax,8 ; jb short ...
      "replace": "0f ba e0 08 eb ??",      # bt eax,8 ; jmp short ... (?? keeps the byte)
      "near_string": "does not support a required feature (AVX2)",
      "expect": 1
    }

With "near_string", the pattern is only searched inside the functions (from the
exception table) that reference that string, as ASCII or UTF-16. "expect" is how
many matches there must be; anything else is an error, so a changed game never
gets patched in the wrong place.
"""
from __future__ import annotations

import bisect
import re

import iced_x86 as ix


class PatchError(RuntimeError):
    pass


def parse_hex(text: str) -> list[int | None]:
    out = []
    for tok in text.replace(",", " ").split():
        if tok in ("??", "?"):
            out.append(None)
        else:
            out.append(int(tok, 16))
    if not out:
        raise PatchError("empty byte pattern")
    return out


def _regex(pattern: list[int | None]) -> re.Pattern:
    return re.compile(b"".join(b"." if b is None else re.escape(bytes([b])) for b in pattern), re.DOTALL)


def _functions(pe):
    pe.parse_data_directories(directories=[3])
    funcs = sorted((e.struct.BeginAddress, e.struct.EndAddress)
                   for e in getattr(pe, "DIRECTORY_ENTRY_EXCEPTION", []))
    return funcs, [f[0] for f in funcs]


def _string_vas(pe, data: bytes, text: str) -> set[int]:
    base = pe.OPTIONAL_HEADER.ImageBase
    vas = set()
    for needle, unit in ((text.encode("utf-16-le"), 2), (text.encode("latin-1", "ignore"), 1)):
        pos = data.find(needle)
        while pos >= 0:
            start = pos
            # walk back to the start of the containing string
            while start >= unit and data[start - unit:start] != b"\0" * unit and data[start - unit] >= 0x20:
                start -= unit
            try:
                vas.add(base + pe.get_rva_from_offset(start))
            except Exception:
                pass
            pos = data.find(needle, pos + unit)
    return vas


def _code_sections(pe):
    for sec in pe.sections:
        if sec.Characteristics & 0x20000000:
            yield sec


def _regions_near(pe, data: bytes, text: str) -> list[tuple[int, int]]:
    base = pe.OPTIONAL_HEADER.ImageBase
    targets = _string_vas(pe, data, text)
    if not targets:
        raise PatchError(f'string not found: "{text}"')
    funcs, starts = _functions(pe)
    regions = set()
    for sec in _code_sections(pe):
        code = sec.get_data()[:sec.Misc_VirtualSize]
        for ins in ix.Decoder(64, code, ip=base + sec.VirtualAddress):
            if ins.is_ip_rel_memory_operand and ins.ip_rel_memory_address in targets:
                rva = ins.ip - base
                i = bisect.bisect_right(starts, rva) - 1
                if i >= 0 and rva < funcs[i][1]:
                    regions.add(funcs[i])
    if not regions:
        raise PatchError(f'no function references "{text}"')
    return sorted(regions)


def locate(pe, data: bytes, spec: dict) -> list[tuple[int, bytes, bytes]]:
    """Return [(rva, original_bytes, new_bytes)] for one patch spec, or raise PatchError."""
    find = parse_hex(spec["find"])
    replace = parse_hex(spec["replace"])
    if len(find) != len(replace):
        raise PatchError(f'{spec.get("name", "patch")}: "find" and "replace" differ in length')
    if spec.get("near_string"):
        regions = _regions_near(pe, data, spec["near_string"])
    else:
        regions = [(s.VirtualAddress, s.VirtualAddress + s.Misc_VirtualSize) for s in _code_sections(pe)]
    rx = _regex(find)
    hits = []
    for begin, end in regions:
        blob = pe.get_data(begin, end - begin)
        for m in rx.finditer(blob):
            rva = begin + m.start()
            old = m.group(0)
            new = bytes(o if r is None else r for o, r in zip(old, replace))
            hits.append((rva, old, new))
    hits = sorted(set(hits))
    expect = spec.get("expect", 1)
    if len(hits) != expect:
        where = ", ".join(hex(h[0]) for h in hits[:10])
        raise PatchError(f'{spec.get("name", "patch")}: expected {expect} match(es), found {len(hits)}'
                         + (f" at {where}" if hits else ""))
    return hits


def locate_all(pe, data: bytes, specs: list[dict]) -> list[dict]:
    out = []
    for spec in specs:
        for rva, old, new in locate(pe, data, spec):
            out.append({"name": spec.get("name", "patch"), "rva": rva, "old": old.hex(), "new": new.hex()})
    return out
