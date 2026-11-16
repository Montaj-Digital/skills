#!/usr/bin/env python3
"""Client brand kits for the reel template.

A brand kit is a folder `<Brands>/<id>/` with `brand.json` and its assets (fonts/, logos/, images/).
your brand is the default look and needs no kit: build.py only calls this module when reel.json
has `"brand": "<id>"` with an id other than default, so default reels build byte-for-byte as before.

The kit is applied as one extra stylesheet appended after brand.css + styles.css:
  - the :root tokens (colours, gradients, glass tint, glow) are redefined;
  - the client's font files are registered under the template's family names ("Display" for display,
    "Inter" for body), so every rule that names those families picks them up;
  - the few rules in styles.css with literal colours (glows, icon tints, takeover blobs, chat bubble,
    end screen background) are restated with the brand's colours.

    python3 brand.py <brand-id> [project-dir]   # print the CSS (debugging)
"""
import json, os, shutil, sys
from pathlib import Path

DEFAULT = "default"
DISPLAY_WEIGHTS = (500, 600, 700, 800)   # weights the template uses for "Display"
BODY_WEIGHTS = (400, 700)                # and for "Inter"


def brand_dirs(proj=None):
    """Where brand kits can live: $STUDIO_BRANDS, then any '03. Brands' / 'Brands' folder above the project or the skill."""
    out = []
    if os.environ.get("STUDIO_BRANDS"):
        out.append(Path(os.environ["STUDIO_BRANDS"]))
    for start in filter(None, (proj, Path(__file__).resolve())):
        for p in [Path(start).resolve()] + list(Path(start).resolve().parents):
            for name in ("03. Brands", "Brands"):
                if (p / name).is_dir() and (p / name) not in out:
                    out.append(p / name)
    return out


def load(bid, proj=None):
    for d in brand_dirs(proj):
        f = d / bid / "brand.json"
        if f.exists():
            kit = json.loads(f.read_text())
            kit["_dir"] = str(f.parent)
            kit.setdefault("id", bid)
            return kit
    return None   # deleted or not on this Mac: build.py uses the default look and says so


# ---------------------------------------------------------------- colour helpers
def rgb(c):
    """'#rrggbb' / '#rgb' / 'rgb(a)(r, g, b, …)' -> (r, g, b)."""
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


def rgba(c, a):
    r, g, b = rgb(c)
    return f"rgba({r}, {g}, {b}, {a})"


def mix(c, other, t):
    """Blend colour c towards other by t (0..1)."""
    a, b = rgb(c), rgb(other)
    return "#" + "".join(f"{round(x + (y - x) * t):02x}" for x, y in zip(a, b))


def nearest(files, weight):
    return min(files, key=lambda f: (abs(int(f.get("weight", 400)) - weight), -int(f.get("weight", 400))))


# ---------------------------------------------------------------- the stylesheet
def reel_css(kit, proj, copy=True):
    """Copy the kit's assets into <proj>/assets/brand/<id>/ and return (css, info) for build.py.
    copy=False only writes the CSS (the Studio's Brand screen serves the kit's files at the same URLs)."""
    bid, src = kit["id"], Path(kit["_dir"])
    dst = Path(proj) / "assets/brand" / bid
    if copy:
        dst.mkdir(parents=True, exist_ok=True)

    def asset(rel):
        if not rel:
            return None
        f = src / rel
        if not f.exists():
            return None
        out = dst / rel
        if copy and (not out.exists() or out.stat().st_mtime < f.stat().st_mtime):
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(f, out)
        return f"assets/brand/{bid}/{rel}"

    col = kit.get("colors", {})
    P = col.get("primary", "#2563eb")
    A = col.get("accent", P)
    G = (col.get("gradient") or [A, P]) + [P]
    K = (col.get("keyword") or [G[0], mix(G[0], G[1], 0.5), G[1]])
    K = (K + K[-1:] * 3)[:3]
    H = col.get("highlight", mix(P, "#4aa8ff", 0.6))
    kicker = col.get("kicker", mix(A, "#ffffff", 0.45))
    tint = col.get("glass_tint") or [rgba(mix(P, "#1d1925", 0.75), 0.60), rgba(mix(P, "#1d1925", 0.9), 0.74)]
    text = col.get("text", "#ffffff")
    tk_bg = col.get("takeover_bg", mix(P, "#000000", 0.55))

    css = [f"/* brand kit: {kit.get('name', bid)} */"]
    # fonts: register the client's files under the template's family names
    fonts = kit.get("fonts", {})
    for role, family, weights in (("display", "Display", DISPLAY_WEIGHTS), ("body", "Inter", BODY_WEIGHTS)):
        files = [f for f in (fonts.get(role) or {}).get("files", []) if (src / f.get("file", "")).exists()]
        for w in weights:
            if files:
                f = nearest(files, w)
                url = asset(f["file"])
                fmt = {"ttf": "truetype", "otf": "opentype", "woff": "woff", "woff2": "woff2"}.get(url.rsplit(".", 1)[-1].lower(), "truetype")
                css.append(f'@font-face {{ font-family: "{family}"; src: url("{url}") format("{fmt}"); font-weight: {w}; font-display: block; }}')
            else:  # no file in the kit: never fall back to the licensed default font
                css.append(f'@font-face {{ font-family: "{family}"; src: local("Helvetica Neue"), local("Arial"); font-weight: {w}; }}')

    gr, gg, gb = rgb(K[1])
    css.append(f""":root {{
  --magenta: {A}; --violet: {P}; --lilac: {kicker}; --blue: {H};
  --grad: linear-gradient(265.4deg, {G[0]} -26.78%, {G[1]} 111.51%);
  --grad-text: linear-gradient(90deg, {K[0]} 0%, {K[1]} 45%, {K[2]} 100%);
  --glass: linear-gradient(160deg, {tint[0]} 0%, {tint[-1]} 100%);
  --glow-rgb: {gr}, {gg}, {gb};
}}""")
    if text.lower() not in ("#fff", "#ffffff"):
        css.append(f"html, body {{ color: {text}; }}")
    # rules in styles.css with literal colours
    css.append(f""".g::before {{ background: linear-gradient(135deg, {A} 0%, {rgba(K[1], 0.55)} 45%, {rgba(K[2], 0.25)} 70%, {K[2]} 100%); }}
.pill .dot {{ box-shadow: 0 0 18px {rgba(A, 0.45)}; }}
.orb {{ background: radial-gradient(circle at 35% 30%, {mix(A, '#ffffff', 0.45)} 0%, {K[1]} 35%, {P} 100%); box-shadow: 0 0 36px {rgba(A, 0.55)}; }}
.fdot.ok {{ box-shadow: 0 0 20px {rgba(H, 0.55)}; }}
.fdot.no {{ box-shadow: 0 0 20px {rgba(A, 0.55)}; }}
.swap {{ box-shadow: 0 0 24px {rgba(A, 0.5)}; }}
.itile {{ box-shadow: 0 0 30px {rgba(A, 0.35)}; }}
.chip .arr, .app .ic, .plus .ic, .ctile .ic, .chead .ic {{ color: {K[1]}; }}
.ubub {{ background: linear-gradient(90deg, {A} 0%, {K[2]} 100%); box-shadow: 0 8px 26px {rgba(A, 0.35)}; }}
.tkbg {{ background: {tk_bg}; }}
.b1 {{ background: {A}; }}
.b2 {{ background: {H}; }}
.b3 {{ background: {P}; }}
.tkb .ic, .tkb.tkn {{ color: {P}; }}""")
    bg = asset((kit.get("images") or {}).get("background"))
    # no background image: a gradient from the dark takeover base into the brand colour, so white text stays readable
    bg_css = f'url("{bg}") center / cover' if bg else f"linear-gradient(160deg, {tk_bg} 0%, {mix(tk_bg, P, 0.45)} 65%, {P} 130%)"
    css.append(f".endcard::before, .tkbg::before {{ background: {bg_css}; }}")
    # captions: keywords as the gradient (default) or one solid colour
    cap = kit.get("captions", {})
    if cap.get("keyword") and cap["keyword"] != "gradient":
        css.append(f".cap .kw {{ background-image: none; color: {cap['keyword']}; }}")
    if cap.get("weight"):
        css.append(f".cap {{ font-weight: {int(cap['weight'])}; }}")

    logos = kit.get("logos", {})
    info = {
        "logo": asset(logos.get("light")) or asset(logos.get("dark")),   # end screen sits on a dark background
        "line": K,                                                         # hub connector line gradient
        "endscreen": kit.get("endscreen", {}),
    }
    return "\n".join(css), info


if __name__ == "__main__":
    k = load(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(reel_css(k, sys.argv[2] if len(sys.argv) > 2 else "/tmp/brand-preview")[0])
