const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("application/json") ? await res.json() : null;
  if (!res.ok) {
    const msg = body?.error?.message || `Request failed (${res.status})`;
    throw new Error(msg);
  }
  return body;
}

function fillList(el, items, mapFn) {
  if (!el) return;
  el.innerHTML = "";
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "None yet.";
    el.appendChild(li);
    return;
  }
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = mapFn(item);
    el.appendChild(li);
  }
}

function renderAccuracy(days) {
  const host = $("[data-accuracy]");
  if (!host) return;
  host.innerHTML = "";
  const recent = days.slice(-14);
  for (const day of recent) {
    const scored = Number(day.scored) || 0;
    const correct = Number(day.correct) || 0;
    const pct = scored ? Math.round((100 * correct) / scored) : 0;
    const row = document.createElement("div");
    row.className = "bar-row";
    row.innerHTML = `
      <span>${day.date.slice(5)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <span>${scored ? `${pct}%` : "—"}</span>
    `;
    host.appendChild(row);
  }
}

function renderSounds(payload) {
  const note = $("[data-sounds-note]");
  const host = $("[data-sounds]");
  if (note) note.textContent = payload.note || "";
  if (!host) return;
  host.innerHTML = "";
  const tags = payload.tags || [];
  if (!tags.length) {
    host.textContent = "No tagged attempts yet.";
    return;
  }
  for (const tag of tags) {
    const scored = Number(tag.scored) || 0;
    const correct = Number(tag.correct) || 0;
    const pct = scored ? Math.round((100 * correct) / scored) : 0;
    const chip = document.createElement("span");
    chip.className = "heat-chip";
    chip.style.opacity = String(0.45 + (pct / 100) * 0.55);
    chip.textContent = `${tag.tag}: ${pct}% (${correct}/${scored})`;
    host.appendChild(chip);
  }
}

function syncBuddyThumb(buddy) {
  const thumb = $("[data-buddy-thumb]");
  if (!thumb) return;
  let raw = buddy;
  if (raw === "mouse") raw = "unicorn";
  if (raw === "cat") raw = "krishna";
  const name = ["krishna", "unicorn"].includes(raw) ? raw : "krishna";
  thumb.src = `/static/mascots/${name}.svg`;
}

function fillSettings(settings) {
  const form = $("[data-settings]");
  if (!form) return;
  form.profile_name.value = settings.profile_name || "";
  form.mode.value = settings.mode || "beginner";
  form.level.value = settings.level ?? 1;
  form.session_length.value = settings.session_length ?? 10;
  form.buddy.value = settings.buddy || "krishna";
  form.keep_audio.checked = Boolean(settings.keep_audio);
  form.auto_strict.checked = settings.auto_strict !== false;
  syncBuddyThumb(form.buddy.value);
}

async function loadKept(keepOn) {
  const panel = $("[data-kept-panel]");
  const list = $("[data-kept]");
  if (!panel || !list) return;
  if (!keepOn) {
    panel.hidden = true;
    list.innerHTML = "";
    return;
  }
  const data = await api("/api/parent/kept");
  panel.hidden = false;
  list.innerHTML = "";
  const clips = data.clips || [];
  if (!clips.length) {
    const li = document.createElement("li");
    li.textContent = "No kept clips yet.";
    list.appendChild(li);
    return;
  }
  for (const clip of clips) {
    const li = document.createElement("li");
    li.innerHTML = `
      <div><strong>${clip.text}</strong> — ${clip.result} · ${clip.created_at}</div>
      <audio controls preload="none" src="${clip.audio_url}"></audio>
    `;
    list.appendChild(li);
  }
}

async function refresh() {
  const [settings, accuracy, mastered, tricky, sounds] = await Promise.all([
    api("/api/parent/settings"),
    api("/api/parent/accuracy"),
    api("/api/parent/mastered"),
    api("/api/parent/tricky"),
    api("/api/parent/sounds"),
  ]);
  fillSettings(settings);
  renderAccuracy(accuracy.days || []);
  fillList(
    $("[data-mastered-week]"),
    mastered.this_week || [],
    (m) => `${m.text} (L${m.level})`
  );
  fillList(
    $("[data-mastered-all]"),
    mastered.mastered || [],
    (m) => `${m.text} (L${m.level})${m.mastered_on ? ` · ${m.mastered_on}` : ""}`
  );
  fillList(
    $("[data-tricky]"),
    tricky.items || [],
    (t) => `${t.text} — recent ${t.recent_misses}, all ${t.all_misses}`
  );
  renderSounds(sounds);
  await loadKept(Boolean(settings.keep_audio));
}

function wire() {
  const form = $("[data-settings]");
  form.buddy.addEventListener("change", () => {
    syncBuddyThumb(form.buddy.value);
  });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const status = $("[data-settings-status]");
    const payload = {
      profile_name: form.profile_name.value.trim(),
      mode: form.mode.value,
      level: Number(form.level.value),
      session_length: Number(form.session_length.value),
      buddy: form.buddy.value,
      keep_audio: form.keep_audio.checked,
      auto_strict: form.auto_strict.checked,
    };
    try {
      const saved = await api("/api/parent/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      fillSettings(saved);
      await loadKept(Boolean(saved.keep_audio));
      if (status) status.textContent = "Saved.";
    } catch (err) {
      if (status) status.textContent = err.message || "Could not save.";
    }
  });

  $("[data-export]").addEventListener("click", () => {
    window.location.href = "/api/parent/export";
  });
}

wire();
refresh().catch((err) => {
  const status = $("[data-settings-status]");
  if (status) status.textContent = err.message || "Could not load parent data.";
});
