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
      SW.renderAI(d);
    } catch (e) { /* ignore */ }
  };

  SW.renderAI = function (d) {
    const el = document.getElementById("ai-body");
    if (!el) return;
    const insights = d.insights || [];
    let head = "";
    if (d.ollama_error)
      head = `<p class="muted">⚠ Ollama: ${d.ollama_error}. Heuristic ranking is used. Fix the URL/model in Settings 🛠️ → Test.</p>`;
    else if (!d.ollama)
      head = '<p class="muted">Heuristic ranking. Enable a (remote) Ollama in Settings 🛠️ for AI reasons.</p>';
    if (d.credit_budget && d.credits >= d.credit_budget)
      head += '<p class="muted">⚠ Daily OpenSky credit budget reached — scans paused until reset.</p>';
    if (!insights.length) {
      const why = (d.global_count === 0)
        ? "Global scan found nothing yet (or OpenSky is rate-limited). It runs every few minutes."
        : "No rare/military/emergency aircraft worldwide right now.";
      el.innerHTML = head + `<p class="muted">${why}</p>`;
      return;
    }
    el.innerHTML = head + insights.map((i) => {
      const color = SW.CATEGORY_COLORS[i.marker_category] || SW.CATEGORY_COLORS.normal;
      const lat = i.latitude, lon = i.longitude;
      // Show WHERE it is: country + coordinates (click flies you there).
      const loc = [i.origin_country,
        (lat != null ? `${lat.toFixed(2)}, ${lon.toFixed(2)}` : "")]
        .filter(Boolean).join(" · ");
      const srcs = (i.sources || []).slice(0, 3).map((u, n) =>
        `<a href="${u}" target="_blank" onclick="event.stopPropagation()">src${n + 1}</a>`).join(" · ");
      return `<div class="ai-item" onclick="SkyWatch.flyToAircraft('${i.icao24}',${lat},${lon})">
        <div class="ai-head"><span class="cat-swatch" style="background:${color}"></span>
          <b>${(i.callsign || i.icao24).trim()}</b>
          <span class="muted">${i.typecode || ""}</span></div>
        <div class="ai-reason">${i.analysis || i.reason || i.marker_category}</div>
        <div class="muted" style="font-size:.72rem">📍 ${loc}${i.operator ? " · " + i.operator : ""}${srcs ? " · " + srcs : ""}</div>
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
