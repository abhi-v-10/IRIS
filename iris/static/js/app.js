/* Invoice & Receipt Intelligence System - page behaviour (no frameworks needed) */
(function () {
  "use strict";
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const inr = (v) => "₹" + Number(v || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  // Whole table row clickable
  document.addEventListener("click", (e) => {
    const tr = e.target.closest("tr.clickable");
    if (tr && !e.target.closest("a, button, input, select")) window.location = tr.dataset.href;
  });

  // "Working..." overlay for slow forms (upload / OCR)
  $$("form[data-busy]").forEach((f) => f.addEventListener("submit", () => {
    const o = $("#busy");
    if (!o) return;
    $("#busy-text").textContent = f.dataset.busy;
    o.classList.add("show");
  }));
  window.addEventListener("pageshow", () => { const o = $("#busy"); if (o) o.classList.remove("show"); });

  // Upload drop zone
  const dz = $("#dropzone"), input = $("#files"), list = $("#file-list");
  if (dz && input) {
    const show = () => {
      list.innerHTML = "";
      Array.from(input.files).forEach((f) => {
        const li = document.createElement("li");
        li.innerHTML = `<span></span><span class="muted">${(f.size / 1024).toFixed(0)} KB</span>`;
        li.firstChild.textContent = f.name;
        list.appendChild(li);
      });
      const n = input.files.length;
      $("#upload-hint").textContent = n ? `${n} file${n > 1 ? "s" : ""} selected` : "Each document takes about 1–3 seconds.";
    };
    input.addEventListener("change", show);
    ["dragenter", "dragover"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach((ev) => dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("over"); }));
    dz.addEventListener("drop", (e) => { input.files = e.dataTransfer.files; show(); });
    $("#upload-form").addEventListener("submit", (e) => {
      if (!input.files.length) { e.preventDefault(); alert("Choose at least one file first."); $("#busy").classList.remove("show"); }
    });
  }

  const IRIS = {};

  // ---------------------------------------------------------------- dashboard charts
  IRIS.dashboard = function (d) {
    if (!window.Chart) return;
    const palette = ["#1f3a5f", "#1f8a7e", "#e0a33b", "#c8553d", "#6f63b3", "#3f88c5", "#8c9aa8", "#9c6b3f", "#4c9a5a"];
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = "#4a5468";
    const money = { callbacks: { label: (c) => ` ${c.label || c.dataset.label}: ${inr(c.parsed.y ?? c.parsed.x ?? c.parsed)}` } };

    new Chart($("#chartMonthly"), {
      type: "bar",
      data: { labels: d.monthly.map((m) => m.label),
              datasets: [{ label: "Spent", data: d.monthly.map((m) => m.spent), backgroundColor: "#1f3a5f", borderRadius: 5, maxBarThickness: 46 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: money },
                 scales: { y: { beginAtZero: true, ticks: { callback: (v) => "₹" + Number(v).toLocaleString("en-IN") }, grid: { color: "#eef1f5" } },
                           x: { grid: { display: false } } } },
    });
    new Chart($("#chartCategory"), {
      type: "doughnut",
      data: { labels: d.by_category.map((c) => c.category),
              datasets: [{ data: d.by_category.map((c) => c.spent), backgroundColor: palette, borderColor: "#fff", borderWidth: 2 }] },
      options: { maintainAspectRatio: false, cutout: "58%",
                 plugins: { legend: { position: "bottom", labels: { boxWidth: 12, padding: 12 } },
                            tooltip: { callbacks: { label: (c) => {
                              const sum = c.dataset.data.reduce((a, b) => a + b, 0);
                              return ` ${c.label}: ${inr(c.parsed)} (${((100 * c.parsed) / sum).toFixed(0)}%)`; } } } } },
    });
    new Chart($("#chartVendors"), {
      type: "bar",
      data: { labels: d.top_vendors.map((v) => v.vendor),
              datasets: [{ label: "Spent", data: d.top_vendors.map((v) => v.spent), backgroundColor: "#1f8a7e", borderRadius: 4, maxBarThickness: 22 }] },
      options: { indexAxis: "y", maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: money },
                 scales: { x: { beginAtZero: true, ticks: { callback: (v) => "₹" + Number(v).toLocaleString("en-IN") }, grid: { color: "#eef1f5" } },
                           y: { grid: { display: false } } } },
    });
  };

  // ---------------------------------------------------------------- review page
  IRIS.review = function () {
    const img = $("#doc-img");
    if (img) img.addEventListener("click", () => img.classList.toggle("zoom"));
    const tbody = $("#items tbody");
    const num = (el) => (el && el.value !== "" ? parseFloat(el.value) : null);
    const mark = (el, ok, text) => { el.textContent = text; el.className = ok === null ? "" : ok ? "ok" : "bad"; };

    function check() {
      const amts = $$("input[name=item_amount]", tbody).map((i) => parseFloat(i.value)).filter((v) => !isNaN(v));
      const sum = amts.reduce((a, b) => a + b, 0);
      const sub = num($("#subtotal")), tax = num($("#tax")), tot = num($("#total"));
      mark($("#chk-items"), null, amts.length ? inr(sum) : "no items");
      if (amts.length && sub !== null) {
        const ok = Math.abs(sum - sub) <= 0.05;
        mark($("#chk-sub"), ok, ok ? "✓ match" : `✗ differ by ${inr(Math.abs(sum - sub))}`);
      } else mark($("#chk-sub"), null, "–");
      const base = sub !== null ? sub : amts.length ? sum : null;
      const t = tax !== null ? tax : sub === null ? 0 : null;
      if (base !== null && t !== null && tot !== null) {
        const ok = Math.abs(base + t - tot) <= 0.05;
        mark($("#chk-total"), ok, ok ? "✓ match" : `✗ ${inr(base + t)} ≠ ${inr(tot)}`);
      } else mark($("#chk-total"), null, "–");
    }
    $("#add-item").addEventListener("click", () => {
      tbody.appendChild($("#item-row").content.cloneNode(true));
      $$("tr:last-child input", tbody)[0].focus();
      check();
    });
    tbody.addEventListener("click", (e) => { if (e.target.matches("[data-remove]")) { e.target.closest("tr").remove(); check(); } });
    $("#doc-form").addEventListener("input", check);
    check();
  };

  window.IRIS = IRIS;
})();
