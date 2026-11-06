// Melodrop web UI. Plain ES module, no build step.

const $ = (id) => document.getElementById(id);
const POLL_MS = 700;
const SETTINGS_KEY = "melodrop-settings";
const SETTING_IDS = ["format", "bitrate", "height", "browser", "embed_cover", "square_cover", "number_files"];
const STATUS_LABEL = {
  queued: "Waiting", converting: "Converting…", done: "Saved ✓", error: "Failed", cancelled: "Cancelled",
};

const state = { config: null, playlist: null, job: null, jobRows: [], pollTimer: null };

// ---------- helpers ----------
const api = {
  async request(method, path, body) {
    const res = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  },
  get: (path) => api.request("GET", path),
  post: (path, body = {}) => api.request("POST", path, body),
};

const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function formatDuration(seconds) {
  if (!seconds && seconds !== 0) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${sec}` : `${m}:${sec}`;
}

function setMessage(html, isError = false) {
  $("msg").className = "msg" + (isError ? " err" : "");
  $("msg").innerHTML = html;
}

const show = (id, visible) => $(id).classList.toggle("hidden", !visible);

// ---------- settings ----------
function fillSelect(select, items) {
  const keep = select.querySelector('option[value=""]');
  select.innerHTML = "";
  if (keep) select.append(keep);
  for (const { value, label } of items) select.append(new Option(label, value));
}

function inputValue(el) { return el.type === "checkbox" ? el.checked : el.value; }

function saveSettings() {
  const values = Object.fromEntries(SETTING_IDS.map((id) => [id, inputValue($(id))]));
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(values)); } catch { /* private mode */ }
}

function restoreSettings() {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(SETTINGS_KEY) || "{}"); } catch { /* ignore */ }
  for (const id of SETTING_IDS) {
    if (!(id in saved)) continue;
    const el = $(id);
    if (el.type === "checkbox") el.checked = Boolean(saved[id]);
    else if ([...el.options].some((o) => o.value === String(saved[id]))) el.value = String(saved[id]);
  }
}

function currentFormat() {
  return state.config.formats.find((f) => f.key === $("format").value) || state.config.formats[0];
}

function syncFormatOptions() {
  const f = currentFormat();
  const audio = f.kind === "audio";
  show("heightWrap", !audio);
  show("bitrateWrap", audio && f.lossy);
  show("coverWrap", f.supports_cover);
  show("squareWrap", audio && f.supports_cover && $("embed_cover").checked);
}

function readOptions() {
  return {
    format: $("format").value,
    bitrate: Number($("bitrate").value),
    height: Number($("height").value),
    browser: $("browser").value,
    embed_cover: $("embed_cover").checked,
    square_cover: $("square_cover").checked,
    number_files: $("number_files").checked,
  };
}

async function loadConfig() {
  const config = await api.get("/api/config");
  state.config = config;
  fillSelect($("format"), config.formats.map((f) => ({ value: f.key, label: f.label })));
  fillSelect($("bitrate"), config.bitrates.map((b) => ({ value: b, label: `${b} kbps` })));
  fillSelect($("height"), config.heights.map((h) => ({ value: h, label: h >= 2160 ? "4K (2160p)" : `${h}p` })));
  fillSelect($("browser"), config.browsers.map((b) => ({ value: b, label: b[0].toUpperCase() + b.slice(1) })));
  $("height").value = "1080";
  restoreSettings();
  syncFormatOptions();
}

// ---------- playlist ----------
async function onFetch(event) {
  event.preventDefault();
  const url = $("url").value.trim();
  if (!url) return;
  $("fetchBtn").disabled = true;
  setMessage('<span class="spin"></span>Reading link… big playlists can take a moment.');
  try {
    state.playlist = await api.post("/api/playlist", { url, browser: $("browser").value });
    stopPolling();
    state.job = null;
    renderPlaylist();
    setMessage("");
  } catch (err) {
    setMessage(escapeHtml(err.message), true);
  } finally {
    $("fetchBtn").disabled = false;
  }
}

function renderPlaylist() {
  const { playlist } = state;
  const count = playlist.tracks.length;
  show("result", true);
  $("plTitle").textContent = playlist.title;
  $("plThumb").src = playlist.thumbnail || "";
  show("plThumb", Boolean(playlist.thumbnail));
  $("plMeta").textContent = [
    playlist.uploader,
    `${count} track${count === 1 ? "" : "s"}`,
    playlist.total_duration ? formatDuration(playlist.total_duration) : "",
  ].filter(Boolean).join(" · ");
  ["overall", "openBtn", "cancelBtn", "retryBtn"].forEach((id) => show(id, false));

  $("tracks").innerHTML = playlist.tracks.map((t, i) => `
    <li data-index="${i}">
      <input type="checkbox" class="pick" checked aria-label="Select ${escapeHtml(t.title)}">
      <span class="num">${t.position ?? i + 1}</span>
      <img class="thumb" loading="lazy" src="${escapeHtml(t.thumbnail || "")}" alt="">
      <div class="info">
        <div class="t" title="${escapeHtml(t.title)}">${escapeHtml(t.title)}</div>
        <div class="a">${escapeHtml(t.artist)}</div>
        <div class="bar hidden"><div></div></div>
        <div class="errline hidden"></div>
      </div>
      <span class="status">${formatDuration(t.duration)}</span>
    </li>`).join("");
  updateDownloadButton();
}

const rows = () => [...$("tracks").querySelectorAll("li")];
const selectedIndexes = () => rows().filter((li) => li.querySelector(".pick").checked).map((li) => Number(li.dataset.index));
const jobRunning = () => Boolean(state.job && !state.job.finished);

function updateDownloadButton() {
  const n = selectedIndexes().length;
  const total = state.playlist.tracks.length;
  $("dlBtn").textContent = n === total ? `Download all (${n})` : `Download ${n} selected`;
  $("dlBtn").disabled = n === 0 || jobRunning();
  $("toggleAll").textContent = n ? "Select none" : "Select all";
}

function toggleAll() {
  const select = selectedIndexes().length === 0;
  rows().forEach((li) => { li.querySelector(".pick").checked = select; });
  updateDownloadButton();
}

// ---------- downloads ----------
async function startDownload(indexes) {
  if (!indexes.length) return;
  setMessage("");
  $("browser").classList.remove("attn");
  show("retryBtn", false);
  $("dlBtn").disabled = true;
  try {
    const tracks = indexes.map((i) => {
      const { id, title, url, position } = state.playlist.tracks[i];
      return { id, title, url, position };
    });
    state.job = await api.post("/api/jobs", { folder: state.playlist.title, options: readOptions(), tracks });
    state.jobRows = indexes;
    setPicksDisabled(true);
    ["cancelBtn", "openBtn", "overall"].forEach((id) => show(id, true));
    renderJob();
    state.pollTimer = setInterval(poll, POLL_MS);
  } catch (err) {
    setMessage(escapeHtml(err.message), true);
    $("dlBtn").disabled = false;
  }
}

function setPicksDisabled(disabled) {
  rows().forEach((li) => { li.querySelector(".pick").disabled = disabled; });
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

async function poll() {
  try {
    state.job = await api.get(`/api/jobs/${state.job.id}`);
  } catch {
    return; // server busy; try again on the next tick
  }
  renderJob();
  if (state.job.finished) finishJob();
}

function renderTrackRow(li, track) {
  const status = li.querySelector(".status");
  const bar = li.querySelector(".bar");
  const errLine = li.querySelector(".errline");
  const percent = track.status === "done" ? 100 : track.percent || 0;
  const active = track.status === "downloading" || track.status === "converting";

  bar.classList.toggle("hidden", !active);
  bar.firstElementChild.style.width = `${percent}%`;
  status.className = `status ${track.status}`;
  if (track.status === "downloading") {
    status.textContent = `${percent.toFixed(0)}%`;
  } else if (track.status === "done" && track.file_url) {
    status.innerHTML = `<a href="${track.file_url}" title="Saved as ${escapeHtml(track.file_name)}. Click to save another copy.">${STATUS_LABEL.done}</a>`;
  } else {
    status.textContent = STATUS_LABEL[track.status] || track.status;
  }
  errLine.classList.toggle("hidden", !track.error);
  errLine.textContent = track.error || "";
}

function renderJob() {
  const { job } = state;
  const all = rows();
  let progress = 0;
  job.tracks.forEach((track, k) => {
    renderTrackRow(all[state.jobRows[k]], track);
    progress += ["error", "cancelled", "done"].includes(track.status) ? 100 : track.percent || 0;
  });
  const total = job.tracks.length;
  const done = job.tracks.filter((t) => t.status === "done").length;
  const failed = job.tracks.filter((t) => t.status === "error").length;
  const pct = Math.round(progress / total);
  $("overallBar").style.width = `${pct}%`;
  $("overallPct").textContent = `${pct}%`;
  const folderName = job.folder.split(/[\\/]/).pop();
  $("overallTxt").title = job.folder;
  $("overallTxt").textContent = job.finished
    ? `Finished: ${done} of ${total} saved${failed ? `, ${failed} failed` : ""}${job.cancelled ? " (cancelled)" : ""} · in “${folderName}”`
    : `Downloading ${done} of ${total}…`;
}

function finishJob() {
  stopPolling();
  show("cancelBtn", false);
  setPicksDisabled(false);
  updateDownloadButton();

  const failed = state.job.tracks.filter((t) => t.status === "error");
  $("retryBtn").textContent = `Retry failed (${failed.length})`;
  show("retryBtn", failed.length > 0);

  if (failed.some((t) => /not a bot|age-restricted/.test(t.error || ""))) {
    setMessage($("browser").value
      ? "YouTube still blocked some songs. Open youtube.com in that browser, check you're signed in, play any video, then click <b>Retry failed</b>."
      : "YouTube blocked some songs. Choose a browser under <b>Use browser login</b> (one where you're signed in to YouTube), then click <b>Retry failed</b>.", true);
    $("browser").classList.add("attn");
    $("browser").scrollIntoView({ behavior: "smooth", block: "center" });
  }
}

function retryFailed() {
  if (!state.job) return;
  const indexes = state.job.tracks
    .map((t, k) => (t.status === "error" ? state.jobRows[k] : -1))
    .filter((i) => i >= 0);
  startDownload(indexes);
}

function cancelJob() {
  if (state.job) api.post(`/api/jobs/${state.job.id}/cancel`).catch(() => {});
}

function openFolder() {
  const path = state.job ? `/api/jobs/${state.job.id}/open-folder` : "/api/open-folder";
  api.post(path).catch((err) => setMessage(escapeHtml(err.message), true));
}

// ---------- wiring ----------
function bindEvents() {
  $("form").addEventListener("submit", onFetch);
  $("format").addEventListener("change", syncFormatOptions);
  $("embed_cover").addEventListener("change", syncFormatOptions);
  SETTING_IDS.forEach((id) => $(id).addEventListener("change", saveSettings));
  $("tracks").addEventListener("change", (e) => { if (e.target.classList.contains("pick")) updateDownloadButton(); });
  $("toggleAll").addEventListener("click", toggleAll);
  $("dlBtn").addEventListener("click", () => startDownload(selectedIndexes()));
  $("retryBtn").addEventListener("click", retryFailed);
  $("cancelBtn").addEventListener("click", cancelJob);
  $("openBtn").addEventListener("click", openFolder);
}

bindEvents();
loadConfig().catch((err) => setMessage(escapeHtml(err.message), true));
