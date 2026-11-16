"""Long-form render: longform.json + the camera file -> one MP4 (and chapters.txt next to it).

Rendering a whole hour frame by frame in a browser would take hours, so the work is split:
  graphics  headless Chrome draws each lower-third, card and the end screen as transparent PNG frames, and one small PNG per
            highlighted caption word, using the same overlays.css / overlays.js as the editor (render_overlays.cjs).
  video     ONE ffmpeg pass: keeps the kept segments of the camera file (the cut list), scales to 1920x1080, lays all the
            graphics over it at their times, appends the end screen, and encodes (VideoToolbox, or x264 as a fallback).
Everything drawn is cached in work/render/, so a re-render only redraws what changed, and a stopped render picks up again.
A "preview" renders about a minute from any point, which is how to check the look before a full render.
Python 3.9 standard library only.
"""
import hashlib, json, os, re, shutil, subprocess, threading, time
from pathlib import Path
import sys

import osutil                      # 01. Short-form/04. Editor (loaded by longform.py): macOS / Windows differences
try:
    from workspace import Thread   # Studio AI: the render keeps the workspace (portal user) it was started in
except ImportError:
    from threading import Thread

# Studio AI brand kits (03. Brands/brandkit.py); without it every video uses the default look
try:
    sys.path.append(str(Path(__file__).resolve().parent.parent.parent / "03. Brands"))
    import brandkit
except ImportError:
    brandkit = None

STEPS = [
    ("prepare", "Prepare the plan"),
    ("graphics", "Draw lower-thirds, cards and the end screen"),
    ("captions", "Draw the captions"),
    ("video", "Render the video"),
    ("finish", "Save the video"),
]
FPS = 30


def renders_dir(base, brand=None):
    """06. Renders/Long-form 16x9 for the default brand; 06. Renders/<Client>/Long-form 16x9 for a client brand."""
    client = brandkit.folder_name(brand) if brandkit and brand else None
    return Path(base) / "06. Renders" / (client or "") / "Long-form 16x9"
W, H = 1920, 1080


def find_puppeteer():
    """A node_modules folder that holds puppeteer-core (hyperframes brings it); installs one into the cache if there is none."""
    for d in sorted((Path.home() / ".npm/_npx").glob("*/node_modules"), key=lambda p: -p.stat().st_mtime):
        if (d / "puppeteer-core").is_dir():
            return d
    prefix = Path.home() / ".cache/studio-longform"
    if (prefix / "node_modules/puppeteer-core").is_dir():
        return prefix / "node_modules"
    return None


def dir_hash(*parts):
    h = hashlib.md5()
    for p in parts:
        h.update(p if isinstance(p, bytes) else str(p).encode())
    return h.hexdigest()[:10]


class RenderJob:
    def __init__(self, root, here, base, skill, env, settings, mode="preview", t0=0.0, length=60.0):
        self.root, self.here, self.base, self.skill, self.env, self.settings = Path(root), Path(here), Path(base), Path(skill), env, settings
        self.mode, self.t0, self.length = mode, float(t0), float(length)
        self.work = self.root / "work" / "render"
        self.state = {k: "pending" for k, _ in STEPS}
        self.info, self.log, self.error = {}, [], None
        self.done = self.running = False
        self.pct, self.output, self.chapters_out = 0.0, None, None
        self.proc = None
        self.stopped = False
        self.started = None
        self.thread = None

    def say(self, line):
        parts = [x.strip() for x in re.split(r"\x1b\[[0-9;?]*[A-Za-z]|\r", line) if x.strip()]
        if parts:
            self.log.append(parts[-1]); del self.log[:-300]

    def popen(self, cmd, **kw):
        self.say("$ " + " ".join(str(c) for c in cmd)[:300])
        self.proc = subprocess.Popen([str(c) for c in cmd], env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1, **kw)
        return self.proc

    # ------------------------------------------------------------ steps
    def s_prepare(self):
        self.work.mkdir(parents=True, exist_ok=True)
        self.spec = json.loads((self.root / "longform.json").read_text())
        self.meta = json.loads((self.root / "project.json").read_text())
        self.segs = json.loads((self.root / "work/edl.json").read_text())["segments"]
        self.words = json.loads((self.root / "work/words-edit.json").read_text())
        self.raw = self.meta["raw"]
        if not Path(self.raw).exists():
            raise RuntimeError(f"The camera file isn't there any more: {self.raw}")
        total = self.spec["duration"]
        if self.mode == "preview":
            self.w0 = max(0.0, min(self.t0, total - 1.0)); self.w1 = min(total, self.w0 + self.length)
        else:
            self.w0, self.w1 = 0.0, total
        self.out_dur = self.w1 - self.w0 + (self.spec["endcard"]["duration"] if self.mode == "full" and self.spec.get("endcard") else 0)
        # kept camera ranges (raw time) inside the window, in order; inserts (Studio AI: segments with "src") are pieces
        # of other files that play between them
        keep, pieces, o = [], [], 0.0
        for s in self.segs:
            a, b = o, o + s["out"] - s["in"]; o = b
            lo, hi = max(a, self.w0), min(b, self.w1)
            if hi - lo > 1e-3:
                piece = (s["in"] + (lo - a), s["in"] + (hi - a))
                if s.get("src"):
                    f = Path(s["src"]).expanduser(); f = f if f.is_absolute() else self.root / f
                    if not f.exists():
                        raise RuntimeError(f"An inserted clip isn't there any more: {s['src']}")
                    pieces.append(("ins", str(f)) + piece)
                else:
                    keep.append(piece); pieces.append(("cam",) + piece)
        if not pieces:
            raise RuntimeError("Nothing to render in that range")
        self.keep, self.pieces = keep, pieces
        # fonts, css and js for the stage page
        st = self.work / "stage"
        (st / "fonts").mkdir(parents=True, exist_ok=True)
        for f in (self.skill / "template/assets/fonts").glob("*"):
            shutil.copy(f, st / "fonts" / f.name)
        if (self.skill / "template/assets/brand/logo-white.svg").exists():
            shutil.copy(self.skill / "template/assets/brand/logo-white.svg", st / "logo.svg")
        for f in ("overlays.css", "overlays.js", "render-stage.html"):
            shutil.copy(self.here / "app" / f, st / f)
        # a client brand: its fonts, logo and background go into stage/brand/, its colours onto .ov-root
        bid = self.spec.get("brand") or "default"
        self.brand_logo = None
        kit = brandkit.client(bid) if brandkit else None   # None also when the kit was deleted: default look
        if kit:
            shutil.rmtree(st / "brand", ignore_errors=True)
            for rel in brandkit.long_files(kit):
                (st / "brand" / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(brandkit.kit_dir(bid) / rel, st / "brand" / rel)
            with open(st / "overlays.css", "a") as fh:
                fh.write("\n" + brandkit.long_css(kit, "brand/") + "\n")
            light = (kit.get("logos") or {}).get("light")
            self.brand_logo = f"brand/{light}" if light and (st / "brand" / light).exists() else ""
        self.stage = st / "render-stage.html"
        self.style_hash = dir_hash((st / "overlays.css").read_bytes(), (st / "overlays.js").read_bytes())
        mm = int(self.out_dur // 60)
        self.info["prepare"] = f"{'Preview' if self.mode == 'preview' else 'Full video'}: {mm} min {int(self.out_dur % 60)} s, {len(keep)} camera pieces"

    def items(self):
        out, w0, w1 = [], self.w0, self.w1
        for i, x in enumerate(self.spec.get("lowerThirds", [])):
            if x["t"] < w1 and x["t"] + x["dur"] > w0:
                out.append({"id": f"lt-{i}", "kind": "lt", "item": x, "dur": x["dur"], "t": x["t"]})
        for i, x in enumerate(self.spec.get("cards", [])):
            if x["t"] < w1 and x["t"] + x["dur"] > w0:
                out.append({"id": f"cd-{i}", "kind": "card", "item": x, "dur": x["dur"], "t": x["t"]})
        for it in out:
            it["hash"] = dir_hash(json.dumps(it["item"], sort_keys=True), self.style_hash)
        if self.mode == "full" and self.spec.get("endcard"):
            e = dict(self.spec["endcard"]); e["logo"] = "logo.svg" if self.brand_logo is None else self.brand_logo
            out.append({"id": "end", "kind": "end", "item": e, "dur": e["duration"], "t": self.spec["duration"], "hash": dir_hash(json.dumps(e, sort_keys=True), self.style_hash)})
        return out

    def _drive_node(self, job, on_line):
        pup = find_puppeteer()
        if not pup:
            self.say("Installing the drawing tool (puppeteer-core), once…")
            prefix = Path.home() / ".cache/studio-longform"; prefix.mkdir(parents=True, exist_ok=True)
            r = subprocess.run(["npm", "install", "--prefix", str(prefix), "puppeteer-core", "--no-audit", "--no-fund"], env=self.env, capture_output=True, text=True)
            self.say((r.stdout + r.stderr)[-300:])
            pup = find_puppeteer()
            if not pup:
                raise RuntimeError("Couldn't set up puppeteer-core (needed to draw the graphics). Is Node installed?")
        r = subprocess.run([osutil.NPX, "-y", "hyperframes@latest", "browser", "path"], env=self.env, capture_output=True, text=True)
        chrome = (r.stdout.strip().splitlines() or [""])[-1].strip()
        if not chrome or not Path(chrome).exists():
            subprocess.run([osutil.NPX, "-y", "hyperframes@latest", "browser", "ensure"], env=self.env, capture_output=True, text=True)
            r = subprocess.run([osutil.NPX, "-y", "hyperframes@latest", "browser", "path"], env=self.env, capture_output=True, text=True)
            chrome = (r.stdout.strip().splitlines() or [""])[-1].strip()
        if not chrome or not Path(chrome).exists():
            raise RuntimeError("No Chrome found to draw the graphics. Run: npx hyperframes browser ensure")
        job.update(chrome=chrome, stage=str(self.stage), out=str(self.work / "gfx"), fps=FPS)
        (self.work / "gfx").mkdir(exist_ok=True)
        jf = self.work / "job.json"; jf.write_text(json.dumps(job))
        self.say("$ node render_overlays.cjs")
        p = subprocess.Popen(["node", str(self.here / "render_overlays.cjs"), str(jf)], env=dict(self.env, NODE_PATH=str(pup)), text=True,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1)
        self.proc = p
        for line in p.stdout:
            if self.stopped:
                osutil.kill_tree(p); raise RuntimeError("Stopped")
            line = line.strip()
            if line.startswith("{"):
                try:
                    on_line(json.loads(line)); continue
                except ValueError:
                    pass
            self.say(line)
        if p.wait() != 0:
            raise RuntimeError("Drawing the graphics failed (see Details)")

    def s_graphics(self):
        its = self.items()
        self.its = its
        if not its:
            self.state["graphics"] = "skipped"; self.info["graphics"] = "No lower-thirds or cards in this range"; return
        n = [0]
        def on(o):
            if "done" in o and o["done"] != "cap":
                n[0] += 1; self.info["graphics"] = f"{n[0]} of {len(its)}"
        self._drive_node({"items": [{k: v for k, v in it.items() if k != "t"} for it in its]}, on)
        self.info["graphics"] = f"{len(its)} drawn"

    def cap_conf(self):
        c = self.spec.get("captions") or {}
        return int(c.get("size", 54)), int(c.get("bottom", 120))

    def s_captions(self):
        c = self.spec.get("captions") or {}
        if not c.get("on") or not self.words:
            self.state["captions"] = "skipped"; self.info["captions"] = "Captions are off" if not c.get("on") else "No words"; self.cap = None; return
        size, bottom = self.cap_conf()
        sig = dir_hash(json.dumps([w["text"] for w in self.words]), size, bottom, self.style_hash)
        self.cap_dir = f"cap-{sig}"
        idx = [i for i, w in enumerate(self.words) if w["end"] > self.w0 - 1 and w["start"] < self.w1 + 1]
        cdir = self.work / "gfx" / self.cap_dir
        self.cap = {"dir": self.cap_dir, "size": size, "bottom": bottom, "words": [{"text": w["text"]} for w in self.words], "indices": idx}
        todo = sum(1 for i in idx if not (cdir / f"{i}.png").exists())
        if not todo and (cdir / "blank.png").exists():
            self.info["captions"] = f"{len(idx)} words (already drawn)"; self._cap_files(); return
        def on(o):
            if o.get("done") == "cap":
                self.info["captions"] = f"{o['n']} of {o['of']} words"
        self._drive_node({"items": [], "captions": self.cap}, on)
        self.info["captions"] = f"{len(idx)} words"
        self._cap_files()

    def _cap_files(self):
        """The ffmpeg list for the captions: a PNG per word state, a blank between."""
        cdir = (self.work / "gfx" / self.cap_dir).resolve()
        W_ = self.words; n = len(W_); lines, cur = [], 0.0
        def add(f, d):
            lines.append(f"file '{cdir / f}'"); lines.append(f"duration {d:.5f}")
        for i, w in enumerate(W_):
            nxt = W_[i + 1]["start"] if i + 1 < n else 1e9
            e = nxt if nxt < w["end"] + 0.6 else w["end"] + 0.6
            if e <= self.w0 or w["start"] >= self.w1:
                continue
            s, e = max(w["start"], self.w0) - self.w0, min(e, self.w1) - self.w0
            s = max(s, cur)
            if e - s < 0.002:
                continue
            if s - cur > 0.002:
                add("blank.png", s - cur)
            add(f"{i}.png", e - s); cur = e
        if not lines:
            self.cap = None; return
        lines.append(lines[-2])
        (self.work / "captions.txt").write_text("\n".join(lines) + "\n")

    @staticmethod
    def rd_expr(keys, axis, start, hi):
        """Position of a blur region over time: linear between its points, as an ffmpeg expression of t (seconds since the window start)."""
        pts = []
        for k in sorted(keys, key=lambda k: k["dt"]):
            v = max(0, min(int(hi), int(k[axis])))
            if pts and k["dt"] - pts[-1][0] < 0.05:
                continue
            pts.append((float(k["dt"]), v))
        if len(pts) == 1:
            return str(pts[0][1])
        e = str(pts[-1][1])
        for (d0, v0), (d1, v1) in reversed(list(zip(pts, pts[1:]))):
            e = f"if(lt(TT,{d1:.3f}),{v0}+({v1}-{v0})*(TT-{d0:.3f})/{d1 - d0:.3f},{e})"
        e = f"if(lt(TT,{pts[0][0]:.3f}),{pts[0][1]},{e})"
        return e.replace("TT", f"(t-{start:.3f})")

    def rgba_frames(self, folder):
        """Chrome saves fully opaque frames (an end screen, the end of a fade) as RGB PNGs. Turn them into RGBA like the rest,
        so ffmpeg sees one pixel format all the way through (see overlay() in s_video)."""
        for f in Path(folder).glob("*.png"):
            with open(f, "rb") as fh:
                head = fh.read(26)
            if len(head) == 26 and head[25] != 6:          # PNG IHDR colour type: 6 = RGBA
                tmp = f.with_suffix(".rgba.png")
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-pix_fmt", "rgba", str(tmp)], env=self.env, check=True)
                tmp.replace(f)

    def filter_arg(self, f):
        """ffmpeg 7 replaced -filter_complex_script with -/filter_complex."""
        r = subprocess.run(["ffmpeg", "-hide_banner", "-h", "full"], capture_output=True, text=True, env=self.env).stdout
        return ["-filter_complex_script", str(f)] if "filter_complex_script" in r else ["-/filter_complex", str(f)]

    def joined_graph(self, ss, end_d, inputs):
        """[v0] and [aout] when the cut list has inserts: each run of camera parts is one select on the camera file (a
        split of input 0), each insert is its own input (-ss/-t), all brought to the same size, rate and sound format,
        then concatenated in order. Returns (graph, next free input index)."""
        groups = []
        for p in self.pieces:
            if p[0] == "cam" and groups and groups[-1][0] == "cam":
                groups[-1][1].append(p[1:])
            else:
                groups.append(("cam", [p[1:]]) if p[0] == "cam" else p)
        ncam = sum(1 for g in groups if g[0] == "cam")
        common = (f"scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,"
                  f"setsar=1,fps={FPS},format=yuv420p")
        AF = "aformat=sample_rates=48000:channel_layouts=stereo"
        g = []
        if ncam:
            g.append(f"[0:v]split={ncam}" + "".join(f"[cv{j}]" for j in range(ncam)))
            g.append(f"[0:a]asplit={ncam}" + "".join(f"[ca{j}]" for j in range(ncam)))
        k, j, outs = 1, 0, ""
        for n, grp in enumerate(groups):
            if grp[0] == "cam":
                sel = "+".join(f"gte(t,{a - ss:.3f})*lt(t,{b - ss:.3f})" for a, b in grp[1])
                g.append(f"[cv{j}]select='{sel}',setpts=N/FRAME_RATE/TB,{common}[pv{n}]")
                g.append(f"[ca{j}]aselect='{sel}',asetpts=N/SR/TB,{AF}[pa{n}]")
                j += 1
            else:
                _, f, a, b = grp; L = b - a
                inputs.extend(["-ss", f"{a:.3f}", "-t", f"{L:.3f}", "-i", f])
                g.append(f"[{k}:v]setpts=PTS-STARTPTS,{common}[pv{n}]")
                sound = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", f],
                                       capture_output=True, text=True, env=self.env).stdout.strip()
                g.append(f"[{k}:a]{AF},asetpts=PTS-STARTPTS,apad=whole_dur={L:.3f},atrim=0:{L:.3f}[pa{n}]" if sound
                         else f"aevalsrc=0:c=stereo:s=48000:d={L:.3f}[pa{n}]")
                k += 1
            outs += f"[pv{n}][pa{n}]"
        g.append(f"{outs}concat=n={len(groups)}:v=1:a=1[vcat][acat]")
        video = ";\n".join(g) + f";\n[vcat]" + (f"tpad=stop_mode=clone:stop_duration={end_d}" if end_d else "null") + "[v0]"
        audio = "[acat]" + (f"apad=pad_dur={end_d}" if end_d else "anull") + "[aout]"
        return [video, audio], k

    def s_video(self):
        w = self.work
        # 1) the cut: keep these raw ranges
        # a preview far into the file seeks there first instead of decoding everything before it
        ss = max(0.0, self.keep[0][0] - 1.0) if self.mode == "preview" and self.keep else 0.0
        sel = "+".join(f"gte(t,{a - ss:.3f})*lt(t,{b - ss:.3f})" for a, b in self.keep)
        has_end = self.mode == "full" and any(i["id"] == "end" for i in getattr(self, "its", []))
        end_d = self.spec["endcard"]["duration"] if has_end else 0
        inputs = (["-ss", f"{ss:.3f}"] if ss else []) + ["-i", self.raw]
        # setpts uses the camera's own frame rate (FRAME_RATE): N/30 made 25 fps footage play fast and drift from the sound
        graph = [f"[0:v]select='{sel}',setpts=N/FRAME_RATE/TB,scale={W}:{H}:force_original_aspect_ratio=decrease:flags=bicubic,"
                 f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}" + (f",tpad=stop_mode=clone:stop_duration={end_d}" if end_d else "") + "[v0]",
                 f"[0:a]aselect='{sel}',asetpts=N/SR/TB" + (f",apad=pad_dur={end_d}" if end_d else "") + "[aout]"]
        k = 1
        if any(p[0] == "ins" for p in self.pieces):
            graph, k = self.joined_graph(ss, end_d, inputs)     # camera parts and inserts, joined in order
        cur = "v0"
        # overlay videos (inserts, B-roll, testimonials) go on the picture first: blurs and graphics sit above them.
        # Higher track on top. Unmuted ones add their sound; "duck" lowers the speaker while one plays.
        a_mix, ducks = [], []
        ovs = sorted((x for x in self.spec.get("overlays", []) if x.get("src") and x["t"] < self.w1 and x["t"] + x["dur"] > self.w0),
                     key=lambda x: x.get("track", 1))
        for n, o in enumerate(ovs):
            if not Path(o["src"]).is_file():
                raise RuntimeError(f"An overlay clip isn't there any more: {o['src']}")
            a0, a1 = max(o["t"], self.w0), min(o["t"] + o["dur"], self.w1)
            L, st, cin = a1 - a0, a0 - self.w0, float(o.get("in", 0)) + (a0 - o["t"])
            inputs.extend(["-ss", f"{cin:.3f}", "-t", f"{L:.3f}", "-i", o["src"]])
            fade, op = min(float(o.get("fade", 0.3)), L / 2), float(o.get("opacity", 1))
            if o.get("mode") == "pip":
                ow, oh = max(2, int(o.get("w", 640)) // 2 * 2), max(2, int(o.get("h", 360)) // 2 * 2)
                ox, oy = int(o.get("x", W - ow - 80)), int(o.get("y", 80))
            else:
                ow, oh, ox, oy = W, H, 0, 0
            chain = f"scale={ow}:{oh}:force_original_aspect_ratio=increase,crop={ow}:{oh},fps={FPS},setsar=1,format=yuva420p"
            if o.get("mode") == "pip":                           # rounded corners, as in the editor
                rr = max(0, min(int(o.get("radius", 24)), ow // 2, oh // 2))
                if rr:
                    inside = (f"lte(hypot(max(0,abs(X-{ow / 2})-{ow / 2 - rr}),max(0,abs(Y-{oh / 2})-{oh / 2 - rr})),{rr})")
                    chain += f",geq=lum='lum(X,Y)':cb='cb(X,Y)':cr='cr(X,Y)':a='255*{inside}'"
            if op < 0.999:
                chain += f",colorchannelmixer=aa={op:.2f}"
            if fade > 0:
                chain += f",fade=t=in:st=0:d={fade:.2f}:alpha=1,fade=t=out:st={max(0, L - fade):.2f}:d={fade:.2f}:alpha=1"
            graph.append(f"[{k}:v]{chain},setpts=PTS-STARTPTS+{st:.3f}/TB[o{n}]")
            graph.append(f"[{cur}][o{n}]overlay={ox}:{oy}:eof_action=pass:format=auto:enable='between(t,{st:.3f},{st + L:.3f})'[ov{n}]")
            cur = f"ov{n}"
            sound = o.get("muted") is False and subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", o["src"]],
                capture_output=True, text=True, env=self.env).stdout.strip()
            if sound:
                af = f",afade=t=in:d={fade:.2f},afade=t=out:st={max(0, L - fade):.2f}:d={fade:.2f}" if fade > 0 else ""
                graph.append(f"[{k}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={float(o.get('volume', 1)):.2f}{af},"
                             f"adelay={int(st * 1000)}:all=1[oa{n}]")
                a_mix.append(f"[oa{n}]")
            if float(o.get("duck", 1)) < 0.999:
                ducks.append((st, st + L, max(0.0, float(o.get("duck", 1)))))
            k += 1
        if a_mix or ducks:
            graph[1] = graph[1].replace("[aout]", ",aformat=sample_rates=48000:channel_layouts=stereo[amain]")
            nxt = "amain"
            if ducks:
                f = "*".join(f"(1-{1 - v:.3f}*min(1,max(0,(t-{a - 0.15:.3f})/0.25))*min(1,max(0,({b + 0.15:.3f}-t)/0.25)))" for a, b, v in ducks)
                graph.append(f"[amain]volume='{f}':eval=frame[aduck]"); nxt = "aduck"
            graph.append(f"[{nxt}]{''.join(a_mix)}amix=inputs={1 + len(a_mix)}:normalize=0:duration=first[aout]" if a_mix else f"[{nxt}]anull[aout]")
        # blur / pixelate / black-box regions go on the picture BEFORE the graphics, so lower-thirds and cards are never blurred
        for n, r in enumerate(x for x in self.spec.get("redactions", []) if x.get("keys") and x["t"] < self.w1 and x["t"] + x["dur"] > self.w0):
            wd, ht = max(2, int(r["w"]) // 2 * 2), max(2, int(r["h"]) // 2 * 2)
            st, en = r["t"] - self.w0, r["t"] + r["dur"] - self.w0
            xs, ys = self.rd_expr(r["keys"], "x", st, 1920 - wd), self.rd_expr(r["keys"], "y", st, 1080 - ht)
            strength = max(2, float(r.get("strength", 28)))
            eff = {"pixel": f"scale=iw/{max(4, int(strength * 0.6))}:ih/{max(4, int(strength * 0.6))}:flags=area,scale={wd}:{ht}:flags=neighbor",
                   "box": "drawbox=x=0:y=0:w=iw:h=ih:color=black:t=fill"}.get(r.get("type"), f"gblur=sigma={strength:.1f}:steps=3")
            graph.append(f"[{cur}]split[m{n}][s{n}]")
            graph.append(f"[s{n}]crop=w={wd}:h={ht}:x='{xs}':y='{ys}':exact=1,{eff}[b{n}]")
            graph.append(f"[m{n}][b{n}]overlay=x='{xs}':y='{ys}':eval=frame:enable='between(t,{st:.3f},{en:.3f})'[r{n}]")
            cur = f"r{n}"
        def overlay(listfile, x, y, offset):
            nonlocal cur, k
            # A change of frame format mid-stream makes ffmpeg rebuild the whole graph, which cut the picture short at the
            # end screen. So every frame is RGBA (rgba_frames) and the graph is never rebuilt (-reinit_filter 0).
            self.rgba_frames(Path(listfile).parent if Path(listfile).name == "list.txt" else w / "gfx" / self.cap_dir)
            inputs.extend(["-reinit_filter", "0", "-itsoffset", f"{offset:.3f}", "-f", "concat", "-safe", "0", "-i", str(listfile)])
            nxt = f"v{k}"
            graph.append(f"[{cur}][{k}:v]overlay={x}:{y}:eof_action=pass:repeatlast=0:format=auto[{nxt}]")
            cur = nxt; k += 1
        if getattr(self, "cap", None) and (w / "captions.txt").exists():
            band = json.loads((w / "gfx" / self.cap_dir / "band.json").read_text())
            overlay(w / "captions.txt", band["x"], band["y"], 0.0)
        for it in getattr(self, "its", []):
            meta = json.loads((w / "gfx" / it["id"] / "meta.json").read_text())
            overlay(w / "gfx" / it["id"] / "list.txt", meta["x"], meta["y"], it["t"] - self.w0)
        graph.append(f"[{cur}]format=yuv420p[vout]")
        (w / "filter.txt").write_text(";\n".join(graph))
        out = w / ("preview.mp4" if self.mode == "preview" else "full.partial.mp4")
        if out.exists():
            out.unlink()
        enc = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19"] if self.settings.get("software_encode") else ["-c:v", "h264_videotoolbox", "-b:v", self.settings.get("video_bitrate", "10M")]
        cmd = ["ffmpeg", "-v", "error", "-y", "-nostdin", *inputs, *self.filter_arg(w / "filter.txt"), "-map", "[vout]", "-map", "[aout]",
               *enc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", f"{self.out_dur:.3f}", "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(out)]
        p = self.popen(cmd)
        for line in p.stdout:
            if self.stopped:
                osutil.kill_tree(p); raise RuntimeError("Stopped")
            m = re.match(r"out_time_(?:us|ms)=(\d+)", line)
            if m:
                self.pct = min(99.0, int(m.group(1)) / 1e6 / self.out_dur * 100)
                self.info["video"] = f"{self.pct:.0f}%"
            elif line.strip() and not line.startswith(("frame=", "fps=", "stream_", "bitrate=", "total_size=", "out_time", "dup_", "drop_", "speed=", "progress=")):
                self.say(line)
        if p.wait() != 0:
            raise RuntimeError("ffmpeg failed (see Details)")
        self.pct = 100.0; self.info["video"] = "100%"
        self.partial = out

    def s_finish(self):
        if self.mode == "preview":
            self.output = str(self.partial); self.info["finish"] = "Preview ready"; return
        name = re.sub(r"[^\w\- ]+", "", self.meta.get("name", "Long video")).strip() or "Long video"
        dest_dir = renders_dir(self.base, self.spec.get("brand")); dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{name}.mp4"
        if dest.exists():
            prev = dest_dir / "Previous versions"; prev.mkdir(exist_ok=True)
            shutil.move(str(dest), str(prev / f"{name} — {time.strftime('%Y-%m-%d %H%M')}.mp4"))
        shutil.move(str(self.partial), str(dest))
        ch = self.root / "chapters.txt"
        if ch.exists():
            shutil.copy(ch, dest_dir / f"{name} - chapters.txt"); self.chapters_out = str(dest_dir / f"{name} - chapters.txt")
        self.output = str(dest); self.info["finish"] = dest.name

    # ------------------------------------------------------------ driver
    def start(self):
        if self.running:
            return False
        self.error = None; self.done = False; self.running = True; self.started = time.time()

        def go():
            try:
                for k, _ in STEPS:
                    self.state[k] = "running"
                    getattr(self, "s_" + k)()
                    if self.state[k] == "running":
                        self.state[k] = "done"
                self.done = True
            except Exception as e:
                for k in self.state:
                    if self.state[k] == "running":
                        self.state[k] = "failed"
                self.error = "Stopped" if self.stopped else str(e); self.say("ERROR: " + str(e))
            finally:
                self.running = False
        self.thread = Thread(target=go, daemon=True); self.thread.start()
        return True

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            osutil.kill_tree(self.proc)

    def status(self):
        return {"mode": self.mode, "running": self.running, "done": self.done, "error": self.error, "pct": round(self.pct, 1), "output": self.output,
                "chapters": self.chapters_out, "elapsed": (time.time() - self.started) if self.started else 0,
                "steps": [{"key": k, "label": l, "state": self.state[k], "info": self.info.get(k, "")} for k, l in STEPS], "log": self.log[-40:]}
