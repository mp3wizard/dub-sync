#!/usr/bin/env python3
"""Validate SRT structure. Catches the failure modes that break muxing or playback:
malformed timestamps (typo'd/stray non-ASCII chars), duplicate indices, cue-count
drift vs the source, zero-length or overlapping cues, empty text.

Usage:
    python validate_srt.py FILE.srt [FILE2.srt ...]
    python validate_srt.py TH.srt --expect-count 957      # assert exact cue count
    python validate_srt.py TH.srt --compare EN.srt        # report timestamp alignment vs source

Exit code is non-zero if any hard error is found, so it can gate a mux step.
"""
import re, sys, argparse

TS = re.compile(r'^(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)$')

def parse(path):
    # utf-8-sig transparently strips a BOM if present
    with open(path, encoding='utf-8-sig') as f:
        raw = f.read()
    had_bom = raw != open(path, encoding='utf-8').read() if False else None
    blocks = re.split(r'\n\s*\n', raw.strip())
    cues = []
    for i, b in enumerate(blocks):
        lines = b.split('\n')
        cues.append((i, lines))
    return cues

def ms(h, m, s, x):
    return ((h * 60 + m) * 60 + s) * 1000 + x

def validate(path, expect_count=None, compare=None):
    cues = parse(path)
    errors, warnings = [], []
    indices, starts = [], []
    prev_end = None
    for i, lines in cues:
        if len(lines) < 2:
            errors.append(f"block {i}: fewer than 2 lines: {lines!r}")
            continue
        idx, ts = lines[0].strip(), lines[1].strip()
        if not re.fullmatch(r'\d+', idx):
            errors.append(f"block {i}: index line is not a plain number: {idx!r}")
        else:
            indices.append(int(idx))
        m = TS.match(ts)
        if not m:
            # give a precise reason — stray non-ASCII in a timestamp is the classic typo
            stray = [c for c in ts if c not in '0123456789:,-> ']
            hint = f" (stray chars: {stray})" if stray else ""
            errors.append(f"block {i} (idx {idx}): bad timestamp {ts!r}{hint}")
        else:
            a = ms(*map(int, m.groups()[:4]))
            z = ms(*map(int, m.groups()[4:]))
            starts.append(a)
            if z <= a:
                errors.append(f"block {i} (idx {idx}): end <= start")
            if prev_end is not None and a < prev_end:
                warnings.append(f"block {i} (idx {idx}): starts before previous cue ends (overlap)")
            prev_end = z
        if len([l for l in lines[2:] if l.strip()]) == 0:
            errors.append(f"block {i} (idx {idx}): no subtitle text")

    dupes = sorted({x for x in indices if indices.count(x) > 1})
    if dupes:
        errors.append(f"duplicate indices: {dupes}")
    if indices and indices != list(range(indices[0], indices[0] + len(indices))):
        warnings.append("indices are not strictly sequential (usually harmless, but check for skips)")

    if expect_count is not None and len(cues) != expect_count:
        errors.append(f"cue count {len(cues)} != expected {expect_count}")

    if compare:
        ref = parse(compare)
        if len(ref) != len(cues):
            warnings.append(f"cue count differs from source: this={len(cues)} source={len(ref)} "
                            f"(fine if you deliberately merged/split cues; otherwise a red flag)")
        # count how many start-times line up
        ref_starts = []
        for _, rl in ref:
            if len(rl) > 1:
                rm = TS.match(rl[1].strip())
                if rm:
                    ref_starts.append(ms(*map(int, rm.groups()[:4])))
        common = len(set(starts) & set(ref_starts))
        print(f"  [compare] {common}/{len(starts)} cue start-times match the source")

    print(f"=== {path} ===")
    print(f"  cues: {len(cues)}   errors: {len(errors)}   warnings: {len(warnings)}")
    for e in errors:
        print("  ERROR:", e)
    for w in warnings:
        print("  warn :", w)
    return len(errors) == 0

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--expect-count", type=int, default=None)
    ap.add_argument("--compare", default=None, help="reference SRT to compare cue count / timestamps against")
    args = ap.parse_args()
    ok = True
    for p in args.files:
        ok &= validate(p, args.expect_count, args.compare)
    sys.exit(0 if ok else 1)
