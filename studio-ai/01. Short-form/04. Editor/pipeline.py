"""New reel pipeline: raw talking-head video -> drafted reel project, following the studio-reel skill.

Steps (each writes into <project>/work or <project>/edit, exactly where the skill puts things):
  setup       HyperFrames project in edit/
  transcribe  word-level transcript of the raw clip (whisper medium.en)
  lighting    grade.py: even lighting across the clip
  retakes     Claude reads the transcript for false starts, retakes and outtakes
  cuts        plan_cuts.py: trims pauses, removes retakes, alternates punch-in zooms
  edit        edit.py: grade -> cut -> zoom -> 1080x1920 base edit
  captions    transcript of the base edit
  plan        Claude writes reel.json: caption fixes, keywords, cards, end screen
  build       build.py -> index.html

Claude runs through the Claude Code CLI in headless mode (`claude -p`). Without it, retakes are
skipped and reel.json starts with auto captions and the end screen only.
"""
import json, os, re, shutil, subprocess, sys, threading, time

from pathlib import Path

import workspace          # whose storage this job works in (phase 7)
import osutil             # macOS / Windows differences (phase 8)
import claude_client   # 01. Short-form/04. Editor: one way to call Claude (phase 7)

STEPS = [
    ("setup", "Set up the project"),
    ("transcribe", "Transcribe the raw video"),
    ("lighting", "Even out the lighting"),
    ("retakes", "Find retakes and false starts"),
    ("cuts", "Plan cuts and zooms"),
    ("edit", "Render the base edit"),
    ("captions", "Transcribe the edit"),
    ("plan", "Plan captions and cards"),
    ("build", "Build the video"),
]

# Studio AI brand kits (03. Brands/brandkit.py): client end screens and tone of voice for Claude
try:
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "03. Brands"))
    import brandkit
except ImportError:
    brandkit = None

DEFAULT_END = {"duration": 3.5, "lines": [{"text": "Follow"}, {"text": "for more", "bold": True}]}


def find_claude(settings):
    return claude_client.find_claude(settings)


# output formats: canvas size, HyperFrames resolution name, and how Claude should plan for it
FORMATS = {
    "reel": {"label": "Reel 9:16", "w": 1080, "h": 1920, "hf": "portrait", "guide": ""},
    "feed": {"label": "Feed 4:5", "w": 1080, "h": 1350, "hf": "portrait", "guide": """
THIS IS A 4:5 FEED VIDEO (1080x1350), not a full-height reel. Set "format": "feed".
- Same style as a reel, on a shorter frame: captions at chest height, cards centred below them, scaled to fit.
- Keep card text short and prefer compact cards (statement, feature, chips, 2-3 tiles or steps).
- In 4:5 a card's optional "y" (vertical centre in px, 820-1180) replaces "top"."""},
    "square": {"label": "Square 1:1", "w": 1080, "h": 1080, "hf": "square", "guide": """
THIS IS A 1:1 SQUARE VIDEO (1080x1080), not a full-height reel. Set "format": "square".
- Captions at chest height, cards centred below them and scaled down; space is tight.
- Use fewer, compact cards (statement, feature, chips, short tiles or steps): one idea every 6-10 s.
- In 1:1 a card's optional "y" (vertical centre in px, 700-960) replaces "top"."""},
    "landscape": {"label": "Landscape 16:9", "w": 1920, "h": 1080, "hf": "landscape", "guide": """
THIS IS A LANDSCAPE 16:9 VIDEO (1920x1080), not a vertical reel. Set "format": "landscape" and
"layout": {"cards": "right"} (use "left" only if the notes say the speaker sits on the right).
- Cards appear in a side panel beside the speaker, scaled down, so keep each card's text short.
- Captions sit as a lower third; keep groups to 2-4 words.
- Use fewer cards than a reel: one idea every 6-12 s, only where a visual genuinely helps.
- Chips sit at the top of the side panel.
- In landscape a card's optional "y" (vertical centre in px, 150-930) replaces "top"."""},
}


# looks: "clean" = glass cards over the footage; "takeover" = gradient cutaways for the key points as well
TEMPLATES = {
    "clean": {"label": "Clean", "example": "example-reel.json", "guide": """
TEMPLATE: CLEAN. Glass cards over the footage only: do not add "takeovers" or "fx"."""},
    "takeover": {"label": "Takeover", "example": "example-takeovers.json", "guide": """
TEMPLATE: TAKEOVER. As well as cards, add "takeovers" (gradient cutaways, see "takeovers" in the spec) for the key
points: a list being named, a tool reveal, a big number, a "thing one / thing two", a closing recap. About one every
15-25 s (4-6 in 60-100 s), never two in a row, with ordinary cards between them and never a card during a takeover.
Alternate "pip" and "full" in a reel; other formats use "full" only. Add 2-4 "fx" punches on words that need weight,
kept off the takeovers. Give the last takeover no "out" if it should run into the end screen."""},
}


class NotSignedIn(Exception):
    pass


SIGN_IN = "Claude Code isn't signed in: run claude in Terminal once, then retry this step"


class Job:
    def __init__(self, root, raw, notes, skill, env, settings, fmt="reel", template="clean", brand=None, creds=None):
        self.root, self.raw, self.notes, self.skill, self.env, self.settings = root, raw, notes, skill, env, settings
        # a client brand (Studio AI); None or default = the default look, exactly as before
        self.brand = brand if brandkit and brandkit.client(brand) else None
        self.end = brandkit.endcard(self.brand, DEFAULT_END) if self.brand else DEFAULT_END
        self.voice = brandkit.voice_note(self.brand) if self.brand else ""
        self.fmt = fmt if fmt in FORMATS else "reel"
        self.template = template if template in TEMPLATES else "clean"
        self.work, self.edit = root / "work", root / "edit"
        self.state = {k: "pending" for k, _ in STEPS}
        self.info = {}          # per-step one-line results shown in the UI
        self.log = []
        self.error = None
        self.done = False
        self.running = False
        # how to reach Claude: the request's credentials (portal: the user's API key), else Claude Code here
        self.claude = creds if creds is not None else claude_client.creds_from({}, settings)
        self.claude = self.claude if self.claude.available else None
        self.thread = None

    # ------------------------------------------------------------ plumbing
    def say(self, line):
        # CLI spinners redraw with escape codes; keep only the last frame of each line
        parts = [x.strip() for x in re.split(r"\x1b\[[0-9;?]*[A-Za-z]|\r", line) if x.strip()]
        if parts:
            self.log.append(parts[-1])
            del self.log[:-500]

    def run(self, cmd, cwd=None, timeout=3600, stdin=None):
        self.say("$ " + " ".join(str(c) for c in cmd)[:400])
        p = subprocess.Popen([str(c) for c in cmd], cwd=cwd or self.root, env=dict(self.env, NO_COLOR="1", CI="1"), text=True,
                             stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        out = []
        if stdin is not None:
            threading.Thread(target=lambda: (p.stdin.write(stdin), p.stdin.close()), daemon=True).start()
        start = time.time()
        for line in p.stdout:
            out.append(line)
            self.say(line)
            if time.time() - start > timeout:
                osutil.kill_tree(p); raise RuntimeError(f"{cmd[0]} timed out")
        code = p.wait()
        if code != 0:
            raise RuntimeError(f"{Path(str(cmd[0])).name} {' '.join(str(c) for c in cmd[1:3])} failed (exit {code})")
        return "".join(out)

    def py(self, script, *a, **kw):
        return self.run(["python3", self.skill / "scripts" / script, *a], **kw)

    def probe(self, video):
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=r_frame_rate:format=duration", "-of", "json", str(video)],
                             capture_output=True, text=True, env=self.env).stdout
        d = json.loads(out or "{}")
        num, den = (d.get("streams", [{}])[0].get("r_frame_rate", "25/1").split("/") + ["1"])[:2]
        fps = round(float(num) / float(den or 1))
        return float(d.get("format", {}).get("duration", 0)), fps or 25

    def ask_claude(self, prompt, step):
        """One JSON answer from Claude through claude_client (Claude Code on this Mac, or the API with the user's key)."""
        if not self.claude:
            return None
        try:
            return claude_client.ask_json(self.claude, prompt, cwd=self.work, env=self.env, timeout=1200,
                                          on_event=lambda line: self.say(line), what=f"{step} reply")
        except claude_client.NotSignedIn as e:
            self.say(str(e)); raise NotSignedIn()
        except claude_client.ClaudeError as e:
            raise RuntimeError(str(e))

    def s_setup(self):
        self.work.mkdir(parents=True, exist_ok=True)
        if not (self.edit / "hyperframes.json").exists():
            if self.edit.exists() and not any(self.edit.iterdir()):
                self.edit.rmdir()
            env = dict(self.env, HYPERFRAMES_SKIP_SKILLS="1")
            self.say("$ npx hyperframes init edit")
            r = subprocess.run([osutil.NPX, "-y", "hyperframes@latest", "init", "edit", "--example", "blank",
                                "--resolution", FORMATS[self.fmt]["hf"], "--non-interactive"], cwd=self.root, env=env,
                               capture_output=True, text=True, timeout=900)
            self.say(r.stdout + r.stderr)
            if r.returncode != 0:
                raise RuntimeError("hyperframes init failed")
        dur, fps = self.probe(self.raw)
        self.meta = {"raw_duration": dur, "fps": fps}
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                              "-of", "csv=p=0", str(self.raw)], capture_output=True, text=True, env=self.env).stdout.split()
        w, h = (int(x) for x in (out[0].split(",")[:2] if out else (0, 0)))
        F = FORMATS[self.fmt]
        crop = ""
        if w and h and (w > h) != (F["w"] > F["h"]):
            crop = f"; the {'portrait' if h > w else 'landscape'} video will be cropped to {F['label']}"
        self.info["setup"] = f"{F['label']} · source {w}x{h}, {dur:.1f}s at {fps} fps{crop}"

    def s_transcribe(self):
        if not (self.work / "transcript.json").exists():
            self.run([osutil.NPX, "-y", "hyperframes@latest", "transcribe", self.raw, "-d", self.work,
                      "-m", "medium.en", "-l", "en", "--engine", "whisper"])
        self.raw_words = json.loads((self.work / "transcript.json").read_text())
        self.info["transcribe"] = f"{len(self.raw_words)} words"

    def s_lighting(self):
        end = (self.raw_words[-1]["end"] + 1) if self.raw_words else self.meta["raw_duration"]
        self.py("grade.py", self.raw, self.work, "--end", f"{end:.2f}")
        rep = (self.work / "grade-report.txt")
        self.info["lighting"] = rep.read_text().strip().splitlines()[0][:90] if rep.exists() else "done"

    def s_retakes(self):
        self.remove = []
        if not self.claude:
            self.state["retakes"] = "skipped"; self.info["retakes"] = "Needs Claude Code; no retakes removed"; return
        lines = "\n".join(f"{w['start']:.2f}-{w['end']:.2f}\t{w['text']}" for w in self.raw_words)
        prompt = f"""You are editing a raw talking-head clip for a default-brand social reel (studio-reel skill, step 3).

Read the word-level transcript below (raw clip times in seconds) and find what should be cut:
false starts, retakes ("let me say that again", a sentence restarted from the top), stumbles that are
re-said straight after, and any outtake after the natural ending. When a line is said twice, keep the
LAST clean take and remove the earlier attempt(s). Do not cut normal pauses (a later step trims those)
and do not cut content that is only said once.

Reply with JSON only:
{{"remove": [[start, end], ...], "notes": ["one short line per cut: what was removed and why"]}}
Use raw times taken from the transcript (start of the first removed word, end of the last). Empty list if nothing needs cutting.

Notes from the person (may mention takes to drop): {self.notes or "none"}

TRANSCRIPT (start-end<TAB>word)
{lines}
"""
        try:
            res = self.ask_claude(prompt, "retakes") or {}
        except NotSignedIn:
            self.state["retakes"] = "skipped"; self.info["retakes"] = SIGN_IN; return
        self.remove = [(float(a), float(b)) for a, b in res.get("remove", []) if float(b) > float(a)]
        (self.work / "retakes.json").write_text(json.dumps(res, indent=2))
        cut = sum(b - a for a, b in self.remove)
        self.info["retakes"] = f"{len(self.remove)} cut ({cut:.1f}s)" if self.remove else "None found"

    def s_cuts(self):
        args = ["--remove", *[f"{a:.2f}-{b:.2f}" for a, b in self.remove]] if self.remove else []
        self.py("plan_cuts.py", self.raw, self.work / "transcript.json", self.work, "--format", self.fmt, *args)
        edl = json.loads((self.work / "edl.json").read_text())
        segs = edl.get("segments", [])
        total = sum(s["out"] - s["in"] for s in segs)
        self.info["cuts"] = f"{len(segs)} segments, {total:.1f}s"

    def s_edit(self):
        g = self.work / "grade-cmds.txt"
        self.py("edit.py", self.raw, self.work / "edl.json", self.edit / "base-edit.mp4", *(["--grade", g] if g.exists() else []))
        self.dur, _ = self.probe(self.edit / "base-edit.mp4")
        self.info["edit"] = f"{self.dur:.2f}s"

    def s_captions(self):
        self.run([osutil.NPX, "-y", "hyperframes@latest", "transcribe", "base-edit.mp4", "-m", "medium.en", "-l", "en",
                  "--engine", "whisper"], cwd=self.edit)
        self.words = json.loads((self.edit / "transcript.json").read_text())
        self.info["captions"] = f"{len(self.words)} words"

    def base_spec(self):
        spec = {"duration": round(self.dur, 2), "fps": self.meta["fps"], "video": "base-edit.mp4",
                "captions": {"fix": {}, "drop": [], "keywords": [], "lead": 0.05},
                "cards": [], "endcard": self.end, "sfx": []}
        if self.brand:
            spec = {"brand": self.brand, **spec}
        if self.fmt != "reel":
            spec = {"format": self.fmt, **({"layout": {"cards": "right"}} if self.fmt == "landscape" else {}), **spec}
        spec = {"template": self.template, **spec}
        return spec

    def s_plan(self):
        spec = self.base_spec()
        if not self.claude:
            (self.edit / "reel.json").write_text(json.dumps(spec, indent=2))
            self.state["plan"] = "skipped"; self.info["plan"] = "Needs Claude Code; auto captions and end screen only"; return
        skill_md = (self.skill / "SKILL.md").read_text()
        rules = skill_md[skill_md.find("### 6."):skill_md.find("### 7.")]
        house = skill_md[skill_md.find("## House style"):skill_md.find("## Gotchas")]
        words = "\n".join(f"{i}\t{w['start']:.2f}\t{w['text']}" for i, w in enumerate(self.words))
        who = brandkit.display_name(self.brand) if self.brand else "Your brand"
        prompt = f"""You are planning a {who} social reel with the studio-reel skill (step 6: captions and cards).
Write the complete reel.json for this edit.
{FORMATS[self.fmt]["guide"]}
{TEMPLATES[self.template]["guide"]}

FIXED VALUES: "duration": {spec['duration']}, "fps": {spec['fps']}, "video": "base-edit.mp4", "sfx": [].
Use exactly this "endcard" unless the notes ask for another call to action (then keep the same shape:
regular lines first, the offer as bold lines; no asterisks): {json.dumps(self.end)}
{self.voice}

{rules}
{house}

THE SPEC (every card type and field):
{(self.skill / 'references/reel-spec.md').read_text()}

A COMPLETE APPROVED EXAMPLE (copy its patterns, density and timing style):
{(self.skill / 'references' / TEMPLATES[self.template]['example']).read_text()}

Rules for this output:
- Every time is seconds on the EDITED timeline (the transcript below). A card lands on its trigger word: word start - 0.1.
- Never two card groups on screen at once (a chip may sit above a card); leave ~0.2 s between cards.
- Only use icons that are Lucide names and logos from the spec. Use the "text" type only for a line that no other card fits.
- Word indices in captions.fix / drop / keywords refer to the transcript below.

Notes from the person: {self.notes or "none"}

TRANSCRIPT OF THE EDIT (index<TAB>start<TAB>word)
{words}

Reply with the reel.json object only.
"""
        last_err = None
        for attempt in range(2):
            p = prompt if not last_err else prompt + f"\n\nYour previous reel.json failed to build with this error, fix it:\n{last_err}\n"
            try:
                res = self.ask_claude(p, "plan")
            except NotSignedIn:
                (self.edit / "reel.json").write_text(json.dumps(spec, indent=2))
                self.state["plan"] = "skipped"; self.info["plan"] = SIGN_IN; return
            chosen = res.get("layout") or {}
            res.update({k: spec[k] for k in ("duration", "fps", "video", "format", "template", "brand") if k in spec})
            if self.brand and "for more" in json.dumps(res.get("endcard") or {}).lower():   # copied from the default brand example
                res["endcard"] = self.end
            if self.template == "clean":
                res.pop("takeovers", None)
            if self.fmt != "reel":
                res["layout"] = {**spec.get("layout", {}), **chosen}
            res.setdefault("captions", spec["captions"]); res.setdefault("cards", []); res.setdefault("sfx", [])
            (self.edit / "reel.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
            r = subprocess.run(["python3", str(self.skill / "scripts/build.py"), str(self.edit)], capture_output=True, text=True, env=self.env)
            if r.returncode == 0:
                tk = f", {len(res.get('takeovers') or [])} takeovers" if self.template == "takeover" else ""
                self.info["plan"] = f"{len(res['cards'])} cards{tk}, {len(res['captions'].get('keywords', []))} keywords"
                return
            last_err = (r.stdout + r.stderr)[-2000:]
            self.say(last_err)
        (self.edit / "reel.json").write_text(json.dumps(spec, indent=2))
        self.info["plan"] = "Claude's plan didn't build; started with captions only"

    def s_build(self):
        self.py("build.py", self.edit)
        self.info["build"] = "Ready to edit"

    # ------------------------------------------------------------ driver
    def start(self, from_step=None):
        if self.running:
            return False
        self.error = None; self.done = False; self.running = True
        names = [k for k, _ in STEPS]
        first = names.index(from_step) if from_step in names else 0
        for k in names[first:]:
            self.state[k] = "pending"

        def go():
            try:
                # cheap re-derivation of in-memory state when resuming mid-way
                if first > 0:
                    self.meta = {"raw_duration": self.probe(self.raw)[0], "fps": self.probe(self.raw)[1]}
                    if (self.work / "transcript.json").exists():
                        self.raw_words = json.loads((self.work / "transcript.json").read_text())
                    rj = self.work / "retakes.json"
                    self.remove = [tuple(x) for x in json.loads(rj.read_text()).get("remove", [])] if rj.exists() else []
                    if (self.edit / "base-edit.mp4").exists():
                        self.dur = self.probe(self.edit / "base-edit.mp4")[0]
                    if (self.edit / "transcript.json").exists():
                        self.words = json.loads((self.edit / "transcript.json").read_text())
                for k in names[first:]:
                    self.state[k] = "running"
                    getattr(self, "s_" + k)()
                    if self.state[k] == "running":
                        self.state[k] = "done"
                self.done = True
            except Exception as e:
                for k in names:
                    if self.state[k] == "running":
                        self.state[k] = "failed"
                self.error = str(e)
                self.say("ERROR: " + str(e))
            finally:
                self.running = False
        self.thread = workspace.Thread(target=go, daemon=True)
        self.thread.start()
        return True

    def status(self):
        return {"root": str(self.root), "edit": str(self.edit), "format": self.fmt, "template": self.template, "brand": self.brand, "running": self.running, "done": self.done, "error": self.error,
                "claude": bool(self.claude),
                "steps": [{"key": k, "label": l, "state": self.state[k], "info": self.info.get(k, "")} for k, l in STEPS],
                "log": self.log[-40:]}
