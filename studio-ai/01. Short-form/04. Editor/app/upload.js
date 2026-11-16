// Files from the browser instead of Finder (ROADMAP phase 7: the team portal). window.PORTAL is set by the server on the
// portal; on a Mac the editor keeps its Finder dialogs and "Show in Finder".
// uploadFile() sends a file in 8 MB pieces to /api/upload (uploads.py). If the connection drops, it asks the server how
// much arrived and carries on from there, so a 50 GB camera file never starts again from zero.
(function () {
  const PIECE = 8 * 1024 * 1024;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function json(url, opts) {
    const r = await fetch(url, opts);
    const body = await r.json().catch(() => ({}));
    return { status: r.status, body };
  }

  // → the upload id, for {"upload": id} in the route that uses the file. onProgress(fraction, sentBytes, totalBytes).
  window.uploadFile = async function (file, onProgress) {
    const st = await json("/api/upload/start", { method: "POST", body: JSON.stringify({ name: file.name, size: file.size }) });
    if (!st.body.id) throw new Error(st.body.error || "The upload couldn't start");
    const id = st.body.id;
    let at = 0, tries = 0;
    if (onProgress) onProgress(file.size ? 0 : 1, 0, file.size);
    while (at < file.size) {
      const piece = file.slice(at, Math.min(file.size, at + PIECE));
      let r;
      try {
        r = await json(`/api/upload/${id}?offset=${at}`, { method: "PUT", body: piece });
      } catch (e) {
        r = { status: 0, body: {} };                        // network: ask where it got to, then carry on
      }
      if (r.status === 200) { at = r.body.size; tries = 0; }
      else {
        if (++tries > 8) throw new Error(r.body.error || "The upload keeps failing. Check the connection and try again");
        await wait(Math.min(15000, 500 * 2 ** tries));
        const s = await json(`/api/upload/${id}`).catch(() => null);
        if (s && s.status === 200) at = s.body.size;
        else if (s && s.status === 400) throw new Error(s.body.error || "The upload was lost");
      }
      if (onProgress) onProgress(file.size ? at / file.size : 1, at, file.size);
    }
    return id;
  };

  // A file chooser instead of Finder. accept like "video/*" or ".srt,.vtt". → [File] (empty when cancelled)
  window.pickFiles = function (accept, multiple) {
    return new Promise((resolve) => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = accept || ""; inp.multiple = !!multiple; inp.style.display = "none";
      inp.onchange = () => { resolve([...inp.files]); inp.remove(); };
      inp.oncancel = () => { resolve([]); inp.remove(); };
      document.body.append(inp); inp.click();
    });
  };

  // Pick one file and upload it with a progress toast. → upload id, or null when cancelled
  window.pickAndUpload = async function (accept, what) {
    const [f] = await pickFiles(accept);
    if (!f) return null;
    const say = (t) => (typeof toast === "function" ? toast(t) : null);
    let last = -1;
    return uploadFile(f, (p) => {
      const pct = Math.floor(p * 100);
      if (pct !== last && (pct % 5 === 0 || pct === 100)) { last = pct; say(`Uploading ${what || f.name}: ${pct}%`); }
    }).catch((e) => { say(e.message); return null; });
  };

  // "Show in Finder" on the portal: download the file instead
  window.downloadFile = function (path) {
    const a = document.createElement("a");
    a.href = `/api/download?path=${encodeURIComponent(path)}`; a.download = "";
    document.body.append(a); a.click(); a.remove();
  };
})();
