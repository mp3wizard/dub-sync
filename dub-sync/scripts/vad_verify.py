#!/usr/bin/env python3
"""Verify dub alignment by SPEECH ONSET times (VAD), not energy correlation.

`dense_verify.py` cross-correlates energy envelopes: it proves the loud/quiet
*pattern* lines up. On a weak-M&E rip (a dub whose music & effects were remixed)
that correlation runs 0.1-0.3 and large stretches come back "uncertain" — the
verdict degrades to CHECK and you are told to spot-check by ear. This script
answers a different, more direct question: **does someone start talking at the
same moment in both tracks?** Speech onsets survive the language gap and the
M&E gap, so coverage is typically near 100% where correlation manages ~30-80%.

Measured on one episode (44 min, Apple silicon, CPU): ~6s per track.

    python vad_verify.py --eng ORIGINAL.mp4 --built OUT.mkv
    python vad_verify.py --eng ORIGINAL.mp4 --built OUT.mkv --built-stream 0:a:1
    python vad_verify.py --eng ORIGINAL.mp4 --built OUT.mkv --from 850 --to 990

Needs `whisper-vad-speech-segments` (whisper.cpp) on PATH plus a silero VAD
model. Point --vad-model at it, or drop it next to this script / in the toolkit
dir and it is found automatically.

CAVEAT on the offset magnitude: onsets are paired nearest-first within
--max-shift. If the dub is off by more than roughly half the gap between
consecutive lines, an onset can pair with the *neighbouring* utterance instead
of its true partner, which understates the offset. So a reported FAIL magnitude
is a LOWER BOUND on the real drift — trust the FAIL, not the exact number. The
`ambiguous` count in the summary flags how often the pairing was a close call.
"""
import subprocess, argparse, os, re, sys, tempfile, shutil
import numpy as np

SEG_RE = re.compile(r"VAD segment\s+\d+:\s*start\s*=\s*([0-9.]+),\s*end\s*=\s*([0-9.]+)")

DEFAULT_VAD_MODELS = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "ggml-silero-v5.1.2.bin"),
    os.path.expanduser("~/Public/thai-media-localization-toolkit/ggml-silero-v5.1.2.bin"),
]


def find_vad_model(explicit):
    if explicit:
        if not os.path.exists(explicit):
            sys.exit(f"VAD model not found: {explicit}")
        return explicit
    for p in DEFAULT_VAD_MODELS:
        if os.path.exists(p):
            return p
    sys.exit("no silero VAD model found — pass --vad-model, or place "
             "ggml-silero-v5.1.2.bin beside this script.\n"
             "  get it: https://huggingface.co/ggml-org/whisper-vad")


def extract(src, stream, wav, ss, to):
    """Decode one audio stream to mono 16k wav (what the VAD binary wants)."""
    c = ["ffmpeg", "-v", "error", "-y"]
    if ss is not None:
        c += ["-ss", str(ss)]
    if to is not None:
        c += ["-to", str(to)] if ss is None else ["-t", str(to - ss)]
    c += ["-i", src, "-map", stream, "-ac", "1", "-ar", "16000", wav]
    r = subprocess.run(c, capture_output=True)
    if r.returncode != 0 or not os.path.exists(wav) or os.path.getsize(wav) < 1000:
        sys.exit(f"ffmpeg failed extracting {stream} from {src}:\n"
                 f"{r.stderr.decode(errors='replace')}")


def vad(wav, model, threshold, threads, base):
    """Run the VAD binary and return speech segments as absolute-time (start,end).

    NOTE: never pass -ug/--use-gpu — the Metal backend aborts on this VAD graph
    (ggml pre-allocated-tensor abort). CPU is ~140x realtime anyway.
    """
    c = ["whisper-vad-speech-segments", "-f", wav, "-vm", model]
    if threshold is not None:
        c += ["-vt", str(threshold)]
    if threads:
        c += ["-t", str(threads)]
    try:
        r = subprocess.run(c, capture_output=True)
    except FileNotFoundError:
        sys.exit("whisper-vad-speech-segments not on PATH (brew install whisper-cpp)")
    out = (r.stdout + r.stderr).decode(errors="replace")
    segs = [(float(a) + base, float(b) + base) for a, b in SEG_RE.findall(out)]
    if not segs:
        sys.exit("VAD returned no speech segments — treating as an error, not a pass.\n"
                 "Check the audio stream spec and that the clip actually has speech.\n"
                 + out[-1500:])
    return np.array(segs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eng", required=True, help="reference/original media")
    ap.add_argument("--built", required=True, help="built file containing the synced dub")
    ap.add_argument("--eng-stream", default="0:a:0")
    ap.add_argument("--built-stream", default="0:a:0", help="the dub track inside --built")
    ap.add_argument("--from", dest="ss", type=float, default=None)
    ap.add_argument("--to", dest="to", type=float, default=None)
    ap.add_argument("--window", type=float, default=120.0, help="reporting window sec")
    ap.add_argument("--max-shift", type=float, default=8.0, help="max |offset| to call a match")
    ap.add_argument("--tolerance", type=float, default=0.5, help="|median| above this = misaligned")
    ap.add_argument("--min-onsets", type=int, default=3, help="min matches for a window to count")
    ap.add_argument("--vad-model", default=None)
    ap.add_argument("--vad-threshold", type=float, default=None)
    ap.add_argument("--threads", type=int, default=None)
    ap.add_argument("--keep-temp", action="store_true")
    a = ap.parse_args()

    model = find_vad_model(a.vad_model)
    base = a.ss or 0.0
    tmp = tempfile.mkdtemp(prefix="vadverify_")
    try:
        print("[extract] reference + dub audio ...", flush=True)
        ew, bw = os.path.join(tmp, "eng.wav"), os.path.join(tmp, "dub.wav")
        extract(a.eng, a.eng_stream, ew, a.ss, a.to)
        extract(a.built, a.built_stream, bw, a.ss, a.to)

        print("[vad] detecting speech ...", flush=True)
        en = vad(ew, model, a.vad_threshold, a.threads, base)
        th = vad(bw, model, a.vad_threshold, a.threads, base)
    finally:
        if a.keep_temp:
            print(f"[temp] kept in {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    en_on, th_on = en[:, 0], th[:, 0]
    print(f"\nspeech segments: reference={len(en_on)}  dub={len(th_on)}\n")

    offs, at, ambiguous = [], [], 0
    for t in en_on:
        d = th_on - t
        order = np.argsort(np.abs(d))
        i = order[0]
        if abs(d[i]) <= a.max_shift:
            offs.append(d[i])
            at.append(t)
            # pairing is a close call if the runner-up is nearly as near
            if len(order) > 1 and abs(abs(d[order[1]]) - abs(d[i])) < 0.3:
                ambiguous += 1
    offs, at = np.array(offs), np.array(at)
    if len(offs) == 0:
        sys.exit("no reference onset paired with any dub onset within --max-shift; "
                 "the tracks are grossly misaligned or not the same content.")

    t_end = float(max(en_on.max(), th_on.max()))
    print("  window     n   median_off")
    misaligned, dropouts = [], []
    w = base
    while w < t_end:
        m = (at >= w) & (at < w + a.window)
        n_ref = int(((en_on >= w) & (en_on < w + a.window)).sum())
        n_dub = int(((th_on >= w) & (th_on < w + a.window)).sum())
        if n_ref >= a.min_onsets and n_dub == 0:
            dropouts.append((w, n_ref))
            print(f"  {int(w)//60:3d}:{int(w)%60:02d}   ---   (dub silent, ref has {n_ref})  <-- DROPOUT")
        elif m.sum():
            md = float(np.median(offs[m]))
            flag = ""
            if abs(md) > a.tolerance and m.sum() >= a.min_onsets:
                misaligned.append((w, int(m.sum()), md))
                flag = "  <-- MISALIGNED"
            print(f"  {int(w)//60:3d}:{int(w)%60:02d}  {m.sum():4d}   {md:+.3f}s{flag}")
        w += a.window

    cov = len(offs) / len(en_on)
    print(f"\nmatched {len(offs)}/{len(en_on)} reference onsets ({100*cov:.0f}%)"
          f";  overall median offset {np.median(offs):+.3f}s")
    if ambiguous:
        print(f"  ({ambiguous} pairings were close calls — offset magnitudes are lower bounds)")
    if misaligned:
        print(f"  misaligned windows: {len(misaligned)}")
    if dropouts:
        print(f"  dropout windows: {len(dropouts)}")

    if misaligned or dropouts:
        print(f"\nVERDICT: FAIL — {len(misaligned)} misaligned window(s), "
              f"{len(dropouts)} dropout window(s). Rescue per SKILL.md 'Hard episodes'.")
        sys.exit(1)
    if cov < 0.5:
        print(f"\nVERDICT: CHECK — only {100*cov:.0f}% of reference onsets paired; "
              f"too little to judge. Spot-check by ear.")
        sys.exit(0)
    print(f"\nVERDICT: PASS — {100*cov:.0f}% onset coverage, no misaligned window.")
    sys.exit(0)


if __name__ == "__main__":
    main()
