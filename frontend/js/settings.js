/* settings.js – in-browser settings editor. Reads /api/settings, renders a form
   grouped by section, and POSTs changes (persisted to an overrides file so your
   commented config.yaml is never touched). Ollama: enter URL, pick a model from a
   dropdown loaded from the server, and test it. */
(function () {
  const SW = (window.SkyWatch = window.SkyWatch || {});
  let schema = [], values = {};

  SW.initSettings = function () {
    const btn = document.getElementById("btn-settings");
    if (!btn) return;
    btn.addEventListener("click", () => {
      document.querySelectorAll(".panel").forEach((p) => {
        if (p.id !== "settings-panel") p.classList.add("hidden");
      });
      const show = document.getElementById("settings-panel").classList.toggle("hidden") === false;
      if (show) SW.loadSettings();
    });
    document.getElementById("settings-save").addEventListener("click", SW.saveSettings);
  };

  SW.loadSettings = async function () {
    try {
      const res = await fetch("/api/settings", SW.fetchOpts());
      const d = await res.json();
      schema = d.schema || []; values = d.values || {};
      renderForm();
    } catch (e) {
      document.getElementById("settings-body").innerHTML =
        '<p class="muted">Failed to load settings.</p>';
    }
  };

  function field(f) {
    const v = values[f.key];
    const id = `set-${f.key}`;
    if (f.type === "bool") {
      return `<label class="switch-row"><input type="checkbox" id="${id}" data-key="${f.key}" ${v ? "checked" : ""}/>
        <span>${f.label}</span></label>`;
    }
    // Ollama model is a dropdown populated from the server.
    if (f.key === "ollama_model") {
      const cur = v == null ? "" : v;
      return `<div class="set-field"><label for="${id}">${f.label}</label>
        <select id="${id}" data-key="${f.key}">
          ${cur ? `<option value="${cur}" selected>${cur}</option>` : `<option value="">(load models)</option>`}
        </select></div>`;
    }
    let input;
    if (f.type === "textarea") {
      input = `<textarea id="${id}" data-key="${f.key}" rows="3">${v == null ? "" : v}</textarea>`;
    } else if (f.type.startsWith("select:")) {
      const opts = f.type.slice(7).split(",").map((o) =>
        `<option value="${o}" ${String(v) === o ? "selected" : ""}>${o}</option>`).join("");
      input = `<select id="${id}" data-key="${f.key}">${opts}</select>`;
    } else {
      const t = f.type === "password" ? "password" : (f.type === "number" ? "number" : "text");
      input = `<input id="${id}" data-key="${f.key}" type="${t}" value="${v == null ? "" : v}"/>`;
    }
    let extra = "";
    if (f.key === "ollama_url") {
      extra = `<div class="ollama-actions">
        <button type="button" class="mini-btn" id="ollama-load">↻ Load models</button>
        <button type="button" class="mini-btn" id="ollama-test">⚡ Test</button>
        <span id="ollama-status" class="muted"></span></div>`;
    }
    return `<div class="set-field"><label for="${id}">${f.label}</label>${input}${extra}</div>`;
  }

  function renderForm() {
    const groups = {};
    schema.forEach((f) => { (groups[f.group] = groups[f.group] || []).push(f); });
    const html = Object.entries(groups).map(([g, fields]) =>
      `<details class="set-group" ${g === "Ollama AI" ? "open" : ""}><summary>${g}</summary>${fields.map(field).join("")}</details>`
    ).join("");
    document.getElementById("settings-body").innerHTML = html;

    document.getElementById("ollama-load")?.addEventListener("click", () => SW.loadOllamaModels(true));
    document.getElementById("ollama-test")?.addEventListener("click", SW.testOllama);
    // Auto-load the model list if a URL is configured.
    if (document.getElementById("set-ollama_url")?.value.trim()) SW.loadOllamaModels(false);
  }

  SW.loadOllamaModels = async function (announce) {
    const url = document.getElementById("set-ollama_url")?.value.trim();
    const status = document.getElementById("ollama-status");
    const sel = document.getElementById("set-ollama_model");
    if (!sel) return;
    if (announce && status) status.textContent = "Loading…";
    try {
      const res = await fetch(`/api/ollama/models?url=${encodeURIComponent(url || "")}`, SW.fetchOpts());
      const d = await res.json();
      const models = d.models || [];
      const current = sel.value;
      if (models.length) {
        sel.innerHTML = models.map((m) =>
          `<option value="${m}" ${m === current ? "selected" : ""}>${m}</option>`).join("");
        if (status) status.textContent = `${models.length} models ✓`;
      } else if (status) {
        status.textContent = "No models / unreachable";
      }
    } catch (e) { if (status) status.textContent = "Failed to reach Ollama"; }
  };

  SW.testOllama = async function () {
    const url = document.getElementById("set-ollama_url")?.value.trim();
    const model = document.getElementById("set-ollama_model")?.value;
    const status = document.getElementById("ollama-status");
    if (status) status.textContent = "Testing…";
    try {
      const q = `?url=${encodeURIComponent(url || "")}&model=${encodeURIComponent(model || "")}`;
      const res = await fetch(`/api/ollama/test${q}`, SW.fetchOpts());
      const d = await res.json();
      if (status) status.textContent = d.ok ? `✓ works (${d.model})` : `✗ ${d.error || "failed"}`;
    } catch (e) { if (status) status.textContent = "✗ test failed"; }
  };

  SW.saveSettings = async function () {
    const status = document.getElementById("settings-status");
    const payload = {};
    document.querySelectorAll("#settings-body [data-key]").forEach((el) => {
      const key = el.dataset.key;
      if (el.type === "checkbox") payload[key] = el.checked;
      else if (el.type === "number") payload[key] = el.value === "" ? null : parseFloat(el.value);
      else payload[key] = el.value;
    });
    status.textContent = "Saving…";
    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: Object.assign({ "Content-Type": "application/json" },
          (SW.fetchOpts().headers || {})),
        body: JSON.stringify(payload),
      });
      const d = await res.json();
      status.textContent = d.restart_recommended
        ? "Saved ✓ — some changes need a restart" : "Saved ✓";
      if (payload.map_style && SW.setBasemap) {
        const map = { "dark-en": "Dark · EN labels", "dark": "Dark (Carto)",
          "german": "Deutsch (OSM.de)", "light": "Light · EN labels", "satellite": "Satellite" };
        if (map[payload.map_style]) SW.setBasemap(map[payload.map_style]);
      }
    } catch (e) { status.textContent = "Save failed"; }
  };
})();
