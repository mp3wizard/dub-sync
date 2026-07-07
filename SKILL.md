---
name: dub-sync
description: >-
  Time-align a foreign-language DUB audio track from one rip onto a DIFFERENT video
  release, then mux both as selectable, scene-synced tracks in one MKV. Corrects
  framerate/PAL speedup (25↔23.976 fps) AND non-linear "staircase" drift from
  commercial-break cuts; cross-language safe (aligns on shared music & effects, not
  dialog). Use when the user wants to: sync/merge a dub with an original-language video,
  add a dub as a second audio track, combine two-language rips of the same title, fix a
  dub that starts in sync then drifts partway, or re-fix a previously-synced dub still
  off from some minute on or with a silent gap/dropout partway (reference has speech but
  the dub goes silent). NOT for a simple constant delay (use mkvmerge/-itsoffset) or
  subtitle sync. Thai triggers: รวมเสียงไทย, ซิงค์เสียงพากย์, เอาเสียงไทยมาใส่,
  ทำไฟล์สองภาษา, เสียงพากย์ไม่ตรงฉาก, เสียงไทยมาช้า/เร็ว, เสียงหลุดซิงค์ตั้งแต่นาที…,
  เสียงพากย์เงียบหายเป็นช่วง. Needs ffmpeg + python/numpy.
---

# dub-sync — align a dub track onto a different video release

Input: an **original video** (reference audio, e.g. English 1080p) + a **dub source**
(separate rip in another language, e.g. a Thai 720p TV broadcast).
Output: one **MKV with both audio tracks**, language-tagged, the dub scene-aligned to
the original — even though the two rips differ in framerate and commercial-break edits.

**Quickstart** (always `--report-only` first to confirm alignment, then build):
```
python scripts/dubsync.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out OUT.mkv --report-only
python scripts/dubsync.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out OUT.mkv
```

## Use it when / skip it when
- **Use**: dub + a *different* release of the same title; a dub that starts synced then
  drifts; combining two-language rips; adding a foreign track that must match the scenes.
- **Skip**: constant-offset delay (use `mkvmerge` / ffmpeg `-itsoffset`); same-release
  remux; subtitle timing (use ffsubsync / alass).

## Why it's hard (any mix of these can be present)
1. **Framerate mismatch** — the dub's source runs at a different frame rate than the master,
   so it drifts progressively. Seen so far: **25fps PAL** (runs ~4.27% fast vs 23.976 → big
   drift, pitch raised) and **24fps** (runs ~0.1% fast → tiny drift). The script auto-detects
   each file's fps and conforms the dub's speed (`asetrate` default — also undoes PAL pitch-up).
2. **Drift shape varies** — after conforming, the residual offset is one of:
   **flat** (clean fps) · **rising staircase** (ad-cuts remove content → offset steps up at
   each break) · **gentle linear ramp, up OR down** (fps label not exact). One global
   offset/stretch fixes none of the last two. So the script chops the dub at silences
   (splitting any long stretch), aligns each chunk independently against the master, and
   reassembles — silence fills the cut gaps. Offsets are **not** assumed monotonic (they rise
   on cuts, fall on a speed ramp); a median smooth kills jitter, and the noisy end-credits tail
   is clamped to the last confident value.

## Tool
`scripts/dubsync.py` — one self-contained CLI (needs `ffmpeg`+`ffprobe` on PATH, python3
+ numpy). Probes both files, auto-detects framerate, conforms, chunks at silences, aligns
via energy-envelope cross-correlation (shared M&E), builds, **verifies residual drift**,
then encodes + muxes.

```
python scripts/dubsync.py --eng ORIGINAL.mp4 --thai DUB.mp4 --out OUT.mkv \
    [--work DIR] [--default thai|eng] [--thai-lang tha] [--eng-lang eng] \
    [--src-fps F --dst-fps F] [--pitch-mode asetrate|atempo] \
    [--silence-db -25] [--search 5.5] [--min-chunk 25] [--report-only]
```
- `--report-only` — detect + verify, print residual/offset tables, no encode/mux. Run this
  first on any new title.
- Read the `[verify]` line: median residual **< 0.4s = PASS** (`OK` < 0.8s, else `CHECK`).
  `CHECK` also fires when **< 5** reliable samples survive. Big residuals appear **only** at
  ad-break gap points (flagged) — expected silences, not errors.
- `--default thai` — make the dub the default track.
- `--silence-db` — silence threshold for chunking (default −25). **Lower it (−30…−35) for a
  loud/continuous mix** that yields too few silences (few chunks → coarse sync). Densification
  helps automatically, but more real silences still align better.
- `--search` — per-chunk offset search half-width (default 5.5s). Widen only for unusually
  large single ad-break jumps; wider = more spurious matches on weak-correlation episodes.
- `--src-fps/--dst-fps` — override only if auto-detection is wrong (residual high *everywhere*).

## Runbook
**0. Gather paths first — never assume.** If the user hasn't clearly given all three, ask
with `AskUserQuestion` (one question each; offer any paths already mentioned as options):
   - **Original/reference source** — folder/file of the good video.
   - **Dub source** — folder/file of the foreign-language rip.
   - **Output destination** — where finished `…TH-EN.mkv` files go.

   **Subfolder rule:** if the output folder is the *same* directory as either source, do
   NOT write beside the sources — make a dedicated subfolder there (e.g. `<dest>/TH-EN/`)
   and write into it, so new files never intermix with or overwrite originals. Echo the
   resolved output path back before building. Different folder/drive → write directly.

**1. Match the pair** by episode number, not filename (naming differs between rips).
**2. Probe both** (`ffprobe … r_frame_rate,duration`) — confirm same episode (durations
   consistent after the fps ratio) and see the fps mismatch.
**3. Dry run** `--report-only` on ONE episode → expect PASS and a near-flat residual profile.
   Residual high *everywhere* (not just gaps) ⇒ wrong fps (pass `--src/--dst-fps`) or not the
   same cut. Verdict `CHECK`/`OK` with few chunks ⇒ loud mix, lower `--silence-db`.
**4. Build** it, then have the user spot-check in VLC (mid-episode + just after an ad break;
   lips vs dub).
**5. Batch the rest** only after one is confirmed. **Re-detect every episode** — durations
   and ad-break positions differ; never reuse another episode's offsets.

## Batch pattern (per season)
Loop episodes, matching `S0#E##` original ↔ dub, writing `…TH-EN.mkv` to the resolved output
path; run in the background (each episode = several ffmpeg decodes). Collect the per-episode
`[verify]` verdict. For a straggler (`OK`/`CHECK`): re-run once with a lower `--silence-db`
(loud mix) or re-check fps before flagging it for manual sync — don't ship a coarse result.
When done, verify track layout on every output, then (if asked) back up originals before
replacing them.

## Hard episodes (weak M&E): the rescue toolkit

Some rips defeat the silence-anchored chunk aligner: a low-bitrate TV rip whose music &
effects were remixed/compressed shares too little with the original, so per-chunk correlation
runs ~0.1–0.3 and the aligner invents huge false ad-break gaps that even `--report-only`
"PASS"es. The signature: `[verify]` shows large residuals flagged gap/uncertain across a
whole half, and/or a chunk offset that jumps tens of seconds. Don't ship it, and don't jump
to manual Audacity — run the toolkit in `scripts/`:

1. **`robust_offset.py --eng ORIG --thai DUB`** — FFT global base offset + a sliding window
   with a *narrow constrained* search around a running estimate. The narrow search can't latch
   a far spurious peak, so on weak M&E you get the true gentle staircase (e.g. +1.5 → +11.5s)
   instead of the aligner's chaotic +5→+44s. Add `--out thai_synced.flac` to also BUILD the
   conformed+placed dub audio from the detected staircase (no gaps but the real small ones).
2. **Mux** that FLAC as the dub track (video + dub[default] + original), then
   **`dense_verify.py --eng ORIG --built OUT.mkv`** — correlates the built dub vs the reference
   every 60s across the WHOLE timeline and prints a coverage-aware verdict (CHECK when too little
   is verifiable → spot-check by ear; FAIL on any reliably-misaligned window). This is the honest
   check the built-in verify isn't.
3. **`gap_scan.py --eng ORIG --built OUT.mkv`** — 1s-resolution RMS scan for spots where the
   reference has speech but the dub is silent. These are real DUB-SOURCE dropouts (a TV rip fades
   ~2–3s at commercial junctions, eating the dubbed line) — inherent holes, not alignment errors.
   The embedded subtitle covers the meaning; optionally fill them:
4. **`fill_gap.py --src thai_synced.flac --out thai_filled.flac --cut-start S --cut-end E --resync N`**
   — deletes the silent dropout, pulls the post-gap dialogue up to fill it, then re-syncs with
   `atempo` (pitch-preserved) over `--resync` seconds so from there on the audio matches the
   un-filled build exactly. Pick `--resync` so it re-syncs at the moment the user says should be
   in sync. Always have the user spot-check the filled second AND the re-sync point.

## Gotchas (each is a rule + the why it cost to learn)
- **Correlate the energy envelope, never dialog.** Subtitle-style shifters (Sushi.Net etc.)
  match dialog, which differs between dub and original → they silently no-op (output = copy).
  Shared music & effects survive the language gap. Don't reach for Sushi.
- **Capture `silencedetect` with `-v info`**, not `-v error` — its output is at `info` level,
  so `error` gives zero silence points.
- **Encode the dub to FLAC, not AAC.** ffmpeg's native `aac` encoder is pathologically slow on
  some boxes; FLAC is lossless, fast, MKV-native. Transcode to AAC/AC3 later only for a hardware
  target that needs it.
- **Never re-impose a monotonic-offset constraint.** True for PAL+cuts, but it silently clamps a
  24fps dub's *downward* linear ramp and mis-syncs the back half. Offsets follow the measured
  trend (median-smoothed), rising OR falling.
- **Don't re-add automated "self-heal."** Re-shifting a region by its verify residual looks
  tempting, but on weak-correlation episodes the verify itself is unreliable — it silently
  degrades a good region while the median only *looks* better. Rare hard episodes (~1 in 45)
  don't need manual Audacity anymore — see **Hard episodes** below for the rescue toolkit.
- **The built-in `[verify] PASS` is NOT trustworthy on weak-M&E episodes.** It samples only
  silence-bounded "real content" points (often <10, clustered in one half) and flags the rest
  gap/uncertain. It once printed `PASS` (median 0.02s) on a build that inserted a bogus **28s**
  gap and was 28s off for half the episode — the broken half simply wasn't in the sample. On any
  low-corr episode, ignore the bare verdict and run `scripts/dense_verify.py` on the OUTPUT.
- **A single offset step of tens of seconds is almost always spurious.** A real ad-cut removes a
  few seconds; a +33s jump with no equally-long real silence to justify it is the chunk aligner
  latching a far correlation peak on weak M&E. `robust_offset.py` (narrow constrained search)
  won't make that mistake — it recovers the true gentle staircase.
- **Seed the global offset from several early windows (median), not one wide search.** The start
  offset is always small; a lone wide seed can latch a spurious far peak on a heavily re-dubbed
  episode and throw off the whole track.
- **Densify sparse silences.** A loud/continuous mix yields few silences → coarse chunks → poor
  sync; the engine splits any span > 70s into ~55s pieces (also lower `--silence-db` for more
  real anchors). Fixed-grid cuts are safe: within a plateau both sides share the offset (seamless).
- **Trust `run_checked`, not silent output.** Every ffmpeg/ffprobe call is return-code checked, so
  a transient extract failure (seen: Windows `0xC0000142`) aborts loudly instead of shipping a
  broken file — re-running the episode usually succeeds.
- **WinGet ffmpeg is a shim/symlink** (fine as-is). Real bin:
  `…\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin`.
- **Prove sync by re-correlating** the built track against the reference; near-zero residual on
  real content (not at gaps) is the confirmation.

## Related
Memory `[[madam-secretary-thai-sync]]` — originating case + drive layout.
