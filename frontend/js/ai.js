/* ai.js – "Interesting worldwide" panel: rare/military/emergency aircraft from the
   global scan, ranked (AI reasons when Ollama is available, else heuristic). */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});

  SW.initAI = function () {
    const btn = document.getElementById("btn-ai");
    if (!btn) return;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".panel").forEach((p) => {
        if (p.id !== "ai-panel") p.classList.add("hidden");
      });
      const show = document.getElementById("ai-panel").classList.toggle("hidden") === false;
      if (show) { btn.classList.remove("pulse"); SW.loadAI(); }
    });
    SW.loadAI();
    setInterval(SW.loadAI, 30000);
  };

  SW.loadAI = async function () {
    try {
      const res = await fetch("/api/ai/insights", SW.fetchOpts());
      const d = await res.json();
      SW.renderAI(d.insights || [], d.enabled, d.ollama);
    } catch (e) { /* ignore */ }
  };

  SW.renderAI = function (insights, enabled, ollama) {
    const el = document.getElementById("ai-body");
    if (!el) return;
    let head = "";
    if (!ollama)
      head = '<p class="muted">Heuristic ranking. Set a (remote) Ollama URL in Settings 🛠️ for AI reasons.</p>';
    if (!insights.length) {
      el.innerHTML = head + '<p class="muted">No rare/military/emergency aircraft worldwide right now. The global scan runs every few minutes.</p>';
      return;
    }
    el.innerHTML = head + insights.map((i) => {
      const color = SW.CATEGORY_COLORS[i.marker_category] || SW.CATEGORY_COLORS.normal;
      const dist = i.distance_km != null ? `${Math.round(i.distance_km).toLocaleString()} km away` : "";
      const lat = i.latitude, lon = i.longitude;
      return `<div class="ai-item" onclick="SkyWatch.flyToAircraft('${i.icao24}',${lat},${lon})">
        <div class="ai-head"><span class="cat-swatch" style="background:${color}"></span>
          <b>${(i.callsign || i.icao24).trim()}</b>
          <span class="muted">${i.typecode || ""}</span></div>
        <div class="ai-reason">${i.reason || i.marker_category}</div>
        <div class="muted" style="font-size:.72rem">${[i.operator, dist].filter(Boolean).join(" · ")}</div>
      </div>`;
    }).join("");
  };

  SW.onAIInsights = function (insights) {
    SW.loadAI();
    const btn = document.getElementById("btn-ai");
    if (btn && document.getElementById("ai-panel").classList.contains("hidden"))
      btn.classList.add("pulse");
  };
})();
