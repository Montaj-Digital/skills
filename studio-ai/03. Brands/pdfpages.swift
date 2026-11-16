// Turns a brand-guide PDF into page images + text for Claude to read (macOS PDFKit; no extra installs).
//   swiftc -O pdfpages.swift -o pdfpages        (brandkit.py compiles it once into .cache/)
//   pdfpages <file.pdf> <out dir> [max pages = 80] [width px = 1400]
// Writes <out>/page-001.png … and <out>/pages.json: [{"page": 1, "file": "page-001.png", "text": "…"}, …]
import AppKit
import Foundation
import PDFKit

let args = CommandLine.arguments
guard args.count >= 3, let doc = PDFDocument(url: URL(fileURLWithPath: args[1])) else {
    FileHandle.standardError.write("Can't open that PDF\n".data(using: .utf8)!)
    exit(1)
}
let out = URL(fileURLWithPath: args[2], isDirectory: true)
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)
let maxPages = args.count > 3 ? Int(args[3]) ?? 80 : 80
let width = args.count > 4 ? Double(args[4]) ?? 1400 : 1400

var pages: [[String: Any]] = []
for i in 0..<min(doc.pageCount, maxPages) {
    guard let page = doc.page(at: i) else { continue }
    let box = page.bounds(for: .mediaBox)
    let scale = width / Double(box.width)
    let size = NSSize(width: Double(box.width) * scale, height: Double(box.height) * scale)
    let img = page.thumbnail(of: size, for: .mediaBox)
    let name = String(format: "page-%03d.png", i + 1)
    if let tiff = img.tiffRepresentation, let rep = NSBitmapImageRep(data: tiff),
       let png = rep.representation(using: .png, properties: [:]) {
        try? png.write(to: out.appendingPathComponent(name))
    }
    pages.append(["page": i + 1, "file": name, "text": page.string ?? ""])
}
let json = try JSONSerialization.data(withJSONObject: ["count": doc.pageCount, "pages": pages], options: [.prettyPrinted])
try json.write(to: out.appendingPathComponent("pages.json"))
print("\(pages.count) of \(doc.pageCount) pages")
