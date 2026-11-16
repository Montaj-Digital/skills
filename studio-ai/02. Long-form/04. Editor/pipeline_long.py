"""Long-form pipeline: a long talking-head recording -> cuts, chapters, lower-thirds and cards (longform.json).

Steps (everything is written under <project>/work, plus longform.json and chapters.txt in <project>):
  setup       probe the linked camera file
  transcript  word-level transcript, ONCE, of the raw file (whisper, an imported SRT/VTT, or whisper corrected by pasted text)
  retakes     Claude reads the transcript in 10-minute windows for false starts and retakes
  cuts        plan_cuts.py (pauses trimmed, retakes removed, no punch-in zooms) -> work/edl.json
  words       raw word times mapped onto the edited timeline through the cut list (no second transcription)
  outline     Claude, pass 1: chapters with titles and times from a sentence-level transcript
  details     Claude, pass 2: per chapter, lower-thirds and key-point cards
  finish      checks the plan against the house rules, writes longform.json and chapters.txt

Claude runs as `claude -p` (Claude Code headless, the user's own login). Without it, retakes, chapters and cards are
skipped and everything else still runs. Python 3.9 standard library only.
"""
import bisect, difflib, json, os, re, shutil, subprocess, threading, time
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "01. Short-form" / "04. Editor"))
import claude_client   # 01. Short-form/04. Editor: one way to call Claude (phase 7)
import workspace
import osutil         # macOS / Windows differences (phase 8)
import sys

# Studio AI brand kits (03. Brands/brandkit.py): client end screens and tone of voice for Claude
try:
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "03. Brands"))
    import brandkit
except ImportError:
    brandkit = None

STEPS = [
    ("setup", "Set up the project"),
    ("transcript", "Transcribe the video"),
    ("retakes", "Find retakes and false starts"),
    ("cuts", "Trim pauses and plan the cuts"),
    ("words", "Match the words to the edit"),
    ("outline", "Plan the chapters"),
    ("details", "Plan lower-thirds and cards"),
    ("finish", "Write the chapters and the plan"),
]

DEFAULT_END = {"duration": 6, "lines": [{"text": "Follow"}, {"text": "for more", "bold": True}]}
MIN_CHAPTER = 10.0
SIGN_IN = "Claude Code isn't signed in: run claude in Terminal once, then retry this step"


class NotSignedIn(Exception):
    pass


def find_claude(settings):
    return claude_client.find_claude(settings)


# ------------------------------------------------------------------ transcripts (pure functions)
def _clock(s):
    s = s.strip().replace(",", ".")
    parts = s.split(":")
    secs = 0.0
    for p in parts:
        secs = secs * 60 + float(p)
    return secs


def parse_subtitles(text):
    """SRT or VTT text -> words [{text,start,end}]. Word times are spread evenly across each cue (a cue has no word timings)."""
    words = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    for b in blocks:
        m = re.search(r"((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[.,]\d{1,3})", b)
        if not m:
            continue
        start, end = _clock(m.group(1)), _clock(m.group(2))
        body = b[m.end():]
        body = re.sub(r"<[^>]+>", "", body)             # VTT tags
        toks = body.split()
        if not toks or end <= start:
            continue
        step = (end - start) / len(toks)
        for i, t in enumerate(toks):
            words.append({"text": t, "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3)})
    return words


def _norm(t):
    return re.sub(r"[^\w']", "", t.lower())


def align_paste(words, pasted):
    """Correct whisper's words with a pasted transcript. Whisper keeps the timings; the pasted text supplies the spelling
    (names, brands, jargon), capitals and punctuation. Words whisper heard that aren't in the paste (ad-libs) stay as they are."""
    toks = pasted.split()
    if not toks or not words:
        return words, 0
    a = [_norm(w["text"]) for w in words]
    b = [_norm(t) for t in toks]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    out, changed = [], 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                w = dict(words[i1 + k])
                if w["text"] != toks[j1 + k]:
                    changed += 1
                w["text"] = toks[j1 + k]
                out.append(w)
        elif tag == "replace":
            n, m = i2 - i1, j2 - j1
            t0, t1 = words[i1]["start"], words[i2 - 1]["end"]
            if n == m:
                for k in range(n):
                    w = dict(words[i1 + k]); w["text"] = toks[j1 + k]; out.append(w)
            else:                                        # spread the pasted words over the same stretch of time
                step = (t1 - t0) / m
                for k in range(m):
                    out.append({"text": toks[j1 + k], "start": round(t0 + k * step, 3), "end": round(t0 + (k + 1) * step, 3)})
            changed += m
        elif tag == "delete":
            out.extend(dict(w) for w in words[i1:i2])
        # "insert": pasted words that were never said; dropped
    return out, changed


def map_to_edit(words, segments):
    """Raw-time words -> edited-timeline words, through the cut list. Words outside every kept segment are dropped.
    Inserts (segments with "src", Studio AI) have no words but take up time: the camera segments after them move later."""
    offs, o = [], 0.0
    for s in segments:
        offs.append(o); o += s["out"] - s["in"]
    cam = sorted(((s, off) for s, off in zip(segments, offs) if not s.get("src")), key=lambda x: x[0]["in"])
    segments = [s for s, _ in cam]; offs = [off for _, off in cam]
    starts = [s["in"] for s in segments]
    out = []
    for w in words:
        mid = (w["start"] + w["end"]) / 2
        i = bisect.bisect_right(starts, w["start"] + 1e-6) - 1
        if i < 0 or not (segments[i]["in"] - 1e-6 <= mid <= segments[i]["out"] + 1e-6):
            continue
        d = offs[i] - segments[i]["in"]
        out.append({"text": w["text"], "start": round(w["start"] + d, 3), "end": round(min(w["end"], segments[i]["out"]) + d, 3)})
    return out


def sentences(words, max_words=32, gap=0.9):
    """Words -> sentences [{start,end,text}] (a full stop, a long pause or a word limit ends one)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1]["start"] if i + 1 < len(words) else None
        if re.search(r"[.?!]$", w["text"]) or len(cur) >= max_words or nxt is None or nxt - w["end"] > gap:
            out.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": " ".join(x["text"] for x in cur)})
            cur = []
    return out


def stamp(t, hours=False):
    t = int(round(t)); h, m, s = t // 3600, (t % 3600) // 60, t % 60
    return f"{h}:{m:02d}:{s:02d}" if hours or h else f"{m}:{s:02d}"


def chapters_txt(chapters, duration):
    return "\n".join(f"{stamp(c['start'])} {c['title']}" for c in chapters) + "\n"


# ------------------------------------------------------------------ plan checks (pure functions)
def clean_chapters(chs, sents, duration):
    """Sort, snap to sentence starts, start at 0, enforce the 10-second minimum, make contiguous."""
    starts = [s["start"] for s in sents] or [0.0]
    rows = []
    for c in chs:
        try:
            t = float(c["start"]); title = str(c["title"]).strip()
        except (KeyError, TypeError, ValueError):
            continue
        if not title or t < 0 or t >= duration:
            continue
        j = bisect.bisect_left(starts, t)
        near = min([x for x in starts[max(0, j - 1):j + 1]], key=lambda x: abs(x - t))
        rows.append({"title": title[:80], "start": round(near, 2)})
    rows.sort(key=lambda r: r["start"])
    if rows:
        rows[0]["start"] = 0.0
    kept = []
    for r in rows:
        if kept and (r["start"] - kept[-1]["start"] < MIN_CHAPTER or r["start"] == kept[-1]["start"]):
            continue
        kept.append(r)
    if len(kept) > 1 and duration - kept[-1]["start"] < MIN_CHAPTER:
        kept.pop()
    for a, b in zip(kept, kept[1:]):
        a["end"] = b["start"]
    if kept:
        kept[-1]["end"] = round(duration, 2)
    return kept


def check_overlays(lts, cards, chapters, duration, end_dur):
    """Apply the house rules: inside the chapter, no overlaps, spacing, limits. Returns (lowerThirds, cards, dropped_count)."""
    def chap(t):
        for c in chapters:
            if c["start"] <= t < c["end"]:
                return c
        return None
    dropped = 0
    limit = duration - end_dur
    L = []
    for x in sorted(lts, key=lambda x: float(x.get("t", 0))):
        try:
            t, d = float(x["t"]), min(max(float(x.get("dur", 4.5)), 3.0), 6.0)
        except (KeyError, TypeError, ValueError):
            dropped += 1; continue
        c = chap(t)
        if not c or not x.get("title") or t + d > min(c["end"], limit) + 0.01 or (L and t < L[-1]["t"] + L[-1]["dur"] + 40):
            dropped += 1; continue
        L.append({"t": round(t, 2), "dur": round(d, 2), "title": str(x["title"])[:60], **({"sub": str(x["sub"])[:70]} if x.get("sub") else {})})
    C = []
    for x in sorted(cards, key=lambda x: float(x.get("t", 0))):
        try:
            t, d = float(x["t"]), min(max(float(x.get("dur", 7)), 5.0), 10.0)
        except (KeyError, TypeError, ValueError):
            dropped += 1; continue
        c = chap(t); ty = x.get("type")
        ok = c and ty in ("keypoint", "stat", "list") and t + d <= min(c["end"], limit) + 0.01
        ok = ok and not (C and t < C[-1]["t"] + C[-1]["dur"] + 20)
        ok = ok and not any(t < l["t"] + l["dur"] + 0.3 and l["t"] < t + d + 0.3 for l in L)
        card = {"type": ty, "t": round(t, 2), "dur": round(d, 2)}
        if ok and ty == "keypoint" and x.get("title"):
            card.update(title=str(x["title"])[:70], body=str(x.get("body", ""))[:120])
        elif ok and ty == "stat" and x.get("value") and x.get("label"):
            card.update(value=str(x["value"])[:12], label=str(x["label"])[:70])
        elif ok and ty == "list" and isinstance(x.get("items"), list) and 2 <= len(x["items"]) <= 6 and x.get("title"):
            card.update(title=str(x["title"])[:70], items=[str(i)[:40] for i in x["items"]])
        else:
            ok = False
        if not ok:
            dropped += 1; continue
        C.append(card)
    return L, C, dropped


# ------------------------------------------------------------------ the job
class LongJob:
    def __init__(self, root, skill, env, settings, creds=None):
        self.root, self.skill, self.env, self.settings = Path(root), Path(skill), env, settings
        self.work = self.root / "work"
        self.meta = json.loads((self.root / "project.json").read_text())
        self.raw = Path(self.meta["raw"])
        # a client brand (Studio AI); none or default = the default look
        self.brand = self.meta.get("brand") if brandkit and brandkit.client(self.meta.get("brand")) else None
        self.who = brandkit.display_name(self.brand) if self.brand else "Your brand"
        self.voice = ("\n" + brandkit.voice_note(self.brand) + "\n") if self.brand else ""
        self.end = brandkit.endcard(self.brand, DEFAULT_END) if self.brand else DEFAULT_END
        self.state = {k: "pending" for k, _ in STEPS}
        self.info, self.log, self.error = {}, [], None
        self.done = self.running = False
        # how to reach Claude: the request's credentials (portal: the user's API key), else Claude Code here
        self.claude = creds if creds is not None else claude_client.creds_from({}, settings)
        self.claude = self.claude if self.claude.available else None
        self.thread = None
        self._load()

    # ---- persistence: lets the Open screen and a restarted server see how far a project got
    def _load(self):
        f = self.work / "job.json"
        if f.exists():
            try:
                d = json.loads(f.read_text())
                self.state.update(d.get("state", {})); self.info.update(d.get("info", {}))
                self.error = d.get("error"); self.done = bool(d.get("done"))
                for k in self.state:                      # a step that was running when the server stopped
                    if self.state[k] == "running":
                        self.state[k] = "failed"; self.error = self.error or "The editor was closed while this step was running"
            except ValueError:
                pass

    def _save(self):
        self.work.mkdir(parents=True, exist_ok=True)
        (self.work / "job.json").write_text(json.dumps({"state": self.state, "info": self.info, "error": self.error, "done": self.done}, indent=1))

    def say(self, line):
        parts = [x.strip() for x in re.split(r"\x1b\[[0-9;?]*[A-Za-z]|\r", line) if x.strip()]
        if parts:
            self.log.append(parts[-1]); del self.log[:-500]

    def run(self, cmd, cwd=None, timeout=4 * 3600, stdin=None):
        self.say("$ " + " ".join(str(c) for c in cmd)[:400])
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd or self.root, env=dict(self.env, NO_COLOR="1", CI="1"), text=True,
                             stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        out = []
        if stdin is not None:
            threading.Thread(target=lambda: (p.stdin.write(stdin), p.stdin.close()), daemon=True).start()
        start = time.time()
        for line in p.stdout:
            out.append(line); self.say(line)
            if time.time() - start > timeout:
                osutil.kill_tree(p); raise RuntimeError(f"{cmd[0]} timed out")
        code = p.wait()
        if code != 0:
            raise RuntimeError(f"{Path(str(cmd[0])).name} {' '.join(str(c) for c in cmd[1:3])} failed (exit {code})")
        return "".join(out)

    def probe(self, video):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=r_frame_rate,width,height:format=duration", "-of", "json", str(video)],
                             capture_output=True, text=True, env=self.env).stdout
        d = json.loads(out or "{}")
        st = (d.get("streams") or [{}])[0]
        num, den = (st.get("r_frame_rate", "30/1").split("/") + ["1"])[:2]
        fps = round(float(num) / float(den or 1)) if float(den or 1) else 30
        return float(d.get("format", {}).get("duration", 0)), fps or 30, st.get("width", 0), st.get("height", 0)

    def ask_claude(self, prompt, step):
        """One JSON answer from Claude through claude_client (Claude Code on this Mac, or the API with the user's key)."""
        if not self.claude:
            return None
        try:
            return claude_client.ask_json(self.claude, prompt, cwd=self.work, env=self.env, timeout=1800,
                                          on_event=lambda line: self.say(line), what=f"{step} reply")
        except claude_client.NotSignedIn as e:
            self.say(str(e)); raise NotSignedIn()
        except claude_client.ClaudeError as e:
            raise RuntimeError(str(e))

    def skip(self, step, why):
        self.state[step] = "skipped"; self.info[step] = why

    # ---- steps
    def s_setup(self):
        self.work.mkdir(parents=True, exist_ok=True)
        if not self.raw.exists():
            raise RuntimeError(f"The camera file isn't there any more: {self.raw}")
        dur, fps, w, h = self.probe(self.raw)
        self.raw_dur, self.fps = dur, fps
        m = int(dur // 60)
        self.info["setup"] = f"{w}x{h}, {m} min {int(dur % 60)} s at {fps} fps" + ("" if w >= h else " (portrait: long-form expects landscape)")

    def s_transcript(self):
        tj, t = self.work / "transcript.json", self.meta.get("transcript") or {"mode": "none"}
        mode = t.get("mode", "none")
        if not tj.exists():
            if mode == "srt":
                words = parse_subtitles(Path(t["path"]).read_text(errors="replace") if t.get("path") else t.get("text", ""))
                if not words:
                    raise RuntimeError("That subtitle file has no timed lines in it")
                tj.write_text(json.dumps(words))
                self.info["transcript"] = f"{len(words)} words from the subtitle file (whisper skipped; word times are spread across each line)"
                self.raw_words = words; return
            wj = self.work / "transcript.whisper.json"
            if not wj.exists():
                self.run([osutil.NPX, "-y", "hyperframes@latest", "transcribe", self.raw, "-d", self.work, "-m", "medium.en", "-l", "en", "--engine", "whisper"])
                shutil.move(str(tj), str(wj))
            words = json.loads(wj.read_text())
            if mode == "paste" and t.get("text", "").strip():
                words, n = align_paste(words, t["text"])
                self.info["transcript"] = f"{len(words)} words; {n} corrected from your pasted transcript"
            else:
                self.info["transcript"] = f"{len(words)} words"
            tj.write_text(json.dumps(words))
        self.raw_words = json.loads(tj.read_text())
        self.info.setdefault("transcript", f"{len(self.raw_words)} words")

    def s_retakes(self):
        self.remove = []
        rj = self.work / "retakes.json"
        if rj.exists():
            res = json.loads(rj.read_text())
        else:
            if not self.claude:
                return self.skip("retakes", "Needs Claude Code; no retakes removed")
            allr, notes = [], []
            WIN = 600.0
            n = int(self.raw_words[-1]["end"] // WIN) + 1
            for k in range(n):
                part = [w for w in self.raw_words if k * WIN <= w["start"] < (k + 1) * WIN]
                if len(part) < 20:
                    continue
                self.info["retakes"] = f"Reading part {k + 1} of {n}…"; self._save()
                lines = "\n".join(f"{w['start']:.2f}-{w['end']:.2f}\t{w['text']}" for w in part)
                prompt = f"""You are editing a long raw talking-head recording for your brand (long-form, studio-longform skill).
This is part {k + 1} of {n} of the transcript (raw times in seconds). Find what should be cut: false starts, retakes
("let me say that again", a sentence restarted from the top), stumbles re-said straight after, and any outtake. When a
line is said twice, keep the LAST clean take and remove the earlier attempts. Do not cut normal pauses (a later step
trims those), do not cut anything said only once, and do not cut across this part's edges. Be conservative: a live
talk or workshop usually has few retakes, so an empty list is a normal answer.

Reply with JSON only: {{"remove": [[start, end], ...], "notes": ["one short line per cut"]}}
Notes from the person (may mention takes to drop): {self.meta.get("notes") or "none"}

TRANSCRIPT (start-end<TAB>word)
{lines}
"""
                try:
                    r = self.ask_claude(prompt, "retakes") or {}
                except NotSignedIn:
                    return self.skip("retakes", SIGN_IN)
                allr += [[float(a), float(b)] for a, b in r.get("remove", []) if float(b) > float(a)]
                notes += r.get("notes", [])
            res = {"remove": allr, "notes": notes}
            rj.write_text(json.dumps(res, indent=2))
        self.remove = [(float(a), float(b)) for a, b in res.get("remove", [])]
        cut = sum(b - a for a, b in self.remove)
        self.info["retakes"] = f"{len(self.remove)} cut ({cut:.0f} s)" if self.remove else "None found"

    def s_cuts(self):
        args = ["--remove", *[f"{a:.2f}-{b:.2f}" for a, b in self.remove]] if getattr(self, "remove", None) else []
        self.run(["python3", self.skill / "scripts/plan_cuts.py", self.raw, self.work / "transcript.json", self.work,
                  "--format", "landscape", "--no-zoom", *args])
        edl = json.loads((self.work / "edl.json").read_text())
        self.segments = edl["segments"]
        self.dur = sum(s["out"] - s["in"] for s in self.segments)
        was = self.raw_words[-1]["end"] if self.raw_words else self.raw_dur
        self.info["cuts"] = f"{len(self.segments)} segments, {int(self.dur // 60)} min {int(self.dur % 60)} s (from {int(was // 60)} min)"

    def s_words(self):
        self.words = map_to_edit(self.raw_words, self.segments)
        (self.work / "words-edit.json").write_text(json.dumps(self.words))
        self.sents = sentences(self.words)
        self.info["words"] = f"{len(self.words)} words, {len(self.sents)} sentences"

    def s_outline(self):
        cj = self.work / "outline.json"
        if cj.exists():
            raw = json.loads(cj.read_text())
        else:
            if not self.claude:
                self.chapters = []; return self.skip("outline", "Needs Claude Code; no chapters planned")
            lines = "\n".join(f"{int(s['start'])}\t{s['text']}" for s in self.sents)
            minutes = self.dur / 60
            prompt = f"""You are planning the chapters of a long-form YouTube video for {self.who} (studio-longform skill).{self.voice}
The edited video is {self.dur:.0f} seconds ({minutes:.1f} minutes). Below is its transcript, one sentence per line:
start time in whole seconds on the EDITED timeline, a tab, then the sentence.

Write the chapters. Rules:
- About one chapter every 5-10 minutes (an hour is 6-12 chapters), and always at least 3 chapters. Chapters must be at least 10 seconds long.
- The first chapter starts at 0. Each later "start" is the start time of a sentence in the transcript, where the topic really changes.
- Titles are 2-6 words, specific and plain, in Title Case, no clickbait, no colons, no emoji.
- Use the speaker's own topics and names. Do not invent content.

Reply with JSON only: {{"chapters": [{{"title": "...", "start": 0}}, ...]}}
Notes from the person: {self.meta.get("notes") or "none"}

TRANSCRIPT
{lines}
"""
            try:
                raw = self.ask_claude(prompt, "outline") or {}
            except NotSignedIn:
                self.chapters = []; return self.skip("outline", SIGN_IN)
            cj.write_text(json.dumps(raw, indent=2))
        self.chapters = clean_chapters(raw.get("chapters", []), self.sents, self.dur)
        if not self.chapters:
            raise RuntimeError("Claude's chapter plan had no usable chapters")
        self.info["outline"] = f"{len(self.chapters)} chapters"

    def s_details(self):
        self.lts, self.cards = [], []
        if not self.claude or not self.chapters:
            return self.skip("details", "Needs Claude Code and the chapters; no lower-thirds or cards planned")
        dj = self.work / "details.json"
        done = json.loads(dj.read_text()) if dj.exists() else {}
        spec = (self.skill / "references/longform-spec.md").read_text()
        sk = (self.skill / "SKILL.md").read_text()
        house = sk[sk.find("## House style"):]
        title = self.meta.get("name", "")
        for i, c in enumerate(self.chapters):
            key = f"{i}:{c['start']}"
            if key not in done:
                self.info["details"] = f"Chapter {i + 1} of {len(self.chapters)}: {c['title']}"; self._save()
                part = [s for s in self.sents if c["start"] <= s["start"] < c["end"]]
                lines = "\n".join(f"{s['start']:.1f}\t{s['text']}" for s in part)
                prompt = f"""You are adding the on-screen graphics for ONE chapter of a long-form {self.who} video (studio-longform skill).{self.voice}
Video: "{title}". Chapter {i + 1} of {len(self.chapters)}: "{c['title']}", from {c['start']:.1f} s to {c['end']:.1f} s (edited timeline).
The whole video is {self.dur:.0f} s long. The end screen covers the last {DEFAULT_END['duration']} s: leave it clear.

{house}

THE SPEC (card types and limits):
{spec}

What to plan for this chapter only:
- "lowerThirds": the chapter title at the chapter start (t = {c['start'] + 0.5:.1f}, dur 4.5), plus a name/role one wherever a person is introduced.
- "cards": only where a visual really helps, about one every 1-3 minutes. A short chapter may have none.
Use only facts, names and numbers that are in the transcript. Every "t" is a time in seconds, inside this chapter, landing on or just before the words it illustrates.

Reply with JSON only: {{"lowerThirds": [{{"t": 0, "dur": 4.5, "title": "...", "sub": "..."}}], "cards": [{{"type": "keypoint", "t": 0, "dur": 7, "title": "...", "body": "..."}}]}}
Notes from the person: {self.meta.get("notes") or "none"}

CHAPTER TRANSCRIPT (start<TAB>sentence)
{lines}
"""
                try:
                    done[key] = self.ask_claude(prompt, "details") or {}
                except NotSignedIn:
                    return self.skip("details", SIGN_IN)
                dj.write_text(json.dumps(done, indent=2))
            self.lts += done[key].get("lowerThirds", []); self.cards += done[key].get("cards", [])
        self.lts, self.cards, dropped = check_overlays(self.lts, self.cards, self.chapters, self.dur, DEFAULT_END["duration"])
        self.info["details"] = f"{len(self.lts)} lower-thirds, {len(self.cards)} cards" + (f" ({dropped} suggestions dropped by the house rules)" if dropped else "")

    def s_finish(self):
        spec = {"version": 1, "title": self.meta.get("name", ""), "duration": round(self.dur, 2), "fps": self.fps, "size": [1920, 1080],
                "source": str(self.raw), "edl": "work/edl.json", "words": "work/words-edit.json",
                "captions": {"on": bool(self.meta.get("captions", True)), "style": "words", "size": 54, "bottom": 120},
                "chapters": self.chapters, "lowerThirds": self.lts, "cards": self.cards, "endcard": self.end}
        if self.brand:
            spec["brand"] = self.brand
        old = self.root / "longform.json"
        if old.exists():                                   # keep the person's captions switch across a re-run
            try:
                spec["captions"] = json.loads(old.read_text()).get("captions", spec["captions"])
            except ValueError:
                pass
        old.write_text(json.dumps(spec, indent=2, ensure_ascii=False))
        if self.chapters:
            (self.root / "chapters.txt").write_text(chapters_txt(self.chapters, self.dur))
        self.info["finish"] = "chapters.txt and longform.json written" if self.chapters else "longform.json written (no chapters)"

    # ---- driver
    def start(self, from_step=None):
        if self.running:
            return False
        self.error = None; self.done = False; self.running = True
        names = [k for k, _ in STEPS]
        first = names.index(from_step) if from_step in names else 0
        for k in names[first:]:
            self.state[k] = "pending"; self.info.pop(k, None)

        def go():
            try:
                for i, k in enumerate(names):
                    quiet = i < first               # earlier steps only rebuild what later ones need, from the files they wrote
                    if quiet and k == "cuts":
                        self.segments = json.loads((self.work / "edl.json").read_text())["segments"]
                        self.dur = sum(s["out"] - s["in"] for s in self.segments); continue
                    if quiet and k == "finish":
                        continue
                    saved = (dict(self.state), dict(self.info))
                    if not quiet:
                        self.state[k] = "running"; self._save()
                    getattr(self, "s_" + k)()
                    if quiet:
                        self.state, self.info = saved
                    else:
                        if self.state[k] == "running":
                            self.state[k] = "done"
                        self._save()
                self.done = True
            except Exception as e:
                for k in names:
                    if self.state[k] == "running":
                        self.state[k] = "failed"
                self.error = str(e); self.say("ERROR: " + str(e))
            finally:
                self.running = False; self._save()
        self.thread = workspace.Thread(target=go, daemon=True)
        self.thread.start()
        return True

    def status(self):
        return {"root": str(self.root), "name": self.meta.get("name"), "running": self.running, "done": self.done, "error": self.error,
                "claude": bool(self.claude),
                "steps": [{"key": k, "label": l, "state": self.state[k], "info": self.info.get(k, "")} for k, l in STEPS],
                "log": self.log[-40:]}
