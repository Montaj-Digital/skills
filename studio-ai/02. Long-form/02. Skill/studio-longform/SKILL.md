---
name: studio-longform
description: Turn a long talking-head recording (60+ minutes, landscape 16:9, YouTube or webinar) into an edited default-brand video - trimmed pauses and retakes, chapters with YouTube timestamps, lower-thirds, occasional brand cards, optional word captions, end screen. Use for long-form edits; for Reels, Feed and Square videos use studio-reel instead.
---

# the default brand long-form

The long-form counterpart of `studio-reel`. It never changes studio-reel and has its own spec, `longform.json`
(see `references/longform-spec.md`). The Studio AI short-form editor's long-form section runs these steps for you; this file
holds the rules Claude follows when planning.

## Steps

1. **Transcribe once** on the raw file (or import SRT/VTT, or correct whisper with a pasted transcript).
2. **Cuts**: `scripts/plan_cuts.py <raw> <transcript.json> <work> --format landscape --no-zoom [--remove A-B ...]`
   trims pauses, drops retakes, writes `edl.json`. No punch-in zooms by default.
3. **Map words** from raw time to edited time through `edl.json`. Never transcribe the edit again.
4. **Outline** (pass a): chapters with titles and start times from a sentence-level transcript.
5. **Per chapter** (pass b): lower-thirds, key-point cards, an occasional stat or list.
6. Write `longform.json` and `chapters.txt` (YouTube chapter timestamps).

## House style (long-form)

- Calm and professional. Slow, soft motion; no flashes, shakes or sound effects.
- **Chapters**: 4-12 for an hour. Titles are 2-6 words, specific, no clickbait. The first chapter starts at 0:00 and
  is at least 10 s long (YouTube's rule). Never shorter than 10 s.
- **Lower-thirds** for names and topics: when a person is introduced, and at each chapter start (the chapter title).
  Visible 4-5 s. Not more than one every 45 s.
- **Cards**: about one every 1-3 minutes, only where a visual helps (a definition, a number, a list of 3-5 items, a
  key takeaway). Visible 5-9 s. Never two on screen at once. Never over a lower-third. Short text: a title of at most
  6 words, body of at most 14 words, list items of at most 5 words.
- **End screen** on the last 6 s: the default brand call to action (same wording as short-form).
- **Captions** are word-by-word, bottom third, burned in. They are on by default and the person can switch them off.
- Brand: Trustline #2563eb, gradient #22d3ee to #2563eb, Display and Inter, glass cards. Reuse studio-reel's
  `template/brand.css`, fonts and logo, with card designs adapted to 1920x1080.
