#!/usr/bin/env python3
"""Mux Thai + English subtitle tracks into a video, copying all existing streams.

Uses ffmpeg via subprocess with an argument list (no shell), which sidesteps the
Windows headache of bracket/space characters in paths (e.g. "Season 03 [1080p]")
breaking shell globbing. Output is MKV, which cleanly holds SRT text subtitles and
per-track language tags.

Usage:
    python mux_subs.py --video IN.mp4 --thai TH.srt --eng EN.srt --out OUT.mkv
    python mux_subs.py --video IN.mkv --thai TH.srt --out OUT.mkv          # Thai only
    python mux_subs.py ... --default eng                                   # make EN sub default
    python mux_subs.py ... --eng-title "English (SDH)"

Notes on Plex: the Thai track is tagged language=tha and marked "default" so players
that honor the container flag pick it. Plex itself largely ignores the default flag for
playback and follows the viewer's preferred-subtitle-language account setting instead —
the language tag (tha/eng) is what lets Plex match, so we always set it.
"""
import argparse, subprocess, sys, os

def probe_has_audio(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=index", "-of", "csv=p=0", video],
        capture_output=True, text=True)
    return bool(r.stdout.strip())

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--thai", "--th", dest="thai", required=True)
    ap.add_argument("--eng", "--en", dest="eng", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--default", choices=["thai", "eng", "none"], default="thai",
                    help="which subtitle track carries the default disposition")
    ap.add_argument("--thai-title", default="Thai")
    ap.add_argument("--eng-title", default="English")
    args = ap.parse_args()

    for p in [args.video, args.thai] + ([args.eng] if args.eng else []):
        if not os.path.exists(p):
            sys.exit(f"missing input: {p}")

    has_audio = probe_has_audio(args.video)

    cmd = ["ffmpeg", "-y", "-i", args.video, "-i", args.thai]
    if args.eng:
        cmd += ["-i", args.eng]

    # map original video + (all) audio, then the subtitle inputs
    cmd += ["-map", "0:v"]
    if has_audio:
        cmd += ["-map", "0:a"]
    cmd += ["-map", "1"]
    if args.eng:
        cmd += ["-map", "2"]

    cmd += ["-c:v", "copy", "-c:s", "srt"]
    if has_audio:
        cmd += ["-c:a", "copy"]

    # Thai subtitle metadata (it is subtitle stream 0)
    cmd += ["-metadata:s:s:0", "language=tha", "-metadata:s:s:0", f"title={args.thai_title}"]
    cmd += ["-disposition:s:0", "default" if args.default == "thai" else "0"]
    if args.eng:
        cmd += ["-metadata:s:s:1", "language=eng", "-metadata:s:s:1", f"title={args.eng_title}"]
        cmd += ["-disposition:s:1", "default" if args.default == "eng" else "0"]

    cmd += [args.out]

    print("running:", " ".join(f'"{c}"' if " " in c else c for c in cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit(f"ffmpeg failed (exit {r.returncode})")

    # confirm the output track layout
    print("\n=== output tracks ===")
    subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=index,codec_type,codec_name:stream_tags=language,title:stream_disposition=default",
         "-of", "compact", args.out])

if __name__ == "__main__":
    main()
