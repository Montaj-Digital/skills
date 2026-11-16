"""The brand-guide tools in Python, for Windows and Linux (ROADMAP phase 8, step 6). Same jobs, arguments and output as
pdfpages.swift and logocrop.swift, which macOS keeps using (they need nothing installed there).

Needs: numpy, pypdfium2 (PDF pages; Google's PDFium, wheels for Windows, macOS and Linux) and Pillow (images).
    python pdftools.py pages <file.pdf> <out dir> [max pages = 80] [width px = 1400]
        → <out>/page-001.png …, <out>/pages.json {"count": N, "pages": [{"page": 1, "file": "page-001.png", "text": "…"}]}
    python pdftools.py logo <file.pdf|image> <page (1-based)> <x> <y> <w> <h> <out dir> <name>
        x, y, w, h: the logo's box as fractions of the page (0-1, from the top left). The box is drawn again at high
        resolution (from the vectors for a PDF), the plain background around the logo is keyed out, and it's trimmed.
        Writes <name>-crop.png (the box as on the page), -color.png (own colours), -light.png (white), -dark.png (#111)
        and prints one line of JSON: {"ok": true, "bg": "#rrggbb", "coverage": 0.21, "size": [w, h]} or {"ok": false, "why": …}
"""
import json, sys
from pathlib import Path

TARGET = 1800.0          # px across the longer side of a logo box
LO, HI = 22.0, 110.0     # colour distance from the background: fully clear below LO, fully solid above HI


def missing():
    """What's not installed (empty when everything is)."""
    out = []
    for mod in ("numpy", "pypdfium2", "PIL"):
        try:
            __import__(mod)
        except ImportError:
            out.append("Pillow" if mod == "PIL" else mod)
    return out


# ---------------------------------------------------------------- pages
def pages(pdf, out, max_pages=80, width=1400):
    import pypdfium2 as pdfium
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(pdf))
    count, items = len(doc), []
    for i in range(min(count, int(max_pages))):
        page = doc[i]
        pw, _ = page.get_size()
        name = f"page-{i + 1:03d}.png"
        page.render(scale=float(width) / pw).to_pil().convert("RGB").save(out / name)
        try:
            text = page.get_textpage().get_text_bounded()
        except Exception:
            text = ""
        items.append({"page": i + 1, "file": name, "text": (text or "").replace("\r\n", "\n")})
    (out / "pages.json").write_text(json.dumps({"count": count, "pages": items}, indent=2), encoding="utf-8")
    return f"{len(items)} of {count} pages"


# ---------------------------------------------------------------- logos
def _box_image(src, page_no, x0, y0, w0, h0):
    """The box drawn at high resolution, on white, as an RGB numpy array."""
    import numpy as np
    from PIL import Image
    src = Path(src)
    if src.suffix.lower() == ".pdf":
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(src))
        if not 1 <= page_no <= len(doc):
            raise ValueError("can't open that page")
        page = doc[page_no - 1]
        pw, ph = page.get_size()
        cw, ch = w0 * pw, h0 * ph
        scale = TARGET / max(cw, ch)
        # crop = how much to cut off each side, in PDF points: (left, bottom, right, top)
        crop = (x0 * pw, (1 - y0 - h0) * ph, (1 - x0 - w0) * pw, y0 * ph)
        img = page.render(scale=scale, crop=crop, fill_color=(255, 255, 255, 255)).to_pil().convert("RGB")
    else:
        try:
            im = Image.open(src).convert("RGBA")
        except Exception:
            raise ValueError("can't open that image")
        white = Image.new("RGBA", im.size, (255, 255, 255, 255))
        im = Image.alpha_composite(white, im).convert("RGB")
        W, H = im.size
        box = (round(x0 * W), round(y0 * H), round((x0 + w0) * W), round((y0 + h0) * H))
        im = im.crop(box)
        scale = TARGET / max(im.size)
        img = im.resize((max(1, round(im.size[0] * scale)), max(1, round(im.size[1] * scale))), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64)


def logo(src, page_no, x, y, w, h, out, name):
    import numpy as np
    from PIL import Image
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    x0, y0 = max(0.0, min(1.0, x)), max(0.0, min(1.0, y))
    w0, h0 = max(0.005, min(1 - x0, w)), max(0.005, min(1 - y0, h))
    try:
        px = _box_image(src, int(page_no), x0, y0, w0, h0)
    except ValueError as e:
        return {"ok": False, "why": str(e)}
    H, W = px.shape[:2]
    Image.fromarray(px.astype(np.uint8)).save(out / f"{name}-crop.png")

    # background = the commonest colour along the border (colours rounded to 16 levels), as in logocrop.swift
    border = np.concatenate([px[0], px[-1], px[:, 0], px[:, -1]])
    q = border.astype(np.int64) >> 4
    keys = (q[:, 0] << 8) | (q[:, 1] << 4) | q[:, 2]
    uniq, counts = np.unique(keys, return_counts=True)
    top = uniq[counts.argmax()]
    bg = border[keys == top].mean(axis=0)
    if counts.max() / float(2 * (W + H)) < 0.45:
        return {"ok": False, "why": "the logo isn't on a plain background here (try a page where it stands on its own)"}

    d = np.sqrt(((px - bg) ** 2).sum(axis=2))
    alpha = np.clip((d - LO) / (HI - LO), 0, 1)
    ys, xs = np.nonzero(alpha > 0.1)
    if not len(xs):
        return {"ok": False, "why": "nothing stands out from the background in that box"}
    minX, maxX, minY, maxY = xs.min(), xs.max(), ys.min(), ys.max()
    pad = int(max(maxX - minX, maxY - minY) * 0.02) + 2
    minX, minY = max(0, minX - pad), max(0, minY - pad)
    maxX, maxY = min(W - 1, maxX + pad), min(H - 1, maxY + pad)
    a = alpha[minY:maxY + 1, minX:maxX + 1]
    c = px[minY:maxY + 1, minX:maxX + 1]

    def save(rgb, file):
        rgba = np.dstack([np.clip(rgb, 0, 255), a * 255]).round().astype(np.uint8)
        Image.fromarray(rgba).save(out / file)

    # the logo's own colours: take the background back out of the anti-aliased edges
    with np.errstate(divide="ignore", invalid="ignore"):
        own = (c - bg * (1 - a)[..., None]) / a[..., None]
    own[a < 0.01] = 0
    save(own, f"{name}-color.png")
    save(np.full(c.shape, 255.0), f"{name}-light.png")
    save(np.full(c.shape, 17.0), f"{name}-dark.png")
    return {"ok": True, "bg": "#%02x%02x%02x" % tuple(int(v) for v in bg),
            "coverage": float((alpha > 0.1).sum()) / alpha.size, "size": [int(a.shape[1]), int(a.shape[0])]}


if __name__ == "__main__":
    a = sys.argv[1:]
    if missing():
        print(json.dumps({"ok": False, "why": "needs " + ", ".join(missing()) + " (pip install numpy pypdfium2 pillow)"}))
        sys.exit(2)
    if a[:1] == ["pages"] and len(a) >= 3:
        try:
            print(pages(a[1], a[2], *(int(v) for v in a[3:5])))
        except Exception as e:
            sys.stderr.write(f"Can't open that PDF ({e})\n"); sys.exit(1)
    elif a[:1] == ["logo"] and len(a) >= 9:
        print(json.dumps(logo(a[1], int(a[2]), *(float(v) for v in a[3:7]), a[7], a[8])))
    else:
        sys.stderr.write(__doc__); sys.exit(1)
