/* ai.js – "AI Picks" panel: the most interesting aircraft per the local LLM. */
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
      if (show) SW.loadAI();
    });
    SW.loadAI();
  };

  SW.loadAI = async function () {
    try {
      const res = await fetch("/api/ai/insights", SW.fetchOpts());
      const d = await res.json();
      SW.renderAI(d.insights || [], d.enabled);
    } catch (e) { /* ignore */ }
  };

  SW.renderAI = function (insights, enabled) {
    const el = document.getElementById("ai-body");
    if (!el) return;
    if (!enabled) {
      el.innerHTML = '<p class="muted">Ollama AI is disabled. Enable it in Settings 🛠️ (works with a remote Ollama URL too).</p>';
      return;
    }
    if (!insights.length) { el.innerHTML = '<p class="muted">No standout aircraft yet.</p>'; return; }
    el.innerHTML = insights.map((i) => {
      const color = SW.CATEGORY_COLORS[i.marker_category] || SW.CATEGORY_COLORS.normal;
      return `<div class="ai-item" onclick="SkyWatch.focusAircraft('${i.icao24}')">
        <div class="ai-head"><span class="cat-swatch" style="background:${color}"></span>
          <b>${(i.callsign || i.icao24).trim()}</b>
          <span class="muted">${i.typecode || ""}</span></div>
        <div class="ai-reason">${i.reason || ""}</div></div>`;
    }).join("");
  };

  // Live push from the per-minute analysis.
  SW.onAIInsights = function (insights) {
    SW.renderAI(insights || [], true);
    const btn = document.getElementById("btn-ai");
    if (btn && document.getElementById("ai-panel").classList.contains("hidden"))
      btn.classList.add("pulse");
  };
})();
