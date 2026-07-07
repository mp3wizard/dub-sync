# dub-sync

**Time-align a foreign-language dub audio track from one rip onto a *different* video release, then mux both as selectable, scene-synced audio tracks in a single MKV.**

You have an English 1080p movie/episode and a Thai TV broadcast rip of the same title. They don't line up — different framerate, different commercial-break cuts, the dub drifts out of sync partway through. `dub-sync` re-aligns the dub scene-by-scene against the original and produces one dual-language MKV where both audio tracks match the picture.

This is a [Claude Skill](https://docs.claude.com/en/docs/agents-and-tools/agent-skills) — but the core is a standalone Python CLI (`scripts/dubsync.py`) you can run by hand.

---

## What it does

Given an **original video** (the reference — good picture, e.g. English 1080p) and a **dub source** (a separate rip in another language, e.g. a Thai 720p broadcast), it outputs **one MKV with both audio tracks**, language-tagged, the dub scene-aligned to the original.

It corrects two problems at once:

1. **Framerate / PAL speedup** — a 25fps PAL dub runs ~4.27% fast against 23.976fps film (big progressive drift, pitch raised); a 24fps source runs ~0.1% fast (tiny drift). The script auto-detects each file's fps and conforms the dub's speed (also undoing PAL pitch-up).
2. **Non-linear "staircase" drift** — commercial-break cuts remove content, so the offset steps up at each break. One global offset can't fix this. The script chops the dub at silences, aligns each chunk independently against the original, and reassembles (silence fills the cut gaps).

**Cross-language safe:** it aligns on the shared **music & effects** energy envelope, *not* dialog — so a Thai dub aligns correctly against an English reference. (Dialog-based subtitle shifters like Sushi silently no-op here because the dialog differs between languages.)

### Use it when
- You have a dub + a *different* release of the same title.
- A dub that starts synced then drifts partway through.
- You want to combine two-language rips into one file.

### Skip it when
- It's a **constant** delay → use `mkvmerge` or ffmpeg `-itsoffset`.
- Same-release remux → nothing to align.
- You're syncing **subtitles** → use `ffsubsync` or `alass`.

---

## Flow

The pipeline runs in four phases. Full interactive diagram:
**[FigJam flow board ↗](https://www.figma.com/board/4HR7zNSUdmkedtbr52UDuI/Claude-skill--dub-sync)**

```
1 · ANALYZE & CONFORM
   Inputs (reference video + dub) → Probe both (ffprobe)
   → Conform dub speed to reference fps → Extract energy envelopes

2 · ALIGN DUB TO REFERENCE
   Detect silences, cut into chunks → Per-chunk offset (M&E cross-correlation)
   → Clean offsets (median smooth) → Build synced track

3 · VERIFY (QA gate)
   Verify: re-correlate built track vs reference → Median residual < 0.4s?
   ├─ No (OK/CHECK) → Adjust (lower silence-db / re-check fps) ↺ back to align
   └─ Yes ↓

4 · ENCODE & DELIVER
   Report-only mode?
   ├─ Yes → print residual + offset tables, stop
   └─ No  → Encode dub to FLAC → Mux MKV → Output: one dual-language MKV
```

---

## Requirements

- **`ffmpeg` + `ffprobe`** on your `PATH`
- **Python 3** + **numpy**

```bash
pip install numpy
# ffmpeg: macOS  -> brew install ffmpeg
#         Ubuntu -> sudo apt install ffmpeg
#         Windows-> winget install Gyan.FFmpeg
```

> **Windows note:** the WinGet ffmpeg is a shim/symlink (works fine). The real binaries live under
> `…\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin`.

---

## Install (as a Claude Skill)

Drop the `dub-sync/` folder into your skills directory so Claude can discover it:

```bash
# Claude Code — personal skills
cp -r dub-sync ~/.claude/skills/

# or per-project
cp -r dub-sync /path/to/project/.claude/skills/
```

Then just ask Claude in natural language (English or Thai), e.g.
*"sync this Thai dub onto the English file"* / *"รวมเสียงไทยกับไฟล์อังกฤษ"*.
Claude loads the skill, asks for your three paths, dry-runs, and builds.

To run the CLI directly (no Claude), skip install and see **Usage** below.

---

## Usage

Always **`--report-only` first** to confirm alignment, then build:

```bash
# 1. Dry run — detect + verify, print residual/offset tables, no encode
python scripts/dubsync.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out OUT.mkv --report-only

# 2. Build the dual-language MKV
python scripts/dubsync.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out OUT.mkv
```

`--eng` is the **original/reference** video, `--thai` is the **dub source** (the flags are named for the original use case but work for any language pair — set the tags with `--eng-lang`/`--thai-lang`).

### The three things you must specify

When Claude runs this it will ask you for exactly these (and you pass them as `--eng` / `--thai` / `--out` on the CLI):

| # | What | Flag | Notes |
|---|------|------|-------|
| 1 | **Original / reference video** | `--eng` | The good picture (e.g. English 1080p). Its audio is the alignment reference. |
| 2 | **Dub source** | `--thai` | The separate foreign-language rip to align (e.g. Thai broadcast). |
| 3 | **Output destination** | `--out` | Where the finished `…TH-EN.mkv` goes. |

> **Output-folder safety:** if the output is in the *same* directory as either source, write into a dedicated subfolder (e.g. `<dest>/TH-EN/`) so new files never intermix with or overwrite the originals.

### Reading the report

Look at the `[verify]` line — it reports the **median residual drift** on real content:

| Verdict | Median residual | Meaning |
|---------|-----------------|---------|
| **PASS** | < 0.4s | Ship it. |
| **OK** | < 0.8s | Usable; spot-check. |
| **CHECK** | ≥ 0.8s, **or** fewer than 5 reliable samples | Investigate before shipping. |

Big residuals that appear **only at ad-break gap points** are flagged and expected (they're the silence-filled cuts, not errors). A residual that's high *everywhere* means the wrong fps was detected (pass `--src-fps`/`--dst-fps`) or the two files aren't the same cut.

### Options

```
--default thai|eng      which audio track is the default (default: thai)
--thai-lang / --eng-lang   MKV language tags (default: tha / eng)
--src-fps / --dst-fps   override fps auto-detection (only if residual is high everywhere)
--pitch-mode asetrate|atempo   speed-conform method (asetrate also undoes PAL pitch-up)
--silence-db -25        silence threshold for chunking. Lower to -30…-35 for a
                        loud/continuous mix that yields too few silences.
--search 5.5            per-chunk offset search half-width (s); widen for big ad-break jumps
--min-chunk 25          minimum chunk length (s)
--work DIR              keep working files in DIR (else a temp dir, auto-cleaned)
--keep-temp             don't delete the working dir
--report-only           detect + verify only, no encode/mux
```

---

## Recommended workflow

1. **Match the pair** by episode number, not filename (naming differs between rips).
2. **Probe both** — confirm same episode (durations consistent after the fps ratio) and see the fps mismatch.
3. **Dry run** `--report-only` on **one** episode → expect `PASS` and a near-flat residual profile.
4. **Build** it, then spot-check in VLC (mid-episode + just after an ad break; lips vs dub).
5. **Batch the rest** only after one is confirmed — and **re-detect every episode** (durations and ad-break positions differ; never reuse another episode's offsets).

---

## Hard episodes — rescue toolkit

`dubsync.py` handles the common case. On a **weak-correlation episode** (heavily re-dubbed, sparse shared music & effects), its silence-anchored chunk aligner can latch onto a spurious far peak and *invent* a huge false ad-break gap — and worse, its own sparse `[verify]` can print `PASS` while half the track is badly misaligned.

> **Why this exists:** a real "Madam Secretary" S01E09 build reported `PASS` while a chunk aligner had invented a **28s silent gap** from a bad offset jump (`+33s` where the truth was `+4.8s`). Manual FFT re-analysis found the real gentle staircase (`+1.5 → +11.5s`), plus a genuine ~3s dub-source dropout (TV-rip ad-fade). The four scripts below now handle that scenario without manual Audacity work.

Run these when an episode looks wrong or you don't trust a bare `PASS`:

| Script | What it does |
|--------|--------------|
| **`robust_offset.py`** | Rescue aligner for hard episodes. FFT global offset + a **narrow constrained** sliding search that *cannot* jump to a far spurious peak — recovers the true gentle staircase instead of noise. Prints the curve, or builds the corrected audio with `--out`. |
| **`dense_verify.py`** | The honest verification. Correlates the **built** track against the reference every 60s across the *whole* timeline with a coverage-aware verdict — catches the misaligned half that `dubsync.py`'s sparse verify misses. Trust this over a bare `[verify] PASS`. |
| **`gap_scan.py`** | Finds genuine **dub-source dropouts** at 1s resolution (reference has speech, built dub is silent) — TV rips fade ~2–3s at ad junctions and eat a line. These are source holes, not alignment errors. |
| **`fill_gap.py`** | Fills a short dropout: pulls post-gap dialogue up into the hole, then re-syncs with pitch-preserved `atempo` over a chosen window so everything past it still matches. |

```bash
# 1. Re-align a hard episode with the constrained search
python scripts/robust_offset.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out thai_synced.flac

# 2. Verify honestly across the whole timeline (never trust a sparse PASS on these)
python scripts/dense_verify.py --eng ORIGINAL.mp4 --built OUT.mkv --built-stream 0:a:0

# 3. Scan for a real dub dropout (whole episode, or a suspect region)
python scripts/gap_scan.py --eng ORIGINAL.mp4 --built OUT.mkv --from 890 --to 940

# 4. Fill a ~3s dropout found at 15:10, re-syncing over the next 27s
python scripts/fill_gap.py --src thai_synced.flac --out thai_filled.flac \
    --cut-start 910 --cut-end 913 --resync 27
```

Rule of thumb: `dubsync.py` first; if `dense_verify.py` shows a misaligned stretch, rebuild with `robust_offset.py`; if a line is missing from the dub, `gap_scan.py` → `fill_gap.py`.

---

## How it works (short version)

`ffprobe` both files → auto-detect fps → conform the dub's speed → extract energy envelopes → detect silences → chunk the dub → cross-correlate each chunk's M&E envelope against the reference → median-smooth the offsets (rising on ad-cuts, falling on a speed ramp — never forced monotonic) → place each chunk on the reference timeline with short crossfades at real seams → **verify** by re-correlating the built track → encode the dub to FLAC → mux both tracks into the MKV.

Every ffmpeg/ffprobe call is return-code checked, so a transient extraction failure aborts loudly instead of shipping a broken file. Designed to run **unattended across a whole season**.

---

## License

MIT
