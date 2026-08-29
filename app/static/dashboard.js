const TYPE_LABELS = {
  MISSING_PAYMENT: "Missing payment",
  ORPHAN_PAYMENT: "Orphan payment",
  AMOUNT_MISMATCH: "Amount mismatch",
  CURRENCY_MISMATCH: "Currency mismatch",
  DUPLICATE_CHARGE: "Duplicate charge",
  CHARGE_ON_CANCELLED_ORDER: "Charged, order cancelled",
  PARTIAL_REFUND_SHORTFALL: "Partial refund shortfall",
  UNSETTLED_PAYMENT: "Unsettled payment",
  FAILED_PAYMENT_ON_COMPLETED_ORDER: "Failed payment, order completed",
};

const PAGE_SIZE = 10;

const state = {
  runId: null,
  type: "",
  search: "",
  page: 1,
  runs: [],
};

let chart = null;

const el = (id) => document.getElementById(id);

function money(n) {
  return `$${Number(n).toFixed(2)}`;
}

function debounce(fn, ms) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  };
}

async function loadData() {
  el("loading-state").classList.remove("hidden");
  el("error-state").classList.add("hidden");
  el("error-state").classList.remove("flex");

  const params = new URLSearchParams();
  if (state.runId) params.set("run_id", state.runId);
  if (state.type) params.set("type", state.type);
  if (state.search) params.set("search", state.search);
  params.set("page", state.page);
  params.set("page_size", PAGE_SIZE);

  try {
    const res = await fetch(`/api/reconciliation?${params.toString()}`, { credentials: "same-origin" });
    if (res.status === 401) {
      window.location.href = "/login";
      return;
    }
    const data = await res.json();
    if (!res.ok) {
      showError(data.detail || "Could not load reconciliation data.");
      return;
    }
    el("loading-state").classList.add("hidden");
    render(data);
  } catch {
    showError("Network error while loading the dashboard.");
  }
}

function showError(message) {
  el("loading-state").classList.add("hidden");
  el("error-state").classList.remove("hidden");
  el("error-state").classList.add("flex");
  el("error-message").textContent = message;
}

function render(data) {
  state.runs = data.runs || [];
  const hasRun = !!data.run;

  el("toggle-upload-btn").classList.toggle("hidden", !hasRun);
  el("upload-section").classList.toggle("hidden", hasRun && !uploadForcedOpen);
  el("dashboard-section").classList.toggle("hidden", !hasRun);

  if (!hasRun) return;

  // Run selector
  if (state.runs.length > 1) {
    el("run-selector").classList.remove("hidden");
    const select = el("run-select");
    select.innerHTML = "";
    state.runs.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r.id;
      opt.textContent = `${new Date(r.created_at).toLocaleString()} — ${r.orders_file_name} / ${r.payments_file_name}`;
      if (r.id === data.run.id) opt.selected = true;
      select.appendChild(opt);
    });
  } else {
    el("run-selector").classList.add("hidden");
  }

  const run = data.run;
  el("stat-orders").textContent = run.total_orders;
  el("stat-payments").textContent = run.total_payments;
  el("stat-reconciled").textContent = money(run.total_value_reconciled);
  el("stat-dispute").textContent = money(run.total_value_in_dispute);
  el("stat-risk").textContent = money(run.total_money_at_risk);

  renderChart(data.by_type || []);
  renderTypeFilter(data.by_type || []);
  renderTable(data);
}

function renderChart(byType) {
  const canvas = el("type-chart");
  if (byType.length === 0) {
    canvas.classList.add("hidden");
    el("no-discrepancies").classList.remove("hidden");
    if (chart) chart.destroy();
    return;
  }
  canvas.classList.remove("hidden");
  el("no-discrepancies").classList.add("hidden");

  const sorted = [...byType].sort((a, b) => b.amount - a.amount);
  const labels = sorted.map((d) => TYPE_LABELS[d.type] || d.type);
  const amounts = sorted.map((d) => Math.round(d.amount * 100) / 100);

  if (chart) chart.destroy();
  chart = new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels,
      datasets: [{ label: "Amount at risk ($)", data: amounts, backgroundColor: "#dc2626" }],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      plugins: { legend: { display: false } },
      scales: { x: { ticks: { callback: (v) => `$${v}` } } },
    },
  });
}

function renderTypeFilter(byType) {
  const select = el("type-filter");
  const current = state.type;
  select.innerHTML = '<option value="">All types</option>';
  byType.forEach((d) => {
    const opt = document.createElement("option");
    opt.value = d.type;
    opt.textContent = TYPE_LABELS[d.type] || d.type;
    if (d.type === current) opt.selected = true;
    select.appendChild(opt);
  });
}

function renderTable(data) {
  el("table-title").textContent = `Discrepancies (${data.total})`;
  const tbody = el("table-body");
  tbody.innerHTML = "";

  if (data.discrepancies.length === 0) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td colspan="6" class="text-center text-slate-400 px-4 py-8">No discrepancies match the current filters.</td>`;
    tbody.appendChild(tr);
  }

  data.discrepancies.forEach((row) => {
    const tr = document.createElement("tr");
    tr.className = "border-b border-slate-50 hover:bg-slate-50 align-top";
    tr.innerHTML = `
      <td class="px-4 py-3"><span class="badge badge-${row.severity}">${row.severity}</span></td>
      <td class="px-4 py-3 text-slate-700">${TYPE_LABELS[row.type] || row.type}</td>
      <td class="px-4 py-3 font-mono text-xs text-slate-600">${row.order_id || "—"}</td>
      <td class="px-4 py-3 tabular-nums">${row.currency} ${row.amount_at_risk.toFixed(2)}</td>
      <td class="px-4 py-3 text-slate-600 max-w-md">${escapeHtml(row.summary)}</td>
      <td class="px-4 py-3"></td>
    `;
    const btn = document.createElement("button");
    btn.textContent = "Explain";
    btn.className = "rounded-md border border-slate-300 px-2.5 py-1 text-xs font-medium hover:bg-slate-100 whitespace-nowrap";
    btn.addEventListener("click", () => openExplain([row.id], row.explanation));
    tr.lastElementChild.appendChild(btn);
    tbody.appendChild(tr);
  });

  const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
  el("page-info").textContent = `Page ${data.page} of ${totalPages}`;
  el("prev-page").disabled = data.page <= 1;
  el("next-page").disabled = data.page >= totalPages;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// --- Explain modal ---
function openExplain(ids, existingExplanation) {
  el("explain-modal").classList.remove("hidden");
  el("explain-title").textContent = ids.length > 1 ? `Explain ${ids.length} discrepancies` : "Explain this discrepancy";
  const body = el("explain-body");

  if (existingExplanation) {
    renderExplanation(existingExplanation, ids);
    return;
  }

  body.innerHTML = `
    <p class="text-sm text-slate-500 mb-4">
      Generate a plain-language explanation using the LLM. This only summarizes the deterministic
      result above — it does not change any matching decision.
    </p>
    <button id="generate-btn" class="w-full rounded-md bg-slate-900 text-white py-2 text-sm font-medium hover:bg-slate-800">
      Generate explanation
    </button>
  `;
  el("generate-btn").addEventListener("click", () => generateExplanation(ids));
}

async function generateExplanation(ids) {
  const body = el("explain-body");
  body.innerHTML = `
    <div class="flex items-center gap-2 text-sm text-slate-500 py-6">
      <span class="animate-spin h-4 w-4 rounded-full border-2 border-slate-300 border-t-slate-900"></span>
      Generating explanation...
    </div>
  `;
  try {
    const res = await fetch("/api/reconciliation/explain", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ discrepancy_ids: ids }),
      credentials: "same-origin",
    });
    const data = await res.json();
    if (!res.ok) {
      renderExplainError(data.detail || "Could not generate an explanation.", ids);
      return;
    }
    renderExplanation(data, ids);
  } catch {
    renderExplainError("Network error while contacting the explanation service.", ids);
  }
}

function renderExplainError(message, ids) {
  const body = el("explain-body");
  body.innerHTML = `
    <div class="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 mb-3">${escapeHtml(message)}</div>
    <button id="retry-explain-btn" class="w-full rounded-md border border-slate-300 py-2 text-sm font-medium hover:bg-slate-50">Retry</button>
  `;
  el("retry-explain-btn").addEventListener("click", () => generateExplanation(ids));
}

function renderExplanation(explanation, ids) {
  const body = el("explain-body");
  const badgeClass =
    explanation.confidence === "high" ? "badge-low" : explanation.confidence === "medium" ? "badge-medium" : "badge-high";
  body.innerHTML = `
    <span class="badge ${badgeClass} inline-block mb-3">${explanation.confidence} confidence</span>
    <p class="font-medium text-slate-900 mb-3">${escapeHtml(explanation.headline)}</p>
    <p class="text-xs font-semibold uppercase text-slate-400">Likely cause</p>
    <p class="text-sm text-slate-700 mb-3">${escapeHtml(explanation.likely_cause)}</p>
    <p class="text-xs font-semibold uppercase text-slate-400">Recommended action</p>
    <p class="text-sm text-slate-700 mb-4">${escapeHtml(explanation.recommended_action)}</p>
    <button id="regenerate-btn" class="w-full rounded-md border border-slate-300 py-2 text-sm font-medium hover:bg-slate-50">Regenerate</button>
  `;
  el("regenerate-btn").addEventListener("click", () => generateExplanation(ids));
}

el("explain-close").addEventListener("click", () => el("explain-modal").classList.add("hidden"));

// --- Upload ---
let uploadForcedOpen = false;

el("toggle-upload-btn").addEventListener("click", () => {
  uploadForcedOpen = !uploadForcedOpen;
  el("upload-section").classList.toggle("hidden", !uploadForcedOpen);
  el("toggle-upload-btn").textContent = uploadForcedOpen ? "Cancel" : "Load new data";
});

el("upload-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const ordersFile = el("orders-file").files[0];
  const paymentsFile = el("payments-file").files[0];
  const errorEl = el("upload-error");
  const btn = el("upload-btn");
  errorEl.classList.add("hidden");

  if (!ordersFile || !paymentsFile) {
    errorEl.textContent = "Please select both an orders CSV and a payments CSV.";
    errorEl.classList.remove("hidden");
    return;
  }

  btn.disabled = true;
  btn.textContent = "Reconciling...";

  const form = new FormData();
  form.append("orders", ordersFile);
  form.append("payments", paymentsFile);

  try {
    const res = await fetch("/api/ingest", { method: "POST", body: form, credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) {
      errorEl.textContent = data.detail || "Ingestion failed.";
      errorEl.classList.remove("hidden");
      btn.disabled = false;
      btn.textContent = "Upload & reconcile";
      return;
    }
    uploadForcedOpen = false;
    state.runId = data.run_id;
    state.type = "";
    state.search = "";
    state.page = 1;
    el("search-input").value = "";
    btn.disabled = false;
    btn.textContent = "Upload & reconcile";
    loadData();
  } catch {
    errorEl.textContent = "Network error while uploading. Please try again.";
    errorEl.classList.remove("hidden");
    btn.disabled = false;
    btn.textContent = "Upload & reconcile";
  }
});

el("search-input").addEventListener(
  "input",
  debounce((e) => {
    state.search = e.target.value;
    state.page = 1;
    loadData();
  }, 300)
);

el("type-filter").addEventListener("change", (e) => {
  state.type = e.target.value;
  state.page = 1;
  loadData();
});

el("prev-page").addEventListener("click", () => {
  if (state.page > 1) {
    state.page -= 1;
    loadData();
  }
});

el("next-page").addEventListener("click", () => {
  state.page += 1;
  loadData();
});

el("run-select").addEventListener("change", (e) => {
  state.runId = e.target.value;
  state.type = "";
  state.search = "";
  state.page = 1;
  el("search-input").value = "";
  loadData();
});

el("retry-btn").addEventListener("click", loadData);

el("signout-btn").addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  window.location.href = "/login";
});

loadData();