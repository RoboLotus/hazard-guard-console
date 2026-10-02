// RGB diagnostics only. No image bytes, credentials, URLs or user text in reports.
export const AGE_BOUNDS_MS = [50, 100, 200, 300, 500, 750, 1000, 1500, 2000, 3000, 5000, 10000, 30000, 60000];

export function parseFrameHeader(value) {
  try {
    if (!value || value.length > 1024) return null;
    const frame = JSON.parse(value);
    if (frame.v !== 1 || !/^[a-f0-9]{32}$/.test(frame.s)
      || !Number.isSafeInteger(frame.n) || frame.n < 1
      || !Number.isFinite(frame.age_ms) || frame.age_ms < 0 || frame.age_ms > 1e12
      || !["ingress", "cache"].includes(frame.reference)
      || !["basic", "detailed"].includes(frame.mode)) return null;
    if (frame.capture_age_ms !== null && (!Number.isFinite(frame.capture_age_ms)
      || frame.capture_age_ms < 0 || frame.capture_age_ms > 1e12)) return null;
    return frame;
  } catch { return null; }
}

export class RgbTelemetry {
  constructor(clientId, now = () => performance.now()) {
    this.clientId = clientId;
    this.now = now;
    this.sequence = 0;
    this.frame = null;
    this.metadataMissing = false;
    this.sessionId = null;
    this.mode = "basic";
    this.lastIdentity = null;
    this.lastNewFrameAt = now();
    this.resetWindow(now());
  }

  resetWindow(at) {
    this.start = this.lastSampleAt = at;
    this.values = [];
    this.references = new Set();
    this.observed = this.missing = this.stale = this.hidden = this.unobserved = 0;
    this.maxGap = this.uncertainty = this.loaded = this.unique = this.errors = this.reportErrors = 0;
    this.metadataErrors = 0;
  }

  displayed(frame, receivedAt, requestElapsedMs, displayedAt = this.now()) {
    this.loaded += 1;
    this.frame = frame ? { ...frame, receivedAt, requestElapsedMs } : null;
    this.metadataMissing = !frame;
    if (!frame) this.metadataErrors += 1;
    if (frame) { this.sessionId = frame.s; this.mode = frame.mode; }
    const identity = frame ? `${frame.s}:${frame.n}` : null;
    if (identity && identity !== this.lastIdentity) {
      this.unique += 1;
      this.lastIdentity = identity;
      this.lastNewFrameAt = displayedAt;
    }
    this.uncertainty = Math.max(this.uncertainty, requestElapsedMs);
  }

  unavailable() { this.frame = null; this.metadataMissing = false; this.errors += 1; }

  sample(visible = true, at = this.now()) {
    const elapsed = Math.max(0, at - this.lastSampleAt);
    this.lastSampleAt = at;
    if (!visible) { this.hidden += elapsed; return; }
    // A suspended/throttled JS timer cannot certify what happened during the gap.
    if (elapsed > 500) { this.unobserved += elapsed; return; }
    this.observed += elapsed;
    this.maxGap = Math.max(this.maxGap, at - this.lastNewFrameAt);
    if (!this.frame) {
      if (this.metadataMissing) { this.observed -= elapsed; this.unobserved += elapsed; }
      else this.missing += elapsed;
      return;
    }
    const f = this.frame;
    const base = f.capture_age_ms ?? f.age_ms;
    // Upper estimate: age at server response + full request time + local elapsed.
    // The matching lower estimate excludes requestElapsedMs. No cross-host clock subtraction.
    const age = Math.max(0, base + f.requestElapsedMs + at - f.receivedAt);
    this.references.add(f.capture_age_ms === null ? f.reference : "capture");
    this.values.push(age);
    if (this.values.length > 6000) this.values.shift();
    if (age > 1000) this.stale += elapsed;
  }

  report(at = this.now()) {
    const windowMs = at - this.start;
    if (windowMs <= 0 || windowMs > 600000) { this.resetWindow(at); return null; }
    const values = [...this.values].sort((a, b) => a - b);
    const histogram = Array(AGE_BOUNDS_MS.length + 1).fill(0);
    for (const value of values) {
      const bucket = AGE_BOUNDS_MS.findIndex(bound => value <= bound);
      histogram[bucket < 0 ? AGE_BOUNDS_MS.length : bucket] += 1;
    }
    const report = {
      client_id: this.clientId, session_id: this.sessionId,
      sequence: ++this.sequence,
      reference: this.references.size > 1 ? "mixed" : [...this.references][0] ?? "unavailable",
      window_ms: windowMs, observed_ms: this.observed, missing_ms: this.missing,
      stale_ms: this.stale, hidden_ms: this.hidden, unobserved_ms: this.unobserved,
      max_gap_ms: this.maxGap, uncertainty_max_ms: this.uncertainty,
      frames_loaded: this.loaded, unique_frames: this.unique,
      request_errors: this.errors, report_errors: this.reportErrors,
      metadata_errors: this.metadataErrors,
      age: {
        samples: values.length,
        mean_ms: values.length ? values.reduce((a, b) => a + b, 0) / values.length : null,
        p95_ms: values.length ? values[Math.ceil(values.length * 0.95) - 1] : null,
        max_ms: values.length ? values.at(-1) : null, histogram,
      },
      detail_age_ms: this.mode === "detailed" ? this.values.slice(-50) : [],
    };
    this.resetWindow(at);
    return report;
  }
}
