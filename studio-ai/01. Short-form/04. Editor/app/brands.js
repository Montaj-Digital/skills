// Brand kits screen (Studio AI): pick a client, edit its look, see it live on a real caption, card, takeover,
// lower-third and end screen. your brand is the built-in look and is shown read-only.
// Server side: 04. Editor/brands.py (+ 03. Brands/brandkit.py).
"use strict";
(function () {   // own scope: the editor already has globals such as section()

const BR = { list: [], id: null, draft: null, files: {}, saved: "", timer: 0, css: null, frames: [] };
const BR_DEFAULT = "default";
const REEL_SCENES = [["caption", 2.2, "Caption + card"], ["card", 6.4, "Card"], ["takeover", 11.6, "Takeover"], ["end", 16.3, "End screen"]];
const WEIGHT_WORDS = [["extrabold", 800], ["ultrabold", 800], ["semibold", 600], ["demibold", 600], ["black", 900], ["heavy", 900],
  ["bold", 700], ["medium", 500], ["light", 300], ["thin", 100], ["regular", 400], ["book", 400]];

// ---------------------------------------------------------------- colour helpers (contrast check)
function hexOf(c) {
  c = String(c || "").trim();
  if (/^#[0-9a-f]{6}$/i.test(c)) return c.toLowerCase();
  if (/^#[0-9a-f]{3}$/i.test(c)) return "#" + c.slice(1).split("").map((x) => x + x).join("").toLowerCase();
  const m = c.match(/rgba?\(([^)]+)\)/);
  if (m) return "#" + m[1].split(",").slice(0, 3).map((x) => Math.round(parseFloat(x)).toString(16).padStart(2, "0")).join("");
  return "#000000";
}
const rgbOf = (c) => { const h = hexOf(c); return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); };
function mixHex(a, b, t) { const x = rgbOf(a), y = rgbOf(b); return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join(""); }
function contrast(a, b) {
  const lum = (c) => { const v = rgbOf(c).map((x) => { x /= 255; return x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4; }); return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]; };
  const [hi, lo] = [lum(a), lum(b)].sort((p, q) => q - p);
  return Math.round(((hi + 0.05) / (lo + 0.05)) * 10) / 10;
}

// ---------------------------------------------------------------- open / close
async function showBrands(selectId) {
  const v = $("#brandview"); v.hidden = false; v.innerHTML = "";
  const list = el("div", { class: "blist" });
  const main = el("div", { class: "bmain" }, el("div", { class: "empty" }, "Loading brand kits…"));
  const prev = el("div", { class: "bprev" });
  v.append(el("div", { class: "home-in bwrap" },
    el("div", { class: "hh" },
      el("h1", {}, "Brand ", el("span", { class: "gt" }, "kits")),
      el("button", { class: "icon", onclick: hideBrands, title: "Close", "aria-label": "Close" }, ic("x"))),
    el("div", { class: "lib" }, "your brand is the default look. Add a client to give their videos their own colours, fonts, logo and end screen."),
    el("div", { class: "bgrid" }, list, main, prev)));
  BR.listEl = list; BR.main = main; BR.prev = prev;
  buildPreview(prev);
  await loadBrandList();
  window.brandsReady = kitsLoad();
  pickBrand(selectId || (BR.list.find((b) => b.id === BR.id) ? BR.id : BR_DEFAULT));
}
function hideBrands() {
  if (brandDirty() && !confirm("You have unsaved brand changes. Close without saving?")) return;
  $("#brandview").hidden = true; $("#brandview").innerHTML = ""; BR.frames = [];
}
const brandDirty = () => BR.draft && BR.id !== BR_DEFAULT && JSON.stringify(BR.draft) !== BR.saved;

async function loadBrandList() {
  const r = await fetch("/api/brands").then((x) => x.json());
  BR.list = r.brands || [];
  drawBrandList();
}
function drawBrandList() {
  const l = BR.listEl; l.innerHTML = "";
  BR.list.forEach((b) => {
    const c = b.colors || {}, g = c.gradient || [c.accent, c.primary];
    l.append(el("button", { class: `btile${b.id === BR.id ? " on" : ""}`, onclick: () => pickBrand(b.id) },
      el("span", { class: "bsw", style: `background:linear-gradient(135deg, ${g[0] || "#888"}, ${g[1] || "#444"})` }),
      el("span", { class: "bname" }, el("b", {}, b.name), el("small", {}, b.default ? "Default look" : b.id))));
  });
  l.append(el("button", { class: "btile add", onclick: addClient }, el("span", { class: "bsw plus" }, ic("plus")), el("span", { class: "bname" }, el("b", {}, "Add a client"))));
}
async function addClient() {
  const name = prompt("Client name (for example: Acme Dental)");
  if (!name || !name.trim()) return;
  const r = await fetch("/api/brands/new", { method: "POST", body: JSON.stringify({ name: name.trim() }) }).then((x) => x.json());
  if (r.error) return toast(r.error);
  await loadBrandList(); pickBrand(r.brand.id);
}
async function pickBrand(id) {
  if (id !== BR.id && brandDirty() && !confirm("You have unsaved brand changes. Switch without saving?")) return;
  const r = await fetch(`/api/brands/${encodeURIComponent(id)}`).then((x) => x.json());
  if (r.error) return toast(r.error);
  BR.importNotes = null;
  BR.id = id; BR.draft = r.brand; BR.files = r.files || {}; BR.saved = JSON.stringify(r.brand);
  drawBrandList(); drawEditor(); refreshPreview(true);
}
async function saveBrand() {
  const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}`, { method: "POST", body: JSON.stringify({ brand: BR.draft }) }).then((x) => x.json());
  if (r.error) return toast(r.error);
  BR.draft = r.brand; BR.saved = JSON.stringify(r.brand);
  await loadBrandList(); window.brandsReady = kitsLoad(); if (window.updateBrandChip) updateBrandChip(); drawEditor(); toast("Brand kit saved");
}
async function deleteBrand() {
  const id = BR.id, name = BR.draft.name || id;
  // which videos use this brand (short-form and long-form libraries)
  const [sf, lf] = await Promise.all([
    fetch("/api/reels").then((r) => r.json()).then((r) => r.reels || []).catch(() => []),
    fetch("/api/long/projects").then((r) => (r.ok ? r.json() : {})).then((r) => r.projects || []).catch(() => []),
  ]);
  const used = sf.filter((r) => r.brand === id).length + lf.filter((p) => p.brand === id).length;
  const msg = `Delete the ${name} brand kit?\n\nIt moves to the Bin, so it can be put back from there.` +
    (used ? `\n\n${used} video${used === 1 ? " uses" : "s use"} it. They'll show the default look until you pick another brand or restore the kit.` : "");
  if (!confirm(msg)) return;
  const r = await fetch(`/api/brands/${encodeURIComponent(id)}/delete`, { method: "POST" }).then((x) => x.json());
  if (r.error) return toast(r.error);
  BR.saved = JSON.stringify(BR.draft);   // nothing left to save
  toast(`${name} moved to the Bin`);
  await loadBrandList(); window.brandsReady = kitsLoad(); if (window.updateBrandChip) updateBrandChip();
  pickBrand(BR_DEFAULT);
}
function changed(redraw) { if (redraw) drawEditor(); else setSaveState(); refreshPreview(); }
function setSaveState() {
  const b = $("#bSave"), s = $("#bState");
  if (!b) return;
  b.disabled = !brandDirty();
  s.textContent = brandDirty() ? "Unsaved changes" : "Saved"; s.className = "status" + (brandDirty() ? " dirty" : "");
}

// ---------------------------------------------------------------- the editor form
function field(label, input, hint) { return el("label", { class: "bfield" }, el("span", { class: "blab" }, label), input, hint ? el("small", {}, hint) : null); }
function section(title, ...kids) { return el("section", { class: "bsec" }, el("h3", {}, title), ...kids); }
function textIn(get, set, ph) { return el("input", { type: "text", value: get() || "", placeholder: ph || "", oninput: (e) => { set(e.target.value); changed(); } }); }
function colourIn(get, set) {
  const sw = el("input", { type: "color", value: hexOf(get()), oninput: (e) => { set(e.target.value); hx.value = e.target.value; changed(); refreshContrast(); } });
  const hx = el("input", { type: "text", class: "hex", value: hexOf(get()), maxlength: 7,
    onchange: (e) => { const v = hexOf(e.target.value); set(v); sw.value = v; e.target.value = v; changed(); refreshContrast(); } });
  return el("span", { class: "cpick" }, sw, hx);
}

function drawEditor() {
  const d = BR.draft, ro = BR.id === BR_DEFAULT, m = BR.main;
  m.innerHTML = "";
  d.colors = d.colors || {}; d.fonts = d.fonts || {}; d.logos = d.logos || {}; d.images = d.images || {};
  d.captions = d.captions || {}; d.endscreen = d.endscreen || {}; d.voice = d.voice || {};
  const C = d.colors;
  C.gradient = C.gradient || [C.accent || "#22d3ee", C.primary || "#2563eb"];
  C.keyword = C.keyword || [C.gradient[0], mixHex(C.gradient[0], C.gradient[1], 0.5), C.gradient[1]];
  const head = el("div", { class: "bhead" },
    el("div", {}, el("h2", {}, d.name || BR.id), el("small", {}, ro ? "Built into the templates. Every video without a client brand uses this look." : `03. Brands/${BR.id}`)),
    ro ? null : el("span", { id: "bState", class: "status" }),
    ro ? null : el("button", { class: "danger", onclick: deleteBrand, title: "Move this kit to the Bin" }, ic("trash-2"), "Delete"),
    ro ? null : el("button", { id: "bSave", class: "primary", onclick: saveBrand }, ic("save"), "Save"));
  m.append(head);
  if (ro) {
    m.append(el("div", { class: "bnote" }, "To change the default look, edit the skill's template (brand.css, styles.css). Client kits never change default videos."));
  }
  const body = el("div", { class: `bbody${ro ? " ro" : ""}` });
  m.append(body);

  if (!ro) body.append(importSection());
  body.append(section("Client",
    field("Name", textIn(() => d.name, (v) => (d.name = v))),
    field("Website", textIn(() => d.website, (v) => (d.website = v), "example.com"))));

  const cRow = (label, get, set, hint) => field(label, colourIn(get, set), hint);
  const glassGet = () => hexOf((C.glass_tint || [])[0] || mixHex(C.primary || "#2563eb", "#1d1925", 0.75));
  body.append(section("Colours",
    el("div", { class: "bcols" },
      cRow("Primary", () => C.primary, (v) => (C.primary = v), "Main brand colour"),
      cRow("Accent", () => C.accent, (v) => (C.accent = v), "Bright highlight colour"),
      cRow("Gradient from", () => C.gradient[0], (v) => (C.gradient[0] = v)),
      cRow("Gradient to", () => C.gradient[1], (v) => (C.gradient[1] = v)),
      cRow("Keyword 1", () => C.keyword[0], (v) => (C.keyword[0] = v), "Caption keywords and card titles"),
      cRow("Keyword 2", () => C.keyword[1], (v) => (C.keyword[1] = v)),
      cRow("Keyword 3", () => C.keyword[2], (v) => (C.keyword[2] = v)),
      cRow("Small labels", () => C.kicker || mixHex(C.accent || "#22d3ee", "#ffffff", 0.45), (v) => (C.kicker = v)),
      cRow("Ticks / yes marks", () => C.highlight || "#34d399", (v) => (C.highlight = v)),
      cRow("Text", () => C.text || "#ffffff", (v) => (C.text = v)),
      cRow("Glass tint", glassGet, (v) => (C.glass_tint = [`rgba(${rgbOf(v).join(", ")}, 0.60)`, `rgba(${rgbOf(mixHex(v, "#000000", 0.4)).join(", ")}, 0.74)`]), "Card background (see-through)"),
      cRow("Takeover base", () => C.takeover_bg || mixHex(C.primary || "#2563eb", "#000000", 0.55), (v) => (C.takeover_bg = v))),
    el("div", { id: "bContrast", class: "bcontrast" })));

  body.append(section("Fonts", fontRole("display", "Headlines and captions"), fontRole("body", "Small text"),
    el("small", { class: "lic" }, "Font licences are the client's responsibility. Google Fonts (from Fontsource) are free to use (OFL). Uploaded fonts must be licensed for video.")));

  body.append(section("Logos and background",
    el("div", { class: "blogos" },
      assetSlot("Light logo", "For dark backgrounds: shown on the end screen", "logos", () => d.logos.light, (v) => (d.logos.light = v), "light"),
      assetSlot("Dark logo", "For light backgrounds", "logos", () => d.logos.dark, (v) => (d.logos.dark = v), "dark"),
      assetSlot("Logo mark", "Icon only (square)", "logos", () => d.logos.mark, (v) => (d.logos.mark = v), "mark"),
      assetSlot("Background image", "End screen and takeovers; without it a gradient is made from the colours", "images", () => d.images.background, (v) => (d.images.background = v), "bg"))));

  const kwSel = el("select", { onchange: (e) => { d.captions.keyword = e.target.value === "gradient" ? "gradient" : (C.accent || "#22d3ee"); changed(true); } },
    el("option", { value: "gradient", selected: (d.captions.keyword || "gradient") === "gradient" }, "Gradient (keyword colours)"),
    el("option", { value: "solid", selected: (d.captions.keyword || "gradient") !== "gradient" }, "One colour"));
  const wSel = el("select", { onchange: (e) => { d.captions.weight = +e.target.value; changed(); } },
    [[500, "Medium"], [600, "SemiBold"], [700, "Bold"], [800, "ExtraBold"]].map(([w, n]) => el("option", { value: w, selected: +(d.captions.weight || 800) === w }, n)));
  body.append(section("Captions",
    el("div", { class: "brow" }, field("Keywords", kwSel), (d.captions.keyword || "gradient") !== "gradient" ? field("Keyword colour", colourIn(() => d.captions.keyword, (v) => (d.captions.keyword = v))) : null, field("Weight", wSel))));

  const lines = d.endscreen.lines = d.endscreen.lines || [];
  const linesBox = el("div", { class: "blines" });
  const drawLines = () => {
    linesBox.innerHTML = "";
    lines.forEach((l, i) => linesBox.append(el("div", { class: "bline" },
      el("input", { type: "text", value: l.text || "", oninput: (e) => { l.text = e.target.value; changed(); } }),
      el("label", { class: "tool" }, el("input", { type: "checkbox", checked: !!l.bold, onchange: (e) => { l.bold = e.target.checked; changed(); } }), "Big"),
      el("button", { class: "icon small", title: "Remove line", onclick: () => { lines.splice(i, 1); drawLines(); changed(); } }, ic("x")))));
    linesBox.append(el("button", { class: "small", onclick: () => { lines.push({ text: "" }); drawLines(); } }, ic("plus"), "Add a line"));
  };
  drawLines();
  body.append(section("End screen", linesBox,
    field("Call to action", textIn(() => d.endscreen.cta, (v) => (d.endscreen.cta = v), "Book a free consultation at example.com"), "Claude ends videos with this")));

  body.append(section("Tone of voice (for Claude)",
    field("Tone", el("textarea", { rows: 3, value: d.voice.tone || "", placeholder: "Friendly and expert. Sentence case, UK spelling, no emoji.", oninput: (e) => { d.voice.tone = e.target.value; changed(); } })),
    field("Call to action", textIn(() => d.voice.cta, (v) => (d.voice.cta = v)))));

  if (ro) body.querySelectorAll("input, select, textarea, .bbody button").forEach((x) => (x.disabled = true));
  setSaveState(); refreshContrast();
}

// ---------------------------------------------------------------- import a brand guide (brand_import.py)
function importSection() {
  const file = el("input", { type: "file", accept: ".pdf,.png,.jpg,.jpeg,.webp" });
  const url = el("input", { type: "text", placeholder: "or a website: example.com" });
  const prog = el("div", { class: "bimp-prog" });
  const go = el("button", { class: "primary", onclick: () => startImport(file.files[0], url.value.trim(), prog) }, ic("sparkles"), "Read it with Claude");
  const box = section("Import a brand guide",
    el("small", { class: "lic" }, "Claude reads a brand guide (PDF or images) or the client's website and fills in this kit. It also cuts the logo out of a PDF or image guide. Nothing is saved until you check it and press Save."),
    el("div", { class: "bimp" }, file, url, go), prog);
  box.classList.add("bimp-sec");
  if (BR.importNotes) prog.append(notesBox(BR.importNotes));
  pollImport(prog, true);
  return box;
}
function notesBox(notes) {
  return el("div", { class: "bnote bimp-notes" }, el("b", {}, "From the import: please check"), el("ul", {}, ...notes.map((n) => el("li", {}, n))));
}
async function startImport(f, url, prog) {
  if (!f && !url) return toast("Choose a PDF or an image, or type the website");
  if (brandDirty() && !confirm("The import replaces the unsaved changes on this screen. Carry on?")) return;
  prog.innerHTML = ""; prog.append(el("div", { class: "hint" }, f ? `Sending ${f.name}…` : "Starting…"));
  const q = `name=${encodeURIComponent(f ? f.name : "")}&url=${encodeURIComponent(url)}`;
  const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}/import?${q}`, { method: "POST", body: f || "" }).then((x) => x.json()).catch((e) => ({ error: e.message }));
  if (r.error) { prog.innerHTML = ""; return toast(r.error); }
  pollImport(prog);
}
async function pollImport(prog, quiet) {
  clearTimeout(BR.impT);
  const id = BR.id;
  const st = await fetch(`/api/brands/${encodeURIComponent(id)}/import`).then((x) => x.json()).catch(() => null);
  if (!st || id !== BR.id || !prog.isConnected) return;
  if (st.state === "none" || (quiet && st.state !== "running")) return;
  prog.innerHTML = "";
  if (st.state === "running") {
    prog.append(el("div", { class: "bimp-run" }, el("span", { class: "spin" }), el("b", {}, st.step), el("small", {}, `${Math.floor(st.elapsed / 60)}:${String(st.elapsed % 60).padStart(2, "0")}`),
      el("button", { class: "small", onclick: () => fetch(`/api/brands/${encodeURIComponent(id)}/import/stop`, { method: "POST" }) }, "Stop")));
    BR.impT = setTimeout(() => pollImport(prog), 1500);
    return;
  }
  if (st.state === "failed" || st.state === "stopped") { prog.append(el("div", { class: "err" }, st.error || "Stopped")); return; }
  if (st.state === "done" && st.result && !BR.importSeen?.[id + st.elapsed]) {
    BR.importSeen = { ...(BR.importSeen || {}), [id + st.elapsed]: true };
    BR.draft = st.result.brand; BR.files = st.result.files || BR.files; BR.importNotes = st.result.notes || [];
    toast("The guide is read. Check the kit, then press Save.");
    drawEditor(); refreshPreview(true);
  }
}

function refreshContrast() {
  const box = $("#bContrast"); if (!box) return;
  const C = BR.draft.colors, text = C.text || "#ffffff";
  const glass = mixHex(hexOf((C.glass_tint || [])[0] || "#223c52"), "#6d737c", 0.4);   // glass over a mid-grey video
  const checks = [["Text on primary", text, C.primary], ["Text on gradient start", text, C.gradient[0]], ["Text on glass cards", text, glass],
    ["Keyword on glass", C.keyword[1], glass]];
  box.innerHTML = "";
  checks.forEach(([label, a, b]) => {
    const r = contrast(a, b), cls = r >= 4.5 ? "ok" : r >= 3 ? "mid" : "bad";
    box.append(el("span", { class: `bcr ${cls}`, title: "WCAG contrast: 4.5 for normal text, 3 for large text" },
      el("i", { style: `background:${b};color:${a}` }, "Aa"), label, el("b", {}, `${r}:1`), cls === "ok" ? "" : cls === "mid" ? " large text only" : " too low"));
  });
}

// ---------------------------------------------------------------- fonts: Fontsource search + upload
const loadedFonts = new Set();
function previewFont(f, weight) {
  const w = (f.weights || [400]).reduce((a, b) => (Math.abs(b - weight) < Math.abs(a - weight) ? b : a));
  const key = `${f.id}-${w}`;
  if (!loadedFonts.has(key)) {
    loadedFonts.add(key);
    const face = new FontFace(`fs-${f.id}`, `url(https://cdn.jsdelivr.net/fontsource/fonts/${f.id}@latest/latin-${w}-normal.woff2)`, { weight: String(w) });
    face.load().then((x) => document.fonts.add(x)).catch(() => {});
  }
  return `font-family:"fs-${f.id}", sans-serif; font-weight:${w}`;
}
function fontRole(role, label) {
  const d = BR.draft, cur = d.fonts[role] || {};
  const files = (cur.files || []).length;
  const results = el("div", { class: "fresults" });
  const q = el("input", { type: "search", placeholder: "Search Google Fonts (for example Poppins)" });
  let t = 0;
  const search = async () => {
    const r = await fetch(`/api/fonts/search?q=${encodeURIComponent(q.value)}`).then((x) => x.json()).catch(() => ({ fonts: [] }));
    results.innerHTML = "";
    if (r.error) { results.append(el("div", { class: "empty" }, "Couldn't reach Google Fonts: " + r.error)); return; }
    (r.fonts || []).slice(0, 24).forEach((f) => results.append(el("button", { class: "fres", title: `${f.family} · ${f.category} · ${f.license}`, onclick: () => useFont(role, f) },
      el("span", { class: "fsamp", style: previewFont(f, role === "display" ? 700 : 400) }, role === "display" ? "Grow your business" : "The quick brown fox"),
      el("small", {}, f.family))));
  };
  q.oninput = () => { clearTimeout(t); t = setTimeout(search, 250); };
  q.onfocus = () => { if (!results.childElementCount) search(); };
  const up = el("input", { type: "file", multiple: true, accept: ".ttf,.otf,.woff,.woff2", hidden: true, onchange: (e) => uploadFonts(role, [...e.target.files]) });
  return el("div", { class: "frole" },
    el("div", { class: "fcur" }, el("span", { class: "blab" }, label),
      el("b", {}, cur.family || (BR.id === BR_DEFAULT ? "" : "Not set: Helvetica / Arial")), files ? el("small", {}, `${files} file${files === 1 ? "" : "s"}${cur.license ? " · " + cur.license : ""}`) : null,
      el("button", { class: "small", onclick: () => up.click() }, ic("upload"), "Upload font files"), up),
    BR.id === BR_DEFAULT ? null : q, results);
}
async function useFont(role, f) {
  toast(`Downloading ${f.family}…`);
  const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}/font`, { method: "POST", body: JSON.stringify({ role, font: f.id }) }).then((x) => x.json());
  if (r.error) return toast(r.error);
  BR.draft.fonts[role] = r.font; BR.files = r.files; toast(`${f.family} added (${r.font.files.length} weights)`); changed(true);
}
function weightFromName(n) {
  const s = n.toLowerCase().replace(/[^a-z0-9]/g, "");
  const m = s.match(/(\d{3})/); if (m && +m[1] >= 100 && +m[1] <= 900) return +m[1];
  for (const [w, v] of WEIGHT_WORDS) if (s.includes(w)) return v;
  return 400;
}
async function uploadFonts(role, files) {
  if (!files.length) return;
  const cur = BR.draft.fonts[role] = BR.draft.fonts[role] && BR.draft.fonts[role].source !== "fontsource" ? BR.draft.fonts[role] : { family: "", files: [] };
  for (const f of files) {
    const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}/upload?sub=fonts&name=${encodeURIComponent(f.name)}`, { method: "POST", body: f }).then((x) => x.json());
    if (r.error) { toast(r.error); continue; }
    cur.files = cur.files.filter((x) => x.file !== r.path).concat([{ file: r.path, weight: weightFromName(f.name) }]);
    BR.files = r.files;
  }
  if (!cur.family) cur.family = files[0].name.replace(/\.[^.]+$/, "").replace(/[-_ ]?(extra|semi|demi|ultra)?(bold|black|medium|regular|light|thin|book|heavy|\d{3}).*$/i, "") || "Brand font";
  cur.source = "upload";
  toast(`${files.length} font file${files.length === 1 ? "" : "s"} added. Check the weights in brand.json if a name had no weight in it.`); changed(true);
}

// ---------------------------------------------------------------- logos and images
function assetSlot(label, hint, sub, get, set, key) {
  const cur = get();
  const up = el("input", { type: "file", hidden: true, accept: ".svg,.png,.jpg,.jpeg,.webp", onchange: async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const ext = f.name.split(".").pop().toLowerCase();
    const name = sub === "logos" ? `logo-${key}.${ext}` : `background.${ext}`;
    const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}/upload?sub=${sub}&name=${encodeURIComponent(name)}`, { method: "POST", body: f }).then((x) => x.json());
    if (r.error) return toast(r.error);
    set(r.path); BR.files = r.files; changed(true);
  } });
  const src = cur ? `/brands/${encodeURIComponent(BR.id)}/${cur}?v=${Date.now()}` : "";
  return el("div", { class: `bslot ${key}` },
    el("div", { class: "bthumb", onclick: () => BR.id !== BR_DEFAULT && up.click() }, src ? el("img", { src, alt: label }) : ic("image")),
    el("b", {}, label), el("small", {}, hint),
    el("div", { class: "bslot-act" },
      el("button", { class: "small", onclick: () => up.click() }, ic("upload"), cur ? "Replace" : "Upload"),
      cur ? el("button", { class: "small", onclick: () => { set(null); changed(true); } }, "Remove") : null), up);
}

// ---------------------------------------------------------------- live preview (real template + long-form graphics)
function frame(src, w, h, width, label) {
  const s = width / w;
  const f = el("iframe", { src, title: label, tabindex: "-1", style: `width:${w}px;height:${h}px;transform:scale(${s})` });
  BR.frames.push(f);
  return el("figure", { class: "bfr" }, el("div", { class: "bfr-in", style: `width:${width}px;height:${Math.round(h * s)}px` }, f), el("figcaption", {}, label));
}
function buildPreview(box) {
  BR.frames = [];
  box.append(el("h3", {}, "Preview"),
    el("div", { class: "bfr-row" }, REEL_SCENES.map(([k, t, label]) => frame(`/brandstage/index.html?t=${t}`, 1080, 1920, 118, label))),
    el("div", { class: "bfr-row" }, frame("/brandstage/long.html?kind=lt", 1920, 1080, 250, "Long-form: lower-third, card"), frame("/brandstage/long.html?kind=end", 1920, 1080, 250, "Long-form end screen")),
    el("small", { class: "lic" }, "The reel preview is a real composition built by the studio-reel skill, so this is how the render will look."));
}
function postTo(f) {
  const c = BR.css; if (!c || !f.contentWindow) return;
  const long = f.src.includes("long.html");
  f.contentWindow.postMessage(long ? { type: "brand", css: c.long, lines: c.lines, logo: c.long_logo } : { type: "brand", css: c.reel, lines: c.lines, logo: c.logo, line: c.line }, "*");
}
function refreshPreview(now) {
  clearTimeout(BR.timer);
  BR.timer = setTimeout(async () => {
    const r = await fetch(`/api/brands/${encodeURIComponent(BR.id)}/css`, { method: "POST", body: JSON.stringify({ brand: BR.draft }) }).then((x) => x.json()).catch((e) => ({ error: e.message }));
    if (r.error) return toast(r.error);
    if (!r.lines || !r.lines.length) r.lines = null;
    BR.css = r; BR.frames.forEach(postTo);
  }, now ? 0 : 250);
}
window.addEventListener("message", (e) => {
  if ((e.data || {}).type !== "stage-ready") return;
  const f = BR.frames.find((x) => x.contentWindow === e.source);
  if (f) postTo(f);
});

$("#brandsBtn").onclick = () => showBrands();
window.showBrands = showBrands;

// ---------------------------------------------------------------- brand per video (wizard, header, Open, end screen)
// The kit list is shared by everything below; refreshed after the Brand screen saves or adds a kit.
let KITS = [];
const kitsLoad = () => fetch("/api/brands").then((r) => r.json()).then((r) => { KITS = r.brands || []; window.BRAND_KITS = KITS; return KITS; }).catch(() => KITS);
window.brandsReady = kitsLoad();
const kitOf = (id) => KITS.find((k) => k.id === (id || BR_DEFAULT));
const swatch = (k, cls) => { const c = (k && k.colors) || {}, g = c.gradient || [c.accent, c.primary]; return el("span", { class: cls || "bsw", style: `background:linear-gradient(135deg, ${g[0] || "#888"}, ${g[1] || "#444"})` }); };
window.brandName = (id) => (kitOf(id) || {}).name || (id && id !== BR_DEFAULT ? id : "Your brand");
window.brandEndLines = (id) => { const k = id && id !== BR_DEFAULT ? kitOf(id) : null; return k && k.lines && k.lines.length ? k.lines : null; };

// header: which brand the open video uses; click to switch
window.updateBrandChip = async function () {
  const chip = $("#brandChip"); if (!chip) return;
  if (typeof S === "undefined" || !S.spec) { chip.hidden = true; return; }
  await window.brandsReady;
  const id = S.spec.brand || BR_DEFAULT, k = kitOf(id);
  chip.hidden = false; chip.innerHTML = "";
  chip.append(swatch(k, "bdot"), el("span", {}, k ? k.name : `${id} (kit missing)`), ic("chevron-right"));
  chip.classList.toggle("client", id !== BR_DEFAULT);
};
function brandMenu() {
  document.querySelector(".brandmenu")?.remove();
  const chip = $("#brandChip"), r = chip.getBoundingClientRect(), cur = S.spec.brand || BR_DEFAULT;
  const m = el("div", { class: "menu list brandmenu", style: `position:fixed;left:${r.left}px;top:${r.bottom + 6}px;z-index:80` },
    el("div", { class: "mgroup" }, "Who is this video for?"),
    ...KITS.map((k) => el("button", { class: k.id === cur ? "on" : "", onclick: () => { m.remove(); switchBrand(k.id); } }, swatch(k, "bdot"), k.name)),
    el("button", { onclick: () => { m.remove(); showBrands(cur); } }, ic("palette"), "Edit brand kits…"));
  document.body.append(m);
  setTimeout(() => document.addEventListener("click", function off(e) { if (!m.contains(e.target)) { m.remove(); document.removeEventListener("click", off); } }), 0);
}
function switchBrand(id) {
  const old = S.spec.brand || BR_DEFAULT;
  if (id === old) return;
  snapshot();
  if (id === BR_DEFAULT) delete S.spec.brand; else S.spec.brand = id;
  // the end screen follows the brand when it still shows the old brand's standard lines
  const E = S.spec.endcard, same = (a, b) => JSON.stringify((a || []).map((l) => [l.text, !!l.bold])) === JSON.stringify((b || []).map((l) => [l.text, !!l.bold]));
  const oldStd = window.brandEndLines(old) || STANDARD_END, newStd = window.brandEndLines(id) || STANDARD_END;
  if (E && E.lines && !same(E.lines, newStd)) {
    if (same(E.lines, oldStd) || confirm(`Use ${window.brandName(id)}'s end screen lines too?`)) E.lines = clone(newStd);
  }
  change();
  toast(`This video now uses the ${window.brandName(id)} brand`);
}
$("#brandChip").onclick = (e) => { e.stopPropagation(); brandMenu(); };

// the first wizard step (short-form and long-form): your brand + client tiles + Add a client
window.brandStep = async function (box, current, onPick) {
  await kitsLoad();
  const tile = (k) => el("button", { class: `look brandpick${(current || BR_DEFAULT) === k.id ? " on" : ""}`, onclick: () => onPick(k.id) },
    k.logo ? el("div", { class: "bp-logo", style: "background:" + ((k.colors || {}).primary || "#222") }, el("img", { src: `/brands/${encodeURIComponent(k.id)}/${k.logo}`, alt: "" })) : swatch(k, "bp-logo"),
    el("div", { class: "look-t" }, el("b", {}, k.name), el("span", {}, k.default ? "your brand's own look" : k.website || "Client brand")),
    el("span", { class: "look-go" }, "Choose", ic("chevron-right")));
  box.append(el("h2", { class: "wz-h" }, "Who is this ", el("span", { class: "gt" }, "video"), " for?"),
    el("p", { class: "wz-sub" }, "The brand sets the colours, fonts, logo, end screen and how Claude writes."),
    el("div", { class: "looks brandpicks" }, ...KITS.map(tile),
      el("button", { class: "look brandpick add", onclick: async () => {
        const name = prompt("Client name (for example: Acme Dental)"); if (!name || !name.trim()) return;
        const r = await fetch("/api/brands/new", { method: "POST", body: JSON.stringify({ name: name.trim() }) }).then((x) => x.json());
        if (r.error) return toast(r.error);
        await kitsLoad(); toast(`${r.brand.name} added. Set their colours, fonts and logo under Brands.`); onPick(r.brand.id);
      } }, el("span", { class: "bp-logo plus" }, ic("plus")), el("div", { class: "look-t" }, el("b", {}, "Add a client"), el("span", {}, "Starts from the default look; finish it under Brands")))));
};
})();
