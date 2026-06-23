/* archive.js – worldwide Flight Archive: records (fastest/highest, today + all-time)
   and a searchable list of every flight we've ever logged from the global scan. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let timer = null, query = "";

  SW.initArchive = function () {
    const btn = document.getElementById("btn-archive");
    if (!btn) return;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".panel").forEach((p) => {
        if (p.id !== "archive-panel") p.classList.add("hidden");
      });
      const show = document.getElementById("archive-panel")
        .classList.toggle("hidden") === false;
      if (show) { SW.loadArchive(); timer = setInterval(SW.loadArchive, 20000); }
      else if (timer) { clearInterval(timer); timer = null; }
    });
    const input = document.getElementById("archive-search");
    if (input) {
      let deb = null;
      input.addEventListener("input", (e) => {
        query = e.target.value.trim();
        clearTimeout(deb);
        deb = setTimeout(SW.loadArchive, 300);
      });
    }
  };

  function fmtDur(s, e) {
    const m = Math.max(0, Math.round((e - s) / 60));
    return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`;
  }
  function ago(ts) {
    const m = Math.round((Date.now() / 1000 - ts) / 60);
    if (m < 60) return `${m}m ago`;
    if (m < 1440) return `${Math.floor(m / 60)}h ago`;
    return `${Math.floor(m / 1440)}d ago`;
  }

  function recordCard(title, rec, unit, fmt) {
    if (!rec) return `<div class="rec-card"><span class="rec-title">${title}</span>
      <b class="rec-val">—</b></div>`;
    return `<div class="rec-card"><span class="rec-title">${title}</span>
      <b class="rec-val">${fmt(rec.value)} ${unit}</b>
      <span class="rec-who">${rec.label || rec.icao24 || ""}</span></div>`;
  }

  SW.loadArchive = async function () {
    try {
      const [statsRes, flRes] = await Promise.all([
        fetch("/api/archive/stats", SW.fetchOpts()),
        fetch(`/api/archive/flights?limit=80&q=${encodeURIComponent(query)}`, SW.fetchOpts()),
      ]);
      const st = await statsRes.json();
      const fl = (await flRes.json()).flights || [];
      const r = st.records || {};
      const kmh = (ms) => Math.round(ms * 3.6).toLocaleString();
      const km = (m) => Math.round(m).toLocaleString();

      const records = `
        <div class="rec-grid">
          ${recordCard("⚡ Fastest today", r["fastest:today"], "km/h", kmh)}
          ${recordCard("⚡ Fastest ever", r["fastest:alltime"], "km/h", kmh)}
          ${recordCard("⛰️ Highest today", r["highest:today"], "m", km)}
          ${recordCard("⛰️ Highest ever", r["highest:alltime"], "m", km)}
        </div>`;

      const banner = st.archiving
        ? `<p class="muted">🗄️ Archiving every flight · <b>${(st.flights || 0).toLocaleString()}</b> flights ·
           <b>${(st.positions || 0).toLocaleString()}</b> positions ·
           <b>${(st.aircraft || 0).toLocaleString()}</b> aircraft</p>`
        : `<p class="muted">Archiving is off — only recent history is kept.</p>`;

      const list = fl.length ? fl.map((f) => {
        const name = (f.callsign || f.icao24 || "").trim();
        const route = (f.origin || f.destination)
          ? `${f.origin || "?"} → ${f.destination || "?"}` : "";
        return `<div class="ai-item" onclick="SkyWatch.focusFromLink('${f.icao24}')">
          <div class="ai-head"><b>${name}</b>
            <span class="muted">${f.typecode || ""}${f.registration ? " · " + f.registration : ""}</span></div>
          <div class="muted" style="font-size:.74rem">
            ${route ? route + " · " : ""}${fmtDur(f.start_ts, f.end_ts)} ·
            max ${f.max_alt_m ? km(f.max_alt_m) + " m" : "—"} ·
            ${f.points} pts · ${ago(f.end_ts)}</div>
        </div>`;
      }).join("") : `<p class="muted">${query ? "No flights match." : "No flights archived yet."}</p>`;

      document.getElementById("archive-body").innerHTML = records + banner + list;
    } catch (e) { /* ignore */ }
  };
})();
