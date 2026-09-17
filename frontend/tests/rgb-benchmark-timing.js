// Experiment-only wrapper: same production preview, no extra traffic while measuring.
export function timingPlatform(base, capture, delivery = 'poll', imageFetch = base.fetch.bind(base)) {
  let received = null;
  let cursor = null;
  let displayed = null;
  const wrapper = {
    performance: base.performance, crypto: base.crypto, document: base.document,
    URL: base.URL,
    setTimeout: base.setTimeout.bind(base), clearTimeout: base.clearTimeout.bind(base),
    setInterval: base.setInterval.bind(base), clearInterval: base.clearInterval.bind(base),
    cancelAnimationFrame: base.cancelAnimationFrame.bind(base),
    async fetch(url, options) {
      if (new URL(url, 'http://127.0.0.1').pathname !== '/api/v1/media/rgb') return base.fetch(url, options);
      const start = base.performance.now();
      try {
        const requestUrl = delivery === 'new-frame'
          ? url + (url.includes('?') ? '&' : '?') + 'delivery=new-frame' + (cursor ? `&session=${cursor.s}&after=${cursor.n}` : '')
          : url;
        const response = await imageFetch(requestUrl, options);
        const headersAt = base.performance.now();
        if (!response.ok) { displayed=null; capture.fail(start); return response; }
        let nextCursor = null;
        let frame=null;
        try {
          const f = JSON.parse(response.headers.get?.('X-HazardGuard-Frame') || 'null');
          frame=f;
          if (f && /^[a-f0-9]{32}$/.test(f.s) && Number.isSafeInteger(f.n) && f.n >= 0) nextCursor = {s:f.s,n:f.n};
        } catch { /* Do not carry malformed identity into the next request. */ }
        const serverText = response.headers.get?.('Server-Timing') || '';
        const beforeAgeMatch=serverText.match(/(?:^|,\s*)beforeage;dur=([0-9.]+)/);
        const beforeAge=beforeAgeMatch?Number(beforeAgeMatch[1]):null;
        const server = ['handler','wait','active'].map(key => {
          const match = serverText.match(new RegExp(`(?:^|,\\s*)${key};dur=([0-9.]+)`));
          return match ? Number(match[1]) : NaN;
        });
        return {
          ok: response.ok, status: response.status, headers: response.headers,
          async blob() {
            try {
              const blob = await response.blob();
              cursor = nextCursor;
              received = { start, headersAt, bodyAt: base.performance.now() };
              if(frame && Number.isFinite(frame.age_ms) && Number.isFinite(beforeAge))received.fresh={age:frame.age_ms,beforeAge};
              if (server.every(Number.isFinite)) received.server = server;
              return blob;
            } catch (e) { displayed=null; capture.fail(start); throw e; }
          },
        };
      } catch (e) { displayed=null; capture.fail(start); throw e; }
    },
    requestAnimationFrame(callback) {
      return base.requestAnimationFrame(at => {
        const row = received;
        received = null;
        callback(at);
        if(row?.fresh)displayed=row;
        if (row) capture.add(row, base.performance.now());
      });
    },
    freshness(at) {
      if(!displayed?.fresh)return null;
      const r=displayed, elapsed=r.bodyAt-r.start, local=at-r.bodyAt;
      // Durations measured on each host; no subtraction of cross-host timestamps.
      // beforeAge is sampled just BEFORE computing server age, preserving an upper bound.
      const lower=Math.max(0,r.fresh.age+local);
      return [lower,lower+Math.max(0,elapsed-r.fresh.beforeAge),lower+elapsed];
    },
  };
  return wrapper;
}
