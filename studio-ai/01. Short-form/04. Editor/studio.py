"""AI studio (ROADMAP phase 6): build a clip from several videos with Claude, for the open video.

Per project (short-form or long-form: see Ctx), everything lives in <project>/studio/:
  media/<id>/   source.<ext> (the uploaded video), meta.json, transcript.json (whisper words), scenes.json,
                sheet.jpg (contact sheet: one thumbnail every `step` seconds, 6 across)
  clips/<id>/   plan.json (Claude's cut list), title-N.png (brand title cards), clip.mp4, thumb.jpg, job.json
Music for clips comes from the team library: <Studio AI>/05. Music/ (anyone can add files; the panel can upload too).

Routes (server.py calls handle(); an open project is needed):
  GET  /api/studio/state                media, clips, music library, the video's format and brand
  PUT  /api/studio/media?name=          add a video (raw body, copied); it's analysed once in the background
  POST /api/studio/media/pick           pick videos in Finder; they're linked, not copied (long-form)
  POST /api/studio/media/delete {id}
  POST /api/studio/ask {prompt, length, titles, music, base}   plan + build a clip (base = a clip id to change)
  GET  /api/studio/clip?id=             one clip's progress and result
  POST /api/studio/clip/delete {id}
  PUT  /api/studio/music?name=          add a music file to the team library
  POST /api/studio/overlay {id}         short-form: copy a finished clip into edit/assets/overlays; long-form: its path
Long-form reaches the same routes as /api/long/studio/…?root=<project> and /long/studio/…?root= (longform.py).
  GET  /studio/<path>                   files under studio/ (contact sheets, clips) and /studio/music/<file>
"""
import json, re, shutil, subprocess, threading, time, uuid

from pathlib import Path
from urllib.parse import unquote

import brandkit
import workspace          # whose storage this job works in (phase 7)
import osutil             # macOS / Windows differences (phase 8)
import claude_client

HERE = Path(__file__).resolve().parent
STUDIO = HERE.parent.parent
SKILL = None        # set by server.py


def music_dir():
    """The team's music library: <Studio AI>/05. Music on a Mac."""
    return workspace.current().music

ENV = None
settings = dict
FORMATS = {"reel": (1080, 1920), "feed": (1080, 1350), "square": (1080, 1080), "landscape": (1920, 1080)}
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".aac", ".aiff", ".flac"}
FPS = 30
XF = 0.25           # cross-fade between parts, seconds
jobs = {}           # "media:<id>" / "clip:<id>" -> job


def run(cmd, timeout=1800, cwd=None):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, env=ENV, timeout=timeout, cwd=cwd)
    if r.returncode:
        raise RuntimeError((r.stderr or r.stdout)[-600:])
    return r.stdout


def probe(f):
    d = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
                        "-of", "json", f]) or "{}")
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"dur": round(float(d.get("format", {}).get("duration") or 0), 2), "w": v.get("width"), "h": v.get("height"),
            "audio": any(s.get("codec_type") == "audio" for s in d.get("streams", []))}


def safe_name(name, fallback="file"):
    stem = re.sub(r"[^\w.-]+", "-", Path(name).stem).strip("-.")[:60] or fallback
    return stem, Path(name).suffix.lower()


# ---------------------------------------------------------------- media: analysed once
class MediaJob:
    def __init__(self, mdir):
        self.dir, self.state, self.step, self.error = Path(mdir), "running", "Waiting…", None

    def start(self):
        workspace.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            src = next(self.dir.glob("source.*"))
            meta = json.loads((self.dir / "meta.json").read_text())
            meta.update(probe(src)); (self.dir / "meta.json").write_text(json.dumps(meta, indent=1))
            dur = meta["dur"] or 1
            self.step = "Making the contact sheet…"
            step = max(1.0, round(dur / 30, 1))         # at most 30 thumbnails, 6 per row
            rows = max(1, min(5, -(-int(dur // step + 1) // 6)))
            run(["ffmpeg", "-v", "error", "-y", "-i", src, "-vf", f"fps=1/{step},scale=320:-2,tile=6x{rows}:padding=4:color=black",
                 "-frames:v", "1", "-q:v", "4", self.dir / "sheet.jpg"])
            run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(1.0, dur / 3):.2f}", "-i", src, "-frames:v", "1", "-vf", "scale=360:-2",
                 "-q:v", "4", self.dir / "thumb.jpg"])
            meta["sheet_step"] = step
            self.step = "Finding the scene changes…"
            out = subprocess.run(["ffmpeg", "-v", "info", "-i", str(src), "-vf", "scale=320:-2,select='gt(scene,0.3)',showinfo", "-an", "-f", "null", "-"],
                                 capture_output=True, text=True, env=ENV, timeout=1800).stderr
            scenes = [round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", out)]
            (self.dir / "scenes.json").write_text(json.dumps(scenes))
            if meta.get("audio"):
                self.step = "Transcribing…"
                run([osutil.NPX, "-y", "hyperframes@latest", "transcribe", src, "-d", self.dir, "-m", "medium.en", "-l", "en", "--engine", "whisper"], timeout=3600)
            if not (self.dir / "transcript.json").exists():
                (self.dir / "transcript.json").write_text("[]")
            meta["ready"] = True
            (self.dir / "meta.json").write_text(json.dumps(meta, indent=1))
            self.state, self.step = "done", "Ready"
        except Exception as e:
            self.state, self.error, self.step = "failed", str(e)[-300:], "Couldn't analyse it"


def media_list(sd):
    out = []
    for d in sorted((sd / "media").glob("*/meta.json"), key=lambda f: f.stat().st_ctime):
        m = json.loads(d.read_text()); mid = d.parent.name
        j = jobs.get(f"media:{mid}")
        words = json.loads((d.parent / "transcript.json").read_text()) if (d.parent / "transcript.json").exists() else []
        out.append({"id": mid, "name": m.get("name"), "dur": m.get("dur"), "w": m.get("w"), "h": m.get("h"), "audio": m.get("audio"),
                    "ready": bool(m.get("ready")), "words": len(words),
                    "state": "done" if m.get("ready") else (j.state if j else "failed"), "step": j.step if j else "",
                    "error": j.error if j else (None if m.get("ready") else "Stopped before it finished; delete and add it again")})
    return out


# ---------------------------------------------------------------- clips: Claude plans, ffmpeg builds
def sentences(words, gap=0.7):
    """Words -> [(start, end, text)] split at full stops and pauses (a compact transcript for Claude)."""
    out, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        if not nxt or re.search(r"[.!?]$", w["text"]) or nxt["start"] - w["end"] > gap:
            out.append((cur[0]["start"], cur[-1]["end"], " ".join(x["text"] for x in cur))); cur = []
    return out


def media_brief(sd, media):
    lines = []
    for m in media:
        d = sd / "media" / m["id"]
        meta = json.loads((d / "meta.json").read_text())
        scenes = json.loads((d / "scenes.json").read_text()) if (d / "scenes.json").exists() else []
        words = json.loads((d / "transcript.json").read_text()) if (d / "transcript.json").exists() else []
        sent = "\n".join(f"    {a:.2f}-{b:.2f}  {t}" for a, b, t in sentences(words)) or "    (no speech)"
        lines.append(f"""VIDEO "{m['id']}": {meta.get('name')} | {meta.get('dur')} s | {meta.get('w')}x{meta.get('h')} | {'has sound' if meta.get('audio') else 'no sound'}
  scene changes at (s): {', '.join(f'{s:.1f}' for s in scenes[:60]) or 'none'}
  contact sheet: media/{m['id']}/sheet.jpg (6 thumbnails per row, one every {meta.get('sheet_step')} s from 0, left to right then down)
  what is said (start-end s):
{sent}""")
    return "\n\n".join(lines)


def build_prompt(sd, media, req, fmt, bid, base_plan):
    W, H = FORMATS.get(fmt, FORMATS["reel"])
    voice = brandkit.voice_note(bid) if bid else ""
    change = f"""
THIS IS A CHANGE to a clip you made before. Its plan was:
{json.dumps(base_plan, indent=1)}
Keep what works and change it as asked.""" if base_plan else ""
    return f"""You are a video editor making a short clip from several source videos for {brandkit.display_name(bid)}.
The clip is {W}x{H} ({fmt}); the source videos are cropped to fill that frame. Target length: about {req['length']} s.
The person asked: "{req['prompt']}"
{voice}
{change}
SOURCE VIDEOS (read the contact sheets with the Read tool to see what each video shows):

{media_brief(sd, media)}

How to cut:
- A part is [source video, in, out] in that video's own seconds. Start and end parts on sentence boundaries or scene
  changes so nobody is cut off mid-word; never go past a video's length. Parts can be very short (0.6 s) for pace.
- The clip plays the parts in order, with a short cross-fade between them. Their total should be close to the target.
- Use the strongest moments: hooks, results, emotion, testimonials. Vary the sources unless asked otherwise.
{"- Title cards: add 1-3 short ones (2-6 words, in the brand's voice) where they help: an opening line, a section, the ending." if req.get('titles') else "- No title cards."}

Reply with JSON only:
{{"title": "a name for this clip", "summary": "2-3 sentences: what you made and why",
  "parts": [{{"video": "<id>", "in": 0.0, "out": 3.2, "why": "short reason"}}],
  "titles": [{{"before": 0, "kicker": "optional small line", "text": "Title card text", "dur": 1.6}}]}}
("before": the title card plays before that part number, 0 = at the start; use the number of parts for the very end.)
"""


def clean_plan(plan, sd, media):
    """Keep only parts that exist and fit inside their videos; clamp title cards."""
    durs = {m["id"]: float(m["dur"] or 0) for m in media}
    parts = []
    for p in plan.get("parts") or []:
        v = p.get("video")
        if v not in durs:
            continue
        a = max(0.0, float(p.get("in", 0))); b = min(durs[v], float(p.get("out", 0)))
        if b - a >= 0.5:
            parts.append({"video": v, "in": round(a, 2), "out": round(b, 2), "why": p.get("why", "")})
    if not parts:
        raise RuntimeError("Claude's plan had no usable parts")
    titles = []
    for t in plan.get("titles") or []:
        if (t.get("text") or "").strip():
            titles.append({"before": max(0, min(len(parts), int(t.get("before", 0)))), "kicker": (t.get("kicker") or "").strip(),
                           "text": t["text"].strip(), "dur": max(1.0, min(3.0, float(t.get("dur", 1.6))))})
    return {"title": plan.get("title") or "AI clip", "summary": plan.get("summary") or "", "parts": parts, "titles": titles}


# ---------------------------------------------------------------- title cards (brand style, drawn by Chrome)
_chrome = None


def chrome():
    global _chrome
    if not _chrome:
        out = subprocess.run([osutil.NPX, "-y", "hyperframes@latest", "browser", "path"], capture_output=True, text=True, env=ENV).stdout
        _chrome = (out.strip().splitlines() or [""])[-1].strip()
        if not Path(_chrome).exists():
            raise RuntimeError("Couldn't find the render browser (run: npx hyperframes browser ensure)")
    return _chrome


def title_html(t, W, H, bid):
    kit = brandkit.client(bid)
    tpl = SKILL / "template/assets"
    if kit:
        col, kd = kit.get("colors", {}), brandkit.kit_dir(kit["id"])
        P = col.get("primary", "#2563eb"); base = col.get("takeover_bg", brandkit.mix(P, "#000000", 0.55))
        bgimg = (kit.get("images") or {}).get("background")
        bg = f'url("{(kd / bgimg).as_uri()}") center / cover' if bgimg and (kd / bgimg).exists() else \
            f"linear-gradient(160deg, {base} 0%, {brandkit.mix(base, P, 0.45)} 65%, {P} 130%)"
        kick = col.get("kicker", brandkit.mix(col.get("accent", P), "#ffffff", 0.45))
        files = [f for f in ((kit.get("fonts") or {}).get("display") or {}).get("files", []) if (kd / f["file"]).exists()]
        face = "".join(f'@font-face{{font-family:T;src:url("{(kd / f["file"]).as_uri()}");font-weight:{f.get("weight", 700)}}}' for f in files)
        fam = "T, 'Helvetica Neue', Arial" if files else "'Helvetica Neue', Arial"
    else:   # your brand
        bg = f'url("{(tpl / "brand/end-bg.jpg").as_uri()}") center / cover'
        kick = "#a5f3fc"
        face = "".join(f'@font-face{{font-family:T;src:url("{(tpl / "fonts" / f).as_uri()}");font-weight:{w}}}'
                       for f, w in (("Display-Bold.ttf", 700), ("Display-ExtraBold.ttf", 800)))
        fam = "T"
    n = len(t["text"])
    size = round(min(W, H) * (0.14 if n <= 14 else 0.115 if n <= 26 else 0.09))   # big and readable on a phone
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;")
    return f"""<!doctype html><meta charset="utf-8"><style>{face}
html,body{{margin:0;width:{W}px;height:{H}px;overflow:hidden;background:{bg};}}
.c{{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:0 {round(W * 0.09)}px;color:#fff;font-family:{fam};}}
.k{{font-weight:700;font-size:{round(size * 0.3)}px;letter-spacing:.18em;text-transform:uppercase;color:{kick};margin-bottom:{round(size * 0.35)}px}}
.t{{font-weight:800;font-size:{size}px;line-height:1.04;letter-spacing:-.02em;text-shadow:0 6px 40px rgba(0,0,0,.35)}}
</style><div class="c">{f'<div class="k">{esc(t["kicker"])}</div>' if t.get("kicker") else ""}<div class="t">{esc(t["text"])}</div></div>"""


def draw_title(t, W, H, bid, out):
    html = out.with_suffix(".html"); html.write_text(title_html(t, W, H, bid))
    run([chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1", "--allow-file-access-from-files",
         f"--window-size={W},{H}", "--virtual-time-budget=2000", f"--screenshot={out}", html.as_uri()], timeout=120)
    if not out.exists():
        raise RuntimeError("A title card didn't draw")


# ---------------------------------------------------------------- the render
def render(sd, cdir, plan, fmt, music, enc_soft):
    W, H = FORMATS.get(fmt, FORMATS["reel"])
    seq = []                         # in order: ("video", part) / ("title", png, dur)
    for i in range(len(plan["parts"]) + 1):
        for n, t in enumerate(plan["titles"]):
            if t["before"] == i:
                seq.append(("title", t["png"], t["dur"]))
        if i < len(plan["parts"]):
            seq.append(("video", plan["parts"][i]))
    inputs, g, lens = [], [], []
    for k, s in enumerate(seq):
        if s[0] == "video":
            p = s[1]; src = next((sd / "media" / p["video"]).glob("source.*"))
            meta = json.loads((sd / "media" / p["video"] / "meta.json").read_text())
            L = p["out"] - p["in"]
            inputs += ["-ss", f"{p['in']:.3f}", "-t", f"{L:.3f}", "-i", str(src)]
            g.append(f"[{k}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{k}]")
            g.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,asetpts=PTS-STARTPTS,apad=whole_dur={L:.3f},atrim=0:{L:.3f}[a{k}]"
                     if meta.get("audio") else f"aevalsrc=0:c=stereo:s=48000:d={L:.3f}[a{k}]")
        else:
            L = s[2]
            inputs += ["-loop", "1", "-t", f"{L:.3f}", "-i", str(s[1])]
            g.append(f"[{k}:v]scale={W}:{H},setsar=1,fps={FPS},format=yuv420p,setpts=PTS-STARTPTS[v{k}]")
            g.append(f"aevalsrc=0:c=stereo:s=48000:d={L:.3f}[a{k}]")
        lens.append(L)
    # cross-fade chain: each join shortens the clip by XF (skipped when a part is too short to fade)
    cv, ca, total = "v0", "a0", lens[0]
    for k in range(1, len(seq)):
        d = XF if min(lens[k - 1], lens[k]) > 2.5 * XF else 0.04
        g.append(f"[{cv}][v{k}]xfade=transition=fade:duration={d}:offset={total - d:.3f}[xv{k}]")
        g.append(f"[{ca}][a{k}]acrossfade=d={d}[xa{k}]")
        cv, ca, total = f"xv{k}", f"xa{k}", total - d + lens[k]
    if music:
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        mk = len(seq)
        g.append(f"[{ca}]asplit[sp][key]")
        g.append(f"[{mk}:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{total:.3f},volume=0.5,"
                 f"afade=t=in:d=0.6,afade=t=out:st={max(0, total - 1.5):.3f}:d=1.5[mus]")
        g.append("[mus][key]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[duck]")   # music dips under speech
        g.append("[sp][duck]amix=inputs=2:duration=first:normalize=0[mix]")
        ca = "mix"
    g.append(f"[{ca}]loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[aout]")
    (cdir / "filter.txt").write_text(";\n".join(g))
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "19"] if enc_soft else ["-c:v", "h264_videotoolbox", "-b:v", "12M"]
    out = cdir / "clip.mp4"
    run(["ffmpeg", "-v", "error", "-y", *inputs, "-/filter_complex", cdir / "filter.txt", "-map", f"[{cv}]", "-map", "[aout]",
         *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{total:.3f}", "-movflags", "+faststart", out], timeout=3600)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{min(1.0, total / 3):.2f}", "-i", out, "-frames:v", "1", "-vf", "scale=360:-2", "-q:v", "4", cdir / "thumb.jpg"])
    return round(total, 2)


class ClipJob:
    def __init__(self, sd, cid, req, fmt, bid, creds=None):
        self.sd, self.cid, self.req, self.fmt, self.bid, self.creds = sd, cid, req, fmt, bid, creds
        self.dir = sd / "clips" / cid
        self.state, self.step, self.error, self.started = "running", "Starting…", None, time.time()

    def save(self, **extra):
        j = {"id": self.cid, "req": self.req, "fmt": self.fmt, "brand": self.bid, "state": self.state, "step": self.step,
             "error": self.error, "created": self.started, **extra}
        old = json.loads((self.dir / "job.json").read_text()) if (self.dir / "job.json").exists() else {}
        (self.dir / "job.json").write_text(json.dumps({**old, **j}, indent=1))

    def start(self):
        self.dir.mkdir(parents=True, exist_ok=True); self.save()
        workspace.Thread(target=self.run, daemon=True).start()

    def run(self):
        try:
            media = [m for m in media_list(self.sd) if m["ready"] and (not self.req.get("media") or m["id"] in self.req["media"])]
            if not media:
                raise RuntimeError("Add a video to the bin first (and wait until it's analysed)")
            base = None
            if self.req.get("base"):
                bp = self.sd / "clips" / self.req["base"] / "plan.json"
                base = json.loads(bp.read_text()) if bp.exists() else None
            self.step = "Claude is watching the videos…"; self.save()
            sheets = [self.sd / "media" / m["id"] / "sheet.jpg" for m in media]     # attached for the API back end
            plan = clean_plan(claude_client.ask_json(self.creds, build_prompt(self.sd, media, self.req, self.fmt, self.bid, base),
                                                     cwd=self.sd, tools="Read,Glob", files=sheets, env=ENV, timeout=900,
                                                     what="clip plan"), self.sd, media)
            W, H = FORMATS.get(self.fmt, FORMATS["reel"])
            for n, t in enumerate(plan["titles"]):
                self.step = f"Drawing title card {n + 1} of {len(plan['titles'])}…"; self.save()
                t["png"] = str(self.dir / f"title-{n}.png")
                draw_title(t, W, H, self.bid, Path(t["png"]))
            (self.dir / "plan.json").write_text(json.dumps(plan, indent=1))
            self.step = "Building the clip…"; self.save(plan=plan)
            music = None
            if self.req.get("music"):
                music = music_dir() / Path(self.req["music"]).name
                if not music.exists():
                    raise RuntimeError(f"The music file {music.name} isn't in 05. Music any more")
            dur = render(self.sd, self.dir, plan, self.fmt, music, settings().get("software_encode"))
            self.state, self.step = "done", "Ready"; self.save(plan=plan, dur=dur)
        except Exception as e:
            self.state, self.error, self.step = "failed", str(e)[-500:], "Stopped"; self.save()


def clip_list(sd):
    out = []
    for f in sorted((sd / "clips").glob("*/job.json"), key=lambda f: -f.stat().st_ctime):
        j = json.loads(f.read_text()); live = jobs.get(f"clip:{j['id']}")
        if live:
            j.update(state=live.state, step=live.step, error=live.error)
        elif j.get("state") == "running":
            j.update(state="failed", error="Stopped when the editor was restarted")
        out.append(j)
    return out


# ---------------------------------------------------------------- routes
def read_body_to(h, dest, limit=8 * 1024 ** 3):
    left = int(h.headers.get("Content-Length", 0))
    if left > limit:
        raise ValueError("That file is too big")
    with open(dest, "wb") as f:
        while left > 0:
            chunk = h.rfile.read(min(1 << 20, left))
            if not chunk:
                break
            f.write(chunk); left -= len(chunk)
    if left > 0:
        dest.unlink(missing_ok=True); raise ValueError("The upload was cut short")


class Ctx:
    """The open project, short-form or long-form: where studio/ lives, its spec, its format."""
    def __init__(self, root, spec_file, kind, edit=None):
        self.root, self.spec_file, self.kind, self.edit = Path(root), Path(spec_file), kind, edit
        self.sd = self.root / "studio"

    @property
    def spec(self):
        try:
            return json.loads(self.spec_file.read_text())
        except (OSError, ValueError):
            return {}

    @property
    def fmt(self):
        return "landscape" if self.kind == "long" else self.spec.get("format", "reel")


def short_ctx(edit):
    return Ctx(Path(edit).parent, Path(edit) / "reel.json", "short", Path(edit)) if edit else None


def long_ctx(root):
    return Ctx(root, Path(root) / "longform.json", "long") if root else None


def finder_pick_videos():
    """Pick one or more videos in Finder (they're linked, not copied: long recordings are big)."""
    return osutil.pick_files("Choose videos for the AI studio (they are linked, not copied)", "video", multiple=True)


def add_media(sd, name, place):
    """A new media folder; place(dest_without_suffix) puts the video in it. Starts the analysis."""
    stem, ext = safe_name(name, "video")
    if ext not in VIDEO_EXT:
        raise ValueError(f"{name} doesn't look like a video file")
    mid = uuid.uuid4().hex[:8]; mdir = sd / "media" / mid; mdir.mkdir(parents=True)
    place(mdir / f"source{ext}")
    (mdir / "meta.json").write_text(json.dumps({"name": stem, "added": time.time()}))
    j = MediaJob(mdir); jobs[f"media:{mid}"] = j; j.start()
    return mid


def handle(h, method, path, q, ctx):
    try:
        return _handle(h, method, path, q, ctx)
    except (ValueError, KeyError, FileNotFoundError, StopIteration) as e:
        h.send_json({"error": str(e) or "Not found"}, 400); return True
    except (OSError, RuntimeError) as e:
        h.send_json({"error": str(e)}, 500); return True


def _handle(h, method, path, q, ctx):
    # the music library is shared by every project
    if path.startswith("/studio/music/"):
        h.send_file(music_dir() / Path(unquote(path[len("/studio/music/"):])).name, cache="no-cache"); return True
    if method == "PUT" and path == "/api/studio/music":
        stem, ext = safe_name(unquote(q.get("name", ["music.mp3"])[0]), "music")
        if ext not in AUDIO_EXT:
            raise ValueError("Use an MP3, M4A, WAV, AAC, AIFF or FLAC file")
        music_dir().mkdir(parents=True, exist_ok=True)
        read_body_to(h, music_dir() / f"{stem}{ext}", 500 * 1024 ** 2)
        h.send_json({"name": f"{stem}{ext}"}); return True
    if ctx is None:
        h.send_json({"error": "Open a video first"}, 409); return True
    sd = ctx.sd
    if method == "GET" and path.startswith("/studio/"):
        f = (sd / unquote(path[len("/studio/"):])).resolve()
        h.send_file(f if sd.resolve() in f.parents and "source." not in f.name else None, cache="no-cache"); return True
    if method == "GET" and path == "/api/studio/state":
        spec = ctx.spec
        music = sorted(p.name for p in music_dir().glob("*") if p.suffix.lower() in AUDIO_EXT) if music_dir().exists() else []
        h.send_json({"media": media_list(sd), "clips": clip_list(sd), "music": music, "format": ctx.fmt, "kind": ctx.kind,
                     "brand": spec.get("brand") or brandkit.DEFAULT, "brand_name": brandkit.display_name(spec.get("brand"))}); return True
    if method == "GET" and path == "/api/studio/clip":
        cid = q.get("id", [""])[0]
        h.send_json(next((c for c in clip_list(sd) if c["id"] == cid), {"error": "No such clip"})); return True
    if method == "PUT" and path == "/api/studio/media":                         # uploaded (copied): short-form
        mid = add_media(sd, unquote(q.get("name", ["video.mp4"])[0]), lambda dest: read_body_to(h, dest))
        h.send_json({"id": mid}); return True
    if method != "POST":
        return False
    b = h.body()
    if path == "/api/studio/media/add":                                         # uploaded with /api/upload (resumable): the portal
        import uploads
        mid = add_media(sd, b.get("name") or "video.mp4", lambda dest: uploads.take(b["upload"], dest.parent, dest.name))
        h.send_json({"id": mid}); return True
    if path == "/api/studio/media/pick":                                        # picked in Finder (linked): long-form
        if workspace.PORTAL:
            raise ValueError("Upload the videos (there's no Finder on the portal)")
        ids = [add_media(sd, Path(f).name, lambda dest, f=f: osutil.link(Path(f), dest, copy_ok=True)) for f in finder_pick_videos()]
        h.send_json({"ids": ids}); return True
    if path == "/api/studio/media/delete":
        d = sd / "media" / re.sub(r"[^a-f0-9]", "", b["id"])
        shutil.rmtree(d, ignore_errors=True); h.send_json({"ok": True}); return True   # a linked video itself is never touched
    if path == "/api/studio/clip/delete":
        d = sd / "clips" / re.sub(r"[^a-f0-9]", "", b["id"])
        shutil.rmtree(d, ignore_errors=True); h.send_json({"ok": True}); return True
    if path == "/api/studio/ask":
        prompt = (b.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("Say what to make")
        req = {"prompt": prompt, "length": max(5, min(180, float(b.get("length") or 20))), "titles": bool(b.get("titles", True)),
               "music": b.get("music") or None, "base": b.get("base") or None, "media": b.get("media") or None}
        cid = uuid.uuid4().hex[:8]
        j = ClipJob(sd, cid, req, ctx.fmt, ctx.spec.get("brand"), claude_client.creds_from(h.headers, settings()))
        jobs[f"clip:{cid}"] = j; j.start()
        h.send_json({"id": cid}); return True
    if path == "/api/studio/overlay":
        c = sd / "clips" / re.sub(r"[^a-f0-9]", "", b["id"])
        if not (c / "clip.mp4").exists():
            raise ValueError("That clip isn't finished")
        title = json.loads((c / "plan.json").read_text()).get("title", "AI clip")
        if ctx.kind == "long":                                                  # long-form links overlay files where they are
            info = probe(c / "clip.mp4")
            h.send_json({"ok": True, "src": str(c / "clip.mp4"), "name": title, "audio": info["audio"], "dur": info["dur"],
                         "w": info["w"], "h": info["h"]}); return True
        dest = ctx.edit / "assets" / "overlays"; dest.mkdir(parents=True, exist_ok=True)
        name = f"ai-clip-{c.name}.mp4"; shutil.copy2(c / "clip.mp4", dest / name)
        info = probe(dest / name)
        h.send_json({"ok": True, "src": f"assets/overlays/{name}", "name": title,
                     "audio": info["audio"], "dur": info["dur"], "w": info["w"], "h": info["h"]}); return True
    return False
