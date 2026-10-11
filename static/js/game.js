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
  stars: 0,
  level: 1,
  buddy: "krishna",
  closeAgainPending: false,
  /** When set, another read is required for the current word. */
  readAgain: null, // { tryNumber, triesMax, reason } | null
  replay: [],
  replayIndex: 0,
  phase: "read", // "read" | "replay"
  recorder: new RecordingSession(),
  audioEl: null,
  clipGen: 0,
  gardenGrowth: 0,
  svgCache: {},
  combo: 0,
  play: null, // home quest / streak / badges snapshot
  illustrationKeys: null, // Set<string> from /static/illustrations/keys.json
};

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
      greet.textContent = `Hi — I'm ${labels[buddy]}! Ready when you are.`;
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

function setWord(text, { highlight = false, kind = "word" } = {}) {
  const el = $("[data-word]");
  el.textContent = text || "";
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
  const cur = Math.min(state.index + 1, state.items.length);
  const total = state.items.length;
  const item = currentItem();
  labelEl.textContent =
    item && item.kind === "line"
      ? `Line ${cur} of ${total}`
      : `Word ${cur} of ${total}`;
  if (dots) {
    const maxDots = Math.min(total, 12);
    dots.innerHTML = "";
    for (let i = 0; i < maxDots; i++) {
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

function playClip(url) {
  return new Promise((resolve) => {
    stopClip();
    const gen = state.clipGen;
    const audio = new Audio(url);
    state.audioEl = audio;
    const done = () => {
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
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
    audio.play().catch(done);
  });
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
    renderPlayHud(settings.play || {
      lifetime_stars: settings.lifetime_stars || 0,
      day_streak: settings.day_streak || 0,
      quest_complete: false,
      quest_label: "Finish today's reading",
      badges: [],
    });
    setState("home");
    setMessage("");
  } catch {
    setState("boot-error");
  }
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

async function startSession(level) {
  clearReadAgain();
  setMessage("Starting…");
  setMicEnabled(false);
  const body =
    level != null && Number.isFinite(level)
      ? JSON.stringify({ level })
      : undefined;
  const data = await api("/api/sessions", {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body,
  });
  state.sessionId = data.session_id;
  state.items = data.items || [];
  state.index = 0;
  state.stars = 0;
  state.level = data.level;
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
  badge.textContent = `Level ${data.level}`;
  $('[data-view="home"]').hidden = true;
  $('[data-view="end"]').hidden = true;
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
  setState("listen");
  setWord(item.text, { kind: item.kind === "line" ? "line" : "word" });
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
    await playClip(`/api/audio/${encodeURIComponent(item.slug)}`);
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
  if (state.phase === "replay") {
    const entry = currentReplay();
    form.append("item_id", String(entry.item_id));
    form.append("word", entry.word || entry.text);
  } else {
    const item = currentItem();
    form.append("item_id", String(item.id));
    form.append("queue_index", String(state.index));
  }
  try {
    const result = await api(`/api/sessions/${state.sessionId}/attempts`, {
      method: "POST",
      body: form,
    });
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
  const info = result.reinsert;
  if (!info || !info.item) return;
  const at = Number(info.queue_index);
  if (!Number.isFinite(at)) {
    state.items.push(info.item);
    return;
  }
  state.items.splice(at, 0, info.item);
}

function isRhymeSingAlongItem(item) {
  return (
    item &&
    item.kind === "line" &&
    (state.level === 6 || state.level === 7) &&
    item.slug
  );
}

/**
 * Rhyme-time (L6–7): the listen clip on the *current* screen is the sing-along.
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

function handleAttempt(result) {
  state.stars = result.stars_total;
  showPhraseScore(result);
  applyReinsert(result);

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
  if (result.result === "close" && needsAnotherRead(result)) {
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
    finishSession();
  } else {
    showListen();
  }
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
    if (data.garden) {
      const wrap = $("[data-garden-end]");
      const cap = $("[data-garden-end-caption]");
      if (wrap) {
        wrap.hidden = false;
        if (cap) {
          const stage = data.garden.stage;
          cap.textContent =
            stage === "sticker"
              ? "New garden sticker unlocked — it stays forever!"
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
    syncBuddyAnim();
    if (state.replay.length) {
      setTimeout(() => startReplay(), 1100);
    }
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
  const url = entry.audio_url || `/api/audio/${encodeURIComponent(entry.text)}`;
  try {
    await playClip(url);
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
  }
}

function finishReplay() {
  state.phase = "read";
  clearReadAgain();
  setWord("");
  setMessage("Nice reading!");
  setProgress();
  setMicEnabled(false);
  const endStars = $("[data-end-stars]");
  if (endStars) endStars.textContent = String(state.stars);
  const phrase = $(".phrase-score");
  if (phrase) phrase.hidden = true;
  setState("session-end");
  syncBuddyAnim();
}

function wire() {
  document.querySelectorAll("[data-start]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const raw = btn.dataset.levelPick;
      const level =
        raw === undefined || raw === "" ? null : Number(raw);
      startSession(level).catch((err) => {
        console.error(err);
        setMessage(err.message || "Could not start");
        setState("home");
      });
    });
  });
  document.querySelectorAll("[data-buddy-choice]").forEach((btn) => {
    btn.addEventListener("click", () => {
      chooseBuddy(btn.dataset.buddyChoice).catch(console.error);
    });
  });
  $("[data-mic]").addEventListener("click", () => {
    onMicTap().catch(console.error);
  });
  $("[data-play-again]").addEventListener("click", () => {
    stopClip();
    state.sessionId = null;
    state.items = [];
    state.index = 0;
    state.closeAgainPending = false;
    state.replay = [];
    state.replayIndex = 0;
    state.phase = "read";
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
