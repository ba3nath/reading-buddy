/** MediaRecorder + silence-stop. No UI strings. */

const SILENCE_GAP_MS = 1200;
const NO_SPEECH_MS = 4000;
const MAX_MS = 20000;
const SILENCE_THRESHOLD = 0.02;

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
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    return this.stream;
  }

  async start({ oncomplete, onerror }) {
    this._stopped = false;
    this.chunks = [];
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
      const source = this._audioCtx.createMediaStreamSource(stream);
      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 2048;
      source.connect(this._analyser);

      this._startedAt = performance.now();
      this._speechStartedAt = 0;
      this._lastLoudAt = 0;
      this.recorder.start(100);
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
    const level = this._level();
    const loud = level >= SILENCE_THRESHOLD;

    if (loud) {
      if (!this._speechStartedAt) this._speechStartedAt = now;
      this._lastLoudAt = now;
    }

    const elapsed = now - this._startedAt;
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
