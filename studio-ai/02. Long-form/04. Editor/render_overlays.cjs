// Draws the long-form graphics (lower-thirds, cards, end screen, word captions) as transparent PNG frames in one headless
// Chrome session, using the SAME overlays.css / overlays.js as the editor preview. ffmpeg then composites them over the video.
// Usage: node render_overlays.cjs <job.json>   (needs puppeteer-core on NODE_PATH; the Python side arranges that)
// job: {chrome, stage, out, fps, items:[{id,kind,item,dur}], captions:{size,bottom,words:[{text}], indices:[i...]}, endcard}
// Prints one JSON line per finished piece: {"done":"item-3"} / {"done":"cap","n":120,"of":4000} and finally {"finished":true}.
"use strict";
const fs = require("fs"), path = require("path");
const puppeteer = require("puppeteer-core");

const job = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const W = 1920, H = 1080, FPS = job.fps || 30, ENTER = 0.62, EXIT = 0.35;
const say = (o) => process.stdout.write(JSON.stringify(o) + "\n");
const c_dir = (j) => j.captions.dir || "cap";
const even = (n) => Math.round(n / 2) * 2;

(async () => {
  const browser = await puppeteer.launch({ executablePath: job.chrome, headless: "shell", args: ["--no-sandbox", "--allow-file-access-from-files", "--hide-scrollbars"] });
  const page = await browser.newPage();
  await page.setViewport({ width: W, height: H, deviceScaleFactor: 1 });
  await page.goto("file://" + job.stage);
  await page.evaluate(() => document.fonts.ready);
  await page.evaluate(() => { document.fonts.load('700 40px "Display"'); document.fonts.load('400 20px "Inter"'); document.fonts.load('700 20px "Inter"'); document.fonts.forEach((f) => f.load()); });
  await page.evaluate(() => document.fonts.ready);

  const seek = (tau) => page.evaluate((ms) => { document.getAnimations().forEach((a) => { a.pause(); a.currentTime = ms; }); }, tau * 1000);
  const shot = (file, clip) => page.screenshot({ path: file, clip, omitBackground: true, type: "png" });

  // ---- lower-thirds, cards, end screen: an entrance, one held frame, an exit
  for (const it of job.items) {
    const dir = path.join(job.out, it.id); const listF = path.join(dir, "list.txt"), metaF = path.join(dir, "meta.json");
    if (fs.existsSync(metaF) && fs.existsSync(listF) && it.hash && JSON.parse(fs.readFileSync(metaF, "utf8")).hash === it.hash) { say({ done: it.id, reused: true }); continue; }
    fs.rmSync(dir, { recursive: true, force: true }); fs.mkdirSync(dir, { recursive: true });
    const hasExit = it.kind !== "end";
    await page.evaluate(({ kind, item, dur, EXIT, hasExit }) => {
      const root = document.getElementById("root"); root.innerHTML = "";
      const el = kind === "lt" ? OV.lowerThird(item) : kind === "end" ? OV.endcard(item) : OV.card(item);
      root.append(el);
      if (hasExit) el.animate([{ opacity: 1 }, { opacity: 0 }], { duration: EXIT * 1000, delay: Math.max(0, dur - EXIT) * 1000, fill: "forwards" });
      window.__el = el;
    }, { kind: it.kind, item: it.item, dur: it.dur, EXIT, hasExit });
    await page.evaluate(() => document.fonts.ready);
    await seek(ENTER + 0.01);
    let clip;
    if (it.kind === "end") clip = { x: 0, y: 0, width: W, height: H };
    else {
      const r = await page.evaluate(() => { const b = window.__el.getBoundingClientRect(); return { x: b.x, y: b.y, w: b.width, h: b.height }; });
      const pad = 56, x0 = Math.max(0, even(r.x - pad)), y0 = Math.max(0, even(r.y - pad)), x1 = Math.min(W, even(r.x + r.w + pad)), y1 = Math.min(H, even(r.y + r.h + pad));
      clip = { x: x0, y: y0, width: x1 - x0, height: y1 - y0 };
    }
    const lines = []; let n = 0;
    const frame = async (tau, d) => { const f = `f${String(n++).padStart(4, "0")}.png`; await seek(tau); await shot(path.join(dir, f), clip); lines.push(`file '${f}'`, `duration ${d.toFixed(5)}`); };
    const step = 1 / FPS, holdEnd = hasExit ? Math.max(ENTER, it.dur - EXIT) : it.dur;
    let tau = 0;
    for (; tau < Math.min(ENTER, holdEnd); tau += step) await frame(tau, step);
    if (holdEnd - tau > 0.001) { await frame(Math.min(tau, holdEnd), holdEnd - tau); tau = holdEnd; }
    if (hasExit) for (; tau < it.dur - 1e-6; tau += step) await frame(tau, Math.min(step, it.dur - tau));
    // the concat demuxer ignores the duration of the last entry: repeat it
    lines.push(lines[lines.length - 2]);
    fs.writeFileSync(listF, lines.join("\n") + "\n");
    fs.writeFileSync(metaF, JSON.stringify({ hash: it.hash, x: clip.x, y: clip.y, w: clip.width, h: clip.height }));
    say({ done: it.id });
  }

  // ---- captions: one fixed-size band per highlighted word
  if (job.captions && job.captions.indices.length) {
    const c = job.captions, dir = path.join(job.out, c_dir(job)); fs.mkdirSync(dir, { recursive: true });
    const sizePx = c.size, bottomPx = c.bottom;
    const y0 = even(H - bottomPx - sizePx * 2.7), h = even(sizePx * 3.3), clip = { x: 0, y: Math.max(0, y0), width: W, height: Math.min(h, H - Math.max(0, y0)) };
    fs.writeFileSync(path.join(dir, "band.json"), JSON.stringify(clip));
    await page.evaluate(() => { document.getElementById("root").innerHTML = ""; });
    await page.evaluate((words, size, bottom) => { window.__words = words; window.__cap = { size: size / 19.2, bottom: bottom / 10.8 }; }, c.words, sizePx, bottomPx);
    let k = 0;
    for (const i of c.indices) {
      const f = path.join(dir, `${i}.png`);
      if (!fs.existsSync(f)) {
        await page.evaluate((i) => { const root = document.getElementById("root"); root.innerHTML = ""; root.append(OV.caption(window.__words, i, window.__cap)); }, i);
        await shot(f, clip);
      }
      if (++k % 200 === 0) say({ done: "cap", n: k, of: c.indices.length });
    }
    // a transparent frame for the gaps between words
    await page.evaluate(() => { document.getElementById("root").innerHTML = ""; });
    await shot(path.join(dir, "blank.png"), clip);
    say({ done: "cap", n: c.indices.length, of: c.indices.length });
  }
  await browser.close();
  say({ finished: true });
})().catch((e) => { process.stderr.write(String(e && e.stack || e) + "\n"); process.exit(1); });
