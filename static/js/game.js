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
  recorder: new RecordingSession(),
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
}

function setMessage(text) {
  $("[data-message]").textContent = text || "";
}

function setWord(text) {
  $("[data-word]").textContent = text || "";
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
  if (!state.items.length) {
    $("[data-progress]").textContent = "";
    return;
  }
  $("[data-progress]").textContent = `Word ${Math.min(state.index + 1, state.items.length)} of ${state.items.length}`;
}

function setMicEnabled(on) {
  $("[data-mic]").disabled = !on;
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
  const body = level ? JSON.stringify({ level }) : undefined;
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
  setStars(0);
  const badge = $("[data-level]");
  badge.hidden = false;
  badge.textContent = `Level ${data.level}`;
  $('[data-view="home"]').hidden = true;
  showListenPlaceholder();
}

function currentItem() {
  return state.items[state.index];
}

function showListenPlaceholder() {
  const item = currentItem();
  if (!item) {
    finishSession();
    return;
  }
  setState("listen-placeholder");
  setWord(item.text);
  setMessage("Your turn");
  setProgress();
  setMicEnabled(false);
  setTimeout(() => {
    if (state.id === "listen-placeholder") enterIdle();
  }, 1000);
}

function enterIdle() {
  setState("idle");
  setMessage("Tap the button and read the word");
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
  const item = currentItem();
  const form = new FormData();
  form.append("item_id", String(item.id));
  form.append("phase", "read");
  form.append("audio", blob, "take.webm");
  try {
    const result = await api(`/api/sessions/${state.sessionId}/attempts`, {
      method: "POST",
      body: form,
    });
    handleAttempt(result);
  } catch (err) {
    console.error(err);
    setMessage("Something went quiet on our side. Try that word again.");
    setTimeout(() => showListenPlaceholder(), 1200);
  }
}

function handleAttempt(result) {
  state.stars = result.stars_total;
  setStars(result.stars_total);
  setMessage(result.message || "");

  if (result.skipped || result.result === "skipped") {
    setState("result-skip");
    state.closeAgainPending = false;
    setTimeout(() => advance(), 1400);
    return;
  }
  if (result.retry || result.result === "retry") {
    setState("result-retry");
    setTimeout(() => showListenPlaceholder(), 1400);
    return;
  }
  if (result.result === "close" && result.again) {
    setState("result-close");
    state.closeAgainPending = true;
    setTimeout(() => showListenPlaceholder(), 1400);
    return;
  }
  if (result.result === "correct") {
    setState("result-correct");
    state.closeAgainPending = false;
    setTimeout(() => advance(), 1200);
    return;
  }
  // missed or locking close
  setState(result.result === "missed" ? "result-miss" : "result-close");
  state.closeAgainPending = false;
  setTimeout(() => advance(), 1400);
}

function advance() {
  state.index += 1;
  if (state.index >= state.items.length) {
    finishSession();
  } else {
    showListenPlaceholder();
  }
}

async function finishSession() {
  setMicEnabled(false);
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
  } catch (err) {
    console.error(err);
    setState("session-end");
    $("[data-end-stars]").textContent = String(state.stars);
  }
}

function wire() {
  document.querySelectorAll("[data-start]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const level = Number(btn.dataset.levelPick || "1");
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
    state.sessionId = null;
    state.items = [];
    state.index = 0;
    state.closeAgainPending = false;
    setStars(0);
    setWord("");
    setMessage("");
    $("[data-level]").hidden = true;
    setState("home");
  });
}

wire();
boot();
