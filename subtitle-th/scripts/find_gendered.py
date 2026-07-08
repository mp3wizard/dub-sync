#!/usr/bin/env python3
"""Scan a Thai SRT and list every cue that contains a gender-marked word, so the
gender-verification pass can focus only on cues that can actually be wrong.

Thai first-person pronouns and polite ending particles are gendered; English has no
equivalent, so a straight translation guesses the speaker's gender and gets it wrong
for roughly half of a female character's lines. This script surfaces the candidates;
a human or a subagent then confirms each against the speaker (see references/thai-gender-guide.md).

Usage:
    python find_gendered.py TH.srt
    python find_gendered.py TH.srt --only male     # or: female

Some matches are false positives because the marker is a substring of an unrelated word
(ผม = "hair", หนู = "mouse", ค่ะ inside no common word but คะ inside คะแนน "score",
คะนอง). Those are flagged with (?) so you don't blindly flip them.
"""
import re, sys, argparse

MALE = ["กระผม", "ผม", "ครับผม", "นะครับ", "ครับ"]
FEMALE = ["ดิฉัน", "ฉัน", "หนู", "นะคะ", "ค่ะ", "คะ"]

# substrings that commonly cause false positives, with the innocent word they belong to
FALSE_POS = {
    "ผม": ["ผมยาว", "เส้นผม", "ทรงผม", "ตัดผม", "สระผม"],   # hair
    "หนู": ["หนูนา", "หนูตะเภา"],                              # mouse/rat
    "คะ": ["คะแนน", "คะนอง", "อยากคะ"],                        # score / roaring
}

def load(path):
    with open(path, encoding='utf-8-sig') as f:
        raw = f.read()
    out = []
    for b in re.split(r'\n\s*\n', raw.strip()):
        lines = b.split('\n')
        if len(lines) >= 3:
            out.append((lines[0].strip(), lines[1].strip(), "\n".join(lines[2:])))
    return out

def hits(text, markers):
    found = []
    for mk in markers:
        idx = text.find(mk)
        while idx != -1:
            # skip if this marker is already covered by a longer marker at the same spot
            fp = any(fpw in text for fpw in FALSE_POS.get(mk, []))
            found.append((mk, "?" if fp else ""))
            idx = text.find(mk, idx + 1)
            break  # one flag per marker per cue is enough
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("srt")
    ap.add_argument("--only", choices=["male", "female"], default=None)
    args = ap.parse_args()

    markers = []
    if args.only in (None, "male"):
        markers += [(m, "M") for m in MALE]
    if args.only in (None, "female"):
        markers += [(m, "F") for m in FEMALE]

    cues = load(args.srt)
    n = 0
    for idx, ts, text in cues:
        one_line = text.replace("\n", " ")
        found = []
        for mk, gender in markers:
            for hit, flag in hits(one_line, [mk]):
                found.append(f"{gender}:{hit}{flag}")
        if found:
            n += 1
            print(f"[{idx}] {'  '.join(sorted(set(found)))}")
            print(f"      {one_line}")
    print(f"\n{n} cues contain gender markers (of {len(cues)}). "
          f"'?' = possible false positive — verify before changing.")

if __name__ == "__main__":
    main()
