/** MediaRecorder + silence-stop. No UI strings. */

// Tuned for short kids words: do not cut final plosives (T in "cat").
const SILENCE_GAP_MS = 1600;
const NO_SPEECH_MS = 5000;
const MAX_MS = 20000;
const MIN_SPEECH_MS = 450;
const SPEECH_START_THRESHOLD = 0.028;
const SPEECH_HOLD_THRESHOLD = 0.012;
const START_GRACE_MS = 180;

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
  }

  async ensureStream() {
    if (this.stream) return this.stream;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    return this.stream;
  }

  async start({ oncomplete, onerror }) {
    this._stopped = false;
    this.chunks = [];
    try {
      const stream = await this.ensureStream();
      // Resume AudioContext after a user gesture when needed.
      if (this._audioCtx && this._audioCtx.state === "suspended") {
        await this._audioCtx.resume().catch(() => {});
      }
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
      // Smaller timeslice → less trailing audio lost when stop() fires.
      this.recorder.start(50);
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

  _tick = () => {
    if (this._stopped) return;
    const now = performance.now();
    const elapsed = now - this._startedAt;
    const level = this._level();

    // Ignore mic settle noise for a short grace after tap.
    if (elapsed >= START_GRACE_MS) {
      const startThresh = SPEECH_START_THRESHOLD;
      const holdThresh = SPEECH_HOLD_THRESHOLD;
      const loudEnough = this._speechStartedAt
        ? level >= holdThresh
        : level >= startThresh;

      if (loudEnough) {
        if (!this._speechStartedAt) this._speechStartedAt = now;
        this._lastLoudAt = now;
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
      now - this._speechStartedAt >= MIN_SPEECH_MS &&
      now - this._lastLoudAt >= SILENCE_GAP_MS
    ) {
      this.stop();
      return;
    }
    this._raf = requestAnimationFrame(this._tick);
  };

  stop() {
    if (this._stopped) return;
    this._stopped = true;
    if (this._raf) cancelAnimationFrame(this._raf);
    if (this.recorder && this.recorder.state !== "inactive") {
      try {
        // Flush the current timeslice before stop so the tail isn't dropped.
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

  release() {
    this.cancel();
    if (this.stream) {
      this.stream.getTracks().forEach((t) => t.stop());
      this.stream = null;
    }
  }
}
