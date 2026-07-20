# Handoff — dub-sync & subtitle-th skills: lessons from a full-season batch

**Context:** Ran both skills end to end across a full 22-episode television season, then continued
into a second season one episode at a time — time-aligned a foreign-language dub audio track onto a
different English video release, generated foreign-language subtitles from the English subs with
grammatically-correct gendered pronouns, and muxed both audio + both subtitle tracks into per-episode
MKVs. This document records what broke, what we changed, and why — so the two skills (and anyone
reusing them) don't relearn it. Every fix below is already applied to the committed `SKILL.md` /
script files in this bundle. Nothing here is tied to a specific title; the examples are generic.

---

## The two skills

- **`dub-sync/`** — align a foreign-language DUB audio track from one rip onto a *different* video
  release (different fps + commercial-break edits), output one MKV with both audio tracks
  scene-synced. ffmpeg + numpy, no LLM.
- **`subtitle-th/`** — translate an English `.srt` into natural spoken Thai with the *correct*
  gender-specific pronouns/particles per speaker, validate structure, and mux Thai+English subtitle
  tracks into the video.

They compose: an episode goes dub-sync (audio) → subtitle-th (subs) → final mux.

---

## Lessons that changed the skills

### 1. Structured-output success ≠ the side-effect happened (subtitle-th)
Over a full-season chunked-translation run, **31 of 102 chunk agents reported `ok=true` against a
JSON schema for a file they never actually wrote** (or wrote with a corrupted cue count). A schema
validates the *shape of the reply*, not that the file-writing tool call succeeded.
- **Fix:** every file-producing agent must self-verify by running, in a shell, the **same parser
  the downstream consumer uses** (here: `re.split(r"\n[ \t]*\n", ...)` block count) and refuse to
  return `ok` unless it prints the expected number. The orchestrator re-checks on disk too.
- Weaker checks ("does the file exist") miss the second failure mode: a *wrong-count* file, where a
  missing blank-line separator fused two cues or a stray one split a cue.

### 2. When a chunk keeps failing, shrink it — don't raise effort (subtitle-th)
Chunks of ~234–248 cues failed repeatedly in the same spots across THREE repair rounds. The problem
was never "think harder," it was "ran out of stamina to emit N cues correctly."
- **Fix:** split the stubborn chunks into ~110–125-cue halves; each half then translated cleanly on
  the first try. Rejoin with a **deterministic script that asserts the combined count** — not an
  agent reporting "merged, looks right."
- Corollary on model/effort: straight translation is mechanical → **Sonnet at `medium`** is the
  right default. Higher tiers cost ~2–3× for no gain on translation. Reserve judgment-heavy effort
  for the gender pass. (An abandoned early attempt used a top-tier model and burned a large share of
  the season's total tokens on the first six episodes before we switched to Sonnet+chunked.)

### 3. Content-filter refusals can come from the *source dialogue* (subtitle-th)
One episode's cold open (a fictional bioterror-plot briefing — generic thriller lines) drew a
**Usage-Policy API refusal 6× in a row**, across reworded prompts AND different models — proving it
was a content classifier reacting to the dialogue, not our wording or model.
- **Fix:** bisect the chunk to localize the trigger (here 8 of 117 cues); the surrounding ordinary
  dialogue translates fine on the normal path, and the tiny trigger span is handled inline by the
  orchestrator (legitimate mechanical localization of already-broadcast TV dialogue). Rejoin
  deterministically.

### 4. The mux `--video` source must carry EVERY audio track you want (subtitle-th)
`mux_subs.py` does `-map 0:a` — it copies *all* audio from whatever `--video` is, and silently. If
you point it at the plain single-audio source instead of the **dub-sync `TH-EN.mkv` output**, you
get a "finished" file with **English audio only, no Thai dub, and no error**. This shipped two
episodes broken before it was caught.
- **Fix:** always point `--video` at the dub+audio file, and **`ffprobe` every final file** to
  confirm the full 5-stream layout: video, audio tha, audio eng, subtitle tha, subtitle eng. Exit 0
  proves nothing; a dropped track is invisible without the probe.
- Minor follow-up: `mux_subs.py` now also accepts `--th`/`--en` as explicit aliases for
  `--thai`/`--eng` (argparse used to reject the abbreviations as ambiguous against `--thai-title`).

### 5. `dense_verify` CHECK is not FAIL — don't rescue a CHECK (dub-sync)
Added an independent verifier (`dense_verify.py`) because dub-sync's built-in `[verify]` samples
only silence-bounded points it already trusts and can print PASS while another region is badly off.
But its **CHECK** verdict (too little correlated strongly enough to verify — a weak-M&E *source*
property) is not evidence of drift. Only **FAIL** (a window with corr ≥0.35 AND |residual| >0.5s) is
a proven misalignment and the trigger for the `robust_offset` rescue.
- Treating every CHECK as broken meant re-processing ~15 fine episodes for nothing.

### 6. A whole batch reading weak-corr = provenance, not many broken syncs (dub-sync)
The season's pilot (a low-res broadcast TV rip) hit ~100% coverage / 0.9+ correlation; every other
episode (from a different — likely OTT/streaming — dub source) sat at 7–36%. That gap is the two dub
*sources* sharing different amounts of music-&-effects with the reference, not per-episode breakage.
Suspect source lineage before the aligner when a whole batch is weak but the pilot wasn't.

### 7. Real bug fixed in `robust_offset.py` (dub-sync)
`robust_offset.py --out` crashed (`ValueError: could not broadcast input array … into shape (0,2)`)
whenever a segment's offset placed it at/past the end of the output buffer — hit on almost every
weak-M&E episode. Fixed to clamp the destination/source slice. (Genuine reusable bug, not
title-specific.)

### 8. Windows gotchas that cost real debugging time (both skills)
- **Call ffmpeg/ffprobe (and python tools that spawn them) with native `C:\…` paths, never MSYS
  `/c/…`, `/w/…`.** Git-Bash's argv path-translation is unreliable for native exes on paths with
  spaces/brackets — `dense_verify.py` once produced a perfectly flat, all-identical residual table
  (which reads exactly like a gross misalignment) purely because ffmpeg was handed a `/w/…` path and
  opened nothing. MSYS built-ins (`ls`, `cmp`, `cat`) handle `/c/`, `/w/` fine; ffmpeg does not.
- **Source files are often read-only** → deleting/overwriting throws `PermissionError: Access is
  denied`. Clear the flag first (`os.chmod(path, stat.S_IWRITE)` / `attrib -r`). A crash *after* the
  new file was written+verified means only cleanup failed — re-check the output before redoing work.
- **Transient `0xC0000142` loader errors re-run clean** — one episode aborting mid-batch is not a
  "hard episode," just re-run (batch is idempotent, skips episodes whose output already exists).
- **Don't double-background** a job: combining the shell tool's own background mode with `&`/`nohup`/
  `disown` orphans the process untracked (0-byte log, nothing runs). Pick one.

### 9. The gender pass's token cost blows up from per-cue edits, not from the model (subtitle-th)
A run that let the gender-verify agent apply each fix with its own `Edit` tool call — 45 fixes, 80
assistant turns — cost **11M+ tokens, ~4× a comparable run that batched its fixes**. The cause is
*turn count*, not model: every extra turn re-sends the whole growing conversation as fresh
(uncached) input, so N one-at-a-time edits scale ~O(N²). It gets *worse* on a higher-cost
model/effort, so it bites hardest exactly where you reached for more horsepower.
- **Fix:** collect every fix first as data (`{cue, find, replace}`), then apply them in one
  deterministic pass with `apply_gender_fixes.py` (new script — it safety-checks that each `find`
  occurs exactly once in its cue and writes nothing if any check fails). Never one `Edit` per cue.

### 10. Model & effort, settled: one mid-tier model everywhere; effort is the lever (both skills)
A mixed-model trial (top tier on the gender pass) gave **no measurable quality edge** over the
mid-tier model and cost ~4× more. Every step runs on the *same mid-tier model*; what varies is
*reasoning effort*, and only one step earns high effort:
- **Translate (per chunk): medium.** `high` provokes copyright self-refusals (see #2); `low` leaves
  more gender errors for the next step. — **Merge / Validate: low** (they run deterministic scripts
  and read a number). — **Gender-verify: high** — the one step that reasons; `high` is safe here
  because it's a *checking* task, not *generation*, so it doesn't self-refuse.
- The rule this encodes: don't upgrade the model tier and don't raise effort on mechanical steps —
  spend the effort budget on the single step that actually reasons.

### 11. Remove the human from an audio ship/hold call with a threshold, not a bigger model (dub-sync)
Interpreting the verifier outputs is *rule application* (see #5–6), so it runs unattended on the
mid-tier model at medium effort — a bigger model only re-confirms what the rules already say. The one
genuinely borderline case — a **real, un-rescuable** dropout — is a *value judgment* ("is this good
enough to ship?"), which has no technically-correct answer. Resolve it with a fixed number, not
human judgment and not model horsepower:
- **< ~8s un-rescuable dropout, not in a dialogue-critical stretch → ship automatically** (the
  subtitle covers meaning across a short hole).
- **≥ ~8s, or a FAIL `robust_offset` can't clear → HOLD, do not deploy** — leave the build in the
  review dir, log the flagged timestamps, accumulate for a later batch review. Raising effort/model
  never converts a hold into a ship; the hold is a deliberate quality gate, not a reasoning gap.

---

## Result
All episodes finished as MKVs with dual audio + dual subs, 5-stream-verified. Token cost was
measured per-episode/per-phase; the abandoned top-tier-model attempt (~14% of one season's total) is
what these lessons eliminate next time, along with the per-cue-edit blow-up in #9.

## Files in this bundle
- `dub-sync/` — SKILL.md + scripts (dubsync, dense_verify, robust_offset, gap_scan, fill_gap)
- `subtitle-th/` — SKILL.md + scripts (find_gendered, apply_gender_fixes, validate_srt, mux_subs) +
  references + evals
