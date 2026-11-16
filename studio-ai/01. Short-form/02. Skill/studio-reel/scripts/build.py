#!/usr/bin/env python3
"""Build a HyperFrames reel composition (index.html) from reel.json + transcript.json.

    python3 build.py <project-dir>

The project dir needs: reel.json, transcript.json (word-level, timed on the
edited video) and the edited video named in reel.json. Template CSS/JS and
assets are copied in on first run. See references/reel-spec.md for the spec.
"""
import json, re, html, shutil, sys, urllib.request
from pathlib import Path

SKILL = Path(__file__).resolve().parent.parent
TPL = SKILL / "template"
proj = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
spec = json.load(open(proj / "reel.json"))
words = json.load(open(proj / "transcript.json"))
DUR = float(spec["duration"])                       # length of the edited video
END = spec.get("endcard")                            # optional branded end screen after it
TOTAL = DUR + (float(END.get("duration", 3.5)) if END else 0)
# canvas formats. Cards keep their designs; outside "reel" each card group is scaled and centred on a
# panel point (cx, cy), chips on (cx, chipY). Landscape's panel side comes from layout.cards: right | left | centre.
FORMATS = {
    "reel":      {"w": 1080, "h": 1920, "res": "portrait"},
    "feed":      {"w": 1080, "h": 1350, "res": "portrait", "cx": 540, "cy": 1040, "scale": 0.86, "chipY": 92, "chipScale": 0.9,
                  "cap_top": 660, "cap_size": 64, "cap_side": 40},
    "square":    {"w": 1080, "h": 1080, "res": "square", "cx": 540, "cy": 832, "scale": 0.74, "chipY": 80, "chipScale": 0.82,
                  "cap_top": 560, "cap_size": 58, "cap_side": 60},
    "landscape": {"w": 1920, "h": 1080, "res": "landscape", "cx": 1400, "cy": 470, "scale": 0.78, "chipY": 100, "chipScale": 0.85,
                  "cap_top": 880, "cap_size": 60, "cap_side": 300},
}
FORMAT = spec.get("format", "reel") if spec.get("format", "reel") in FORMATS else "reel"
FMT = FORMATS[FORMAT]
CW, CH = FMT["w"], FMT["h"]
LAYOUT = spec.get("layout", {})
if FORMAT == "landscape":
    FMT = dict(FMT, cx={"left": 520, "centre": 960, "center": 960}.get(LAYOUT.get("cards", "right"), 1400))

T = [w["start"] for w in words]
for k, v in spec.get("captions", {}).get("at", {}).items():  # pin a word's start where the transcript drifts
    T[int(k)] = float(v)

# ---------------------------------------------------------------- assets
for sub in ("fonts", "vendor", "icons", "sfx", "brand", "logos"):
    (proj / "assets" / sub).mkdir(parents=True, exist_ok=True)
    for f in (TPL / "assets" / sub).iterdir():
        dst = proj / "assets" / sub / f.name
        if not dst.exists():
            shutil.copy(f, dst)

# ---------------------------------------------------------------- brand: a client kit (scripts/brand.py); the default brand needs none
BRAND_ID = spec.get("brand") or "default"
BRAND_CSS, BRAND = "", None
if BRAND_ID != "default":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import brand as brandkit
    _kit = brandkit.load(BRAND_ID, proj)
    if _kit:
        BRAND_CSS, BRAND = brandkit.reel_css(_kit, proj)
    else:
        print(f"warning: brand kit '{BRAND_ID}' not found; using the default look", file=sys.stderr)

def icon_src(name):
    p = TPL / "assets/icons" / f"{name}.svg"
    if not p.exists():  # any Lucide icon / simple-icons logo by name; cached into the skill for next time
        url = (f"https://cdn.jsdelivr.net/npm/simple-icons@13/icons/{name[3:]}.svg" if name.startswith("si-")
               else f"https://unpkg.com/lucide-static@0.460.0/icons/{name}.svg")
        p.write_bytes(urllib.request.urlopen(url, timeout=20).read())
    shutil.copy(p, proj / "assets/icons" / p.name)
    return p.read_text()

def icon(name, cls="", draw=False):
    inner = re.sub(r"<!--.*?-->", "", icon_src(name), flags=re.S)
    inner = re.search(r"<svg[^>]*>(.*)</svg>", inner, re.S).group(1).strip()
    if draw:
        inner = re.sub(r"<(path|circle|rect|ellipse|line|polyline)\b", r'<\1 pathLength="1"', inner)
    return (f'<svg class="ic {cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')

def si_path(name):
    return re.search(r'<path d="([^"]+)"', icon_src(f"si-{name}")).group(1)

LOGOS = {
    "ghl": lambda: '<svg class="logo" viewBox="0 0 24 24"><rect x="3.2" y="9" width="3.6" height="12" rx=".6" fill="#F5B400"/><path d="M1 10 5 4l4 6z" fill="#F5B400"/>'
                   '<rect x="10.2" y="13.5" width="3.6" height="7.5" rx=".6" fill="#2F7CF6"/><path d="M8 14.5 12 9l4 5.5z" fill="#2F7CF6"/>'
                   '<rect x="17.2" y="8" width="3.6" height="13" rx=".6" fill="#2DBE5B"/><path d="M15 9 19 3l4 6z" fill="#2DBE5B"/></svg>',
    "sm": lambda: '<svg class="logo" viewBox="0 0 24 24"><circle cx="12" cy="12" r="11" fill="#E5312D"/><rect x="6" y="6.6" width="9" height="2.8" rx="1.1" fill="#fff"/>'
                  '<rect x="6" y="10.6" width="12" height="2.8" rx="1.1" fill="#fff"/><rect x="6" y="14.6" width="7" height="2.8" rx="1.1" fill="#fff"/></svg>',
    "meta": lambda: f'<svg class="logo" viewBox="0 0 24 24"><path fill="url(#gMeta)" d="{si_path("meta")}"/></svg>',
    "gads": lambda: '<svg class="logo" viewBox="0 0 24 24"><line x1="5" y1="18.5" x2="10.6" y2="6" stroke="#FBBC04" stroke-width="6.6" stroke-linecap="round"/>'
                    '<line x1="12" y1="5" x2="19" y2="18.5" stroke="#4285F4" stroke-width="6.6" stroke-linecap="round"/><circle cx="5" cy="18.5" r="3.4" fill="#34A853"/></svg>',
    "claude": lambda: f'<svg class="logo" viewBox="0 0 24 24"><path fill="#D97757" d="{si_path("claude")}"/></svg>',
}

def logo(key):
    """A brand logo key (ghl, sm, meta, gads, claude), an image in template/assets/logos (fathom, slack,
    gmail, or any '<name>' with a matching .png/.svg there), 'si:<simple-icons name>[:#hex]', or 'icon:<lucide name>'."""
    for ext in ("png", "svg"):
        if (TPL / "assets/logos" / f"{key}.{ext}").exists():
            return f'<img class="logo" src="assets/logos/{key}.{ext}" alt="" />'
    if key.startswith("icon:"):
        return icon(key[5:])
    if key.startswith("si:"):
        parts = key.split(":")
        colour = parts[2] if len(parts) > 2 else "#ffffff"
        return f'<svg class="logo" viewBox="0 0 24 24"><path fill="{colour}" d="{si_path(parts[1])}"/></svg>'
    return LOGOS[key]()

esc = html.escape

# ---------------------------------------------------------------- captions
cap = spec.get("captions", {})
FIX = {int(k): v for k, v in cap.get("fix", {}).items()}
DROP = set(cap.get("drop", []))
KW = set(cap.get("keywords", []))
KW_WORDS = {w.lower() for w in cap.get("keyword_words", [])}
LEAD = cap.get("lead", 0.05)

def clean(i):
    return re.sub(r"[^\w']", "", FIX.get(i, words[i]["text"]).lower())

def is_kw(i):
    return i in KW or clean(i) in KW_WORDS

BREAK_BEFORE = {"and", "or", "but", "because", "so", "then", "which", "what", "that's", "if", "when", "really", "like", "the"}
NO_END = {"the", "a", "an", "to", "of", "your", "my", "our", "for", "in", "on", "with", "is", "are", "be", "i", "i'd", "you", "we"}

def auto_groups(max_words=3, gap=0.3):
    """Split at sentence ends and pauses into phrases, then cut each phrase into
    1-3 word chunks choosing the split that reads most naturally: chunks start on
    conjunctions/keywords, never end on an article or preposition, sizes stay even."""
    live = [i for i in range(len(words)) if i not in DROP]
    phrases, cur = [], []
    for n, i in enumerate(live):
        cur.append(i)
        nxt = live[n + 1] if n + 1 < len(live) else None
        if nxt is None or re.search(r"[.?!]$", FIX.get(i, words[i]["text"])) or words[nxt]["start"] - words[i]["end"] > gap:
            phrases.append(cur); cur = []

    def cost(chunk):
        c = 0.0
        if clean(chunk[-1]) in NO_END: c += 3
        if len(chunk) == 1 and not is_kw(chunk[0]): c += 1.5
        if clean(chunk[0]) in BREAK_BEFORE or is_kw(chunk[0]): c -= 0.8
        if is_kw(chunk[0]) and chunk[0] - 1 >= 0 and is_kw(chunk[0] - 1) and chunk[0] - 1 not in DROP: c += 3  # keep "human judgement" together
        return c + 0.4 * abs(len(chunk) - 2.5)

    groups = []
    for p in phrases:
        best = {0: (0.0, [])}  # best split of p[:k]
        for k in range(1, len(p) + 1):
            best[k] = min((best[j][0] + cost(p[j:k]), best[j][1] + [p[j:k]]) for j in range(max(0, k - max_words), k))
        groups += [(c[0], c[-1]) for c in best[len(p)][1]]
    return groups

GROUPS = [tuple(g) for g in cap["groups"]] if cap.get("groups") else auto_groups(cap.get("max_words", 3))
TK = spec.get("takeovers") or []
TKW = [(k["t"], min(k.get("out", DUR), DUR)) for k in TK]
caps_html, js = [], []
for gi, (a, b) in enumerate(GROUPS):
    start = T[a] - LEAD - 0.02
    if any(t0 - 0.05 <= start < t1 - 0.1 for t0, t1 in TKW):
        continue  # a takeover's own text carries these words
    end = (T[GROUPS[gi + 1][0]] - LEAD - 0.02) if gi + 1 < len(GROUPS) else DUR
    end = min([end, words[b]["end"] + 0.9, DUR] + [t0 for t0, _ in TKW if t0 > start])  # clear before a takeover
    spans = []
    for i in range(a, b + 1):
        if i in DROP:
            continue
        txt = FIX.get(i, words[i]["text"]).rstrip(",")
        spans.append(f'<span class="{"w kw" if is_kw(i) else "w"}" id="w{i}">{esc(txt)}</span>')
        js.append(f"word('#w{i}', {T[i] - LEAD:.3f});")
    caps_html.append(f'<div class="cap clip" id="g{gi}" data-start="{start:.3f}" data-duration="{end - start:.3f}" data-track-index="3">'
                     + " ".join(spans) + "</div>")
    js.append(f"capOut('#g{gi}', {end:.3f});")

# ---------------------------------------------------------------- cards
def pos(x, y, extra=""):
    return f'style="left:{x}px;top:{y}px;{extra}"'

def r_questions(cid, c):
    top = c.get("top", 1240); xs = [96, 386, 158]
    return "".join(f'<div class="pill g" id="{cid}-q{i}" {pos(xs[i % 3], top + 82 * i)}><span class="dot">{icon(c.get("icon", "message-square"))}</span>'
                   f'<span class="ptxt">{esc(t)}</span></div>' for i, t in enumerate(c["items"]))

def r_hub(cid, c):
    top = c.get("top", 1200)
    L, R = c["left"], c["right"]
    tiles = "".join(f'<div class="tile g side" {pos(160, top + 88 * i)}>{icon(n)}</div>' for i, n in enumerate(L)) + \
            "".join(f'<div class="tile g side" {pos(686, top + 88 * i)}>{icon(n)}</div>' for i, n in enumerate(R))
    cy = top + 130
    paths = "".join(f'<path class="ln" pathLength="1" d="M244 {top + 88 * i + 42} C318 {top + 88 * i + 42} 318 {cy} 392 {cy}"/>' for i in range(len(L))) + \
            "".join(f'<path class="ln" pathLength="1" d="M534 {cy} C610 {cy} 610 {top + 88 * i + 42} 686 {top + 88 * i + 42}"/>' for i in range(len(R)))
    return (f'<svg class="lines" viewBox="0 0 1080 1920">{paths}</svg>{tiles}'
            f'<div class="hub g" {pos(392, top + 59)}><div class="orb">{icon(c.get("center", "database"))}</div></div>')

def r_statement(cid, c):
    # optional "leads": words that cycle in the same spot before the final word, e.g. Writing -> Producing -> Content
    leads = "".join(f'<span class="sword lead">{esc(l["text"])}</span>' for l in c.get("leads", []))
    return (f'<div class="card g statement" {pos(170, c.get("top", 1222))}><div class="kick">{esc(c["kicker"])}</div>'
            f'<div class="srow"><span class="sicon">{icon(c.get("icon", "lightbulb"), draw=True)}</span>'
            f'<span class="swords">{leads}<span class="sword final">{esc(c["word"])}<i class="uline"></i></span></span></div></div>')

def r_compare(cid, c):
    top = c.get("top", 1230)
    def card(side, x, d):
        def row(r, cls):
            ok = r.get("ok", True)
            return (f'<div class="frow {cls}"><span class="fdot {"ok" if ok else "no"}">{icon("check" if ok else "x")}</span>'
                    f'<span>{esc(r["text"])}</span></div>')
        rows = row(d["first"], "ra") + (row(d["then"], "rb") if d.get("then") else "")
        return (f'<div class="card g flipc" id="{cid}-{side}" {pos(x, top, "width:410px;height:188px")}>'
                f'<div class="kick">{esc(d["kicker"])}</div><div class="rows">{rows}</div></div>')
    swap = f'<div class="swap" {pos(486, top + 61)}>{icon("arrow-left-right")}</div>' if c.get("t_swap") else ""
    return card("a", 96, c["left"]) + card("b", 532, c["right"]) + swap

def r_steps(cid, c):
    top = c.get("top", 1232); n = len(c["steps"])
    out = ""
    for i, s in enumerate(c["steps"]):
        extra = icon(s["badge_icon"], "zp") if s.get("badge_icon") else ""
        sub = f'<div class="ssub">{esc(s["sub"])}</div>' if s.get("sub") else ""
        long = " long" if len(s["label"]) > 11 else ""
        out += (f'<div class="card g step{" has-sub" if sub else ""}" id="{cid}-s{i}" {pos(96 + i * 268, top, "width:250px;height:178px")}>'
                f'<span class="num">{i + 1}</span><div class="sic">{icon(s["icon"])}{extra}</div>'
                f'<div class="slab{long}">{esc(s["label"])}</div>{sub}</div>')
    return out + f'<div class="bar" {pos(96, top + 200, f"width:{n * 268 - 18}px")}><i></i></div>'

def r_chip(cid, c):
    # text like "Insights -> *Action*" or "So how*?*": *...* = gradient, -> = arrow icon
    def fmt(seg):
        return re.sub(r"\*(.+?)\*", lambda m: f'<span class="gt">{m.group(1)}</span>', esc(seg.strip()))
    inner = icon("arrow-right", "arr").join(f"<span>{fmt(s)}</span>" for s in c["text"].split("->"))
    return f'<div class="chip g">{inner}</div>'

def r_feature(cid, c):
    rest = f' <span id="{cid}-w2">{esc(c["title_rest"])}</span>' if c.get("title_rest") else ""
    return (f'<div class="card g hug" {pos(140, c.get("top", 1232))}><div class="itile">{icon(c["icon"])}</div>'
            f'<div class="mcol"><div class="kick">{esc(c["kicker"])}</div>'
            f'<div class="mtitle"><span class="gt" id="{cid}-w1">{esc(c["title"])}</span>{rest}</div></div></div>')

def r_tiles(cid, c):
    top = c.get("top", 1210); n = len(c["items"])
    out = "".join(f'<div class="app g" id="{cid}-a{i}" {pos(110 + i * 194, top)}>{logo(it["logo"])}<span>{esc(it["label"])}</span></div>'
                  for i, it in enumerate(c["items"]))
    if c.get("plus"):
        centre = 110 + ((n - 1) * 194 + 178) / 2
        w = 74 + 18 * len(c["plus"])
        out += f'<div class="pill g plus" {pos(int(centre - w / 2), top + 194)}>{icon("plus")}<span>{esc(c["plus"])}</span></div>'
    return out

def r_connect(cid, c):
    top = c.get("top", 1192); sats = c["satellites"]
    spots = [(105, top), (105, top + 130), (705, top), (705, top + 130)]
    lines = (f'<path class="ln" pathLength="1" d="M222 {top + 60} C290 {top + 60} 290 {top + 108} 355 {top + 108}"/>'
             f'<path class="ln" pathLength="1" d="M222 {top + 190} C290 {top + 190} 290 {top + 153} 355 {top + 153}"/>'
             f'<path class="ln" pathLength="1" d="M570 {top + 108} C636 {top + 108} 636 {top + 60} 705 {top + 60}"/>'
             f'<path class="ln" pathLength="1" d="M570 {top + 153} C636 {top + 153} 636 {top + 190} 705 {top + 190}"/>')
    badge = f'<span class="mbadge">{esc(c["badge"])}</span>' if c.get("badge") else ""
    return (f'<svg class="lines" viewBox="0 0 1080 1920">{lines}</svg>'
            + "".join(f'<div class="mini g" {pos(x, y)}>{logo(k)}</div>' for k, (x, y) in zip(sats, spots))
            + f'<div class="ctile g" {pos(355, top + 20)}>{badge}{logo(c["center"])}<span class="cname">{esc(c["label"])}</span></div>')

def r_chat(cid, c):
    chars = "".join(f'<span class="ch">{esc(ch)}</span>' for ch in c["question"])
    pulls = "".join(f'<span class="pl">{logo(k)}</span>' for k in c.get("sources", []))
    return (f'<div class="card g chat" {pos(100, c.get("top", 1203), "width:722px;height:240px")}>'
            f'<div class="chead">{logo(c.get("logo", "claude"))}<b>{esc(c.get("name", "Claude"))}</b>'
            + (f'<span class="src"><i></i>{esc(c["status"])}</span>' if c.get("status") else "") + '</div>'
            f'<div class="ubub">{chars}</div><div class="abub dots"><i></i><i></i><i></i></div>'
            f'<div class="abub pull"><span>{esc(c.get("result", "Pulling data from"))}</span>{pulls}</div></div>')

def r_task(cid, c):
    return (f'<div class="card g hug task" {pos(96, c.get("top", 1240))}><div class="itile sm">{icon(c.get("icon", "calendar-clock"))}</div>'
            f'<div class="mcol"><div class="kick">{esc(c["kicker"])}</div><div class="stitle">{esc(c["title"])}</div>'
            f'<div class="ssub2">{esc(c.get("sub", ""))}</div></div><div class="tog"><i></i></div></div>')

def r_text(cid, c):
    # free text: "Book your *free audit*" (*...* = gradient); style "glass" (card) or "bare" (text only)
    def fmt(w):
        return re.sub(r"\*(.+?)\*", lambda m: f'<span class="gt">{m.group(1)}</span>', esc(w))
    words = re.findall(r"\*[^*]+\*|\S+", c["text"])
    body = " ".join(f'<span class="tw">{fmt(w)}</span>' for w in words)
    kick = f'<div class="kick">{esc(c["kicker"])}</div>' if c.get("kicker") else ""
    cls = "bare" if c.get("style") == "bare" else "card"
    size = f"--tsize:{c.get('size', 64)}px"
    return f'<div class="g tbox {cls}" {pos(100, c.get("top", 1240), size)}>{kick}<div class="ttext">{body}</div></div>'

RENDER = {k[2:]: v for k, v in globals().items() if k.startswith("r_")}
TIME_KEYS = ("t", "t_left", "t_hub")

cards_html = []
for n, c in enumerate(spec["cards"]):
    cid = f"c{n}"
    first = min([c[k] for k in TIME_KEYS if k in c] + c.get("times", [99]))
    out = min(c.get("out", DUR), DUR)
    start = max(0, first - 0.1)
    end = min(out + 0.05, DUR)
    ydata = f' data-y="{c["y"]}"' if c.get("y") is not None and FORMAT != "reel" else ""   # panel formats
    if c.get("x") is not None:                       # moved sideways in the editor: the group's centre, canvas px
        ydata += f' data-x="{c["x"]}"'
    chip = " is-chip" if c["type"] == "chip" else ""
    cards_html.append(f'<div class="card-host clip{chip}" id="{cid}" data-start="{start:.2f}" data-duration="{end - start:.2f}"{ydata} '
                      f'data-track-index="2">{RENDER[c["type"]](cid, c)}</div>')
    js.append(f"CARD.{c['type']}('{cid}', {json.dumps(dict(c, out=out))});")

# ---------------------------------------------------------------- effects on the video (punch, push, flash)
FX = spec.get("fx") or []
for f in FX:
    js.append(f"fx({json.dumps(f)});")
flash_html = '<div id="flash"></div>' if any(f.get("kind") == "flash" for f in FX) else ""

# ---------------------------------------------------------------- takeovers (gradient cutaways)
# "full": the footage wipes away to the brand gradient; "pip": it shrinks into a floating window
# over the gradient (reel format only; other formats fall back to full). Headline, items or a big stat
# land on their words. Captions under a takeover are left out.
def tk_title(txt):
    return re.sub(r"\*(.+?)\*", lambda m: f'<span class="tku">{m.group(1)}</span>', esc(txt))

tk_html = []
for n, k in enumerate(TK):
    kid = f"tk{n}"
    mode = k.get("mode", "full") if FORMAT == "reel" else "full"
    t0 = k["t"]; t1 = min(k.get("out", DUR), DUR); span = f'data-start="{t0:.2f}" data-duration="{t1 - t0 + 0.05:.2f}"'
    body = f'<div class="tkkick">{esc(k["kicker"])}</div>' if k.get("kicker") else ""
    if k.get("title"):
        body += '<div class="tktitle">' + " ".join(f'<span class="tw">{tk_title(w)}</span>' for w in k["title"].split(" ")) + "</div>"
    if k.get("stat"):
        st = k["stat"]
        body += (f'<div class="tkstat" style="font-size:{st.get("size", 300)}px"><span class="tkval">{esc(st.get("value", ""))}</span></div>'
                 + ('<div class="tkbar"><i></i></div>' if st.get("bar") else "")
                 + f'<div class="tklabel">{esc(st.get("label", ""))}</div>')
    if k.get("items"):
        rows = ""
        for i, it in enumerate(k["items"]):
            badge = (f'<span class="tkb tkn">{i + 1}</span>' if k.get("numbered")
                     else f'<span class="tkb">{logo(it["logo"])}</span>' if it.get("logo") else "")
            rows += f'<div class="tkrow" id="{kid}-r{i}">{badge}<span class="tkt">{esc(it["text"])}</span></div>'
        body += f'<div class="tkitems">{rows}</div>'
    scale = f' style="--tks:{FMT.get("scale", 1)}"' if FORMAT != "reel" else ""
    tk_html.append(f'<div class="tkbg {mode} clip" id="{kid}-bg" {span} data-track-index="{6 + (n % 2) * 2}">'
                   f'<i class="blob b1"></i><i class="blob b2"></i><i class="blob b3"></i></div>'
                   + (f'<div class="pipframe clip" id="{kid}-frame" {span} data-track-index="10"></div>' if mode == "pip" else "")
                   + f'<div class="tkfg {mode} clip" id="{kid}" {span} data-track-index="{7 + (n % 2) * 2}"{scale}><div class="tkbody">{body}</div></div>')
    js.append(f"takeover('{kid}', {json.dumps(dict(k, mode=mode, out=t1, last=t1 >= DUR - 0.01))});")

# ---------------------------------------------------------------- overlay videos (inserts, B-roll, testimonials)
# overlays: [{src, t, dur, in, track, mode: full|pip, x, y, w, h, radius, opacity, fade, muted, volume, duck}]
# src is relative to the project (the editor copies clips into assets/overlays/). in = start point inside the clip.
# Higher track = on top. They sit over the main video, under blurs, cards and captions. muted (default true);
# unmuted plays the clip's sound at volume. duck (0-1) is the speaker's volume while it plays (default 1).
OV = sorted(enumerate(spec.get("overlays") or []), key=lambda p: (int(p[1].get("track", 1)), p[0]))
ov_html, duck = [], []
for n, o in OV:
    t0, d = max(0.0, float(o["t"])), max(0.1, float(o.get("dur", 3)))
    d = min(d, TOTAL - t0)
    if o.get("mode", "full") == "pip":
        w, h = float(o.get("w", CW * 0.42)), float(o.get("h", CW * 0.42 * 16 / 9 if CH > CW else CW * 0.42 * 9 / 16))
        box = (f'left:{float(o.get("x", CW - w - 60)):.0f}px;top:{float(o.get("y", 120)):.0f}px;width:{w:.0f}px;height:{h:.0f}px;'
               f'border-radius:{float(o.get("radius", 28)):.0f}px;box-shadow:0 18px 50px rgba(0,0,0,.45),0 0 0 3px rgba(255,255,255,.85);')
    else:
        box = f"left:0;top:0;width:{CW}px;height:{CH}px;"
    sound = (f'data-has-audio="true" data-volume="{float(o.get("volume", 1)):.2f}"' if o.get("muted") is False else "muted")
    fade = float(o.get("fade", 0.3))
    if o.get("muted") is False and fade:
        sound += f' data-fade-in="{fade:.2f}" data-fade-out="{fade:.2f}"'
    ov_html.append(f'<video id="ov{n}" class="clip overlay" src="{html.escape(o["src"])}" playsinline data-start="{t0:.2f}" data-duration="{d:.2f}" '
                   f'data-media-start="{float(o.get("in", 0)):.2f}" data-track-index="{30 + n}" {sound} '
                   f'style="position:absolute;{box}object-fit:cover;z-index:1;opacity:{float(o.get("opacity", 1)):.2f}"></video>')
    js.append(f"ovfade('ov{n}', {json.dumps(dict(t=t0, dur=d, fade=fade, opacity=float(o.get('opacity', 1))))});")
    if float(o.get("duck", 1)) < 0.999:
        duck.append((t0, t0 + d, max(0.0, float(o.get("duck", 1)))))
# the speaker's volume dips while an overlay with its own sound plays (HyperFrames volume lane on the main video)
duck_attr = ""
if duck:
    pts = [{"t": 0, "v": 1}]
    for a, b, v in sorted(duck):
        a, b = min(a, DUR), min(b, DUR)
        pts += [{"t": round(max(0, a - 0.15), 3), "v": 1}, {"t": round(a + 0.1, 3), "v": v}, {"t": round(max(a + 0.1, b - 0.1), 3), "v": v}, {"t": round(b + 0.15, 3), "v": 1}]
    duck_attr = " data-automation='" + json.dumps({"version": 1, "lanes": [{"target": "volume", "points": pts}]}) + "'"

# ---------------------------------------------------------------- blur / box regions over the footage
# redactions: [{t, dur, type: blur|box, strength, w, h, track, keys: [{dt, x, y}]}], x/y = top-left in canvas px.
# They sit on the video and under cards, captions and takeovers. With track and 2+ keys the box glides between points.
RD = spec.get("redactions") or []
rd_html = []
for n, r in enumerate(RD):
    keys = r.get("keys") or [{"dt": 0, "x": 0, "y": 0}]
    k0 = keys[0]
    kind = r.get("type", "blur")
    look = ("background:#000;" if kind == "box"
            else f"backdrop-filter:blur({float(r.get('strength', 28)):.0f}px);-webkit-backdrop-filter:blur({float(r.get('strength', 28)):.0f}px);background:rgba(128,128,128,.08);")
    t0, d = max(0.0, float(r["t"])), max(0.1, float(r.get("dur", 3)))
    rd_html.append(f'<div class="redact clip" id="rd{n}" data-start="{t0:.2f}" data-duration="{min(d, TOTAL - t0):.2f}" data-track-index="{20 + n}" '
                   f'style="position:absolute;left:{k0["x"]:.0f}px;top:{k0["y"]:.0f}px;width:{float(r.get("w", 300)):.0f}px;height:{float(r.get("h", 200)):.0f}px;'
                   f'z-index:1;border-radius:{float(r.get("radius", 0)):.0f}px;{look}"></div>')
    if r.get("track") and len(keys) > 1:
        js.append(f"redact('rd{n}', {json.dumps(dict(t=t0, keys=keys))});")

# ---------------------------------------------------------------- end screen
end_html = ""
if END:
    # "lines": [{"text": "Visit"}, ..., {"text": "Free AI", "bold": true}, ...]; logo sits below
    lines = END.get("lines") or (BRAND or {}).get("endscreen", {}).get("lines") or [{"text": END.get("headline", "")}, {"text": END.get("sub", "")}]
    elogo = f'assets/brand/{END["logo"]}' if END.get("logo") else BRAND["logo"] if BRAND else "assets/brand/logo-white.svg"
    body = "".join(f'<div class="el {"eb" if l.get("bold") else "er"}">{esc(l["text"])}</div>' for l in lines if l.get("text"))
    end_html = (f'<div class="endcard clip" id="end" data-start="{DUR - 0.45:.2f}" data-duration="{TOTAL - DUR + 0.45:.2f}" data-track-index="4">'
                f'<div class="elines">{body}</div>'
                + (f'<img class="elogo" src="{elogo}" alt="" />' if elogo else "") + '</div>')
    js.append(f"endcard({DUR:.3f});")

# ---------------------------------------------------------------- optional sound
sfx = spec.get("sfx") or []
LEN = {"pop": 0.18, "tick": 0.09}
VOL = {"pop": 0.32, "tick": 0.26}
sfx_html = "".join(f'<audio id="sfx{i}" class="clip" src="assets/sfx/{s["kind"]}.wav" data-start="{s["t"]:.2f}" '
                   f'data-duration="{LEN[s["kind"]]}" data-track-index="5" data-volume="{s.get("volume", VOL[s["kind"]])}"></audio>'
                   for i, s in enumerate(sfx))

# ---------------------------------------------------------------- page
style = (TPL / "brand.css").read_text() + "\n" + (TPL / "styles.css").read_text()
if BRAND_CSS:
    style += "\n" + BRAND_CSS
LINE = BRAND["line"] if BRAND else ["#60a5fa", "#5ca3ff", "#60a5fa"]   # hub connector lines
if FORMAT != "reel":
    style += f"\nhtml, body {{ width: {CW}px; height: {CH}px; }}"
    style += (f"\n:root {{ --cap-top: {FMT['cap_top']}px; --cap-size: {FMT['cap_size']}px; }} "
              f".cap {{ left: {FMT['cap_side']}px; right: {FMT['cap_side']}px; }}")
if cap.get("top"):
    style += f"\n:root {{ --cap-top: {cap['top']}px; }}"
if cap.get("weight"):  # 500 Medium, 600 SemiBold, 700 Bold, 800 ExtraBold (default)
    style += f"\n.cap {{ font-weight: {cap['weight']}; }}"
if cap.get("size"):
    style += f"\n:root {{ --cap-size: {cap['size']}px; }}"
page = f"""<!doctype html>
<html lang="en" data-resolution="{FMT['res']}" data-format="{FORMAT}">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width={CW}, height={CH}" />
<style>
{style}
</style>
</head>
<body>
<svg width="0" height="0" style="position:absolute"><defs>
  <linearGradient id="gMeta" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#0668E1"/><stop offset="1" stop-color="#0081FB"/></linearGradient>
  <linearGradient id="gLine" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{LINE[0]}"/><stop offset=".5" stop-color="{LINE[1]}"/><stop offset="1" stop-color="{LINE[0]}"/></linearGradient>
</defs></svg>
<div id="root" data-composition-id="main" data-start="0" data-fps="{spec.get('fps', 25)}" data-duration="{TOTAL}" data-width="{CW}" data-height="{CH}">
  <video id="a-roll" class="clip" src="{spec.get('video', 'base-edit.mp4')}" playsinline data-start="0" data-duration="{DUR}" data-track-index="0"
    data-has-audio="true"{duck_attr} style="position:absolute;left:0;top:0;width:{CW}px;height:{CH}px;object-fit:cover;object-position:50% 32%;z-index:1"></video>
  {"".join(ov_html)}
  {"".join(rd_html)}
  {"".join(tk_html)}
  {"".join(cards_html)}
  {"".join(caps_html)}
  {flash_html}
  {end_html}
  {sfx_html}
</div>
<script src="assets/vendor/gsap.min.js"></script>
<script>
window.__DUR = {DUR};
window.__LAYOUT = {json.dumps(dict(format=FORMAT, w=CW, h=CH, **{k: FMT[k] for k in ("cx", "cy", "scale", "chipY", "chipScale") if k in FMT}))};
(function () {{
{(TPL / "motion-lib.js").read_text()}
{chr(10).join(js)}
window.__timelines = window.__timelines || {{}};
window.__timelines["main"] = tl;
}})();
</script>
</body>
</html>
"""
(proj / "index.html").write_text(page)
print(f"index.html written: {len(GROUPS)} caption groups, {len(spec['cards'])} cards, {len(TK)} takeovers, {len(sfx)} sound effects"
      + (f", {len(RD)} blur regions" if RD else "") + (f", {len(OV)} overlay videos" if OV else "")
      + (f", end screen {TOTAL - DUR:.1f}s (total {TOTAL:.2f}s)" if END else ""))
