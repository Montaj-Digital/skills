"""Brand kits for the Studio AI dashboard: the /api/brands routes, kit files, Google Fonts (Fontsource) search and
download, and the two preview stages the Brand screen shows.

Routes (handled when server.py calls handle()):
  GET  /api/brands                      list of kits
  GET  /api/brands/<id>                 {brand, files}
  POST /api/brands/new {name}           make a kit
  POST /api/brands/<id> {brand}         save brand.json (previous one kept in .backups/)
  POST /api/brands/<id>/delete          move the kit to the Bin (videos using it go back to the default look)
  POST /api/brands/<id>/css {brand}     the CSS a draft would produce (live preview without saving)
  POST /api/brands/<id>/upload?sub=fonts|logos|images&name=…   raw file body
  POST /api/brands/<id>/font {role, font}   download a Fontsource family into the kit
  POST /api/brands/<id>/import?name=…&url=…   import a brand guide (raw PDF/image body and/or a website link)
  GET  /api/brands/<id>/import          the import's progress and result;  POST …/import/stop stops it
  GET  /api/fonts/search?q=             Fontsource catalogue search (no key)
  GET  /brands/<id>/long.css            long-form overlay CSS for that kit (used by the long-form editor)
  GET  /brands/<id>/<file>              a file inside the kit
  GET  /brandstage/index.html           a sample reel built by the real build.py (Brand screen preview)
  GET  /brandstage/long.html            long-form graphics on a 1920x1080 frame (Brand screen preview)
"""
import importlib.util, json, shutil, subprocess, sys, time, urllib.request
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent                         # 01. Short-form/04. Editor
STUDIO = HERE.parent.parent                                    # 03. Studio AI
sys.path.append(str(STUDIO / "03. Brands"))
import brandkit  # noqa: E402
import brand_import  # noqa: E402
import workspace  # noqa: E402

CACHE = HERE / ".cache"
STAGE = CACHE / "brand-stage"
FONT_LIST = CACHE / "fontsource.json"
SKILL = None   # set by server.py (its studio-reel copy)
LONG_APP = STUDIO / "02. Long-form/04. Editor/app"
UA = {"User-Agent": "Studio-AI/1.0"}


def jkey(bid):
    """Import jobs are per kit folder (two teams may both have a kit called 'acme')."""
    return str(brandkit.kit_dir(bid))


def reel_brand():
    """The skill's scripts/brand.py (the same CSS build.py appends)."""
    spec = importlib.util.spec_from_file_location("reel_brand", SKILL / "scripts/brand.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- the sample reel for the preview
SAMPLE_TEXT = ("Most businesses lose hours every week to admin they could automate. So here is what we do "
               "first. We map every task, then we connect the tools you already use, and the results show up in weeks "
               "not months. Ready to see it for your team?")
SCENES = {"caption": 2.2, "card": 6.4, "takeover": 11.6, "end": 16.3}


def sample_spec():
    words, t = [], 0.2
    for w in SAMPLE_TEXT.split():
        words.append({"text": w, "start": round(t, 2), "end": round(t + 0.28, 2)}); t += 0.3
    spec = {
        "duration": 14.0, "fps": 25, "video": "base-edit.mp4",
        "captions": {"keywords": [4, 9, 10, 26, 27]},
        "cards": [
            {"type": "questions", "items": ["Where do the hours go?", "What can AI take off our plate?"], "times": [0.6, 1.2], "dim_at": 3.2, "out": 3.9},
            {"type": "statement", "kicker": "The first step", "icon": "lightbulb", "word": "Map every task", "t": 4.6, "t_icon": 5.0, "t_word": 5.5, "out": 7.6},
        ],
        "takeovers": [{"mode": "full", "t": 8.4, "out": 13.6, "kicker": "How it works", "title": "Three *simple* steps",
                       "numbered": True, "items": [{"text": "Map every task", "t": 9.4}, {"text": "Connect your tools", "t": 10.0},
                                                   {"text": "See results in weeks", "t": 10.6}]}],
        "endcard": {"duration": 3.5, "lines": [{"text": "Visit"}, {"text": "your website"}, {"text": "for your"},
                                               {"text": "Free", "bold": True}, {"text": "Consultation", "bold": True}]},
    }
    return spec, words


def ensure_stage():
    """Build the sample reel once (and again when the skill's build.py or styles change)."""
    page = STAGE / "index.html"
    srcs = [SKILL / "scripts/build.py", SKILL / "template/styles.css", SKILL / "template/motion-lib.js", Path(__file__)]
    if page.exists() and page.stat().st_mtime > max(p.stat().st_mtime for p in srcs):
        return page
    STAGE.mkdir(parents=True, exist_ok=True)
    spec, words = sample_spec()
    (STAGE / "reel.json").write_text(json.dumps(spec))
    (STAGE / "transcript.json").write_text(json.dumps(words))
    r = subprocess.run([sys.executable, str(SKILL / "scripts/build.py"), str(STAGE)], capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError("Couldn't build the brand preview: " + (r.stderr or r.stdout)[-400:])
    return page


STAGE_SCRIPT = """
// Brand screen preview: the parent posts {css, lines, logo, line} and the time to show.
(function () {
  document.documentElement.style.background = "#000";
  const v = document.getElementById("a-roll"); if (v) { v.removeAttribute("src"); v.style.background = "linear-gradient(170deg, #a7adb6 0%, #6d737c 55%, #3e4249 100%)"; }
  const st = document.createElement("style"); st.id = "brand-css"; document.head.append(st);
  const t = parseFloat(new URLSearchParams(location.search).get("t") || "0");
  function seek() { try { window.__timelines.main.seek(t, false); } catch (e) {} }
  window.addEventListener("message", (e) => {
    const d = e.data || {}; if (d.type !== "brand") return;
    st.textContent = d.css || "";
    const lines = document.querySelector(".elines");
    if (lines && d.lines) {
      lines.innerHTML = "";
      d.lines.filter((l) => l.text).forEach((l) => { const x = document.createElement("div"); x.className = "el " + (l.bold ? "eb" : "er"); x.textContent = l.text; lines.append(x); });
    }
    const lg = document.querySelector(".elogo");
    if (lg) { if (d.logo) { lg.src = d.logo; lg.style.display = ""; } else lg.style.display = "none"; }
    const stops = document.querySelectorAll("#gLine stop");
    if (d.line && stops.length === 3) { stops[0].setAttribute("stop-color", d.line[0]); stops[1].setAttribute("stop-color", d.line[1]); stops[2].setAttribute("stop-color", d.line[0]); }
    document.fonts.ready.then(() => { seek(); requestAnimationFrame(seek); });
  });
  seek(); window.addEventListener("load", seek);
  parent.postMessage({ type: "stage-ready", t }, "*");
})();
"""

LONG_STAGE = """<!doctype html>
<html><head><meta charset="utf-8" />
<style>
  @font-face { font-family: "Display"; src: url("/brand/Display-Bold.ttf"); font-weight: 700; }
  @font-face { font-family: "Display"; src: url("/brand/Display-Medium.ttf"); font-weight: 500; }
  @font-face { font-family: "Display"; src: url("/brand/Display-ExtraBold.ttf"); font-weight: 800; }
  @font-face { font-family: "Inter"; src: url("/brand/Inter-400-latin.woff2"); font-weight: 400; }
  @font-face { font-family: "Inter"; src: url("/brand/Inter-700-latin.woff2"); font-weight: 700; }
  html, body { margin: 0; width: 1920px; height: 1080px; overflow: hidden; background: linear-gradient(170deg, #a7adb6 0%, #6d737c 55%, #3e4249 100%); }
  .a-fade, .a-slide, .a-pop { animation: none !important; }
</style>
<link rel="stylesheet" href="/long/app/overlays.css" />
<style id="brand-css"></style>
</head><body>
<div id="root" class="ov-root"></div>
<script src="/long/app/overlays.js"></script>
<script>
  const root = document.getElementById("root");
  const kind = new URLSearchParams(location.search).get("kind") || "lt";
  let lines = [{ text: "Visit" }, { text: "your website" }, { text: "Free", bold: true }, { text: "Consultation", bold: true }], logo = "";
  function draw() {
    root.innerHTML = "";
    if (kind === "end") root.append(OV.endcard({ lines, logo }));
    else {
      root.append(OV.lowerThird({ title: "Jane Smith", sub: "Founder, Example Co", pos: "left" }));
      root.append(OV.card({ type: "stat", value: "3x", label: "more qualified leads in 90 days", pos: "right" }));
      root.append(OV.caption([{ text: "This" }, { text: "changed" }, { text: "everything" }, { text: "for us" }], 2, { size: 3.3, bottom: 6 }));
    }
  }
  window.addEventListener("message", (e) => {
    const d = e.data || {}; if (d.type !== "brand") return;
    document.getElementById("brand-css").textContent = d.css || "";
    if (d.lines) lines = d.lines; logo = d.logo || ""; draw();
  });
  draw(); parent.postMessage({ type: "stage-ready", kind }, "*");
</script>
</body></html>
"""


# ---------------------------------------------------------------- CSS for a (draft) kit
def draft_css(bid, brand):
    """What the reel template and long-form graphics would look like with this brand.json (saved or not)."""
    kit = dict(brand or brandkit.load(bid)); kit["id"] = bid
    files = f"/brands/{bid}/"
    if bid == brandkit.DEFAULT:   # the default brand is the built-in look: nothing is added
        logo = "assets/brand/logo-white.svg"
        return {"reel": "", "long": "", "logo": logo, "long_logo": "/brand/logo-light.svg", "line": None,
                "lines": (kit.get("endscreen") or {}).get("lines")}
    kit["_dir"] = str(brandkit.kit_dir(bid))
    reel, info = reel_brand().reel_css(kit, STAGE, copy=False)
    light = (kit.get("logos") or {}).get("light")
    return {"reel": reel, "long": brandkit.long_css(kit, files), "logo": info["logo"],
            "long_logo": files + light if light else "", "line": info["line"],
            "lines": (kit.get("endscreen") or {}).get("lines")}


# ---------------------------------------------------------------- Google Fonts through Fontsource (no key)
def font_list():
    if FONT_LIST.exists() and time.time() - FONT_LIST.stat().st_mtime < 7 * 86400:
        return json.loads(FONT_LIST.read_text())
    req = urllib.request.Request("https://api.fontsource.org/v1/fonts", headers=UA)
    data = json.loads(urllib.request.urlopen(req, timeout=20).read())
    keep = [{k: f.get(k) for k in ("id", "family", "weights", "styles", "category", "license", "type", "subsets")} for f in data]
    CACHE.mkdir(parents=True, exist_ok=True)
    FONT_LIST.write_text(json.dumps(keep))
    return keep


def font_search(q, limit=40):
    q = (q or "").strip().lower()
    fonts = [f for f in font_list() if "latin" in (f.get("subsets") or [])]
    if not q:
        popular = ["inter", "poppins", "montserrat", "roboto", "open-sans", "lato", "playfair-display", "dm-sans",
                   "space-grotesk", "raleway", "nunito", "work-sans", "manrope", "plus-jakarta-sans", "outfit", "bebas-neue"]
        by = {f["id"]: f for f in fonts}
        return [by[i] for i in popular if i in by]
    starts = [f for f in fonts if f["family"].lower().startswith(q)]
    within = [f for f in fonts if q in f["family"].lower() and f not in starts]
    return (starts + within)[:limit]


ROLE_WEIGHTS = {"display": (500, 600, 700, 800), "body": (400, 700)}


def font_download(bid, role, font_id):
    """Download the latin woff2 files of a Fontsource family into <kit>/fonts/ (the weights the templates use)."""
    req = urllib.request.Request(f"https://api.fontsource.org/v1/fonts/{font_id}", headers=UA)
    meta = json.loads(urllib.request.urlopen(req, timeout=20).read())
    have = sorted(int(w) for w in meta["variants"])
    picked = sorted({min(have, key=lambda h: (abs(h - w), -h)) for w in ROLE_WEIGHTS[role]})
    files = []
    for w in picked:
        url = meta["variants"][str(w)]["normal"]["latin"]["url"]["woff2"]
        data = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30).read()
        rel = brandkit.add_file(bid, "fonts", f"{font_id}-{w}.woff2", data)
        files.append({"file": rel, "weight": w})
    return {"family": meta["family"], "source": "fontsource", "id": font_id, "license": meta.get("license", ""), "files": files}


def kit_files(bid):
    d = brandkit.kit_dir(bid)
    return {sub: sorted(p.relative_to(d).as_posix() for p in (d / sub).glob("*") if p.is_file()) if (d / sub).is_dir() else []
            for sub in ("fonts", "logos", "images")}


# ---------------------------------------------------------------- routes
def handle(h, method, path, q):
    """Returns True when the request was handled."""
    try:
        return _handle(h, method, path, q)
    except FileNotFoundError as e:
        h.send_json({"error": str(e)}, 404); return True
    except (ValueError, KeyError) as e:
        h.send_json({"error": str(e)}, 400); return True
    except (OSError, RuntimeError) as e:
        h.send_json({"error": str(e)}, 500); return True


def _handle(h, method, path, q):
    if method == "GET":
        if path == "/api/brands":
            h.send_json({"brands": brandkit.list_brands(), "default": brandkit.DEFAULT}); return True
        if path == "/api/fonts/search":
            h.send_json({"fonts": font_search(q.get("q", [""])[0])}); return True
        if path.startswith("/api/brands/") and path.endswith("/import"):
            bid = unquote(path[len("/api/brands/"):-len("/import")])
            j = brand_import.jobs.get(jkey(bid))
            h.send_json(j.status() if j else {"state": "none"}); return True
        if path.startswith("/api/brands/"):
            bid = unquote(path[len("/api/brands/"):])
            h.send_json({"brand": brandkit.load(bid), "files": kit_files(bid)}); return True
        if path == "/brandstage/index.html":
            ensure_stage(); h.send_file(STAGE / "index.html", inject=STAGE_SCRIPT); return True
        if path == "/brandstage/long.html":
            data = LONG_STAGE.encode()
            h.send_response(200); h.send_header("Content-Type", "text/html; charset=utf-8")
            h.send_header("Content-Length", str(len(data))); h.send_header("Cache-Control", "no-store"); h.end_headers()
            h.wfile.write(data); return True
        if path.startswith("/brandstage/assets/"):
            rel = unquote(path[len("/brandstage/assets/"):])
            if rel.startswith("brand/") and rel.count("/") >= 2 and brandkit.kit_dir_ok(rel.split("/")[1]):
                _, bid, inner = rel.split("/", 2)       # assets/brand/<id>/<file> = a file of that kit
                h.send_file(brandkit.safe_file(bid, inner), cache="no-cache"); return True
            f = (STAGE / "assets" / rel).resolve()
            h.send_file(f if (STAGE / "assets").resolve() in f.parents else None); return True
        if path.startswith("/brands/"):
            bid, _, rel = unquote(path[len("/brands/"):]).partition("/")
            if rel == "long.css":
                css = "" if bid == brandkit.DEFAULT else brandkit.long_css(brandkit.load(bid), f"/brands/{bid}/")
                data = css.encode()
                h.send_response(200); h.send_header("Content-Type", "text/css; charset=utf-8")
                h.send_header("Content-Length", str(len(data))); h.send_header("Cache-Control", "no-store"); h.end_headers()
                h.wfile.write(data); return True
            h.send_file(brandkit.safe_file(bid, rel), cache="no-cache"); return True
        return False
    if method == "POST":
        if path == "/api/brands/new":
            name = (h.body().get("name") or "").strip()
            if not name:
                raise ValueError("Give the client a name")
            h.send_json({"brand": brandkit.new_kit(name)}); return True
        if not path.startswith("/api/brands/"):
            return False
        bid, _, action = path[len("/api/brands/"):].partition("/")
        bid = unquote(bid)
        brandkit.kit_dir(bid)   # validates the id
        if action == "":
            if bid == brandkit.DEFAULT:
                raise ValueError("your brand is the built-in look; it can't be changed here")
            h.send_json({"brand": brandkit.save(bid, h.body()["brand"])}); return True
        if action == "delete":
            j = brand_import.jobs.get(jkey(bid))
            if j and j.state == "running":
                j.stop()
            h.send_json({"ok": True, "bin": workspace.current().shown(brandkit.trash(bid))}); return True
        if action == "css":
            h.send_json(draft_css(bid, h.body().get("brand"))); return True
        if action == "upload":
            n = int(h.headers.get("Content-Length", 0))
            if n > 30 * 1024 * 1024:
                raise ValueError("That file is too big (30 MB at most)")
            rel = brandkit.add_file(bid, q.get("sub", [""])[0], unquote(q.get("name", ["file"])[0]), h.rfile.read(n))
            h.send_json({"path": rel, "files": kit_files(bid)}); return True
        if action == "import":
            if bid == brandkit.DEFAULT:
                raise ValueError("Import a guide into a client's kit, not your brand")
            old = brand_import.jobs.get(jkey(bid))
            if old and old.state == "running":
                raise ValueError("A guide is already being read for this client")
            n = int(h.headers.get("Content-Length", 0))
            if n > 300 * 1024 * 1024:
                raise ValueError("That file is too big (300 MB at most)")
            data = h.rfile.read(n) if n else b""
            name, url = unquote(q.get("name", [""])[0]), unquote(q.get("url", [""])[0])
            if not data and not url:
                raise ValueError("Add a PDF, an image or a website link")
            if url and not url.startswith(("http://", "https://")):
                url = "https://" + url
            j = brand_import.ImportJob(bid, brandkit.load(bid).get("name", bid), [(name or "guide.pdf", data)] if data else [], url,
                                       brand_import.claude_client.creds_from(h.headers, brand_import.settings()))
            brand_import.jobs[jkey(bid)] = j; j.start()
            h.send_json(j.status()); return True
        if action == "import/stop":
            j = brand_import.jobs.get(jkey(bid))
            if j:
                j.stop()
            h.send_json({"ok": True}); return True
        if action == "font":
            b = h.body()
            if b.get("role") not in ROLE_WEIGHTS:
                raise ValueError("role must be display or body")
            h.send_json({"font": font_download(bid, b["role"], b["font"]), "files": kit_files(bid)}); return True
        return False
    return False
