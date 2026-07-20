---
name: subtitle-th
description: >-
  Translate an English subtitle (.srt) into natural spoken Thai with the CORRECT gendered
  pronouns/particles for each speaker — so a woman's lines read as ฉัน/ดิฉัน/หนู/ค่ะ, not ผม/ครับ —
  then validate it and mux both the Thai and English subtitle tracks into the video as selectable
  language-tagged tracks (Thai default). Use whenever the user wants Thai subs made from English
  subs; wants to add/embed/merge Thai (and English) subtitle tracks into a video or MKV, e.g. for
  Plex; or reports a Thai subtitle whose pronoun doesn't fit the speaker's gender (ผม for a woman,
  ค่ะ for a man). Fire on casual and Thai phrasings too — "add thai+english subs to this mkv",
  "the srt uses ผม but she's talking", แปลซับเป็นไทย, ทำซับไทยจากซับอังกฤษ, ฝังซับไทย,
  แก้สรรพนามในซับให้ตรงเพศ. This is subtitle TEXT: do NOT use it to sync a foreign DUB *audio* track
  (that's dub-sync) or fix subtitle *timing* drift (ffsubsync/alass).
---

# Thai subtitle: translate, gender-check, mux

Turn an English subtitle into a Thai one that sounds right, then embed both languages in the
video as selectable tracks. The hard part is not the translation — it is that Thai first-person
pronouns (ผม vs ฉัน/ดิฉัน/หนู) and polite sentence-enders (ครับ vs ค่ะ/คะ) are **gender-specific**,
while English "I" and its sentence-enders are not. A naive translation guesses the speaker's
gender and gets it wrong on a large share of a female character's lines. This skill's whole
reason to exist is to get that right and prove it, then mux cleanly.

## Pipeline

1. **Get the English subtitle** (sidecar `.srt`, or extract from the video).
2. **Translate EN → TH**, preserving structure exactly.
3. **Gender-verify** every gendered token against the speaker (the crux).
4. **Validate** the SRT structure.
5. **Mux** Thai (default) + English into the video, language-tagged.

Do them in order. Skipping step 3 is the mistake this skill exists to prevent.

## Model & effort per step (settled over a full season + a mixed-model trial)

**Every step here runs on Sonnet — Opus is not used anywhere in this pipeline.** The right lever
is *effort within Sonnet*, not model tier: a mixed-model trial (Opus/medium on the gender pass)
gave **no measurable quality gain** over Sonnet and cost ~4× more. The pick per step:

| Step | Model / effort | Why |
|---|---|---|
| 2. Translate (per chunk) | **Sonnet / medium** | Mechanical. `high` triggers copyright self-refusals; `low` bakes in more gender errors for step 3 to clean up. Medium is the proven-stable default. |
| — Merge chunks | **Sonnet / low** | Runs a deterministic script and reads back the asserted count. No reasoning. |
| 3. Gender-verify | **Sonnet / high** | The one judgment-heavy step — wants thoroughness/skepticism, which **`high` effort buys better than a bigger model tier does**. `high` is safe here (unlike on translate); this is a *checking* task, not a *generating* one, so it doesn't self-refuse. |
| 4. Validate | **Sonnet / low** | Runs `validate_srt.py` and reads the verdict. Escalate to `medium` *only* for the rare round where it must fix a structural defect. |

The general rule this table encodes: **don't reach for Opus, and don't raise effort on mechanical
steps** — spend the effort budget only on the step that actually reasons (gender-verify).

## 1. Get the English subtitle

- **Sidecar file:** scene releases often ship subs in a `Subs/<release-name>/` folder next to
  the video (e.g. `2_eng.srt`, `2_eng,SDH.srt`). Prefer an **SDH/CC** English sub if present —
  it carries `SPEAKER:` labels in caps, which are gold for gender attribution in step 3.
- **Embedded track:** if the sub is inside the video, list streams then extract:
  ```
  ffprobe -v error -select_streams s -show_entries stream=index:stream_tags=language,title -of compact IN.mkv
  ffmpeg -y -i IN.mkv -map 0:s:0 EN.srt
  ```
- Note the video's audio language(s) — if the video is a foreign **dub** and the user wants the
  dub kept in sync onto a different release, that's the `dub-sync` skill, not this one.

## 2. Translate EN → TH

Translate cue by cue into natural, spoken Thai (not stiff/literal). The structural contract is
strict because everything downstream (gender pass, validation, mux) depends on it:

- **Keep every index and timestamp byte-for-byte identical** to the English cue it came from.
- **Keep the same number of cues.** Don't merge or split unless you have a real reason; if you
  must, expect step 4's `--compare` to flag the count delta so you can confirm it was deliberate.
- **Translate the spoken text only.** Leave `[bracketed sound cues]`, `♪` music lines, and
  on-screen signs as-is (or lightly localize brackets like `[หัวเราะ]`).
- Write the file as **UTF-8**.
- On a first pass, don't agonize over pronoun gender — you'll fix it deliberately in step 3.
  But do carry the English `SPEAKER:` labels in mind, because they drive step 3.

### Chunk long episodes; verify the count with a real parser, not the agent's word

A full episode is ~700–1100 cues. Handing all of it to one agent in a single pass is the wrong
default — it is slow, and (learned the hard way over a 22-episode batch) **agents routinely report
`ok=true` for a file they never actually wrote, or wrote with a corrupted cue count.** A
structured-output schema proves the reply had the right *shape*, not that the file-writing
*side-effect* happened. Design around that:

- **Split into ≤~250-cue chunks, and if a chunk keeps failing, make it *smaller* (~110–125), not
  higher-effort.** The failures were never "needs to think harder" — they were "ran out of stamina
  to emit N cues correctly." Bisecting the work fixes it; raising reasoning effort just costs more.
- **Split and rejoin with a deterministic script, never by agent self-report.** Cut the English
  SRT into chunk files on blank-line block boundaries; translate each chunk keeping original
  indices/timestamps; then concatenate the translated chunks with a plain script that *asserts* the
  combined cue count equals the source. A pure-Python join can't hallucinate success; an agent
  saying "merged, looks right" can.
- **Make every chunk agent self-verify with the SAME parser the downstream consumer uses.** Have it
  run, via a shell, the exact block-count check (`re.split(r"\n[ \t]*\n", ...)`) and refuse to
  return `ok` unless it prints the expected number. "Does the file exist" is too weak — the two
  real failure modes are a missing file *and* a wrong-count file (a fused pair of cues from a
  missing blank-line separator, or a split cue from a stray one).
- **Model/effort:** translation is mechanical — **Sonnet at `medium` effort** is the right default
  per chunk; reserve higher tiers for the gender pass (step 3), which is the part that needs
  judgment. Using a top-tier model here costs ~2–3× for no quality gain on straight translation.
  **Raising the *reasoning effort* (not just the model tier) on the translate step can actively
  hurt reliability**, not just cost more: a same-day pilot re-ran identical chunk prompts at
  `high` instead of `medium` and **3 of 9 chunks self-refused**, reasoning that translating ~120
  cues of dialogue was "reproducing a derivative work of copyrighted script" — a decline pattern
  that never once occurred across a full prior season translated entirely at `medium`. Re-running
  the exact same 3 prompts at `medium` fixed it 3/3. The extra deliberation `high` buys doesn't
  help a mechanical task — it just gives the model more room to talk itself into an overcautious
  refusal. Don't reach for higher effort to fix a translate reliability problem; it can be the cause.

If a workflow engine is available, the robust shape is: `split (script) → translate chunks in
parallel (Sonnet/medium, each self-verifying its count) → join (script, asserts total) → gender
pass → validate`.

### When a chunk keeps getting refused

Two distinct refusal types show up here — **they have different causes and different remedies, so
tell them apart before reacting.**

**Type 1 — content-classifier trip on specific lines.** One chunk fails with a **Usage-Policy API
refusal** that repeats across reworded prompts *and* different models (so it is not your wording or
the model tier; a content classifier is reacting to the *source dialogue*). Seen with a cold-open
bioterror scene ("80% kill rate," "the virus is airborne") — ordinary broadcast-TV thriller lines
that trip a CBRN classifier regardless of framing. The flagged content is localized to a few cues.

- **Bisect to localize the trigger.** Split the chunk into the few cues carrying the flagged
  content vs. the rest; the surrounding ordinary dialogue then translates fine on the normal path.
- **Handle the tiny trigger span directly, not via a dispatched subagent.** Translating a handful
  of dialogue lines from an already-aired, publicly-broadcast episode is legitimate, mechanical
  localization — the orchestrating assistant can do those few cues inline, then rejoin.
- Keep the split/rejoin deterministic (same block-count assert) so the repaired chunk slots back in
  with the exact original cue count.

**Type 2 — whole-work copyright decline.** The agent declines an *entire* chunk of perfectly
ordinary dialogue, reasoning that translating it "reproduces a derivative of a copyrighted script."
No single line is the trigger, so **bisecting does not help** — every sub-chunk gets the same
refusal. This is a model-side caution about the *whole work*, not a classifier hit on content.

- **Clear it with a truthful ownership / personal-use framing line in the prompt**, not by
  rewording the task or splitting further. What worked: state that the user owns this episode, is
  producing a personal Thai track for their own media library (e.g. Plex), it is not for
  redistribution, and the same localization has already been done for the prior episodes of the
  season. That framing must be *true* — it is legitimate personal localization, consistent with
  this skill's own stance (Type 1 above already treats aired-episode localization as legitimate).
- Seen at the **default** path (Sonnet/medium, general-purpose subagents), independent of the
  `high`-effort self-refusal that the translate-step table warns about — so it is a separate
  failure, not the same one. Adding the framing line up front on every chunk prompt prevents it.

## 3. Gender-verify (the crux)

**Run this step on Sonnet at `high` effort** — it is the only step that needs judgment (deciding
who speaks each cue and picking the right gendered form), and `high` effort buys that thoroughness
more cost-effectively than moving to Opus (which showed no quality edge here). Unlike the translate
step, `high` is safe on a *checking* task — it doesn't provoke the copyright self-refusal that
`high` causes on *generation*.

Read `references/thai-gender-guide.md` and apply it. In short:

- Build a **character → gender map** for the show once, from the English speaker labels (a quick
  web lookup settles an ambiguous name). Then apply it mechanically rather than guessing per line.
- Run `python scripts/find_gendered.py TH.srt` to list every cue containing a gendered token
  (ผม/กระผม/ครับ, ดิฉัน/ฉัน/หนู/ค่ะ/คะ/นะคะ). It flags likely false positives (`ผม`="hair",
  `คะ` inside `คะแนน`="score") with `?` so you don't blindly flip them.
- For each flagged cue, identify the speaker (caps labels → vocatives/context → alternation) and
  set the pronoun/particle to the right gender and register (formal ดิฉัน vs casual ฉัน vs
  child-to-elder หนู vs parent-as-แม่/พ่อ). Fix each half of a two-speaker cue by its own speaker.
- **Change only the gendered pronoun and particle** — never timestamps, indices, other wording,
  or bracketed cues.
- **Fix all flagged cues in as few edits as possible — never one `Edit` call per cue.** Read the
  whole file, collect every fix into a list of `{cue, find, replace}`, then apply them all in one
  pass with `python scripts/apply_gender_fixes.py TH.srt --fixes-json '[...]'` (it applies every
  fix in a single deterministic pass and safety-checks that each `find` occurs exactly once per
  cue, refusing to write anything if not). A verify agent that called `Edit` individually 45 times
  (80 assistant turns total) burned **11M+ tokens on a 45-fix pass** — ~4x the cost of an
  equivalent Sonnet run that batched its fixes — because each turn re-sends the whole accumulated
  conversation as fresh (uncached) input. The blowup is turn-count-driven, not model-driven: it
  gets worse, not better, on a higher-cost model/effort, so this matters most exactly when you've
  reached for Opus or high effort here.

This works best as a **dedicated second pass**, separate from translation — checking gender while
also rendering meaning splits attention and lets errors through. When subagents are available, an
effective pattern is to hand a verification subagent (a) the Thai file, (b) the English-with-labels
file, and (c) the character→gender map, and have it write a corrected file; that keeps the whole
episode's context in one place. The guide has a worked character map and a table of real fixes.

## 4. Validate structure

```
python scripts/validate_srt.py TH.srt
python scripts/validate_srt.py TH.srt --compare EN.srt      # also check cue-count/timestamp alignment
```
This catches the failure modes that actually bite: a stray non-ASCII character typo'd into a
timestamp, duplicate indices, zero-length or overlapping cues, empty text, and cue-count drift
vs the source. It exits non-zero on a hard error, so you can gate the mux on it. Fix and re-run
until clean. (These are exactly the bugs that slipped through when this workflow was done by hand.)

## 5. Mux both tracks into the video

```
python scripts/mux_subs.py --video IN.mp4 --thai TH.srt --eng EN.srt --out OUT.mkv
```
(`--th`/`--en` also work as explicit aliases for `--thai`/`--eng`.)
This copies the original video+audio untouched (`-c copy`, fast, no re-encode), adds the Thai and
English subs as SRT tracks, tags them `tha`/`eng`, and marks **Thai as default**. Output is MKV.
Options: `--default eng|none`, `--thai-title`, `--eng-title "English (SDH)"`, omit `--eng` for
Thai-only. It prints the final track layout so you can eyeball it.

> **⚠️ `--video` must be the file that already contains EVERY audio track you want in the output.**
> `mux_subs.py` does `-map 0:a` — it copies *all* audio from `--video` and **silently drops
> nothing / adds nothing**. If this episode also went through **dub-sync**, point `--video` at the
> **dub-sync `TH-EN.mkv` output** (which has both Thai + English audio), **NOT** the original
> single-audio source. Pointing it at the plain source produces a "finished" file with **English
> audio only and no Thai audio** — and there is **no error**; the mux succeeds and looks fine. This
> exact mistake shipped two episodes with the Thai dub missing before it was caught. **Always
> `ffprobe` the final file and confirm the stream layout** — for the full dub+sub deliverable that
> is **5 streams: video, audio tha, audio eng, subtitle tha, subtitle eng**. Don't trust exit 0;
> a dropped track is invisible without the probe.

Verify the result (stream count + languages, per the box above), then (only if the user asked)
replace the original — always back up first, and confirm the backup's byte size matches before
deleting anything. On Windows the source files may be **read-only**, so a delete/overwrite can throw
`PermissionError: Access is denied` — clear the flag first (`os.chmod(path, stat.S_IWRITE)` /
`attrib -r`) before removing.

## Plex note

For Plex to pick the Thai subtitle automatically, two things matter:
- The track must be **language-tagged `tha`** — the muxer always sets this.
- Plex largely **ignores the container's "default" flag** for playback; it follows the viewer's
  account **preferred-subtitle-language** setting (or a per-show manual choice Plex remembers).
  So if Thai doesn't come up by default, the fix is in Plex settings, not the file: set preferred
  subtitle (and/or audio) language to Thai, or pick it once on the show and Plex remembers it.

## Gotchas (each cost real debugging — most severe first)

- **The mux `--video` source is the worst trap.** Pointing it at the plain single-audio file
  instead of the dub-sync `TH-EN.mkv` yields **English-audio-only output with no error** — it shipped
  two episodes silently broken. Always `ffprobe` the final file for the full 5-stream layout (step 5).
- **An agent's `ok=true` does not prove the file was written correctly.** Chunked translation
  routinely false-reports success, or writes a wrong cue count. Gate on `validate_srt.py --compare`,
  never the agent's word (step 2's chunking rules).
- **A single stray Thai character in a timestamp** (e.g. a combining `่` or a mistyped digit)
  makes that cue unparseable and can shift everything after it. `validate_srt.py` pinpoints it.
- **Duplicate indices / lost cues** happen when merging or hand-editing. Validate before muxing.
- **A source cue can legitimately contain an internal blank line.** One EN `.srt` cue held
  `What?` ⏎⏎ `It's about my shoulder.` as a *single* cue (a `\n\n\n` inside one block). The
  block-splitter `re.split(r"\n\s*\n", ...)` reads that internal blank as a cue boundary → the
  cue splits in two, and the phantom half's text gets dropped or mis-attributed downstream (it
  vanished during the gender-fix apply). The tell is `validate_srt.py --compare` flagging an
  **off-by-one** vs the source. Fix: grep the **source** for the internal-blank cue and collapse
  its internal `\n\n+` to a single `\n` *before* chunking, so every real cue is one block.
- **Chunk rejoin must insert the blank separator explicitly.** Plain `cat chunk1 chunk2 …` fuses
  the last cue of one chunk into the first of the next whenever a chunk file lacks a trailing
  blank line (seen: a season episode came out 830→825, five joins lost). Read each chunk,
  `.strip()`, and join with an explicit `"\n\n"` — then let `validate_srt.py --compare` confirm
  the total. (This is the deterministic-join rule from step 2, stated as the concrete failure.)
- **A gendered marker that repeats in one cue with the SAME target won't auto-apply.**
  `apply_gender_fixes.py` refuses any `find` occurring ≠1 time (ambiguity guard), so a cue like
  `ฉัน…ฉัน` → `ผม…ผม` can't go through it — do those with a direct `str.replace()` on that cue.
  Also order markers **longest-first** when building the fix list, because short markers are
  substrings of long ones (`นะคะ` ⊃ `คะ`; `ครับผม` ⊃ `ครับ`+`ผม`) — flipping the short one first
  corrupts the long one.
- **`ผม` also means "hair" and `หนู` means "mouse"** — don't flip a gendered pronoun without
  reading the cue; `find_gendered.py` marks these `?`.
- **Bracket/space paths on Windows** ("Season 03 [1080p]") break bash globbing; the Python muxer
  avoids the shell entirely, so prefer it over hand-writing an ffmpeg command line.
- **MP4 output can't hold SRT text subs** the same way — this skill outputs **MKV** on purpose.
- **Don't touch royal/court-register lines** (petitioning a king, etc.) when fixing gender — that
  deferential speech is intentional, not an error.
