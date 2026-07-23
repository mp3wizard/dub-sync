# foreign-media localization skills

Two composable [Claude Code](https://docs.anthropic.com/en/docs/claude-code) skills for turning a
foreign-language **dub rip** + an **original-language release** into a single clean file with
**dual audio** and **dual subtitles** — the kind of file a Plex/Jellyfin library wants.

| Skill | Does | Stack |
|---|---|---|
| **`dub-sync`** | Time-aligns a dub audio track from one rip onto a *different* video release — correcting framerate/PAL speedup and non-linear "staircase" drift from commercial-break edits — and muxes both audio tracks, scene-synced, into one MKV. Cross-language safe (aligns on shared music & effects, not dialog). | ffmpeg + python/numpy, no LLM |
| **`subtitle-th`** | Translates an English `.srt` into natural spoken **Thai with the correct gender-specific pronouns/particles per speaker** (a woman's lines read as ฉัน/ดิฉัน/ค่ะ, not ผม/ครับ), validates the SRT, and muxes Thai + English subtitle tracks into the video. | ffmpeg + LLM (translation & gender pass) |

They compose into one pipeline: **`dub-sync` (audio) → `subtitle-th` (subs) → final mux**.

## Why they exist

- **dub-sync:** two rips of the same title differ in frame rate *and* in where commercials were cut,
  so a single global offset never fits. dub-sync chops the dub at silences, aligns each chunk
  against the reference on the **energy envelope of shared music & effects** (which survives the
  language gap — dialog does not), and reassembles. Includes a rescue toolkit for weak-M&E rips
  (`robust_offset`, `dense_verify`, `gap_scan`, `fill_gap`). It also distinguishes a genuinely
  weak-M&E episode from a **mislabeled dub source that is actually a different program** — an
  unfixable CHECK with near-zero correlation *everywhere* is a provenance problem, caught by a
  same-timestamp frame compare before a build is wasted (metadata tags don't discriminate).
- **subtitle-th:** English "I" and its sentence-enders carry no gender; Thai first-person pronouns
  and polite particles do. A naive EN→TH translation guesses the speaker's gender and gets it wrong
  on a large fraction of a woman's lines. This skill's reason to exist is to get that right — build a
  character→gender map, then verify every gendered token against the actual speaker — and prove it
  with a validator before muxing. It is also hardened against real-world SRT quirks (a source cue
  carrying an internal blank line; chunk-rejoin separator loss that silently fuses cues) and against
  the two distinct chunk-refusal modes — a content-classifier trip on specific lines vs a whole-work
  copyright decline — each with its own remedy.

## Model & effort guidance (baked into the SKILL.md files)

Both skills carry an explicit, field-tested policy for *which model and reasoning effort each step
should use* — because the wrong choice is expensive in non-obvious ways: a top-tier model on a
mechanical step, or high effort on a step that doesn't reason, costs multiples for no quality gain
and can even introduce new failure modes (a self-refusal on translation, a verify pass that edits
one cue at a time and burns ~4× the tokens). The short version baked into each `SKILL.md`: **stay on
one mid-tier model; make *reasoning effort* the lever, not the model tier; spend that effort only on
the one step that actually reasons (the gender pass); and resolve value-judgments with a written
numeric threshold rather than a bigger model.**

## Install

Drop each folder into your Claude Code skills directory:

```
~/.claude/skills/dub-sync/
~/.claude/skills/subtitle-th/
```

Each skill is self-contained: a `SKILL.md` (instructions + trigger description) plus a `scripts/`
folder of standalone CLIs. Requirements: `ffmpeg` + `ffprobe` on PATH, and `python3` with `numpy`.

## Layout

```
HANDOFF.md    # field notes: failure modes + fixes from a full-season batch run
dub-sync/
  SKILL.md
  scripts/  dubsync.py  dense_verify.py  vad_verify.py  robust_offset.py  gap_scan.py  fill_gap.py
subtitle-th/
  SKILL.md
  scripts/  find_gendered.py  apply_gender_fixes.py  validate_srt.py  mux_subs.py
  references/thai-gender-guide.md
  evals/evals.json
```

## Field notes

`HANDOFF.md` is a distilled set of lessons from running both skills across a full television season
and into a second one — the non-obvious failure modes (silent dropped audio tracks, agents that
report success without writing a file, weak-correlation rips, Windows path/permission traps, a
verify pass whose token cost blew up ~4× from editing one cue at a time) and the fixes now baked
into the skills, including the per-step model/effort policy and the automatic ship/hold decision for
imperfect audio. Read it before a large batch run.

## Scope notes

- `dub-sync` is **language-agnostic** — it aligns *any* dub against *any* original-language release;
  Thai is just the common case in the field notes. `subtitle-th` is Thai-specific because the gender
  problem it solves is a property of the Thai language.
- All examples in these files use generic placeholder titles and characters.
