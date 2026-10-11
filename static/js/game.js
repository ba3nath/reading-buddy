import { RecordingSession } from "./record.js";

const $ = (sel) => document.querySelector(sel);

const state = {
  id: "boot",
  sessionId: null,
  items: [],
  index: 0,
  stars: 0,
  level: 1,
  closeAgainPending: false,
  replay: [],
  replayIndex: 0,
  phase: "read", // "read" | "replay"
  recorder: new RecordingSession(),
  audioEl: null,
};

function setState(id) {
  state.id = id;
  document.body.dataset.state = id;
  const home = $('[data-view="home"]');
  const end = $('[data-view="end"]');
  const bootErr = $('[data-view="boot-error"]');
  home.hidden = id !== "home";
  // Full-screen end only between rounds / after replay — not during listen/replay play.
  end.hidden = id !== "session-end";
  bootErr.hidden = id !== "boot-error";
}

function setMessage(text) {
  $("[data-message]").textContent = text || "";
}

function setWord(text, { highlight = false } = {}) {
  const el = $("[data-word]");
  el.textContent = text || "";
  el.classList.toggle("highlight", Boolean(highlight));
}

function setStars(n) {
  const el = $("[data-stars]");
  const prev = Number(el.textContent) || 0;
  el.textContent = String(n);
  if (n > prev) {
    el.parentElement.classList.remove("bump");
    void el.parentElement.offsetWidth;
    el.parentElement.classList.add("bump");
  }
}

function setProgress() {
  if (state.phase === "replay") {
    if (!state.replay.length) {
      $("[data-progress]").textContent = "";
      return;
    }
    $("[data-progress]").textContent = `Try again ${Math.min(state.replayIndex + 1, state.replay.length)} of ${state.replay.length}`;
    return;
  }
  if (!state.items.length) {
    $("[data-progress]").textContent = "";
    return;
  }
  $("[data-progress]").textContent = `Word ${Math.min(state.index + 1, state.items.length)} of ${state.items.length}`;
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
    // M2: missing clips are a setup/health issue, not a broken child play screen.
    if (health.audio === false) {
      setState("boot-error");
      $("[data-boot-error]").textContent =
        "Voice clips are not ready yet. Ask an adult to run: python scripts/generate_audio.py";
      return;
    }
    setState("home");
    setMessage("");
  } catch {
    setState("boot-error");
  }
}

async function startSession(level) {
  setMessage("Starting…");
  setMicEnabled(false);
  // Omit level → server uses settings.level (adaptive / level_after).
  // Explicit Level 2–7 buttons pass an override for demo decks.
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
  setMessage("Listen…");
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
  setMessage("Your turn — tap and read the word");
  setMicEnabled(true);
}

async function onMicTap() {
  if (state.id !== "idle") return;
  setState("recording");
  setMessage("Listening…");
  setMicEnabled(false);
  await state.recorder.start({
    oncomplete: (blob) => onRecordComplete(blob),
    onerror: (err) => {
      console.error(err);
      setMessage("We need the microphone to hear you. Ask an adult to allow it.");
      setState("idle");
      setMicEnabled(true);
    },
  });
}

async function onRecordComplete(blob) {
  setState("scoring");
  setMessage("Listening…");
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
  // Keep FE items aligned with server play_item_ids.
  state.items.splice(at, 0, info.item);
}

function handleAttempt(result) {
  state.stars = result.stars_total;
  setStars(result.stars_total);
  setMessage(result.message || "");
  showPhraseScore(result);
  applyReinsert(result);

  if (result.skipped || result.result === "skipped") {
    setState("result-skip");
    state.closeAgainPending = false;
    setTimeout(() => advance(), 1400);
    return;
  }
  if (result.retry || result.result === "retry") {
    setState("result-retry");
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1400);
    return;
  }
  if (result.result === "close" && result.again) {
    setState("result-close");
    state.closeAgainPending = true;
    setTimeout(() => {
      if (state.phase === "replay") showReplayItem();
      else showListen();
    }, 1400);
    return;
  }
  if (result.result === "correct") {
    setState("result-correct");
    state.closeAgainPending = false;
    setTimeout(() => advance(), 1200);
    return;
  }
  setState(result.result === "missed" ? "result-miss" : "result-close");
  state.closeAgainPending = false;
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
    setState("session-end");
    $("[data-end-stars]").textContent = String(data.stars);
    setStars(data.stars);
    setWord("");
    setMessage("");
    $("[data-progress]").textContent = "";
    state.replay = data.replay || [];
    state.replayIndex = 0;
    const hint = $("[data-end-hint]");
    if (hint) hint.hidden = !state.replay.length;
    if (state.replay.length) {
      setTimeout(() => startReplay(), 900);
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
    setState("home");
  });
}

wire();
boot();
