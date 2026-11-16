"""Import a brand guide: PDFs, images and/or a website link -> Claude Code fills in brand.json for the Brand screen.

How it works (one background job per kit):
  1. The files go to <kit>/.import/<stamp>/ (kept out of git). PDFs become page images + text with macOS PDFKit
     (03. Brands/pdfpages.swift, compiled once into .cache/pdfpages), so nothing extra has to be installed.
  2. `claude -p` (the user's own Claude Code login) gets an index of the pages and reads the ones it needs with its Read
     tool (WebFetch too when a link was given). It replies with the brand.json fields, notes and font stand-ins.
  3. Fonts: the guide's font is looked up on Google Fonts (Fontsource) and downloaded into the kit; when it isn't there,
     Claude's suggested look-alike from Google Fonts is used instead (never the default font).
The result is NOT saved: the Brand screen loads it as unsaved changes so the person checks it first.
"""
import json, os, re, shutil, subprocess, sys, threading, time

from pathlib import Path

import brandkit
import workspace          # whose storage this job works in (phase 7)
import osutil             # macOS / Windows differences (phase 8)
import claude_client

HERE = Path(__file__).resolve().parent

MAX_PAGES = 120
jobs = {}            # kit id -> ImportJob
ENV = None
settings = dict      # set by server.py: () -> settings.json (claude_model)


def swift_tool(name):
    """03. Brands/<name>.swift compiled once into .cache/<name> (pdfpages: pages to images; logocrop: cut out a logo)."""
    src, exe = brandkit.HOME / f"{name}.swift", HERE / ".cache" / name
    if not exe.exists() or exe.stat().st_mtime < src.stat().st_mtime:
        exe.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(["swiftc", "-O", str(src), "-o", str(exe)], capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"Couldn't build {name} (needs the Xcode command line tools): " + r.stderr[-300:])
    return exe


def pdf_tool(kind):
    """The command for one PDF job ("pages" or "logo"): the Swift tool on a Mac (nothing to install there), else
    03. Brands/pdftools.py (numpy + pypdfium2 + Pillow; Windows and Linux). STUDIO_PDF_TOOLS=python forces Python."""
    python = [sys.executable, str(brandkit.HOME / "pdftools.py"), kind]
    if osutil.MAC and os.environ.get("STUDIO_PDF_TOOLS") != "python":
        try:
            return [str(swift_tool({"pages": "pdfpages", "logo": "logocrop"}[kind]))]
        except (RuntimeError, OSError):
            pass                                  # no Xcode command line tools: Python, if it's installed
    sys.path.insert(0, str(brandkit.HOME))
    import pdftools
    if pdftools.missing():
        raise RuntimeError("Reading PDF brand guides needs " + ", ".join(pdftools.missing()) +
                           " (run the installer again, or: pip install numpy pypdfium2 pillow)")
    return python


SCHEMA = """{
  "name": "Brand name",
  "website": "example.com",
  "colors": {
    "primary": "#rrggbb  (the main brand colour)",
    "accent": "#rrggbb  (a bright highlight colour that stands out on dark video)",
    "gradient": ["#from", "#to"],
    "keyword": ["#a", "#b", "#c"],
    "kicker": "#rrggbb  (small uppercase labels on dark glass cards; must be readable on dark)",
    "highlight": "#rrggbb  (tick / yes marks)",
    "text": "#ffffff  (text on cards; almost always white)",
    "glass_tint": ["rgba(r, g, b, 0.60)", "rgba(r, g, b, 0.74)"],
    "takeover_bg": "#rrggbb  (dark base behind full-screen cutaways)"
  },
  "fonts": {
    "display": {"family": "Exact headline font name from the guide", "google_alternative": "Closest Google Fonts family"},
    "body": {"family": "Exact body font name from the guide", "google_alternative": "Closest Google Fonts family"}
  },
  "captions": {"keyword": "gradient", "weight": 700},
  "endscreen": {"lines": [{"text": "Short regular line"}, {"text": "Offer", "bold": true}], "cta": "One-line call to action"},
  "voice": {"tone": "2-3 sentences: how the brand writes (tone, casing, words to use or avoid)", "cta": "Call to action"},
  "logos": {
    "primary": {"file": "<folder>/page-017.png (or an image file)", "box": [x, y, w, h]},
    "mark": {"file": "...", "box": [x, y, w, h]}
  },
  "notes": ["Short lines for the person checking this: where each value came from, what was guessed or missing"],
  "pages_used": [3, 54]
}"""


def build_prompt(index, url, name):
    return f"""You are setting up a video brand kit for a client called "{name}" from their brand guide.
The videos are talking-head reels and long YouTube videos: white captions with coloured keywords, dark
see-through "glass" cards, full-screen colour cutaways, lower-thirds and an end screen with a call to action.

{"THE GUIDE'S FILES are in the current folder (read them with the Read tool):" if index else ""}
{index}
{f"THE CLIENT'S WEBSITE: {url} (use WebFetch to read it: colours, fonts, tone of voice, call to action)." if url else ""}

How to work:
- For a long PDF, look at the first pages (cover, contents) first, then read the pages about colour, typography,
  logo, tone of voice / messaging. Don't read every page. Hex codes printed in the guide win over what you see.
- Choose colours that work on video: the accent must stand out on dark footage; keyword colours must be readable
  on dark glass; glass_tint and takeover_bg are dark versions of the brand's colours.
- If the guide gives no end screen or call to action, write a short neutral one from the brand's own words.
- Logos: find the page where the primary logo (the full logo the brand signs off with) stands on its own on a plain,
  solid background, and give its box on that page image as fractions of the image width and height from the top
  left: [x, y, w, h]. Leave a small margin around it, but nothing else (text, rulers, other logos) may be inside the
  box. "mark" is the symbol on its own (null if the brand has none, or if it is the same as the primary logo).
  Use null when no clean example exists. White and dark versions are made for you, so a black logo is fine.
- Fonts: give the exact names from the guide, plus the closest Google Fonts family for each (a real Google Fonts
  family name; never "Display").

Reply with ONE JSON object only, in exactly this shape:
{SCHEMA}
"""


class ImportJob:
    def __init__(self, bid, name, files, url, creds=None):
        self.bid, self.name, self.url = bid, name, (url or "").strip()
        self.dir = brandkit.kit_dir(bid) / ".import" / time.strftime("%Y%m%d-%H%M%S")
        self.files = files            # [(filename, bytes)]
        self.state, self.step, self.log = "running", "Starting…", []
        self.result, self.error, self.started = None, None, time.time()
        self.proc = None
        self.sources = {}             # page-image folder or image file name -> the original PDF / image
        self.creds = creds            # how to reach Claude (Claude Code here, or the portal user's API key)

    def say(self, line):
        self.step = line; self.log.append(line); del self.log[:-80]

    def start(self):
        workspace.Thread(target=self.run, daemon=True).start()

    def stop(self):
        self.state = "stopped"
        # a running Claude Code request notices this (should_stop) and is stopped

    def status(self):
        return {"state": self.state, "step": self.step, "log": self.log[-12:], "result": self.result, "error": self.error,
                "elapsed": round(time.time() - self.started)}

    # ------------------------------------------------------------ steps
    def prepare(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for fname, data in self.files:
            clean = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(fname).name).strip("-") or "file"
            ext = Path(clean).suffix.lower()
            if ext == ".pdf":
                self.say(f"Reading the pages of {fname}…")
                src = self.dir / clean; src.write_bytes(data)
                out = self.dir / Path(clean).stem
                r = subprocess.run([*pdf_tool("pages"), str(src), str(out), str(MAX_PAGES), "1100"], capture_output=True, text=True, timeout=600)
                if r.returncode:
                    raise RuntimeError(f"Couldn't read {fname}: {(r.stderr or r.stdout)[-300:]}")
                info = json.loads((out / "pages.json").read_text())
                self.sources[out.name] = src     # kept for cutting logos out of the vector pages
                more = f" (only the first {len(info['pages'])} of {info['count']} pages)" if info["count"] > len(info["pages"]) else ""
                lines.append(f"- {fname}: {len(info['pages'])} pages as images {out.name}/page-001.png … {out.name}/page-{len(info['pages']):03d}.png{more}")
                text = [p for p in info["pages"] if p["text"].strip()]
                if text:
                    (out / "text.txt").write_text("\n\n".join(f"--- page {p['page']} ---\n{p['text'].strip()}" for p in text))
                    lines.append(f"  Its text layer (searchable) is in {out.name}/text.txt; read that first.")
                else:
                    lines.append("  It has no text layer: look at the page images.")
            elif ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                (self.dir / clean).write_bytes(data)
                self.sources[clean] = self.dir / clean
                lines.append(f"- {clean}: an image from the guide")
            elif ext in (".svg", ".txt", ".md", ".html", ".css"):
                (self.dir / clean).write_bytes(data)
                lines.append(f"- {clean}: a text file")
            else:
                raise RuntimeError(f"{fname}: send a PDF, images, or a website link")
        return "\n".join(lines)

    def ask(self, prompt, label="Claude is reading the guide…", tools=None, files=(), web=True):
        """One JSON answer through claude_client: Claude Code reads the files in the import folder itself; the API back
        end gets `files` attached (and the website through its web fetch tool)."""
        self.say(label)
        try:
            return claude_client.ask_json(self.creds, prompt, cwd=self.dir, tools=tools or "Read,Glob,Grep", files=files,
                                          web_url=(self.url or None) if web else None, on_event=self.say, env=ENV,
                                          timeout=1500, what="brand kit", should_stop=lambda: self.state == "stopped")
        except claude_client.ClaudeError as e:
            raise RuntimeError(str(e))

    def api_pages(self):
        """The API can't open files, so for a long PDF guide Claude first sees the opening pages (cover, contents) and
        names the pages it needs; those are attached to the main request. Short guides go in whole."""
        pages = sorted(f for f in self.dir.glob("*/page-*.png"))
        images = sorted(f for f in self.dir.glob("*.*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif"))
        if len(pages) <= 16:
            return pages + images
        first = pages[:6]
        pick = self.ask(f"""These are the first pages of a {len(pages)}-page brand guide (cover and contents).
Which page numbers show the colour palette (with hex codes), the typography, the primary logo and the logo mark (each on
a plain background), and the tone of voice or messaging? Use the contents page; pick at most 14 pages.
Reply with JSON only: {{"pages": [12, 13, 54]}}""", "Finding the pages that matter…", files=first, web=False)
        want = sorted({int(n) for n in (pick.get("pages") or []) if str(n).isdigit() or isinstance(n, int)} | {1, 2, 3})[:17]
        by_no = {int(f.stem.split("-")[1]): f for f in pages}
        return [by_no[n] for n in want if n in by_no] + images

    def fonts(self, got, brands_mod):
        """Download each font (or its Google stand-in) into the kit. Returns the fonts block and notes."""
        fonts, notes = {}, []
        for role in ("display", "body"):
            f = (got.get("fonts") or {}).get(role) or {}
            want, alt = (f.get("family") or "").strip(), (f.get("google_alternative") or "").strip()
            picked = None
            for cand, is_alt in ((want, False), (alt, True)):
                if not cand or cand.lower() == "display":
                    continue
                hit = next((x for x in brands_mod.font_list() if x["family"].lower() == cand.lower() and "latin" in (x.get("subsets") or [])), None)
                if hit:
                    picked = (hit, is_alt); break
            if not picked:
                notes.append(f"{role.title()} font: {want or 'not found'}; no Google Fonts match, upload the font files.")
                fonts[role] = {"family": want, "files": []}
                continue
            hit, is_alt = picked
            self.say(f"Downloading {hit['family']} ({role})…")
            font = brands_mod.font_download(self.bid, role, hit["id"])
            if is_alt:
                font["brand_font"] = want
                notes.append(f"{role.title()} font: the guide uses {want}, which isn't on Google Fonts; {hit['family']} stands in. Upload {want} if the client can supply it.")
            fonts[role] = font
        return fonts, notes

    # ------------------------------------------------------------ logos
    def crop(self, key, spec):
        """Cut one logo out (logocrop.swift / pdftools.py logo); -> (result dict, folder) or (None, why)."""
        if not isinstance(spec, dict) or not spec.get("file") or not isinstance(spec.get("box"), list) or len(spec["box"]) != 4:
            return None, "no box"
        f = spec["file"].strip().lstrip("./")
        folder, _, page_file = f.partition("/")
        if folder in self.sources and page_file:
            m = re.search(r"page-(\d+)", page_file)
            src, page = self.sources[folder], int(m.group(1)) if m else 1
        elif f in self.sources:
            src, page = self.sources[f], 1
        else:
            return None, f"unknown file {f}"
        out = self.dir / "logos"
        self.say(f"Cutting {key} from {f} at {[round(float(v), 3) for v in spec['box']]}")
        r = subprocess.run([*pdf_tool("logo"), str(src), str(page), *[str(float(v)) for v in spec["box"]], str(out), key],
                           capture_output=True, text=True, timeout=120)
        try:
            res = json.loads((r.stdout.strip().splitlines() or ["{}"])[-1])
        except ValueError:
            return None, (r.stderr or r.stdout)[-200:]
        return (res, out) if res.get("ok") else (None, res.get("why", "couldn't cut it out"))

    def logos(self, got):
        """Cut the logos Claude pointed at out of the guide, let Claude check the crops once, copy them into the kit."""
        want = {k: v for k, v in ((got.get("logos") or {}).items()) if k in ("primary", "mark") and v}
        if not want:
            return {}, ["Logos: no clean example found in the guide; upload them by hand."]
        self.say("Cutting out the logos…")
        done, notes = {}, []
        for k, spec in want.items():
            res, why = self.crop(k, spec)
            if res:
                done[k] = spec
            else:
                notes.append(f"Logo ({k}): {why}.")
        if done:   # one check: Claude looks at what was cut out and may correct a box
            look = "\n".join(f"- {k}: logos/{k}-crop.png (cut from {done[k]['file']}, box {done[k]['box']})" for k in done)
            try:
                fix = self.ask(f"""You pointed at these logos in the brand guide and they were cut out:
{look}
Look at each crop with the Read tool. A good crop shows the whole logo, with nothing cut off and nothing else in it
(no text, rulers, other logos). For each one reply "ok", or a corrected {{"file": "...", "box": [x, y, w, h]}} on the page
image (fractions from the top left; look at the page image again first), or null if no clean example exists.
Reply with JSON only: {{"primary": ..., "mark": ...}}""", "Checking the logos…", "Read,Glob",
                                files=[self.dir / "logos" / f"{k}-crop.png" for k in done], web=False)
            except RuntimeError as e:
                fix, notes = {}, notes + [f"Logos weren't double-checked ({e})."]
            for k, v in (fix or {}).items():
                if k not in done:
                    continue
                if v is None:
                    done.pop(k); notes.append(f"Logo ({k}): no clean example; upload it by hand.")
                elif isinstance(v, dict):
                    res, why = self.crop(k, v)
                    if res:
                        done[k] = v
                    else:
                        done.pop(k); notes.append(f"Logo ({k}): {why}.")
        self.logo_specs = dict(done)
        kitlogos = brandkit.kit_dir(self.bid) / "logos"
        kitlogos.mkdir(parents=True, exist_ok=True)
        out = {}
        for k, spec in done.items():
            base = "logo" if k == "primary" else "mark"
            for v in ("light", "dark", "color"):
                f = self.dir / "logos" / f"{k}-{v}.png"
                if f.exists():
                    shutil.copy(f, kitlogos / f"{base}-{v}.png")
            if k == "primary":
                out.update(light="logos/logo-light.png", dark="logos/logo-dark.png", color="logos/logo-color.png")
            else:
                out.update(mark="logos/mark-color.png", mark_light="logos/mark-light.png")
            pg = re.search(r"page-(\d+)", spec["file"])
            notes.append(f"Logo ({k}) cut from {('page ' + str(int(pg.group(1)))) if pg else spec['file']}: white and dark versions made by removing the background. Check the edges; replace with the client's own files when you have them.")
        if "primary" not in done and "mark" in done:   # a brand whose logo is the symbol: use it on the end screen too
            for v in ("light", "dark", "color"):
                if (kitlogos / f"mark-{v}.png").exists():
                    shutil.copy(kitlogos / f"mark-{v}.png", kitlogos / f"logo-{v}.png")
            out.update(light="logos/logo-light.png", dark="logos/logo-dark.png", color="logos/logo-color.png")
        return out, notes

    def run(self):
        import brands as brands_mod
        try:
            index = self.prepare()
            api = self.creds is not None and self.creds.backend == "api"
            got = self.ask(build_prompt(index, self.url, self.name), files=self.api_pages() if api else ())
            fonts, fnotes = self.fonts(got, brands_mod)
            kit = brandkit.load(self.bid)
            for k in ("website", "colors", "captions", "endscreen", "voice"):
                if isinstance(got.get(k), (dict, str)) and got.get(k):
                    kit[k] = got[k] if not isinstance(got[k], dict) else {**(kit.get(k) or {}), **got[k]}
            kit["fonts"] = {**(kit.get("fonts") or {}), **fonts}
            logos, lnotes = self.logos(got)
            fnotes += lnotes
            if logos:
                kit["logos"] = {**(kit.get("logos") or {}), **logos}
            self.logo_specs = getattr(self, "logo_specs", {})
            kit["import"] = {"from": [n for n, _ in self.files] + ([self.url] if self.url else []), "at": time.strftime("%Y-%m-%d %H:%M"),
                             "pages_used": got.get("pages_used") or [], "logos": getattr(self, "logo_specs", {})}
            self.result = {"brand": kit, "notes": (got.get("notes") or []) + fnotes, "files": brands_mod.kit_files(self.bid)}
            self.state = "done"; self.say("Done. Check everything, then press Save.")
        except Exception as e:   # shown to the person on the Brand screen
            if self.state != "stopped":
                self.state, self.error = "failed", str(e)
            self.say(f"Stopped: {e}")
        finally:
            shutil.rmtree(self.dir, ignore_errors=True)   # page images can be large; the kit keeps only what it needs
