// Cuts a logo out of a brand guide page (macOS PDFKit/AppKit; no extra installs).
//   swiftc -O logocrop.swift -o logocrop        (brand_import.py compiles it once into .cache/)
//   logocrop <file.pdf|image> <page (1-based; 1 for images)> <x> <y> <w> <h> <out dir> <name>
// x, y, w, h: the logo's box as fractions of the page (0-1, from the top left).
// The box is drawn again at high resolution (vector for PDFs), the plain background around the logo is keyed out,
// and the result is trimmed to the logo. Writes into <out dir>:
//   <name>-crop.png   the box as it looks on the page (for checking)
//   <name>-color.png  the logo in its own colours on transparency
//   <name>-light.png  a white version (for dark backgrounds: end screens)
//   <name>-dark.png   a near-black version (for light backgrounds)
// and prints one line of JSON: {"ok": true, "bg": "#rrggbb", "coverage": 0.21, "size": [w, h]} or {"ok": false, "why": "..."}.
import AppKit
import Foundation
import PDFKit

func fail(_ why: String) -> Never { print("{\"ok\": false, \"why\": \"\(why)\"}"); exit(0) }

let a = CommandLine.arguments
guard a.count >= 9, let pageNo = Int(a[2]), let fx = Double(a[3]), let fy = Double(a[4]), let fw = Double(a[5]), let fh = Double(a[6])
else { fail("usage: logocrop <file> <page> <x> <y> <w> <h> <out dir> <name>") }
let src = URL(fileURLWithPath: a[1]), outDir = URL(fileURLWithPath: a[7], isDirectory: true), name = a[8]
try? FileManager.default.createDirectory(at: outDir, withIntermediateDirectories: true)
let x0 = max(0, min(1, fx)), y0 = max(0, min(1, fy)), w0 = max(0.005, min(1 - x0, fw)), h0 = max(0.005, min(1 - y0, fh))

// ---------------------------------------------------------------- draw the box at high resolution
let target = 1800.0   // px across the longer side of the box
var pageSize = NSSize.zero
var drawPage: ((CGContext) -> Void)? = nil
var keepDoc: PDFDocument? = nil   // a page can't be drawn once its document is gone
if src.pathExtension.lowercased() == "pdf" {
    guard let doc = PDFDocument(url: src), let page = doc.page(at: pageNo - 1) else { fail("can't open that page") }
    keepDoc = doc
    let box = page.bounds(for: .mediaBox)
    pageSize = box.size
    drawPage = { ctx in ctx.translateBy(x: -box.origin.x, y: -box.origin.y); page.draw(with: .mediaBox, to: ctx) }
} else {
    guard let img = NSImage(contentsOf: src), let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else { fail("can't open that image") }
    pageSize = NSSize(width: cg.width, height: cg.height)
    drawPage = { ctx in ctx.draw(cg, in: CGRect(x: 0, y: 0, width: cg.width, height: cg.height)) }
}
let cropW = w0 * Double(pageSize.width), cropH = h0 * Double(pageSize.height)
let scale = target / max(cropW, cropH)
let W = max(1, Int(cropW * scale)), H = max(1, Int(cropH * scale))
guard let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: W, pixelsHigh: H, bitsPerSample: 8, samplesPerPixel: 4,
                                 hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: W * 4, bitsPerPixel: 32),
      let gctx = NSGraphicsContext(bitmapImageRep: rep) else { fail("can't make an image") }
let ctx = gctx.cgContext
ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: W, height: H))
ctx.scaleBy(x: CGFloat(scale), y: CGFloat(scale))
// page coordinates have their origin at the bottom left; the box is measured from the top left
ctx.translateBy(x: CGFloat(-x0 * Double(pageSize.width)), y: CGFloat(-(1 - y0 - h0) * Double(pageSize.height)))
drawPage!(ctx)
gctx.flushGraphics()

func save(_ r: NSBitmapImageRep, _ file: String) {
    if let png = r.representation(using: .png, properties: [:]) { try? png.write(to: outDir.appendingPathComponent(file)) }
}
save(rep, "\(name)-crop.png")

// ---------------------------------------------------------------- key out the background
guard let px = rep.bitmapData else { fail("no pixels") }
let n = W * H
@inline(__always) func at(_ i: Int) -> (Double, Double, Double) { (Double(px[i * 4]), Double(px[i * 4 + 1]), Double(px[i * 4 + 2])) }
// background = the commonest colour along the border (colours rounded to 16 levels)
var counts: [Int: Int] = [:], sums: [Int: (Double, Double, Double)] = [:]
func vote(_ i: Int) {
    let c = at(i); let k = (Int(c.0) >> 4) << 8 | (Int(c.1) >> 4) << 4 | (Int(c.2) >> 4)
    counts[k, default: 0] += 1; let s = sums[k] ?? (0, 0, 0); sums[k] = (s.0 + c.0, s.1 + c.1, s.2 + c.2)
}
for xx in 0..<W { vote(xx); vote((H - 1) * W + xx) }
for yy in 0..<H { vote(yy * W); vote(yy * W + W - 1) }
guard let top = counts.max(by: { $0.value < $1.value }) else { fail("empty") }
let s = sums[top.key]!, cnt = Double(top.value)
let bg = (s.0 / cnt, s.1 / cnt, s.2 / cnt)
let borderShare = Double(top.value) / Double(2 * (W + H))
if borderShare < 0.45 { fail("the logo isn't on a plain background here (try a page where it stands on its own)") }

let lo = 22.0, hi = 110.0
var alpha = [Double](repeating: 0, count: n)
var minX = W, minY = H, maxX = -1, maxY = -1, solid = 0
for i in 0..<n {
    let c = at(i)
    let d = ((c.0 - bg.0) * (c.0 - bg.0) + (c.1 - bg.1) * (c.1 - bg.1) + (c.2 - bg.2) * (c.2 - bg.2)).squareRoot()
    let al = max(0, min(1, (d - lo) / (hi - lo)))
    alpha[i] = al
    if al > 0.1 {
        let xx = i % W, yy = i / W
        minX = min(minX, xx); maxX = max(maxX, xx); minY = min(minY, yy); maxY = max(maxY, yy); solid += 1
    }
}
if maxX < 0 { fail("nothing stands out from the background in that box") }
let pad = Int(Double(max(maxX - minX, maxY - minY)) * 0.02) + 2
minX = max(0, minX - pad); minY = max(0, minY - pad); maxX = min(W - 1, maxX + pad); maxY = min(H - 1, maxY + pad)
let TW = maxX - minX + 1, TH = maxY - minY + 1

func variant(_ file: String, _ colour: ((Double, Double, Double), Double) -> (Double, Double, Double)) {
    guard let r = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: TW, pixelsHigh: TH, bitsPerSample: 8, samplesPerPixel: 4,
                                   hasAlpha: true, isPlanar: false, colorSpaceName: .deviceRGB, bytesPerRow: TW * 4, bitsPerPixel: 32),
          let o = r.bitmapData else { return }
    for yy in 0..<TH {
        for xx in 0..<TW {
            let i = (yy + minY) * W + (xx + minX), j = (yy * TW + xx) * 4
            let al = alpha[i], c = colour(at(i), al)
            // premultiplied output (what NSBitmapImageRep expects by default)
            o[j] = UInt8(max(0, min(255, c.0 * al))); o[j + 1] = UInt8(max(0, min(255, c.1 * al)))
            o[j + 2] = UInt8(max(0, min(255, c.2 * al))); o[j + 3] = UInt8(max(0, min(255, al * 255)))
        }
    }
    save(r, file)
}
// the logo's own colours: take the background back out of the anti-aliased edges
variant("\(name)-color.png") { c, al in
    al < 0.01 ? (0, 0, 0) : ((c.0 - bg.0 * (1 - al)) / al, (c.1 - bg.1 * (1 - al)) / al, (c.2 - bg.2 * (1 - al)) / al)
}
variant("\(name)-light.png") { _, _ in (255, 255, 255) }
variant("\(name)-dark.png") { _, _ in (17, 17, 17) }
let hex = String(format: "#%02x%02x%02x", Int(bg.0), Int(bg.1), Int(bg.2))
print("{\"ok\": true, \"bg\": \"\(hex)\", \"coverage\": \(Double(solid) / Double(n)), \"size\": [\(TW), \(TH)]}")
