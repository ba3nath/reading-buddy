import { RecordingSession } from "./record.js";

const $ = (sel) => document.querySelector(sel);
const BUDDIES = ["krishna", "unicorn"];

/** Function words we skip when picking a picture for a sentence. */
const ILLUSTRATION_STOPWORDS = new Set([
  "a",
  "an",
  "the",
  "and",
  "or",
  "to",
  "of",
  "on",
  "in",
  "is",
  "it",
  "at",
  "for",
  "as",
  "by",
  "me",
  "be",
  "we",
  "he",
  "she",
  "they",
  "was",
  "were",
  "had",
  "has",
  "have",
  "you",
  "your",
  "my",
  "me",
  "i",
  "am",
  "are",
  "do",
  "did",
  "not",
  "no",
  "yes",
  "sir",
  "up",
  "any",
  "what",
  "how",
  "with",
  "from",
  "that",
  "this",
  "but",
  "so",
  "if",
  "then",
  "when",
  "all",
  "can",
  "will",
  "would",
  "could",
  "into",
  "out",
  "over",
  "under",
  "his",
  "her",
  "him",
  "them",
  "our",
  "us",
  "their",
  "went",
  "sat",
  "great",
  "full",
  "black",
  "wonder",
]);

const state = {
  id: "boot",
  sessionId: null,
  items: [],
  index: 0,
  /** Planned session size (5 or 10) — progress label never uses a grown queue. */
  plannedCount: 0,
  stars: 0,
  level: 1,
  stage: 1,
  stageByDifficulty: { 1: 1, 2: 1, 3: 1, 4: 1 },
  difficultyLabel: "",
  buddy: "krishna",
  profileName: "",
  closeAgainPending: false,
  /** When set, another read is required for the current word. */
  readAgain: null, // { tryNumber, triesMax, reason } | null
  replay: [],
  replayIndex: 0,
  phase: "read", // "read" | "replay" | "passage"
  passageDone: false,
  recorder: new RecordingSession(),
  audioEl: null,
  clipGen: 0,
  gardenGrowth: 0,
  svgCache: {},
  combo: 0,
  play: null, // home quest / streak / badges snapshot
  illustrationKeys: null, // Set<string> from /static/illustrations/keys.json
  paused: false, // mid-session home — Continue resumes without a new session
};

function sessionInPlay() {
  return Boolean(state.sessionId && state.items?.length && state.phase === "read");
}

function syncHomeControls() {
  const goHome = $("[data-go-home]");
  const pauseRow = $("[data-pause-row]");
  const startBtn = document.querySelector(
    '.btn.primary[data-start]:not([data-level-pick])'
  );
  const playing = sessionInPlay() && state.id !== "home" && state.id !== "session-end";
  if (goHome) goHome.hidden = !playing;
  if (pauseRow) pauseRow.hidden = !(state.paused && sessionInPlay());
  if (startBtn) {
    startBtn.textContent =
      state.paused && sessionInPlay() ? "Start fresh" : "Start";
  }
}

function setState(id) {
  state.id = id;
  document.body.dataset.state = id;
  const home = $('[data-view="home"]');
  const end = $('[data-view="end"]');
  const bootErr = $('[data-view="boot-error"]');
  home.hidden = id !== "home";
  end.hidden = id !== "session-end";
  bootErr.hidden = id !== "boot-error";
  syncBuddyAnim();
  syncHomeControls();
  syncHearAgain();
}

function buddyAnimForState(id) {
  if (
    id === "recording" ||
    id === "scoring" ||
    id === "listen" ||
    id === "session-replay"
  ) {
    return "listening";
  }
  if (id === "result-correct" || id === "session-end") return "cheer";
  if (
    id === "result-miss" ||
    id === "result-retry" ||
    id === "result-skip" ||
    id === "result-close"
  ) {
    return "encourage";
  }
  return "idle";
}

function applyAnimToHost(host, anim) {
  if (!host) return;
  host.dataset.buddyState = anim;
  const root = host.querySelector(".buddy-root");
  if (root) {
    root.classList.remove("idle", "listening", "cheer", "encourage");
    root.classList.add(anim);
  }
}

function syncBuddyAnim() {
  const anim = buddyAnimForState(state.id);
  applyAnimToHost($("[data-buddy]"), anim);
  if (state.id === "home") {
    applyAnimToHost($("[data-home-buddy]"), "idle");
  }
  if (state.id === "session-end") {
    applyAnimToHost($("[data-end-buddy]"), "cheer");
  }
}

async function fetchBuddySvg(name) {
  if (state.svgCache[name]) return state.svgCache[name];
  const res = await fetch(`/static/mascots/${name}.svg`);
  const svg = await res.text();
  state.svgCache[name] = svg;
  return svg;
}

async function loadBuddySvg(name) {
  let raw = name;
  if (raw === "mouse") raw = "unicorn"; // migrate retired mouse
  if (raw === "cat") raw = "krishna"; // migrate retired cat
  const buddy = BUDDIES.includes(raw) ? raw : "krishna";
  state.buddy = buddy;
  const host = $("[data-buddy]");
  if (host) host.dataset.buddy = buddy;
  try {
    const svg = await fetchBuddySvg(buddy);
    for (const sel of [
      "[data-buddy-slot]",
      "[data-home-buddy-slot]",
      "[data-end-buddy-slot]",
    ]) {
      const slot = $(sel);
      if (slot) slot.innerHTML = svg;
    }
    const greet = $("[data-home-greeting]");
    if (greet) {
      const labels = { krishna: "Krishna", unicorn: "Unicorn" };
      const name = String(state.profileName || "").trim();
      greet.textContent = name
        ? `Hi ${name} — pick me, then Start!`
        : `Hi — I'm ${labels[buddy]}! Ready when you are.`;
    }
    syncBuddyAnim();
  } catch (err) {
    console.error(err);
  }
  document.querySelectorAll("[data-buddy-choice]").forEach((btn) => {
    const on = btn.dataset.buddyChoice === buddy;
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.classList.toggle("selected", on);
  });
}

function setMessage(text) {
  $("[data-message]").textContent = text || "";
}

function setMicLabel(text) {
  const label = $(".mic-label");
  if (label) label.textContent = text;
  const btn = $("[data-mic]");
  if (!btn) return;
  const done = /when done/i.test(text || "");
  btn.dataset.micMode = done ? "done" : "ready";
  btn.setAttribute("aria-label", done ? "Stop recording" : "Start reading");
}

function setReadAgain(info) {
  state.readAgain = info;
  const el = $("[data-read-again]");
  if (!el) return;
  if (!info) {
    el.hidden = true;
    el.textContent = "Read again";
    return;
  }
  const n = Number(info.tryNumber) || 0;
  const max = Number(info.triesMax) || 0;
  el.textContent =
    n && max ? `Read again · ${n} of ${max}` : "Read again";
  el.hidden = false;
  // Retrigger pulse when a new retry arrives.
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
}

function clearReadAgain() {
  setReadAgain(null);
  setMicLabel("Tap to read");
}

function tokenizeForIllustration(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z\s']/g, " ")
    .split(/\s+/)
    .filter(Boolean);
}

/** Pick an SVG stem for a word or line (kid pictogram, not a meme). */
function resolveIllustrationKey(text, { kind = "word" } = {}) {
  const keys = state.illustrationKeys;
  const tokens = tokenizeForIllustration(text);
  if (!tokens.length) return null;
  if (tokens.length === 1) {
    if (keys && keys.has(tokens[0])) return tokens[0];
    return "_default";
  }
  let best = null;
  for (const t of tokens) {
    if (ILLUSTRATION_STOPWORDS.has(t)) continue;
    if (keys && !keys.has(t)) continue;
    if (!best || t.length > best.length) best = t;
  }
  if (best) return best;
  return kind === "line" ? "_line" : "_default";
}

function setWordArt(text, { kind = "word" } = {}) {
  const wrap = $("[data-word-art]");
  const img = $("[data-word-art-img]");
  if (!wrap || !img) return;
  if (!text) {
    wrap.hidden = true;
    img.removeAttribute("src");
    return;
  }
  wrap.classList.toggle("is-word", kind === "word");
  const key = resolveIllustrationKey(text, { kind });
  if (!key) {
    wrap.hidden = true;
    return;
  }
  const next = `/static/illustrations/${encodeURIComponent(key)}.svg`;
  if (img.getAttribute("src") !== next) {
    img.src = next;
    wrap.classList.remove("pop");
    void wrap.offsetWidth;
    wrap.classList.add("pop");
  }
  wrap.hidden = false;
}

function setHeard(transcript) {
  const el = $("[data-heard]");
  if (!el) return;
  const text = String(transcript || "").trim();
  if (!text) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = `I heard "${text}"`;
}

function setWord(text, { highlight = false, kind = "word", scores = null } = {}) {
  const el = $("[data-word]");
  const multi = Array.isArray(scores) && scores.length > 1;
  if (multi) {
    el.textContent = "";
    scores.forEach((ws, i) => {
      if (i) el.appendChild(document.createTextNode(" "));
      const span = document.createElement("span");
      if (ws.result === "missed") span.className = "word-soft";
      span.textContent = ws.word || "";
      el.appendChild(span);
    });
  } else {
    el.textContent = text || "";
  }
  el.classList.toggle("highlight", Boolean(highlight));
  setWordArt(text, { kind });
}

function popStarBurst() {
  const host = $("[data-star-burst]");
  if (!host) return;
  host.innerHTML = "";
  host.classList.remove("pop");
  void host.offsetWidth;
  const angles = [-50, -20, 10, 40, -35, 25];
  angles.forEach((deg, i) => {
    const el = document.createElement("i");
    el.textContent = "★";
    const rad = (deg * Math.PI) / 180;
    el.style.setProperty("--dx", `${Math.cos(rad) * (40 + i * 8)}px`);
    el.style.setProperty("--dy", `${Math.sin(rad) * (28 + i * 6) - 36}px`);
    el.style.left = `${40 + (i % 3) * 12}%`;
    el.style.top = `${45 + (i % 2) * 10}%`;
    host.appendChild(el);
  });
  host.classList.add("pop");
  setTimeout(() => {
    host.classList.remove("pop");
    host.innerHTML = "";
  }, 750);
}

/** Full-screen success flourishes — pick one at random each correct read. */
const SUCCESS_FX_KINDS = ["glitter", "rainbow", "chocolate", "applause", "stars"];

function popSuccessFx() {
  const host = $("[data-success-fx]");
  if (!host) return;
  const kind = SUCCESS_FX_KINDS[Math.floor(Math.random() * SUCCESS_FX_KINDS.length)];
  host.innerHTML = "";
  host.className = `success-fx success-fx-${kind} pop`;
  host.setAttribute("data-fx", kind);

  if (kind === "rainbow") {
    const arc = document.createElement("div");
    arc.className = "fx-rainbow-arc";
    host.appendChild(arc);
  } else if (kind === "applause") {
    for (let i = 0; i < 8; i += 1) {
      const clap = document.createElement("span");
      clap.className = "fx-clap";
      clap.textContent = "clap!";
      clap.style.setProperty("--i", String(i));
      clap.style.left = `${8 + (i % 4) * 22}%`;
      clap.style.top = `${18 + Math.floor(i / 4) * 40}%`;
      host.appendChild(clap);
    }
  } else {
    const count = kind === "chocolate" ? 28 : 36;
    const glyph =
      kind === "chocolate" ? "●" : kind === "stars" ? "★" : "✧";
    for (let i = 0; i < count; i += 1) {
      const bit = document.createElement("i");
      bit.className = `fx-bit fx-bit-${kind}`;
      bit.textContent = glyph;
      bit.style.setProperty("--i", String(i));
      bit.style.setProperty("--x", `${Math.random() * 100}%`);
      bit.style.setProperty("--delay", `${Math.random() * 0.35}s`);
      bit.style.setProperty("--dur", `${0.9 + Math.random() * 0.7}s`);
      bit.style.setProperty("--spin", `${Math.random() * 360}deg`);
      host.appendChild(bit);
    }
  }

  clearTimeout(popSuccessFx._timer);
  popSuccessFx._timer = setTimeout(() => {
    host.classList.remove("pop");
    host.innerHTML = "";
    host.removeAttribute("data-fx");
  }, 1400);
}

function celebrateCorrectRead() {
  popStarBurst();
  popSuccessFx();
}

function setStars(n, { celebrate = false } = {}) {
  const el = $("[data-stars]");
  const prev = Number(el.textContent) || 0;
  el.textContent = String(n);
  if (n > prev || celebrate) {
    el.parentElement.classList.remove("bump");
    void el.parentElement.offsetWidth;
    el.parentElement.classList.add("bump");
    if (celebrate || n > prev) celebrateCorrectRead();
  }
}

function setProgress() {
  const dots = $("[data-progress-dots]");
  const labelEl = $("[data-progress]");
  if (state.phase === "replay") {
    if (dots) dots.innerHTML = "";
    if (!state.replay.length) {
      labelEl.textContent = "";
      return;
    }
    labelEl.textContent = `Try again ${Math.min(state.replayIndex + 1, state.replay.length)} of ${state.replay.length}`;
    return;
  }
  if (!state.items.length) {
    if (dots) dots.innerHTML = "";
    labelEl.textContent = "";
    return;
  }
  // Sessions are only 5 or 10 — never show a grown total (e.g. 11 from old reinserts).
  let total = state.plannedCount;
  if (total !== 5 && total !== 10) {
    total = state.items.length === 5 || state.items.length === 10 ? state.items.length : 10;
  }
  const cur = Math.min(state.index + 1, total);
  const item = currentItem();
  labelEl.textContent =
    item && item.kind === "line"
      ? `Line ${cur} of ${total}`
      : `Word ${cur} of ${total}`;
  if (dots) {
    dots.innerHTML = "";
    for (let i = 0; i < total; i++) {
      const d = document.createElement("span");
      d.className = "dot";
      if (i < state.index) d.classList.add("done");
      if (i === state.index) d.classList.add("on");
      dots.appendChild(d);
    }
  }
}

function setMicEnabled(on) {
  $("[data-mic]").disabled = !on;
}

function stopClip() {
  state.clipGen = (state.clipGen || 0) + 1;
  if (state.audioEl) {
    try {
      state.audioEl.pause();
      state.audioEl.removeAttribute("src");
      state.audioEl.load();
    } catch {
      /* ignore */
    }
    state.audioEl = null;
  }
}

function clearReadAlong() {
  const el = $("[data-word]");
  if (!el) return;
  el.querySelectorAll(".word-readalong").forEach((span) => {
    span.classList.remove("is-active");
  });
}

function normalizeReadAlongTimings(text, timings) {
  let words = Array.isArray(timings) && timings.length
    ? timings.map((t) => ({
        word: t.word,
        start: Number(t.start) || 0,
        end: Number(t.end) || Number(t.start) || 0,
      }))
    : null;
  if (!words || !words.length) {
    const tokens = String(text || "")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!tokens.length) return [];
    // Fallback until /timings loads: one span for the whole clip.
    words = tokens.map((w, i) => ({
      word: w,
      start: i === 0 ? 0 : i,
      end: i + 1,
    }));
  }
  return words;
}

function setReadAlongWords(text, timings) {
  const el = $("[data-word]");
  if (!el) return [];
  const words = normalizeReadAlongTimings(text, timings);
  if (!words.length) {
    el.textContent = text || "";
    return [];
  }
  // Single words get a span too — visible pointer while listening (Phase 3).
  el.textContent = "";
  words.forEach((t, i) => {
    if (i) el.appendChild(document.createTextNode(" "));
    const span = document.createElement("span");
    span.className = "word-readalong";
    span.dataset.index = String(i);
    span.textContent = t.word;
    el.appendChild(span);
  });
  return words;
}

function syncReadAlong(audio, timings) {
  if (!audio || !Array.isArray(timings) || !timings.length) return;
  const t = audio.currentTime || 0;
  const spans = document.querySelectorAll("[data-word] .word-readalong");
  let active = -1;
  for (let i = 0; i < timings.length; i++) {
    const start = Number(timings[i].start) || 0;
    const end = Number(timings[i].end) || start;
    if (t >= start && t < end + 0.02) {
      active = i;
      break;
    }
    if (t >= start) active = i;
  }
  // Single-word clips: keep lit for the whole play once audio has started.
  if (timings.length === 1 && t > 0.02) active = 0;
  spans.forEach((span, i) => {
    span.classList.toggle("is-active", i === active);
  });
}

function playClip(url, { timings = null, text = "" } = {}) {
  return new Promise((resolve) => {
    stopClip();
    clearReadAlong();
    const gen = state.clipGen;
    const audio = new Audio(url);
    state.audioEl = audio;
    const wordTimings = setReadAlongWords(text, timings);
    const onTime = () => syncReadAlong(audio, wordTimings);
    const done = () => {
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
      audio.removeEventListener("timeupdate", onTime);
      clearReadAlong();
      // A newer stopClip/playClip won — do not keep the old element alive.
      if (gen !== state.clipGen) {
        resolve();
        return;
      }
      if (state.audioEl === audio) state.audioEl = null;
      resolve();
    };
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    if (wordTimings.length >= 1) {
      audio.addEventListener("timeupdate", onTime);
      // Light immediately so single-word listen always shows a pointer.
      if (wordTimings.length === 1) {
        document
          .querySelectorAll("[data-word] .word-readalong")
          .forEach((span) => span.classList.add("is-active"));
      }
    }
    audio.play().catch(done);
  });
}

function slugFromAudioUrl(url) {
  if (!url) return "";
  const m = String(url).match(/\/api\/audio\/([^/?#]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

async function playItemClip(item) {
  const slug = item?.slug || slugFromAudioUrl(item?.audio_url);
  if (!slug) return;
  const url = `/api/audio/${encodeURIComponent(slug)}`;
  let timings = null;
  try {
    const data = await api(`/api/audio/${encodeURIComponent(slug)}/timings`);
    timings = data?.words || null;
  } catch {
    timings = null;
  }
  await playClip(url, { timings, text: item.text || item.word || "" });
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const msg = body?.error?.message || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    err.body = body;
    throw err;
  }
  return body;
}

function gardenStageName(growth) {
  if (growth <= 0) return "seed";
  if (growth <= 2) return "sprout";
  if (growth <= 5) return "flower";
  if (growth <= 9) return "creature";
  return "sticker";
}

function applyGardenStage(root, growth) {
  if (!root) return;
  const stage = gardenStageName(growth);
  const objects = root.querySelectorAll(".garden-art");
  objects.forEach((obj) => {
    const set = () => {
      try {
        const doc = obj.contentDocument;
        const svg = doc && doc.querySelector("svg");
        if (svg) svg.setAttribute("data-stage", stage);
      } catch {
        /* ignore */
      }
    };
    if (obj.contentDocument && obj.contentDocument.querySelector("svg")) set();
    else obj.addEventListener("load", set, { once: true });
  });
}

function showGardenHome(growth) {
  state.gardenGrowth = growth;
  const wrap = $("[data-garden-home]");
  const cap = $("[data-garden-caption]");
  if (!wrap) return;
  if (growth <= 0) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  if (cap) {
    cap.textContent = `Garden: ${gardenStageName(growth)} (${growth} session${growth === 1 ? "" : "s"})`;
  }
  applyGardenStage(wrap, growth);
}

function renderPlayHud(play, { highlightNew = [] } = {}) {
  state.play = play || state.play;
  const p = state.play || {
    quest_complete: false,
    quest_label: "Finish today's reading",
    day_streak: 0,
    lifetime_stars: 0,
    badges: [],
  };
  const quest = $("[data-quest]");
  const mark = $("[data-quest-mark]");
  const label = $("[data-quest-label]");
  if (quest) quest.classList.toggle("is-done", Boolean(p.quest_complete));
  if (mark) mark.textContent = p.quest_complete ? "✓" : "◇";
  if (label) {
    label.textContent = p.quest_complete
      ? "Done for today — play again anytime!"
      : p.quest_label || "Finish today's reading";
  }
  const streak = $("[data-streak]");
  if (streak) {
    const n = Number(p.day_streak) || 0;
    streak.textContent = n > 0 ? `Streak ${n} day${n === 1 ? "" : "s"}` : "Start a streak today";
  }
  const bank = $("[data-star-bank]");
  if (bank) bank.textContent = `★ ${Number(p.lifetime_stars) || 0} all-time`;
  const row = $("[data-badges]");
  if (row) {
    const badges = p.badges || [];
    const news = new Set(highlightNew.map((b) => b.id || b));
    row.innerHTML = "";
    badges.forEach((b) => {
      const chip = document.createElement("span");
      chip.className = "badge-chip" + (news.has(b.id) ? " is-new" : "");
      chip.textContent = b.label || b.id;
      row.appendChild(chip);
    });
    if (!badges.length) {
      const tip = document.createElement("span");
      tip.className = "badge-chip";
      tip.textContent = "Badges unlock as you read";
      row.appendChild(tip);
    }
  }
}

function setCombo(n) {
  state.combo = Math.max(0, n);
  const el = $("[data-combo]");
  if (!el) return;
  if (state.combo < 2) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.textContent = `Sunny streak ×${state.combo}`;
  el.style.animation = "none";
  void el.offsetWidth;
  el.style.animation = "";
}

function popStarFloat(amount) {
  const el = $("[data-star-float]");
  if (!el || !(amount > 0)) return;
  el.textContent = `+${amount}★`;
  el.classList.remove("pop");
  void el.offsetWidth;
  el.classList.add("pop");
}

function showEndPlayRewards(play) {
  const quest = $("[data-end-quest]");
  const streak = $("[data-end-streak]");
  const badges = $("[data-end-badges]");
  if (quest) {
    quest.hidden = !play?.quest_complete;
  }
  if (streak) {
    const n = Number(play?.day_streak) || 0;
    if (n > 0) {
      streak.hidden = false;
      streak.textContent =
        n === 1 ? "Streak started — come back tomorrow!" : `${n}-day reading streak!`;
    } else {
      streak.hidden = true;
    }
  }
  if (badges) {
    const neu = play?.new_badges || [];
    if (neu.length) {
      badges.hidden = false;
      badges.innerHTML = "";
      neu.forEach((b) => {
        const chip = document.createElement("span");
        chip.className = "badge-chip is-new";
        chip.textContent = `New: ${b.label || b.id}`;
        badges.appendChild(chip);
      });
    } else {
      badges.hidden = true;
      badges.innerHTML = "";
    }
  }
}

async function loadIllustrationKeys() {
  try {
    const res = await fetch("/static/illustrations/keys.json");
    if (!res.ok) throw new Error("keys missing");
    const data = await res.json();
    state.illustrationKeys = new Set(data.keys || []);
  } catch {
    state.illustrationKeys = new Set();
  }
}

async function boot() {
  setState("boot");
  setMessage("Getting ready…");
  setMicEnabled(false);
  try {
    const health = await api("/api/health");
    if (!health.whisper || !health.ffmpeg) {
      setState("boot-error");
      $("[data-boot-error]").textContent =
        "Reading Buddy needs Whisper and ffmpeg on this computer. Ask an adult to finish setup, then reload.";
      return;
    }
    if (health.audio === false) {
      setState("boot-error");
      $("[data-boot-error]").textContent =
        "Voice clips are not ready yet. Ask an adult to run: python scripts/generate_audio.py";
      return;
    }
    await loadIllustrationKeys();
    const settings = await api("/api/parent/settings");
    await loadBuddySvg(settings.buddy || "krishna");
    showGardenHome(Number(settings.garden_growth) || 0);
    const name = String(settings.profile_name || "").trim();
    state.profileName = name;
    const greet = $("[data-home-greeting]");
    if (greet) {
      greet.textContent = name
        ? `Hi ${name} — pick me, then Start!`
        : "Hi — pick me, then Start!";
    }
    renderPlayHud(settings.play || {
      lifetime_stars: settings.lifetime_stars || 0,
      day_streak: settings.day_streak || 0,
      quest_complete: false,
      quest_label: "Words · Set 1/8",
      badges: [],
    });
    markCurrentSets(settings);
    const open = await api("/api/sessions/open");
    if (open && open.open) {
      applyOpenSession(open);
    }
    setState("home");
    setMessage("");
  } catch {
    setState("boot-error");
  }
}

async function refreshSetProgress() {
  try {
    const settings = await api("/api/parent/settings");
    markCurrentSets(settings);
  } catch {
    /* keep the last colors */
  }
}

function markCurrentSets(settings) {
  const incoming = settings?.stage_by_difficulty;
  if (incoming && typeof incoming === "object") {
    const next = { ...state.stageByDifficulty };
    for (const [key, val] of Object.entries(incoming)) {
      const n = Number(val);
      // Keep in sync with STAGES_PER_DIFFICULTY (currently 8).
      if (n >= 1 && n <= 8) next[Number(key)] = n;
    }
    state.stageByDifficulty = next;
  } else if (settings?.stage != null && settings?.level != null) {
    state.stageByDifficulty = {
      ...state.stageByDifficulty,
      [Number(settings.level)]: Number(settings.stage) || 1,
    };
  }
  document.querySelectorAll("[data-stage-pick]").forEach((btn) => {
    const diff = Number(btn.dataset.levelPick);
    const stage = Number(btn.dataset.stagePick);
    const current = Number(state.stageByDifficulty[diff]) || 1;
    btn.classList.toggle("is-current", stage === current);
    if (!settings?.set_progress) return;
    const status = settings.set_progress?.[String(diff)]?.[String(stage)] || "new";
    btn.classList.toggle("is-done", status === "done");
    btn.classList.toggle("is-partial", status === "partial");
    const word = status === "done" ? "finished" : status === "partial" ? "started" : "not started";
    btn.setAttribute("aria-label", `Set ${stage}, ${word}`);
  });
}

const OPEN_KEY = "reading-buddy-session";

function applyOpenSession(open) {
  state.sessionId = open.session_id;
  state.items = open.items || [];
  state.index = Number(open.index) || 0;
  state.plannedCount = Number(open.planned_count) || state.items.length;
  state.stars = Number(open.stars) || 0;
  state.level = open.level;
  state.stage = Number(open.stage) || 1;
  state.difficultyLabel = open.stage_label || "";
  state.paused = true;
  state.phase = "read";
  try {
    sessionStorage.setItem(OPEN_KEY, String(open.session_id));
  } catch {
    /* private mode */
  }
  syncHomeControls();
}

async function chooseBuddy(name) {
  if (!BUDDIES.includes(name)) return;
  await loadBuddySvg(name);
  try {
    await api("/api/parent/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ buddy: name }),
    });
  } catch (err) {
    console.error(err);
  }
}

function pauseToHome() {
  // Discard an in-flight take so pause never scores a half-said word.
  if (state.recorder?.isRecording) {
    state.recorder.discard();
  }
  stopClip();
  setMicEnabled(false);
  if (!sessionInPlay()) {
    setState("home");
    return;
  }
  state.paused = true;
  setMessage("Paused — tap Continue when you are ready");
  setState("home");
  refreshSetProgress();
  const hint = $("[data-pause-hint]");
  if (hint) {
    const total =
      state.plannedCount === 5 || state.plannedCount === 10
        ? state.plannedCount
        : state.items.length;
    const cur = Math.min(state.index + 1, total);
    hint.textContent = `Paused on ${cur} of ${total} — Continue anytime`;
  }
}

async function continueSession() {
  if (!sessionInPlay()) {
    setState("home");
    return;
  }
  state.paused = false;
  $('[data-view="home"]').hidden = true;
  $('[data-view="end"]').hidden = true;
  const badge = $("[data-level]");
  if (badge && state.level) {
    badge.hidden = false;
    badge.textContent = state.difficultyLabel || `Level ${state.level}`;
  }
  setStars(state.stars);
  setProgress();
  syncHomeControls();
  if (state.index >= state.items.length && needsReadThrough()) {
    await startReadThrough();
    return;
  }
  await showListen();
}

async function startSession(level, stage) {
  clearReadAgain();
  clearPhraseScore();
  state.paused = false;
  setMessage("Starting…");
  setMicEnabled(false);
  const payload = {};
  if (level != null && Number.isFinite(level)) payload.level = level;
  if (stage != null && Number.isFinite(stage)) payload.stage = stage;
  const body =
    Object.keys(payload).length > 0 ? JSON.stringify(payload) : undefined;
  const data = await api("/api/sessions", {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body,
  });
  state.sessionId = data.session_id;
  state.items = data.items || [];
  state.index = 0;
  const planned = Number(data.planned_count);
  state.plannedCount = planned > 0 ? planned : state.items.length;
  try {
    sessionStorage.setItem(OPEN_KEY, String(data.session_id));
  } catch {
    /* private mode */
  }
  // Never keep a longer play list than the planned session size.
  if (state.items.length > state.plannedCount) {
    state.items = state.items.slice(0, state.plannedCount);
  }
  state.stars = 0;
  state.level = data.level;
  state.stage = Number(data.stage) || 1;
  markCurrentSets({
    level: data.level,
    stage: state.stage,
    stage_by_difficulty: { [String(data.level)]: state.stage },
  });
  state.difficultyLabel =
    data.stage_label ||
    data.difficulty_label ||
    data.difficultyLabel ||
    `Level ${data.level}`;
  if (data.buddy) await loadBuddySvg(data.buddy);
  state.closeAgainPending = false;
  state.replay = [];
  state.replayIndex = 0;
  state.phase = "read";
  state.combo = 0;
  setCombo(0);
  setStars(0);
  const badge = $("[data-level]");
  badge.hidden = false;
  badge.textContent = state.difficultyLabel;
  $('[data-view="home"]').hidden = true;
  $('[data-view="end"]').hidden = true;
  syncHomeControls();
  showListen();
}

function currentItem() {
  return state.items[state.index];
}

function currentReplay() {
  return state.replay[state.replayIndex];
}

async function showListen() {
  const item = currentItem();
  if (!item) {
    finishSession();
    return;
  }
  // Always stop any prior clip before swapping the on-screen line + audio.
  stopClip();
  clearPhraseScore();
  setHeard("");
  setState("listen");
  setWord(item.text, { kind: item.kind || "word" });
  if (state.readAgain) {
    setMessage(rhymeListenMessage(item, { again: true }));
    setMicLabel("Tap to read again");
  } else {
    setMessage(rhymeListenMessage(item));
    setMicLabel("Tap to read");
  }
  setProgress();
  setMicEnabled(false);
  try {
    await playItemClip(item);
  } catch (err) {
    console.error(err);
  }
  if (state.id === "listen") enterIdle();
}

function enterIdle() {
  setState("idle");
  const item = currentItem();
  if (state.readAgain) {
    setMessage(
      item && item.kind === "line"
        ? "Your turn again — tap and read the line"
        : "Your turn again — tap and read it"
    );
    setMicLabel("Tap to read again");
  } else {
    setMessage(
      item && item.kind === "line"
        ? "Your turn — tap and read the line"
        : "Your turn — tap and read the word"
    );
    setMicLabel("Tap to read");
  }
  setMicEnabled(true);
  syncHearAgain();
}

function currentListenUrl() {
  if (state.phase === "replay") {
    const entry = currentReplay();
    if (!entry) return null;
    return entry.audio_url || `/api/audio/${encodeURIComponent(entry.text)}`;
  }
  const item = currentItem();
  if (!item?.slug) return null;
  return `/api/audio/${encodeURIComponent(item.slug)}`;
}

function syncHearAgain() {
  const btn = $("[data-hear-again]");
  if (!btn) return;
  const hasClip = Boolean(currentListenUrl());
  const canShow =
    hasClip &&
    (state.id === "idle" ||
      state.id === "listen" ||
      state.id === "session-replay");
  btn.hidden = !canShow;
  // Only tappable once the auto-play has finished (idle).
  btn.disabled = state.id !== "idle";
}

async function hearAgain() {
  const url = currentListenUrl();
  if (!url || state.id !== "idle") return;
  // Don't steal a live take — only replay while waiting for the mic.
  if (state.recorder?.isRecording) return;
  const btn = $("[data-hear-again]");
  if (btn) btn.disabled = true;
  setMicEnabled(false);
  try {
    if (state.phase === "replay") {
      const entry = currentReplay();
      if (entry) await playItemClip(entry);
      else await playClip(url);
    } else {
      const item = currentItem();
      if (item?.slug) await playItemClip(item);
      else await playClip(url);
    }
  } catch (err) {
    console.error(err);
  }
  if (state.id === "idle" || state.id === "listen" || state.id === "session-replay") {
    // Stay on the same word; re-arm mic + Hear again.
    if (state.id !== "idle") setState("idle");
    setMicEnabled(true);
    syncHearAgain();
  }
}

function hideReadAgainBanner() {
  const el = $("[data-read-again]");
  if (el) el.hidden = true;
}

async function onMicTap() {
  // Second tap while recording = "I'm done" (keeps one clear take).
  if (state.id === "recording" && state.recorder.isRecording) {
    setMessage("Got it…");
    setMicEnabled(false);
    hideReadAgainBanner();
    state.recorder.stop();
    return;
  }
  if (state.id !== "idle") return;
  setState("recording");
  // They pressed for the follow-up take — don't keep saying "one more".
  hideReadAgainBanner();
  setMessage(
    state.readAgain
      ? "I hear you — read it clearly, then tap when done"
      : "I hear you — read the word, then tap again when done"
  );
  setMicEnabled(false);
  setMicLabel("Tap when done");
  await state.recorder.start({
    oncomplete: (blob) => onRecordComplete(blob),
    onarmed: () => {
      // Allow tap-to-finish once the recorder is live.
      setMicEnabled(true);
    },
    onerror: (err) => {
      console.error(err);
      setMessage("We need the microphone to hear you. Ask an adult to allow it.");
      setState("idle");
      setMicEnabled(true);
      if (state.readAgain) {
        setReadAgain(state.readAgain);
        setMicLabel("Tap to read again");
      } else {
        setMicLabel("Tap to read");
      }
    },
  });
}

async function onRecordComplete(blob) {
  setState("scoring");
  setMessage("Listening…");
  setMicEnabled(false);
  hideReadAgainBanner();
  setMicLabel("Tap to read");
  const form = new FormData();
  form.append("phase", state.phase);
  form.append("audio", blob, "take.webm");
  if (state.phase === "passage") {
    form.append("item_id", String(state.items[0].id));
  } else if (state.phase === "replay") {
    const entry = currentReplay();
    form.append("item_id", String(entry.item_id));
    form.append("word", entry.word || entry.text);
  } else {
    const item = currentItem();
    form.append("item_id", String(item.id));
    form.append("queue_index", String(state.index));
  }
  // Prior take's stop→response latency (FormData is already on the wire for this take).
  if (typeof state._lastLatencyMs === "number") {
    form.append("client_latency_ms", String(state._lastLatencyMs));
  }
  const scoreStarted = performance.now();
  try {
    const result = await api(`/api/sessions/${state.sessionId}/attempts`, {
      method: "POST",
      body: form,
    });
    state._lastLatencyMs = Math.round(performance.now() - scoreStarted);
    handleAttempt(result);
  } catch (err) {
    console.error(err);
    const code = err.body?.error?.code;
    if (code === "session_closed") {
      setMessage("That round already ended. Tap Play again when you are ready.");
      setState("session-end");
      return;
    }
    if (code === "already_resolved") {
      setMessage("We already scored that one — moving on.");
      setTimeout(() => advance(), 900);
      return;
    }
    setMessage("Something went quiet on our side. Try that word again.");
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1200);
  }
}

function clearPhraseScore() {
  // Never leave "3 of 3 words" (etc.) on the next listen screen.
  const el = $(".phrase-score");
  if (!el) return;
  el.hidden = true;
  const correct = $("[data-words-correct]");
  const total = $("[data-words-total]");
  if (correct) correct.textContent = "0";
  if (total) total.textContent = "0";
}

function showPhraseScore(result) {
  const el = $(".phrase-score");
  if (!el) return;
  const total = Number(result.words_total) || 0;
  const multi = state.phase === "read" && total > 1;
  el.hidden = !multi;
  if (multi) {
    $("[data-words-correct]").textContent = String(result.words_correct ?? 0);
    $("[data-words-total]").textContent = String(total);
  }
}

function applyReinsert(result) {
  // Same-session reinsert is disabled server-side so sessions stay 5 or 10.
  // Ignore any legacy payload that would grow the on-screen queue.
  if (result && result.reinsert) {
    result.reinsert = null;
  }
}

function isRhymeSingAlongItem(item) {
  // Difficulty 3 = Rhymes (content levels 6–7).
  return item && item.kind === "line" && state.level === 3 && item.slug;
}

/**
 * Rhyme-time: the listen clip on the *current* screen is the sing-along.
 * Do not replay the previous line before advancing — that stacked previous + current
 * audio when the next line appeared.
 */
function rhymeListenMessage(item, { again = false } = {}) {
  if (isRhymeSingAlongItem(item)) {
    return again
      ? "Listen and sing along again, then read the line"
      : "Listen and sing along…";
  }
  if (item && item.kind === "line") {
    return again ? "Listen again, then read the line" : "Listen to the line…";
  }
  return again ? "Listen again, then read it" : "Listen…";
}

function needsAnotherRead(result) {
  // Strict: only when the API says another take is required.
  return Boolean(result.read_again) || Boolean(result.retry) || Boolean(result.again);
}

function needsReadThrough() {
  return state.items.some((item) => item && (item.rhyme_group || item.story_id));
}

function handleAttempt(result) {
  state.stars = result.stars_total;
  showPhraseScore(result);
  applyReinsert(result);
  setHeard(result.transcript);
  const item = state.phase === "replay" ? null : currentItem();
  if (item && result.word_scores && result.word_scores.length > 1) {
    setWord(item.text, { kind: item.kind || "word", scores: result.word_scores });
  }
  if (state.phase === "passage") {
    if (result.retry || result.result === "retry") {
      setMessage(result.message || "Please read it again");
      setState("idle");
      setMicEnabled(true);
      setMicLabel("Tap to read");
      return;
    }
    state.passageDone = true;
    finishSession();
    return;
  }

  if (result.skipped || result.result === "skipped") {
    setCombo(0);
    setStars(result.stars_total);
    setMessage(result.message || "");
    setState("result-skip");
    state.closeAgainPending = false;
    clearReadAgain();
    setTimeout(() => advance(), 1400);
    return;
  }
  if (result.retry || result.result === "retry") {
    setCombo(0);
    setStars(result.stars_total);
    const tryNumber = Number(result.try_number) || 2;
    const triesMax = Number(result.tries_max) || 3;
    setReadAgain({ tryNumber, triesMax, reason: "retry" });
    setMessage(result.message || "Please read it again");
    setMicLabel("Tap to read again");
    setState("result-retry");
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1600);
    return;
  }
  // Close second-chance only when again/read_again is true — never on locked close.
  if (
    (result.result === "close" || result.result === "missed") &&
    needsAnotherRead(result)
  ) {
    setCombo(0);
    setStars(result.stars_total);
    setReadAgain({
      tryNumber: Number(result.try_number) || 2,
      triesMax: Number(result.tries_max) || 2,
      reason: "close",
    });
    setMessage(result.message || "Almost — read it one more time!");
    setMicLabel("Tap to read again");
    setState("result-close");
    state.closeAgainPending = true;
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1600);
    return;
  }
  if (result.result === "correct") {
    setCombo(state.combo + 1);
    const gained = Number(result.stars_awarded) || 0;
    setStars(result.stars_total, { celebrate: true });
    popStarFloat(gained);
    setMessage(result.message || "");
    setState("result-correct");
    state.closeAgainPending = false;
    clearReadAgain();
    setTimeout(() => advance(), 1400);
    return;
  }
  // Locked close / miss — move on; never keep "one more" copy.
  if (result.result === "missed") setCombo(0);
  else setCombo(state.combo + 1); // locked close still nudges the sunny streak
  setStars(result.stars_total);
  if ((Number(result.stars_awarded) || 0) > 0) {
    popStarFloat(Number(result.stars_awarded));
  }
  setMessage(result.message || "");
  setState(result.result === "missed" ? "result-miss" : "result-close");
  state.closeAgainPending = false;
  clearReadAgain();
  setTimeout(() => advance(), 1400);
}

function advance() {
  if (state.phase === "replay") {
    state.replayIndex += 1;
    if (state.replayIndex >= state.replay.length) {
      finishReplay();
    } else {
      showReplayItem();
    }
    return;
  }
  state.index += 1;
  if (state.index >= state.items.length) {
    if (needsReadThrough() && !state.passageDone) {
      startReadThrough();
    } else {
      finishSession();
    }
  } else {
    showListen();
  }
}

async function startReadThrough() {
  if (!state.items.length) {
    finishSession();
    return;
  }
  state.phase = "passage";
  state.passageDone = false;
  setHeard("");
  clearPhraseScore();
  stopClip();
  const text = state.items.map((item) => item.text).join("\n");
  setWord(text, { kind: "line" });
  setState("listen");
  setMessage("Listen to the whole thing…");
  setMicEnabled(false);
  setMicLabel("Tap to read");
  for (const item of state.items) {
    if (state.phase !== "passage") return;
    try {
      await playClip(`/api/audio/${encodeURIComponent(item.slug)}`);
    } catch (err) {
      console.error(err);
    }
  }
  if (state.phase !== "passage") return;
  setState("idle");
  setMessage("Your turn — read it all");
  setMicLabel("Tap to read");
  setMicEnabled(true);
  syncHearAgain();
}

async function finishSession() {
  setMicEnabled(false);
  stopClip();
  try {
    const data = await api(`/api/sessions/${state.sessionId}/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    if (data.buddy) await loadBuddySvg(data.buddy);
    setState("session-end");
    $("[data-end-stars]").textContent = String(data.stars);
    setStars(data.stars, { celebrate: true });
    setCombo(0);
    setWord("");
    setMessage("");
    $("[data-progress]").textContent = "";
    const dots = $("[data-progress-dots]");
    if (dots) dots.innerHTML = "";
    state.replay = data.replay || [];
    state.replayIndex = 0;
    const hint = $("[data-end-hint]");
    if (hint) hint.hidden = !state.replay.length;
    const tryAgain = $("[data-try-again]");
    if (tryAgain) tryAgain.hidden = !state.replay.length;
    const mastered = $("[data-end-mastered]");
    if (mastered) {
      const words = data.mastered_words || [];
      mastered.hidden = !words.length;
      mastered.textContent = words.length
        ? `You can read ${words.join(", ")}`
        : "";
    }
    if (data.garden) {
      const wrap = $("[data-garden-end]");
      const cap = $("[data-garden-end-caption]");
      if (wrap) {
        wrap.hidden = false;
        if (cap) {
          const stage = data.garden.stage;
          const learned = (data.mastered_words || [])[0];
          cap.textContent =
            stage === "sticker"
              ? "New garden sticker unlocked — it stays forever!"
              : learned
                ? `Your garden grew — new ${stage}! ${learned}`
                : `Your garden grew — new ${stage}!`;
        }
        applyGardenStage(wrap, data.garden.growth);
      }
      showGardenHome(data.garden.growth);
    }
    if (data.play) {
      showEndPlayRewards(data.play);
      renderPlayHud(data.home || data.play, {
        highlightNew: data.play.new_badges || [],
      });
    }
    if (data.level_after != null && data.stage_after != null) {
      markCurrentSets({
        level: data.level_after,
        stage: data.stage_after,
        stage_by_difficulty: {
          [String(data.level_after)]: data.stage_after,
        },
        set_progress: data.set_progress,
      });
    }
    syncBuddyAnim();
  } catch (err) {
    console.error(err);
    setState("session-end");
    $("[data-end-stars]").textContent = String(state.stars);
  }
}

function startReplay() {
  state.phase = "replay";
  state.replayIndex = 0;
  $('[data-view="end"]').hidden = true;
  showReplayItem();
}

async function showReplayItem() {
  const entry = currentReplay();
  if (!entry) {
    finishReplay();
    return;
  }
  clearPhraseScore();
  setState("session-replay");
  setWord(entry.text, { highlight: true, kind: "word" });
  if (state.readAgain) {
    setMessage("Listen again, then read it");
    setMicLabel("Tap to read again");
  } else {
    setMessage("Listen, then try again");
    setMicLabel("Tap to read");
  }
  setProgress();
  setMicEnabled(false);
  try {
    await playItemClip(entry);
  } catch (err) {
    console.error(err);
  }
  if (state.id === "session-replay") {
    setState("idle");
    if (state.readAgain) {
      setMessage("Your turn again — tap and read it");
      setMicLabel("Tap to read again");
    } else {
      setMessage("Your turn — tap and read the word");
      setMicLabel("Tap to read");
    }
    setMicEnabled(true);
    syncHearAgain();
  }
}

function finishReplay() {
  state.phase = "read";
  clearReadAgain();
  clearPhraseScore();
  setWord("");
  setMessage("Nice reading!");
  setProgress();
  setMicEnabled(false);
  const endStars = $("[data-end-stars]");
  if (endStars) endStars.textContent = String(state.stars);
  setState("session-end");
  syncBuddyAnim();
}

function wire() {
  document.querySelectorAll("[data-start]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const rawLevel = btn.dataset.levelPick;
      const rawStage = btn.dataset.stagePick;
      const level =
        rawLevel === undefined || rawLevel === "" ? null : Number(rawLevel);
      const stage =
        rawStage === undefined || rawStage === "" ? null : Number(rawStage);
      startSession(level, stage).catch((err) => {
        console.error(err);
        setMessage(err.message || "Could not start");
        setState("home");
      });
    });
  });
  const goHome = $("[data-go-home]");
  if (goHome) {
    goHome.addEventListener("click", () => pauseToHome());
  }
  const continueBtn = $("[data-continue]");
  if (continueBtn) {
    continueBtn.addEventListener("click", () => {
      continueSession().catch((err) => {
        console.error(err);
        setMessage(err.message || "Could not continue");
        setState("home");
      });
    });
  }
  document.querySelectorAll("[data-buddy-choice]").forEach((btn) => {
    btn.addEventListener("click", () => {
      chooseBuddy(btn.dataset.buddyChoice).catch(console.error);
    });
  });
  $("[data-mic]").addEventListener("click", () => {
    onMicTap().catch(console.error);
  });
  const hearAgainBtn = $("[data-hear-again]");
  if (hearAgainBtn) {
    hearAgainBtn.addEventListener("click", () => {
      hearAgain().catch(console.error);
    });
  }
  const tryAgain = $("[data-try-again]");
  if (tryAgain) {
    tryAgain.addEventListener("click", () => startReplay());
  }
  $("[data-play-again]").addEventListener("click", () => {
    stopClip();
    state.sessionId = null;
    state.items = [];
    state.index = 0;
    state.plannedCount = 0;
    state.paused = false;
    state.closeAgainPending = false;
    state.replay = [];
    state.replayIndex = 0;
    state.phase = "read";
    state.passageDone = false;
    try {
      sessionStorage.removeItem(OPEN_KEY);
    } catch {
      /* private mode */
    }
    setStars(0);
    setWord("");
    setMessage("");
    $("[data-level]").hidden = true;
    const gardenEnd = $("[data-garden-end]");
    if (gardenEnd) gardenEnd.hidden = true;
    const dots = $("[data-progress-dots]");
    if (dots) dots.innerHTML = "";
    setState("home");
  });
}

wire();
boot();
