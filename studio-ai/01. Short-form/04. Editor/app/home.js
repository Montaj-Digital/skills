// Open (the reel library) and New (raw video -> drafted reel through the studio-reel pipeline).
"use strict";

const ago = (t) => {
  const s = Date.now() / 1000 - t;
  if (s < 3600) return `${Math.max(1, Math.round(s / 60))} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 86400 * 14) return `${Math.round(s / 86400)} days ago`;
  return new Date(t * 1000).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
};
const leave = (fn) => { if (S.dirty && !confirm("You have unsaved changes. Leave this video without saving?")) return; S.leaving = true; fn(); };

// ---------------------------------------------------------------- Open
async function showHome(landing) {
  const h = $("#home"); h.hidden = false; h.innerHTML = "";
  await sectionsReady;
  if (SECTIONS.long && section === "long") {          // the long-form library is drawn by long.js
    try { await loadLong(); } catch (e) { toast(e.message); setSection("short"); }
    if (section === "long") return LF.renderHome(h, landing);
  }
  const search = el("input", { type: "text", class: "search", placeholder: "Search videos" });
  const searchBox = el("label", { class: "searchbox" }, ic("search"), search);
  // filter by client (Studio AI brand kits); hidden until a video uses a client brand
  const clientSel = el("select", { class: "clientsel", title: "Show one client's videos", hidden: true });
  const chips = el("div", { class: "fchips" });
  const grid = el("div", { class: "grid" }, el("div", { class: "empty" }, "Finding your videos…"));
  h.append(el("div", { class: "home-in" },
    el("div", { class: "hh" },
      el("div", { class: "htitle" }, sectionSwitch(() => showHome(landing)), el("h1", {}, landing ? ["Your ", el("span", { class: "gt" }, "videos")] : ["Open a ", el("span", { class: "gt" }, "video")]),
        el("div", { class: "lib" }, "")),
      el("div", { class: "hact" }, clientSel, searchBox,
        window.PORTAL ? null : el("button", { onclick: browse, title: "Open a video folder from anywhere" }, ic("folder"), "Browse…"),
        window.PORTAL ? null : el("button", { onclick: () => fetch("/api/reveal", { method: "POST", body: JSON.stringify({ path: S.renders }) }), title: "Open 06. Renders in Finder" }, ic("folder-open"), "Finished videos"),
        !landing ? el("button", { class: "icon", onclick: hideHome, title: "Close", "aria-label": "Close" }, ic("x")) : null)),
    chips, grid));
  const { reels, library, renders } = await fetch("/api/reels").then((r) => r.json());
  S.library = library; S.renders = renders;
  h.querySelector(".lib").textContent = `${reels.length} video${reels.length === 1 ? "" : "s"} · new ones are saved in 05. Projects, finished videos in 06. Renders`;
  const FMT_LABEL = { reel: "Reel 9:16", feed: "Feed 4:5", square: "Square 1:1", landscape: "Landscape 16:9" };
  let filter = "all", client = "all";
  try { client = sessionStorage.getItem("clientFilter") || "all"; } catch (e) {}
  if (window.brandsReady) await window.brandsReady;
  const clients = [...new Set(reels.map((r) => r.brand || "default"))];
  if (clients.some((c) => c !== "default")) {
    clientSel.hidden = false;
    const name = (id) => (window.brandName ? brandName(id) : id);
    clientSel.append(el("option", { value: "all" }, "All clients"), ...clients.sort((a, b) => name(a).localeCompare(name(b))).map((c) =>
      el("option", { value: c, selected: c === client }, `${name(c)} (${reels.filter((r) => (r.brand || "default") === c).length})`)));
    if (!clients.includes(client)) client = "all";
    clientSel.value = client;
  } else client = "all";
  const ofClient = (r) => client === "all" || (r.brand || "default") === client;
  clientSel.onchange = () => { client = clientSel.value; try { sessionStorage.setItem("clientFilter", client); } catch (e) {} drawChips(); draw(); };
  const drawChips = () => {
    chips.innerHTML = "";
    const count = (f) => reels.filter((r) => ofClient(r) && (f === "all" || (r.format || "reel") === f)).length;
    [["all", "All"], ...Object.entries(FMT_LABEL)].forEach(([k, l]) => {
      const n = count(k); if (k !== "all" && !n) return;
      chips.append(el("button", { class: `fchip${filter === k ? " on" : ""}`, onclick: () => { filter = k; drawChips(); draw(); } }, l, el("b", {}, String(n))));
    });
  };
  const inLib = (r) => r.path.startsWith(library + "/");
  const card = (r) => {
    const ratio = { landscape: "16:9", feed: "4:5", square: "1:1" }[r.format];
    const url = `/api/thumb?path=${encodeURIComponent(r.path)}`;
    const th = el("div", { class: `th${ratio ? " fit" : ""}`, style: `--img:url("${url}")` }, el("div", { class: "thimg" }),
      el("div", { class: "badges" },
        r.open ? el("span", { class: "badge open" }, "Open now") : r.rendered ? el("span", { class: "badge ok" }, ic("check"), "Rendered") : null,
        el("span", { class: "badge fmtb" }, ratio || "9:16")),
      r.brand && r.brand !== "default" ? el("span", { class: "clientb" }, window.brandName ? brandName(r.brand) : r.brand) : null);
    return el("div", { class: "reel", role: "button", tabindex: "0", title: r.path, onclick: () => openReel(r.path),
      onkeydown: (e) => { if (e.key === "Enter") openReel(r.path); } }, th,
      el("button", { class: "del icon", title: "Delete this video", "aria-label": `Delete ${r.name}`,
        onclick: (e) => { e.stopPropagation(); confirmDelete(r, () => { reels.splice(reels.indexOf(r), 1); drawChips(); draw(); }); } }, ic("trash-2")),
      el("div", { class: "meta" }, el("b", {}, r.name),
        el("span", {}, `${r.duration ? fmtT(r.duration).replace(/\.\d+$/, "") : "?"} · ${r.cards} cards · ${ago(r.modified)}`),
        window.plannerBadge ? plannerBadge(r.path.replace(/\/edit$/, "")) : null,
        r.rendered_path && window.PORTAL ? el("button", { class: "finder", title: "Download the finished video",
          onclick: (e) => { e.stopPropagation(); downloadFile(r.rendered_path); } }, ic("download"), "Download") :
        r.rendered_path ? el("button", { class: "finder", title: r.rendered_path,
          onclick: (e) => { e.stopPropagation(); fetch("/api/reveal", { method: "POST", body: JSON.stringify({ path: r.rendered_path }) }); } }, ic("folder-open"), "Show in Finder") : null));
  };
  const draw = () => {
    const q = search.value.trim().toLowerCase();
    grid.innerHTML = "";
    const list = reels.filter((r) => ofClient(r) && (filter === "all" || (r.format || "reel") === filter) && (!q || (r.name + " " + r.folder).toLowerCase().includes(q)));
    const mine = list.filter(inLib), other = list.filter((r) => !inLib(r));
    if (!q) grid.append(el("button", { class: "reel newcard", onclick: openWizard }, el("span", { class: "plus" }, ic("plus")), el("b", {}, "New video"), el("span", {}, "From a raw camera file")));
    mine.forEach((r) => grid.append(card(r)));
    if (other.length) {
      grid.append(el("div", { class: "gsec" }, ic("folder"), "Elsewhere on this Mac", el("span", {}, "found by Spotlight or opened before; they render into 06. Renders too")));
      other.forEach((r) => grid.append(card(r)));
    }
    if (!list.length && (q || filter !== "all")) grid.append(el("div", { class: "empty" }, "No videos match."));
  };
  search.oninput = draw; drawChips(); draw(); search.focus();
}
function hideHome() { $("#home").hidden = true; }

// delete = move the reel's whole folder to the Trash (it can be put back from there)
function confirmDelete(r, done) {
  const root = r.path.replace(/\/(edit|build)$/, "");
  const inLibrary = root.startsWith(S.caps?.library || "\0");
  const go = el("button", { class: "primary", style: "background:var(--danger);border-color:var(--danger)" }, "Move to Trash");
  const errLine = el("div", { class: "err" });
  openModal(el("div", { class: "box" },
    el("h3", {}, `Delete “${r.name}”?`),
    el("div", { class: "hint" }, "This moves the video's project folder to the Trash: the raw video, the edit, captions and cards. Finished videos in 06. Renders are kept. You can put it back from the Trash."),
    el("pre", {}, root.replace(/^\/Users\/[^/]+/, "~")),
    !inLibrary ? el("div", { class: "note" }, "This video isn't in the editor's library, so it's one of your own project folders. Check it's the one you mean.") : null,
    r.open ? el("div", { class: "note" }, "This video is open in the editor. It will close.") : null,
    errLine,
    el("div", { class: "btns", style: "justify-content:flex-end;margin-top:12px" }, el("button", { onclick: closeModal }, "Cancel"), go)));
  go.onclick = async () => {
    go.disabled = true;
    const res = await fetch("/api/delete", { method: "POST", body: JSON.stringify({ path: r.path }) }).then((x) => x.json()).catch((e) => ({ error: String(e) }));
    if (!res.ok) { errLine.textContent = res.error || "Couldn't delete it."; go.disabled = false; return; }
    closeModal(); toast(`Moved “${r.name}” to the Trash`);
    if (r.open) { S.dirty = false; S.leaving = true; location.reload(); return; }
    done();
  };
}
async function browse() {
  const { path } = await fetch("/api/browse", { method: "POST" }).then((r) => r.json());
  if (path) openReel(path);
}
function openReel(path) {
  leave(async () => {
    const r = await fetch("/api/open", { method: "POST", body: JSON.stringify({ path }) }).then((x) => x.json());
    if (!r.ok) { S.leaving = false; toast(r.error || "That folder isn't a video project."); return; }
    try { localStorage.removeItem("newjob"); } catch (e) {}
    location.reload();
  });
}

// ---------------------------------------------------------------- New
const N = { file: null, root: null, raw: null, timer: 0, format: "reel", template: "clean" };
const TEMPLATES = [
  { key: "clean", label: "Clean", sub: "Glass cards and captions over the footage" },
  { key: "takeover", label: "Takeover", sub: "Adds gradient cutaways for the key points: lists, big numbers, a recap" },
];
function templatePicker() {
  return el("div", { class: "fmts" }, ...TEMPLATES.map((T) => el("button", { class: `fmt tpl${N.template === T.key ? " on" : ""}`, onclick: () => { N.template = T.key; newForm(); } },
    el("span", { class: `tplico ${T.key}` }, el("i"), el("i"), el("i")),
    el("span", { class: "ft" }, el("b", {}, T.label), el("small", {}, T.sub)))));
}
const FORMATS = [
  { key: "reel", label: "Reel", ratio: "9:16", sub: "Instagram, TikTok, Shorts · 1080×1920", w: 9, h: 16 },
  { key: "feed", label: "Feed", ratio: "4:5", sub: "Instagram and LinkedIn feed · 1080×1350", w: 4, h: 5 },
  { key: "square", label: "Square", ratio: "1:1", sub: "Feeds, ads, carousels · 1080×1080", w: 1, h: 1 },
  { key: "landscape", label: "Landscape", ratio: "16:9", sub: "YouTube, LinkedIn, website · 1920×1080", w: 16, h: 9 },
];
function formatPicker() {
  return el("div", { class: "fmts" }, ...FORMATS.map((f) => el("button", { class: `fmt${N.format === f.key ? " on" : ""}`, onclick: () => { N.format = f.key; fitScreen(); newForm(); } },
    el("span", { class: "shape", style: `aspect-ratio:${f.w}/${f.h}` }),
    el("span", { class: "ft" }, el("b", {}, `${f.label} `, el("span", { class: "rt" }, f.ratio)), el("small", {}, f.sub)))));
}

function enterNew() {
  hideHome();
  S.mode = "new"; S.sel = null; S.dirty = false;
  document.body.classList.add("mode-new");
  S.spec = { duration: 60, cards: [], captions: {}, format: N.format }; S.words = []; S.groups = []; S.peaks = []; S.edl = []; S.film = null;
  computeTotals(); drawTimeline();
  frames().forEach((f) => { f.classList.remove("active"); f.src = "about:blank"; });
  active = null;
  $("#pvMsg").hidden = true; $("#drop").hidden = false; $("#rawPv").hidden = true;
  $("#projName").textContent = "New video"; setStatus(" ");
  fitScreen();
  newForm();
}

function newForm(err) {
  const box = $("#insp"); box.innerHTML = "";
  const name = el("input", { type: "text", class: "grow", placeholder: "AI tools for agencies", value: N.name || "" });
  const notes = el("textarea", { class: "notes", placeholder: "Optional: what the cards should say, tools or numbers to show, takes to drop, a different call to action…" });
  notes.value = N.notes || "";
  const errLine = el("div", { class: "err" }, err || "");
  const go = el("button", { class: "primary" }, "Create video");
  box.append(
    el("h2", {}, "New video"),
    el("div", { class: "sub" }, "Drop in the raw talking-head video and pick a format. The editing steps run automatically, then the video opens here to edit."),
    el("div", { class: "row" }, el("label", {}, "Format"), formatPicker()),
    el("div", { class: "row" }, el("label", {}, "Template"), templatePicker()),
    row("Video name", name),
    el("div", { class: "row" }, el("label", {}, "Notes for Claude"), notes),
    claudeNote(),
    el("div", { class: "row" }, el("label", {}, "Video"), el("span", { id: "fileName", class: "hint" }, N.file ? `${N.file.name} · ${(N.file.size / 1e6).toFixed(0)} MB` : "None chosen yet")),
    errLine,
    el("div", { class: "btns" }, go, el("button", { onclick: () => leave(() => location.reload()) }, "Cancel")),
    sec("What happens", el("ul", { class: "steps" }, ...STEP_LABELS.map(([k, l]) => el("li", { class: "pending" }, el("span", { class: "ic" }), el("span", { class: "lbl" }, l))))),
  );
  name.oninput = () => { N.name = name.value; errLine.textContent = ""; };
  notes.oninput = () => (N.notes = notes.value);
  go.onclick = () => {
    if (!N.file) { errLine.textContent = "Choose the raw video first."; return; }
    if (!name.value.trim()) { errLine.textContent = "Give the video a name."; name.focus(); return; }
    startNew(name.value.trim(), notes.value);
  };
}
const STEP_LABELS = [["setup", "Set up the project"], ["transcribe", "Transcribe the raw video"], ["lighting", "Even out the lighting"],
  ["retakes", "Find retakes and false starts"], ["cuts", "Plan cuts and zooms"], ["edit", "Render the base edit"],
  ["captions", "Transcribe the edit"], ["plan", "Plan captions and cards"], ["build", "Build the video"]];

function claudeNote() {
  if (S.caps?.claude) return el("div", { class: "note ok" }, "Claude Code is set up: it will remove retakes and plan the captions and cards.");
  return el("div", { class: "note" },
    "Claude Code isn't installed, so retakes won't be removed and the video starts with captions and the end screen only. ",
    "Every other step still runs. To let Claude plan the cards too, install it in Terminal and sign in once:", el("br"),
    el("code", {}, "curl -fsSL https://claude.ai/install.sh | bash"), " then run ", el("code", {}, "claude"), ".");
}

function chooseFile(f) {
  if (!f) return;
  if (!/^video\//.test(f.type) && !/\.(mov|mp4|m4v|webm|mkv)$/i.test(f.name)) { toast("That isn't a video file."); return; }
  N.file = f;
  if (!N.name) N.name = f.name.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ").trim();
  const v = $("#rawPv"); v.src = URL.createObjectURL(f); v.hidden = false; v.play().catch(() => {});
  $("#drop").hidden = true;
  newForm();
}

function startNew(name, notes) {
  const box = $("#insp"); box.innerHTML = "";
  const bar = el("i"), pct = el("span", { class: "hint" }, "0%");
  box.append(el("h2", {}, name), el("div", { class: "sub" }, "Copying the video into your library…"),
    el("div", { class: "progress" }, bar), pct);
  const xhr = new XMLHttpRequest();
  xhr.open("PUT", `/api/new/upload?name=${encodeURIComponent(name)}&file=${encodeURIComponent(N.file.name)}`);
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) { const p = (e.loaded / e.total) * 100; bar.style.width = p + "%"; pct.textContent = `${Math.round(p)}%`; } };
  xhr.onload = async () => {
    const r = JSON.parse(xhr.responseText || "{}");
    if (xhr.status !== 200) { newForm(r.error || "The upload failed."); return; }
    N.root = r.root; N.raw = r.raw;
    try { localStorage.setItem("newjob", JSON.stringify({ root: r.root, raw: r.raw, name })); } catch (e) {}
    const st = await fetch("/api/new/start", { method: "POST", body: JSON.stringify({ root: r.root, raw: r.raw, notes, format: N.format, template: N.template }) }).then((x) => x.json());
    showJob(st, name);
  };
  xhr.onerror = () => newForm("The upload failed. Is server.py still running?");
  xhr.send(N.file);
}

function showJob(st, name) {
  clearTimeout(N.timer);
  const box = $("#insp"); box.innerHTML = "";
  const icon = { done: "✓", failed: "✕", skipped: "–", running: "", pending: "" };
  const failed = st.steps.find((s) => s.state === "failed");
  box.append(
    el("h2", {}, name || "New video", el("span", { class: "tag" }, st.done ? "ready" : st.error ? "stopped" : "working")),
    el("div", { class: "sub" }, st.done ? "Done. Opening the editor…" : st.error ? "A step failed. You can fix the cause and retry from there." : "This takes a few minutes. You can leave this tab open."),
    el("ul", { class: "steps" }, ...st.steps.map((s) => el("li", { class: s.state },
      el("span", { class: "ic" }, icon[s.state]), el("span", { class: "lbl" }, s.label), s.info ? el("span", { class: "inf" }, s.info) : null))),
    st.error ? el("div", { class: "err" }, st.error) : null,
    failed ? el("div", { class: "btns" },
      el("button", { class: "primary", onclick: async () => showJob(await fetch("/api/new/start", { method: "POST", body: JSON.stringify({ root: st.root, raw: N.raw, from: failed.key }) }).then((x) => x.json()), name) }, `Retry from “${failed.label}”`),
      el("button", { onclick: () => leave(() => { localStorage.removeItem("newjob"); location.reload(); }) }, "Start over")) : null,
    !st.claude && !st.done ? claudeNote() : null,
    el("details", {}, el("summary", { class: "hint" }, "Details"), el("pre", { class: "log" }, st.log.join("\n"))),
  );
  const pre = box.querySelector("pre.log"); if (pre) pre.scrollTop = 1e9;
  if (st.done) { try { localStorage.removeItem("newjob"); } catch (e) {} openReel(st.edit); return; }
  if (st.running) N.timer = setTimeout(async () => {
    const s2 = await fetch(`/api/new/status?root=${encodeURIComponent(st.root)}`).then((x) => x.json()).catch(() => null);
    if (s2 && !s2.error?.startsWith?.("No such")) showJob(s2, name); else N.timer = setTimeout(() => showJob(st, name), 2000);
  }, 1200);
}

// a reel that was being created when the page was reloaded
async function resumeNewJob() {
  let j; try { j = JSON.parse(localStorage.getItem("newjob") || "null"); } catch (e) {}
  if (!j) return false;
  const st = await fetch(`/api/new/status?root=${encodeURIComponent(j.root)}`).then((x) => (x.ok ? x.json() : null)).catch(() => null);
  if (!st) { localStorage.removeItem("newjob"); return false; }
  N.root = j.root; N.raw = j.raw; N.name = j.name;
  enterNew();
  $("#drop").hidden = true;
  const v = $("#rawPv"); v.src = `/api/new/raw?root=${encodeURIComponent(j.root)}`; v.hidden = false; v.play().catch(() => {});
  showJob(st, j.name);
  return true;
}

// ---------------------------------------------------------------- wiring
$("#openBtn").onclick = () => showHome(false);
$("#newBtn").onclick = newInSection;
$("#pickFile").onclick = () => $("#fileIn").click();
$("#fileIn").onchange = (e) => chooseFile(e.target.files[0]);
const drop = $("#drop");
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => chooseFile(e.dataTransfer.files[0]));
// dropping a video anywhere on the page while in New
addEventListener("dragover", (e) => { if (S.mode === "new") e.preventDefault(); });
addEventListener("drop", (e) => { if (S.mode === "new" && e.dataTransfer?.files?.[0]) { e.preventDefault(); chooseFile(e.dataTransfer.files[0]); } });

boot();
