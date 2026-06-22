/* stats.js – live traffic statistics panel. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let timer = null;

  SW.initStats = function () {
    const btn = document.getElementById("btn-stats");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const panel = document.getElementById("stats-panel");
      document.querySelectorAll(".panel").forEach((p) => {
        if (p.id !== "stats-panel") p.classList.add("hidden");
      });
      const showing = panel.classList.toggle("hidden") === false;
      if (showing) { SW.loadStats(); timer = setInterval(SW.loadStats, 15000); }
      else if (timer) { clearInterval(timer); timer = null; }
    });
  };

  function bars(entries, color) {
    const max = Math.max(1, ...entries.map((e) => e[1]));
    return entries.map(([k, v]) =>
      `<div class="bar-row"><span class="bar-label">${k}</span>
        <span class="bar-track"><span class="bar-fill" style="width:${(v / max) * 100}%;background:${color}"></span></span>
        <span class="bar-val">${v}</span></div>`).join("");
  }

  SW.loadStats = async function () {
    try {
      const res = await fetch("/api/stats", SW.fetchOpts());
      const s = await res.json();
      const catEntries = Object.entries(s.by_category || {})
        .sort((a, b) => b[1] - a[1])
        .map(([k, v]) => [SW.CATEGORY_LABELS[k] || k, v]);
      const el = document.getElementById("stats-body");
      el.innerHTML = `
        <p class="muted">${s.scope === "worldwide" ? "🌍 Worldwide" : "📍 Local area"} · live</p>
        <div class="stat-grid">
          <div class="stat-big"><b>${s.total}</b><span>in range</span></div>
          <div class="stat-big"><b>${s.airborne}</b><span>airborne</span></div>
          <div class="stat-big"><b>${s.on_ground}</b><span>on ground</span></div>
          <div class="stat-big"><b>${s.avg_altitude_m ? s.avg_altitude_m.toLocaleString() + " m" : "—"}</b><span>avg alt</span></div>
        </div>
        <h4>By category</h4>${bars(catEntries, "#3498db")}
        <h4>Top countries</h4>${bars(s.top_countries || [], "#2ecc71")}
        <h4>Top types</h4>${bars(s.top_types || [], "#9b59b6")}
        <h4>Alerts (last ${s.alerts_24h})</h4>
        ${bars(Object.entries(s.alerts_by_type || {}), "#e67e22") || '<p class="muted">None</p>'}`;
    } catch (e) { /* ignore */ }
  };
})();
