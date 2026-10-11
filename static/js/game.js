import { RecordingSession } from "./record.js";

const $ = (sel) => document.querySelector(sel);
const BUDDIES = ["cat", "krishna", "mouse"];

const state = {
  id: "boot",
  sessionId: null,
  items: [],
  index: 0,
  stars: 0,
  level: 1,
  buddy: "cat",
  closeAgainPending: false,
  replay: [],
  replayIndex: 0,
  phase: "read", // "read" | "replay"
  recorder: new RecordingSession(),
  audioEl: null,
  gardenGrowth: 0,
  svgCache: {},
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
  const buddy = BUDDIES.includes(name) ? name : "cat";
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
      const labels = { cat: "Cat", krishna: "Krishna", mouse: "Mouse" };
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

function setWord(text, { highlight = false } = {}) {
  const el = $("[data-word]");
  el.textContent = text || "";
  el.classList.toggle("highlight", Boolean(highlight));
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

function setStars(n, { celebrate = false } = {}) {
  const el = $("[data-stars]");
  const prev = Number(el.textContent) || 0;
  el.textContent = String(n);
  if (n > prev || celebrate) {
    el.parentElement.classList.remove("bump");
    void el.parentElement.offsetWidth;
    el.parentElement.classList.add("bump");
    if (celebrate || n > prev) popStarBurst();
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
    const audio = new Audio(url);
    state.audioEl = audio;
    const done = () => {
      audio.removeEventListener("ended", done);
      audio.removeEventListener("error", done);
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
    const settings = await api("/api/parent/settings");
    await loadBuddySvg(settings.buddy || "cat");
    showGardenHome(Number(settings.garden_growth) || 0);
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
  setState("listen");
  setWord(item.text);
  setMessage(item.kind === "line" ? "Listen to the line…" : "Listen…");
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
  setMessage(
    item && item.kind === "line"
      ? "Your turn — tap and read the line"
      : "Your turn — tap and read the word"
  );
  setMicEnabled(true);
}

async function onMicTap() {
  // Second tap while recording = "I'm done" (keeps one clear take).
  if (state.id === "recording" && state.recorder.isRecording) {
    setMessage("Got it…");
    setMicEnabled(false);
    state.recorder.stop();
    return;
  }
  if (state.id !== "idle") return;
  setState("recording");
  setMessage("I hear you — read the word, then tap again when done");
  setMicEnabled(false);
  const label = $(".mic-label");
  if (label) label.textContent = "Tap when done";
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
      if (label) label.textContent = "Tap to read";
    },
  });
}

async function onRecordComplete(blob) {
  setState("scoring");
  setMessage("Listening…");
  setMicEnabled(false);
  const label = $(".mic-label");
  if (label) label.textContent = "Tap to read";
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

async function maybeSingAlongThen(next) {
  const item = currentItem();
  if (state.phase === "read" && isRhymeSingAlongItem(item)) {
    setMessage("Sing along…");
    setState("listen");
    try {
      await playClip(`/api/audio/${encodeURIComponent(item.slug)}`);
    } catch (err) {
      console.error(err);
    }
  }
  next();
}

function handleAttempt(result) {
  state.stars = result.stars_total;
  showPhraseScore(result);
  applyReinsert(result);

  if (result.skipped || result.result === "skipped") {
    setStars(result.stars_total);
    setMessage(result.message || "");
    setState("result-skip");
    state.closeAgainPending = false;
    setTimeout(() => maybeSingAlongThen(advance), 1400);
    return;
  }
  if (result.retry || result.result === "retry") {
    setStars(result.stars_total);
    setMessage(result.message || "");
    setState("result-retry");
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1400);
    return;
  }
  if (result.result === "close" && result.again) {
    setStars(result.stars_total);
    setMessage(result.message || "");
    setState("result-close");
    state.closeAgainPending = true;
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1400);
    return;
  }
  if (result.result === "correct") {
    setStars(result.stars_total, { celebrate: true });
    setMessage(result.message || "");
    setState("result-correct");
    state.closeAgainPending = false;
    setTimeout(() => maybeSingAlongThen(advance), 1200);
    return;
  }
  setStars(result.stars_total);
  setMessage(result.message || "");
  setState(result.result === "missed" ? "result-miss" : "result-close");
  state.closeAgainPending = false;
  setTimeout(() => maybeSingAlongThen(advance), 1400);
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
  setWord(entry.text, { highlight: true });
  setMessage("Listen, then try again");
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
    setMessage("Your turn — tap and read the word");
    setMicEnabled(true);
  }
}

function finishReplay() {
  state.phase = "read";
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
