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

function renderTomorrow(note) {
  const stay = $("[data-tomorrow-stay]");
  const tip = $("[data-tomorrow-tip]");
  const mode = $("[data-tomorrow-mode]");
  const through = $("[data-tomorrow-through]");
  if (stay) stay.textContent = note?.stay || "";
  if (tip) tip.textContent = note?.practice_tip || "";
  if (mode) {
    mode.hidden = !note?.mode_change;
    mode.textContent = note?.mode_change || "";
  }
  if (through) {
    const rt = note?.read_through;
    if (rt && rt.words_total) {
      const seconds = rt.seconds == null ? "" : `${rt.seconds} seconds, `;
      through.hidden = false;
      through.textContent = `Last read-through: ${seconds}${rt.words_correct} of ${rt.words_total} words`;
    } else {
      through.hidden = true;
      through.textContent = "";
    }
  }
  fillList(
    $("[data-tomorrow-tricky]"),
    note?.tricky || [],
    (text) => text
  );
}

function renderWeekStrip(accuracy, mastered, tomorrow) {
  const el = $("[data-week-strip]");
  if (!el) return;
  const recent = (accuracy?.days || []).slice(-7);
  let ind = 0;
  let locks = 0;
  for (const day of recent) {
    ind += Number(day.independent_correct) || 0;
    locks += Number(day.locking_reads) || 0;
  }
  const masteredN = (mastered?.this_week || []).length;
  const due = Number(tomorrow?.due_count) || 0;
  const pct = locks ? Math.round((100 * ind) / locks) : null;
  const parts = [];
  if (pct != null) parts.push(`This week: ${pct}% independent on first-pass locks`);
  else parts.push("This week: no locking reads yet");
  if (masteredN) parts.push(`${masteredN} newly mastered`);
  if (due) parts.push(`${due} due tomorrow`);
  el.textContent = parts.join(" · ");
}

function renderAccuracy(days) {
  const host = $("[data-accuracy]");
  if (!host) return;
  host.innerHTML = "";
  const recent = days.slice(-14);
  for (const day of recent) {
    const locks = Number(day.locking_reads) || Number(day.scored) || 0;
    const independent = Number(day.independent_correct) || 0;
    const assisted = Number(day.assisted_correct) || 0;
    const pct = locks ? Math.round((100 * independent) / locks) : 0;
    const row = document.createElement("div");
    row.className = "bar-row";
    const detail = locks
      ? `${pct}% ind · ${assisted} helped`
      : "—";
    row.innerHTML = `
      <span>${day.date.slice(5)}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${pct}%"></div></div>
      <span>${detail}</span>
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

function renderPatterns(payload) {
  const note = $("[data-patterns-note]");
  const unlocked = $("[data-patterns-unlocked]");
  const host = $("[data-patterns]");
  const heat = payload?.heatmap || payload || {};
  if (note) note.textContent = heat.note || "";
  if (unlocked) {
    const list = payload?.unlocked || [];
    unlocked.textContent = list.length
      ? `Unlocked: ${list.join(", ")}`
      : "";
  }
  if (!host) return;
  host.innerHTML = "";
  const patterns = heat.patterns || [];
  if (!patterns.length) {
    host.textContent = "No pattern attempts yet.";
    return;
  }
  for (const row of patterns) {
    const scored = Number(row.scored) || 0;
    const correct = Number(row.correct) || 0;
    const pct = scored ? Math.round((100 * correct) / scored) : 0;
    const known = Math.round((Number(row.known_ratio) || 0) * 100);
    const chip = document.createElement("span");
    chip.className = "heat-chip";
    chip.style.opacity = String(0.45 + (pct / 100) * 0.55);
    chip.textContent = `${row.pattern}: ${pct}% try · ${known}% known`;
    host.appendChild(chip);
  }
}

function fillVoiceChoices(trickyItems) {
  const sel = $("[data-voice-slug]");
  if (!sel) return;
  const prev = sel.value;
  sel.innerHTML = "";
  const items = (trickyItems || []).slice(0, 20);
  if (!items.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No tricky words yet — play a few rounds first";
    sel.appendChild(opt);
    return;
  }
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.slug;
    opt.textContent = item.text;
    sel.appendChild(opt);
  }
  if (prev && [...sel.options].some((o) => o.value === prev)) {
    sel.value = prev;
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
  const stage = Number(settings.stage);
  // Keep in sync with STAGES_PER_DIFFICULTY (currently 8).
  form.stage.value = String(
    stage >= 1 && stage <= 8 ? stage : 1
  );
  const len = Number(settings.session_length) === 5 ? 5 : 10;
  form.session_length.value = String(len);
  form.buddy.value = settings.buddy || "krishna";
  form.keep_audio.checked = Boolean(settings.keep_audio);
  form.auto_strict.checked = settings.auto_strict !== false;
  if (form.effort_stars) {
    form.effort_stars.checked = settings.effort_stars !== false;
  }
  if (form.scheduler_shadow) {
    form.scheduler_shadow.checked = Boolean(settings.scheduler_shadow);
  }
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
  const [settings, accuracy, mastered, retention, tricky, sounds, patterns] =
    await Promise.all([
      api("/api/parent/settings"),
      api("/api/parent/accuracy"),
      api("/api/parent/mastered"),
      api("/api/parent/retention"),
      api("/api/parent/tricky"),
      api("/api/parent/sounds"),
      api("/api/parent/patterns"),
    ]);
  fillSettings(settings);
  renderTomorrow(settings.tomorrow);
  renderWeekStrip(accuracy, mastered, settings.tomorrow);
  renderAccuracy(accuracy.days || []);
  fillList(
    $("[data-mastered-week]"),
    mastered.this_week || [],
    (m) => `${m.text} (L${m.level})`
  );
  fillList(
    $("[data-independent]"),
    mastered.independent || [],
    (m) =>
      `${m.text}${m.pattern ? ` · ${m.pattern}` : ""} — ${m.independent_oks} independent`
  );
  fillList(
    $("[data-mastered-all]"),
    mastered.mastered || [],
    (m) => `${m.text} (L${m.level})${m.mastered_on ? ` · ${m.mastered_on}` : ""}`
  );
  const retNote = $("[data-retention-note]");
  if (retNote) retNote.textContent = retention?.note || "";
  fillList(
    $("[data-retention]"),
    retention?.items || [],
    (r) => `${r.text}: missed ${r.missed_on}, independent ${r.retained_on}`
  );
  fillList(
    $("[data-tricky]"),
    tricky.items || [],
    (t) => `${t.text} — recent ${t.recent_misses}, all ${t.all_misses}`
  );
  fillVoiceChoices(tricky.items || []);
  renderSounds(sounds);
  renderPatterns(patterns);
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
      stage: Number(form.stage.value),
      session_length: Number(form.session_length.value),
      buddy: form.buddy.value,
      keep_audio: form.keep_audio.checked,
      auto_strict: form.auto_strict.checked,
      effort_stars: form.effort_stars ? form.effort_stars.checked : true,
      scheduler_shadow: form.scheduler_shadow
        ? form.scheduler_shadow.checked
        : false,
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

  const recordBtn = $("[data-voice-record]");
  const playBtn = $("[data-voice-play]");
  const voiceStatus = $("[data-voice-status]");
  let voiceRecorder = null;
  if (recordBtn) {
    recordBtn.addEventListener("click", async () => {
      const sel = $("[data-voice-slug]");
      const slug = sel?.value;
      if (!slug) {
        if (voiceStatus) voiceStatus.textContent = "Pick a word first.";
        return;
      }
      try {
        const { RecordingSession } = await import("./record.js");
        if (!voiceRecorder) voiceRecorder = new RecordingSession();
        if (voiceRecorder.isRecording) {
          voiceRecorder.stop();
          return;
        }
        if (voiceStatus) voiceStatus.textContent = "Recording… tap again when done.";
        recordBtn.textContent = "Stop";
        await voiceRecorder.start({
          oncomplete: async (blob) => {
            recordBtn.textContent = "Record";
            if (voiceStatus) voiceStatus.textContent = "Saving…";
            const body = new FormData();
            body.append("audio", blob, "parent.webm");
            try {
              await api(`/api/parent/voice/${encodeURIComponent(slug)}`, {
                method: "POST",
                body,
              });
              if (voiceStatus) {
                voiceStatus.textContent = `Saved your voice for “${sel.selectedOptions[0]?.text || slug}”.`;
              }
              if (playBtn) {
                playBtn.hidden = false;
                playBtn.onclick = () => {
                  new Audio(`/api/audio/${encodeURIComponent(slug)}?t=${Date.now()}`).play();
                };
              }
            } catch (err) {
              if (voiceStatus) {
                voiceStatus.textContent = err.message || "Could not save recording.";
              }
            }
          },
          onerror: (err) => {
            recordBtn.textContent = "Record";
            if (voiceStatus) {
              voiceStatus.textContent = err?.message || "Microphone error.";
            }
          },
        });
      } catch (err) {
        if (voiceStatus) {
          voiceStatus.textContent = err.message || "Could not start recording.";
        }
      }
    });
  }
}

wire();
refresh().catch((err) => {
  const status = $("[data-settings-status]");
  if (status) status.textContent = err.message || "Could not load parent data.";
});
