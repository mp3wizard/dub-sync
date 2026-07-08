# Thai speaker-gender guide for subtitles

This is the crux of the whole skill. English dialogue carries no grammatical gender on
"I" or on polite sentence-enders, so a straight EN→TH translation silently guesses the
speaker's gender — and guesses wrong on a large fraction of a woman's lines (they come
out sounding like a man). Fixing this well is what separates a usable Thai subtitle from
an embarrassing one.

## The gendered elements

Only two categories are gendered, but they appear constantly:

| Category | Male | Female |
|---|---|---|
| 1st-person pronoun | ผม / กระผม (very formal) | ฉัน (neutral-casual) · ดิฉัน (formal) · หนู (a younger person to an elder) |
| Polite final particle — statement | ครับ | ค่ะ |
| Polite final particle — question | ครับ | คะ |
| Softener before particle | นะครับ | นะคะ |

Everything else (2nd person คุณ/เธอ, most nouns, verbs) is gender-neutral and needs no change.

### Register nuance for the 1st-person pronoun (women)
A woman does not always say ฉัน. Pick by situation and it will read naturally:
- **Formal / professional / to a superior or stranger** → ดิฉัน (e.g. an official addressing a president, a minister, a foreign dignitary).
- **Casual / peers / at home** → ฉัน.
- **Speaking to her own parents / an elder, or a young woman generally** → หนู.
- **A parent referring to themselves when talking to their child** → แม่ (mother) / พ่อ (father) instead of a pronoun. This is extremely common and natural in Thai — "แม่ภูมิใจในตัวลูก" not "ฉันภูมิใจ...". Use it when a parent is clearly speaking to their kid.

Men are simpler: ผม in almost all modern contexts; กระผม only for very deferential/formal speech. A father talking to his kids can likewise use พ่อ.

### Statement vs question particle (women)
ค่ะ ends a statement; คะ ends a question or a calling/rising tone ("แม่คะ", "จริงเหรอคะ").
Getting ค่ะ/คะ mixed up is minor but noticeable — match the sentence type.

## How to attribute a speaker to each cue

You cannot fix gender without knowing who is talking. Work from strongest to weakest signal:

1. **Explicit speaker labels in the English source.** SDH/CC subtitles prefix lines with
   the speaker in caps: `ANA:`, `MARCO:`, `LEO:`. These are ground truth — carry
   the attribution forward until the next label.
2. **Vocatives and context.** "Thanks, Sam." tells you the *previous* line was to Sam
   and the *next* is likely Sam replying. "ma'am" / "sir" reveal the addressee's gender.
   Kids saying "Mom"/"Dad" fix the parent.
3. **Dialogue back-and-forth.** In a two-person scene, speakers alternate; anchor on any
   labelled or context-fixed line and count.
4. **A cue with two speakers.** SDH sometimes packs an exchange into one cue
   (`ANA: ... MARCO: ...`). Fix each half by its own speaker.
5. **Genuinely unknown + gender-neutral wording** → leave it. Don't invent a change.

## Build a character→gender map first

Before touching cues, list the show's recurring speakers and their gender once, from the
English labels (and a quick web lookup if a name is ambiguous). Then apply it mechanically.
This is far more reliable than deciding gender ad-hoc per line.

### Worked example — a hypothetical political / family drama
Names below are illustrative placeholders — build the real map from your own title's English
speaker labels. This archetype (a senior official + her family + staff) exercises every register case.
```
FEMALE (ฉัน/ดิฉัน/หนู + ค่ะ/คะ):
  Ana ("ma'am","Mom") — a senior government official / female lead; ดิฉัน when formal
      (addressing a head of state, a minister, a foreign dignitary), ฉัน casual, แม่ to her kids.
  Nina, Rosa — her daughters; หนู to parents, ฉัน with siblings.
  Dana and other female staff/officials — ดิฉัน/ฉัน.
MALE (ผม + ครับ):
  Marco ("Dad") — her husband.  Leo — their son.
  Sam and other male aides, officials, soldiers — ผม + ครับ.
SPECIAL: royal-address scenes (petitioning a king) use deferential court Thai
  (ข้าพระพุทธเจ้า / ใต้ฝ่าละอองธุลีพระบาท) — keep that register, don't downgrade to ผม.
```

## What to change, and what to leave alone

- Change **only** the gendered pronoun and the gendered particle. Do not touch timestamps,
  indices, other wording, meaning, `[bracketed sound cues]`, or `♪` music lines.
- Preserve the **exact same number of cues** as the file you started from.
- Keep the file **UTF-8**.
- If a line has no first-person pronoun and no polite particle, there is nothing to fix.

## Common concrete fixes (from real corrections)

| Situation | Before (wrong) | After (right) |
|---|---|---|
| Female lead, casual, to her husband | ...ขีดจำกัดของ**ผม** | ...ของ**ฉัน** |
| Female lead, formal, reinstating a colleague | **ผม**อยากให้คุณกลับเข้ามา | **ดิฉัน**อยากให้คุณกลับเข้ามา |
| Female lead addressing a Senate leader (question) | ท่านผู้นำ**ครับ** | ท่านผู้นำ**คะ** |
| Male aide replying "ma'am" | ท่าน**คะ** | ท่าน**ครับ** |
| Male NGO worker | ขอบคุณ**ค่ะ**ท่าน | ขอบคุณ**ครับ**ท่าน |
| Daughter about herself | **ผม**มีระบบเตือน | **หนู**มีระบบเตือน |
| Son about himself | **ฉัน**ไม่สมัคร | **ผม**ไม่สมัคร |
| Female colleague / writer | ดี**ครับ** เพราะ... | ดี**ค่ะ** เพราะ... |

## Verification, not just translation

The reliable pattern is a **dedicated second pass** — translate first, then scan *only* for
gendered tokens and check each against the speaker. Trying to get gender perfect while also
translating meaning splits attention and lets mistakes through. Run
`scripts/find_gendered.py TH.srt` to list every candidate cue, then confirm or flip each.
For a full episode this is a lot of cues; if subagents are available, hand the scan + the
English-with-labels file to a verification subagent with the character map and have it emit
a corrected file — that keeps the whole episode's context in one place and is what worked in
practice. Always re-run `scripts/validate_srt.py` afterward to prove nothing structural moved.
