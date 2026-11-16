"""Brand kits for Studio AI: list, load, save, assets, and the long-form overlay stylesheet.

Used by the short-form server (the /api/brands routes and the Brand screen) and by long-form (preview + render).
The studio-reel skill has its own copy of the CSS logic in scripts/brand.py so the skill stays standalone.
Python 3.9 standard library only.
"""
import json, re, shutil, time
from pathlib import Path

HOME = Path(__file__).resolve().parent          # this folder: the default kit, the Swift tools
BRANDS = HOME                                   # (old name)
DEFAULT = "default"


def root():
    """Where client kits live. A Mac: this folder. The portal's server replaces this with the team's kits folder."""
    return HOME


def bin_dir():
    """Where deleted kits go (the server replaces this with the workspace's: the Mac's Bin, Windows: Studio AI/Bin)."""
    return Path.home() / ".Trash"
FONT_EXT = {".ttf": "truetype", ".otf": "opentype", ".woff": "woff", ".woff2": "woff2"}
IMG_EXT = {".svg", ".png", ".jpg", ".jpeg", ".webp"}


def slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return s[:48] or "client"


def kit_dir(bid):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", bid or ""):
        raise ValueError(f"Bad brand id {bid!r}")
    return HOME / bid if bid == DEFAULT else root() / bid


def safe_file(bid, rel):
    """A file inside the kit (no escaping it with ../)."""
    d = kit_dir(bid).resolve()
    f = (d / rel).resolve()
    if d not in f.parents:
        raise ValueError("Path outside the brand kit")
    return f


def load(bid):
    f = kit_dir(bid) / "brand.json"
    if not f.exists():
        raise FileNotFoundError(f"No brand kit '{bid}'")
    kit = json.loads(f.read_text())
    kit["id"] = bid
    return kit


def list_brands():
    out = []
    files = sorted(root().glob("*/brand.json"))
    if root() != HOME and (HOME / DEFAULT / "brand.json").exists():
        files = [HOME / DEFAULT / "brand.json"] + [f for f in files if f.parent.name != DEFAULT]
    for f in files:
        try:
            k = json.loads(f.read_text())
        except ValueError:
            continue
        bid = f.parent.name
        out.append({"id": bid, "name": k.get("name", bid), "default": bid == DEFAULT,
                    "colors": k.get("colors", {}), "logo": (k.get("logos") or {}).get("light"), "website": k.get("website", ""),
                    "lines": [l for l in (k.get("endscreen") or {}).get("lines") or [] if (l.get("text") or "").strip()],
                    "updated": f.stat().st_mtime})
    out.sort(key=lambda b: (not b["default"], b["name"].lower()))
    return out


def save(bid, data):
    """Write brand.json (the previous one goes to .backups/)."""
    d = kit_dir(bid)
    d.mkdir(parents=True, exist_ok=True)
    f = d / "brand.json"
    if f.exists():
        (d / ".backups").mkdir(exist_ok=True)
        shutil.copy(f, d / ".backups" / f"brand-{time.strftime('%Y%m%d-%H%M%S')}.json")
    data = {k: v for k, v in data.items() if not k.startswith("_")}
    data["id"] = bid
    f.write_text(json.dumps(data, indent=2) + "\n")
    return data


def trash(bid):
    """Move a client's kit to the Bin (it can be put back from there). the default brand can't be deleted."""
    if bid == DEFAULT:
        raise ValueError("your brand is the built-in look; it can't be deleted")
    d = kit_dir(bid)
    if not (d / "brand.json").exists():
        raise FileNotFoundError(f"No brand kit '{bid}'")
    bin_ = bin_dir(); bin_.mkdir(parents=True, exist_ok=True)
    dst, n = bin_ / f"{d.name} (brand kit)", 2
    while dst.exists():
        dst = bin_ / f"{d.name} (brand kit) {n}"; n += 1
    shutil.move(str(d), str(dst))
    return dst


def new_kit(name):
    """A fresh kit from a name; colours start from your brand's so the preview isn't empty."""
    bid = slug(name)
    n = 2
    while kit_dir(bid).exists() or bid == DEFAULT:
        bid = f"{slug(name)}-{n}"; n += 1
    base = load(DEFAULT)
    kit = {"id": bid, "name": name, "website": "", "colors": base["colors"],
           "fonts": {"display": {"family": "", "files": []}, "body": {"family": "", "files": []}},
           "logos": {"light": None, "dark": None, "mark": None}, "images": {"background": None},
           "captions": {"keyword": "gradient", "weight": 800},
           "endscreen": {"lines": [{"text": "Visit"}, {"text": "your website"}], "cta": ""},
           "voice": {"tone": "", "cta": ""}}
    return save(bid, kit)


def add_file(bid, sub, name, data):
    """Store an uploaded file in fonts/, logos/ or images/ and return its path inside the kit."""
    if sub not in ("fonts", "logos", "images"):
        raise ValueError("Unknown folder")
    ext = Path(name).suffix.lower()
    if (sub == "fonts" and ext not in FONT_EXT) or (sub != "fonts" and ext not in IMG_EXT):
        raise ValueError(f"{ext or 'That file'} can't go in {sub}")
    clean = re.sub(r"[^A-Za-z0-9._-]+", "-", Path(name).stem).strip("-")[:60] or "file"
    rel = f"{sub}/{clean}{ext}"
    f = safe_file(bid, rel)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return rel


# ---------------------------------------------------------------- colours
def rgb(c):
    c = str(c).strip()
    if c.startswith("#"):
        h = c[1:]
        if len(h) in (3, 4):
            h = "".join(ch * 2 for ch in h[:3])
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    if c.startswith("rgb"):
        parts = c[c.index("(") + 1:c.rindex(")")].replace("/", ",").split(",")
        return tuple(int(float(x)) for x in parts[:3])
    raise ValueError(f"Can't read colour {c!r}")


def mix(c, other, t):
    a, b = rgb(c), rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def rgba(c, a):
    r, g, b = rgb(c)
    return f"rgba({r}, {g}, {b}, {a})"


def contrast(a, b):
    """WCAG contrast ratio between two colours (1 to 21)."""
    def lum(c):
        ch = [x / 255 for x in rgb(c)]
        ch = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in ch]
        return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2]
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return round((la + 0.05) / (lb + 0.05), 2)


# ---------------------------------------------------------------- long-form overlays
def long_css(kit, prefix):
    """CSS that sets the --ov-* variables of long-form overlays.css, plus @font-face rules.
    prefix = where the kit's files are served from ('/brands/<id>/' in the editor, 'brand/' in the render stage).
    Font families get unique names so the editor's own UI fonts are never replaced."""
    bid = kit["id"]
    col = kit.get("colors", {})
    P = col.get("primary", "#2563eb")
    A = col.get("accent", P)
    G = (col.get("gradient") or [A, P]) + [P]
    K = (col.get("keyword") or [G[0], mix(G[0], G[1], 0.5), G[1]])
    K = (K + K[-1:] * 3)[:3]
    css, fams = [f"/* brand kit: {kit.get('name', bid)} */"], {}
    for role in ("display", "body"):
        files = [f for f in ((kit.get("fonts") or {}).get(role) or {}).get("files", []) if (kit_dir(bid) / f.get("file", "")).exists()]
        if files:
            fams[role] = f"Brand {role.title()} {bid}"
            for f in files:
                fmt = FONT_EXT.get(Path(f["file"]).suffix.lower(), "truetype")
                css.append(f'@font-face {{ font-family: "{fams[role]}"; src: url("{prefix}{f["file"]}") format("{fmt}"); '
                           f'font-weight: {int(f.get("weight", 400))}; font-style: {f.get("style", "normal")}; }}')
    base = col.get("takeover_bg", mix(P, "#000000", 0.6))
    bg = (kit.get("images") or {}).get("background")
    end_bg = (f'url("{prefix}{bg}") center / cover' if bg and (kit_dir(bid) / bg).exists()
              else f"radial-gradient(60% 80% at 15% 0%, {rgba(A, 0.33)} 0%, transparent 60%), "
                   f"linear-gradient(160deg, {base} 0%, {mix(base, P, 0.45)} 70%, {P} 130%)")
    v = {
        "--ov-primary": G[1], "--ov-accent": G[0], "--ov-bar-b": mix(G[1], "#ffffff", 0.3),
        "--ov-glass": rgba(mix(P, "#000000", 0.6), 0.9),
        "--ov-big-a": mix(K[0], "#ffffff", 0.35), "--ov-big-b": mix(K[2], "#ffffff", 0.55),
        "--ov-end-bg": end_bg, "--ov-end-bold": mix(K[0], "#ffffff", 0.45), "--ov-keyword": mix(K[1], "#ffffff", 0.6),
        "--ov-font-display": f'"{fams["display"]}"' if "display" in fams else '"Helvetica Neue", Arial',
        "--ov-font-body": f'"{fams["body"]}"' if "body" in fams else '"Helvetica Neue", Arial',
    }
    css.append(".ov-root { " + " ".join(f"{k}: {val};" for k, val in v.items()) + " }")
    return "\n".join(css)


def long_files(kit):
    """Kit files the long-form render stage needs (fonts, light logo, background)."""
    bid, out = kit["id"], []
    for role in ("display", "body"):
        out += [f["file"] for f in ((kit.get("fonts") or {}).get(role) or {}).get("files", [])]
    out += [x for x in ((kit.get("logos") or {}).get("light"), (kit.get("images") or {}).get("background")) if x]
    return [r for r in out if (kit_dir(bid) / r).exists()]


# ---------------------------------------------------------------- per video: prompts, end screen, renders folder
def client(bid):
    """The kit of a client brand, or None for the default brand / no brand / a missing kit."""
    if not bid or bid == DEFAULT:
        return None
    try:
        return load(bid)
    except (FileNotFoundError, ValueError):
        return None


def endcard(bid, default):
    """The end screen a new video starts with: the client's lines, or the default (the default brand)."""
    kit = client(bid)
    lines = [l for l in ((kit or {}).get("endscreen") or {}).get("lines") or [] if (l.get("text") or "").strip()]
    return dict(default, lines=lines) if lines else default


def voice_note(bid):
    """A block for Claude's prompts: who the video is for, their tone and call to action ('' for the default brand)."""
    kit = client(bid)
    if not kit:
        return ""
    v, e = kit.get("voice") or {}, kit.get("endscreen") or {}
    out = [f"THIS VIDEO IS FOR A CLIENT: {kit.get('name', bid)}" + (f" ({kit['website']})" if kit.get("website") else "") + ", not for your brand.",
           "Write every card, takeover and end screen line in the client's voice; never mention your brand."]
    if v.get("tone"):
        out.append(f"Client's tone of voice (this replaces the default brand voice): {v['tone']}")
    cta = v.get("cta") or e.get("cta")
    if cta:
        out.append(f"Client's call to action: {cta}")
    return "\n".join(out)


def display_name(bid):
    kit = client(bid)
    return kit.get("name", bid) if kit else "Your brand"


def folder_name(bid):
    """Renders folder for a client: '06. Renders/<Client name>/<format>/' (the default brand keeps '06. Renders/<format>/')."""
    kit = client(bid)
    if not kit:
        return None
    return re.sub(r'[\\/:*?"<>|]+', "-", kit.get("name") or bid).strip() or bid


def kit_dir_ok(bid):
    """Is this the id of a kit folder that exists? (Never raises.)"""
    try:
        return kit_dir(bid).is_dir()
    except ValueError:
        return False
