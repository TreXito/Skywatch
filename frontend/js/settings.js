/* settings.js – in-browser settings editor. Reads /api/settings, renders a form
   grouped by section, and POSTs changes (persisted to an overrides file so your
   commented config.yaml is never touched). Includes remote Ollama URL + model load. */
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
      extra = `<button type="button" class="mini-btn" id="ollama-load">Load models</button>
               <datalist id="ollama-models"></datalist>`;
    }
    if (f.key === "ollama_model") input = input.replace("/>", ` list="ollama-models"/>`);
    return `<div class="set-field"><label for="${id}">${f.label}</label>${input}${extra}</div>`;
  }

  function renderForm() {
    const groups = {};
    schema.forEach((f) => { (groups[f.group] = groups[f.group] || []).push(f); });
    const html = Object.entries(groups).map(([g, fields]) =>
      `<details class="set-group" open><summary>${g}</summary>${fields.map(field).join("")}</details>`
    ).join("");
    document.getElementById("settings-body").innerHTML = html;

    const ol = document.getElementById("ollama-load");
    if (ol) ol.addEventListener("click", loadOllamaModels);
  }

  async function loadOllamaModels() {
    const url = document.getElementById("set-ollama_url").value.trim();
    const status = document.getElementById("settings-status");
    status.textContent = "Loading models…";
    try {
      const res = await fetch(`/api/ollama/models?url=${encodeURIComponent(url)}`, SW.fetchOpts());
      const d = await res.json();
      const dl = document.getElementById("ollama-models");
      dl.innerHTML = (d.models || []).map((m) => `<option value="${m}">`).join("");
      status.textContent = (d.models || []).length
        ? `${d.models.length} models found ✓` : "No models / unreachable";
    } catch (e) { status.textContent = "Failed to reach Ollama"; }
  }

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
      // Re-apply map style live if it changed.
      if (payload.map_style && SW.setBasemap) {
        const map = { "dark-en": "Dark · EN labels", "dark": "Dark (Carto)",
          "german": "Deutsch (OSM.de)", "light": "Light · EN labels", "satellite": "Satellite" };
        if (map[payload.map_style]) SW.setBasemap(map[payload.map_style]);
      }
    } catch (e) { status.textContent = "Save failed"; }
  };
})();
