/** MediaRecorder + silence-stop (+ optional tap-to-finish). No UI strings. */

// Tuned for short kids words: keep final plosives; prefer one clear take.
const SILENCE_GAP_MS = 1800;
const NO_SPEECH_MS = 6000;
const MAX_MS = 20000;
const MIN_SPEECH_MS = 350;
const SPEECH_START_THRESHOLD = 0.02;
const SPEECH_HOLD_THRESHOLD = 0.01;
const START_GRACE_MS = 250;
const TRAIL_PAD_MS = 350;

export class RecordingSession {
  constructor() {
    this.stream = null;
    this.recorder = null;
    this.chunks = [];
    this._raf = null;
    this._audioCtx = null;
    this._analyser = null;
    this._startedAt = 0;
    this._speechStartedAt = 0;
    this._lastLoudAt = 0;
    this._stopped = false;
    this._stopTimer = null;
    this._armed = false;
  }

  get isRecording() {
    return Boolean(this.recorder && this.recorder.state === "recording" && !this._stopped);
  }

  async ensureStream() {
    if (this.stream) return this.stream;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: false, // keep soft consonants for kids
        autoGainControl: true,
      },
    });
    return this.stream;
  }

  async start({ oncomplete, onerror, onarmed }) {
    this._stopped = false;
    this._armed = false;
    this.chunks = [];
    if (this._stopTimer) {
      clearTimeout(this._stopTimer);
      this._stopTimer = null;
    }
    try {
      const stream = await this.ensureStream();
      const mime = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
        ? "audio/webm;codecs=opus"
        : undefined;
      this.recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);

      this.recorder.ondataavailable = (ev) => {
        if (ev.data && ev.data.size > 0) this.chunks.push(ev.data);
      };
      this.recorder.onstop = () => {
        const type = this.recorder?.mimeType || "audio/webm";
        const blob = new Blob(this.chunks, { type });
        oncomplete?.(blob);
      };
      this.recorder.onerror = (ev) => onerror?.(ev.error || new Error("record failed"));

      this._audioCtx = new AudioContext();
      if (this._audioCtx.state === "suspended") {
        await this._audioCtx.resume().catch(() => {});
      }
      const source = this._audioCtx.createMediaStreamSource(stream);
      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 2048;
      source.connect(this._analyser);

      this._startedAt = performance.now();
      this._speechStartedAt = 0;
      this._lastLoudAt = 0;
      this.recorder.start(100);
      this._armed = true;
      onarmed?.();
      this._tick();
    } catch (err) {
      onerror?.(err);
    }
  }

  _level() {
    if (!this._analyser) return 0;
    const data = new Uint8Array(this._analyser.fftSize);
    this._analyser.getByteTimeDomainData(data);
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / data.length);
  }

  _scheduleStop() {
    if (this._stopTimer || this._stopped) return;
    this._stopTimer = setTimeout(() => {
      this._stopTimer = null;
      this.stop();
    }, TRAIL_PAD_MS);
  }

  _cancelScheduledStop() {
    if (this._stopTimer) {
      clearTimeout(this._stopTimer);
      this._stopTimer = null;
    }
  }

  _tick = () => {
    if (this._stopped) return;
    const now = performance.now();
    const elapsed = now - this._startedAt;
    const level = this._level();

    if (elapsed >= START_GRACE_MS) {
      const loudEnough = this._speechStartedAt
        ? level >= SPEECH_HOLD_THRESHOLD
        : level >= SPEECH_START_THRESHOLD;

      if (loudEnough) {
        if (!this._speechStartedAt) this._speechStartedAt = now;
        this._lastLoudAt = now;
        this._cancelScheduledStop();
      }
    }

    if (elapsed >= MAX_MS) {
      this.stop();
      return;
    }
    if (!this._speechStartedAt && elapsed >= NO_SPEECH_MS) {
      this.stop();
      return;
    }
    if (
      this._speechStartedAt &&
      this._lastLoudAt &&
      !this._stopTimer &&
      now - this._speechStartedAt >= MIN_SPEECH_MS &&
      now - this._lastLoudAt >= SILENCE_GAP_MS
    ) {
      // Keep recording briefly so the final consonant lands in a chunk.
      this._scheduleStop();
    }
    this._raf = requestAnimationFrame(this._tick);
  };

  stop() {
    if (this._stopped) return;
    this._stopped = true;
    this._armed = false;
    this._cancelScheduledStop();
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this.recorder && this.recorder.state !== "inactive") {
      try {
        if (typeof this.recorder.requestData === "function") {
          this.recorder.requestData();
        }
      } catch {
        /* ignore */
      }
      this.recorder.stop();
    }
    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }
  }

  cancel() {
    this.stop();
  }

  /** Stop without scoring — used when pausing mid-take. */
  discard() {
    if (this.recorder) {
      this.recorder.ondataavailable = null;
      this.recorder.onstop = null;
      this.recorder.onerror = null;
    }
    this.stop();
    this.chunks = [];
  }

  release() {
    this.cancel();
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
