#!/usr/bin/env python3
"""Apply a batch of gender-verify fixes to a Thai SRT in ONE pass.

The gender-verify step (see SKILL.md section 3) tends to accumulate many small,
independent fixes (one per flagged cue). Applying each with a separate `Edit` tool
call is expensive: every additional assistant turn re-sends the whole growing
conversation as fresh input, so N individual edits cost roughly O(N^2) tokens, not
O(N). This script lets the fixes be collected first (as data) and applied in a
single deterministic pass instead.

Usage:
    python apply_gender_fixes.py TH.srt --fixes fixes.json
    python apply_gender_fixes.py TH.srt --fixes-json '[{"cue":"42","find":"ผม","replace":"ฉัน"}]'
    python apply_gender_fixes.py TH.srt --fixes fixes.json --out TH.fixed.srt   # write elsewhere

fixes.json is a JSON list of objects: {"cue": "<index as it appears in the SRT>",
"find": "<exact substring to replace>", "replace": "<new substring>"}. "find" must
appear in that cue's text EXACTLY ONCE — this is a safety check against accidentally
touching the wrong occurrence or a cue that already got fixed. Multiple fixes may
target the same cue (applied in the order given).

Exits non-zero (and applies nothing) if the cue count doesn't match the source SRT's
cue count is not itself checked here — pair this with validate_srt.py --compare
after applying.
"""
import re, sys, json, argparse

def load(path):
    with open(path, encoding='utf-8-sig') as f:
        raw = f.read()
    out = []
    for b in re.split(r'\n\s*\n', raw.strip()):
        lines = b.split('\n')
        if len(lines) >= 3:
            out.append([lines[0].strip(), lines[1].strip(), "\n".join(lines[2:])])
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("--fixes", default=None, help="path to a JSON file of fixes")
    ap.add_argument("--fixes-json", default=None, help="inline JSON list of fixes")
    ap.add_argument("--out", default=None, help="output path (default: overwrite srt in place)")
    args = ap.parse_args()

    if not args.fixes and not args.fixes_json:
        sys.exit("provide --fixes FILE or --fixes-json JSON")
    fixes = json.load(open(args.fixes, encoding='utf-8')) if args.fixes else json.loads(args.fixes_json)

    cues = load(args.srt)
    by_index = {c[0]: c for c in cues}

    errors = []
    applied = 0
    for i, fx in enumerate(fixes):
        cue_idx, find, replace = str(fx["cue"]), fx["find"], fx["replace"]
        c = by_index.get(cue_idx)
        if c is None:
            errors.append(f"fix #{i}: cue [{cue_idx}] not found in {args.srt}")
            continue
        count = c[2].count(find)
        if count == 0:
            errors.append(f"fix #{i}: cue [{cue_idx}] does not contain {find!r} (already fixed, or wrong text)")
            continue
        if count > 1:
            errors.append(f"fix #{i}: cue [{cue_idx}] contains {find!r} {count} times — ambiguous, fix manually")
            continue
        c[2] = c[2].replace(find, replace)
        applied += 1

    if errors:
        print(f"{len(errors)} fix(es) could NOT be applied safely:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(f"\n{applied}/{len(fixes)} applied; nothing written. Fix the list above and re-run.", file=sys.stderr)
        sys.exit(1)

    out_text = "\n\n".join(f"{idx}\n{ts}\n{text}" for idx, ts, text in cues) + "\n"
    out_path = args.out or args.srt
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(out_text)
    print(f"applied {applied}/{len(fixes)} fixes -> {out_path}")

if __name__ == "__main__":
    main()
