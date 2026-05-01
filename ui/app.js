const DATA_URL = "../out/master_prompt_preview.jsonl";

const state = {
  records: [],
  filtered: [],
  selected: 0,
  status: "all",
  domain: "all",
  priority: "all",
  sort: "queue",
  query: "",
  apiOnline: false,
  mode: "Embedded preview",
  readiness: null,
};

const els = {
  metricTotal: document.querySelector("#metricTotal"),
  metricReplied: document.querySelector("#metricReplied"),
  metricEscalated: document.querySelector("#metricEscalated"),
  metricInvalid: document.querySelector("#metricInvalid"),
  metricConfidence: document.querySelector("#metricConfidence"),
  metricReadiness: document.querySelector("#metricReadiness"),
  coverageBadge: document.querySelector("#coverageBadge"),
  readinessScore: document.querySelector("#readinessScore"),
  readinessList: document.querySelector("#readinessList"),
  apiHealth: document.querySelector("#apiHealth"),
  dataMode: document.querySelector("#dataMode"),
  ticketList: document.querySelector("#ticketList"),
  visibleCount: document.querySelector("#visibleCount"),
  selectedIndex: document.querySelector("#selectedIndex"),
  emptyState: document.querySelector("#emptyState"),
  detailContent: document.querySelector("#detailContent"),
  detailStatus: document.querySelector("#detailStatus"),
  detailArea: document.querySelector("#detailArea"),
  detailType: document.querySelector("#detailType"),
  detailConfidence: document.querySelector("#detailConfidence"),
  detailPriority: document.querySelector("#detailPriority"),
  detailCoverage: document.querySelector("#detailCoverage"),
  detailResponse: document.querySelector("#detailResponse"),
  detailJustification: document.querySelector("#detailJustification"),
  detailJson: document.querySelector("#detailJson"),
  decisionTimeline: document.querySelector("#decisionTimeline"),
  draftEditor: document.querySelector("#draftEditor"),
  saveDraftButton: document.querySelector("#saveDraftButton"),
  resetDraftButton: document.querySelector("#resetDraftButton"),
  sourceList: document.querySelector("#sourceList"),
  domainBars: document.querySelector("#domainBars"),
  areaCloud: document.querySelector("#areaCloud"),
  reviewQueue: document.querySelector("#reviewQueue"),
  reasonList: document.querySelector("#reasonList"),
  confidenceBands: document.querySelector("#confidenceBands"),
  coverageBars: document.querySelector("#coverageBars"),
  searchInput: document.querySelector("#searchInput"),
  domainFilter: document.querySelector("#domainFilter"),
  priorityFilter: document.querySelector("#priorityFilter"),
  sortSelect: document.querySelector("#sortSelect"),
  refreshButton: document.querySelector("#refreshButton"),
  loadApiButton: document.querySelector("#loadApiButton"),
  uploadButton: document.querySelector("#uploadButton"),
  csvInput: document.querySelector("#csvInput"),
  exportCsvButton: document.querySelector("#exportCsvButton"),
  exportJsonButton: document.querySelector("#exportJsonButton"),
  escalatedOnlyButton: document.querySelector("#escalatedOnlyButton"),
  labCompany: document.querySelector("#labCompany"),
  labSubject: document.querySelector("#labSubject"),
  labIssue: document.querySelector("#labIssue"),
  runLabButton: document.querySelector("#runLabButton"),
  labResult: document.querySelector("#labResult"),
  labStatus: document.querySelector("#labStatus"),
  ticketTemplate: document.querySelector("#ticketTemplate"),
};

function parseJsonl(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line, index) => normalizeRecord(JSON.parse(line), index));
}

function normalizeRecord(item, index) {
  const result = item.result || item;
  const meta = item.meta || deriveMeta(result);
  const ticket = item.ticket || {};
  return {
    id: item.id || index + 1,
    ticket,
    status: result.status,
    product_area: result.product_area,
    response: result.response,
    justification: result.justification,
    request_type: result.request_type,
    meta,
    draft_response: item.draft_response || result.response,
  };
}

function deriveMeta(result) {
  const justification = result.justification || "";
  const domain = extractTrace(justification, "Domain detected", "unknown").split(" ")[0];
  const risk = extractTrace(justification, "Risk level", "UNKNOWN").split(" ")[0];
  const urgency = extractTrace(justification, "Urgency level", "UNKNOWN").split(" ")[0];
  const coverage = extractTrace(justification, "Corpus coverage", "unknown").split(";")[0];
  const confidence = confidenceFromResult(result, risk, coverage);
  return {
    domain,
    risk_level: risk,
    urgency_level: urgency,
    corpus_coverage: coverage,
    decision: extractTrace(justification, "Decision", "unknown"),
    anomalies: extractTrace(justification, "Anomalies", "none").replace(/\.$/, ""),
    confidence,
    confidence_label: confidence >= 0.85 ? "High" : confidence >= 0.65 ? "Medium" : "Low",
    review_priority: result.status === "escalated" ? (risk === "HIGH" || urgency === "HIGH" ? "High" : "Normal") : "No review needed",
    sources: parseSources(justification),
  };
}

function extractTrace(text, label, fallback) {
  const expression = new RegExp(`${label}:\\s*(.*?)(?=\\.\\s+[A-Z][A-Za-z /]+:|$)`);
  const match = String(text || "").match(expression);
  return match ? match[1].trim() : fallback;
}

function parseSources(justification) {
  const match = String(justification || "").match(/matched docs:\s*(.*?)(?:\.\s+Decision:|$)/);
  if (!match || match[1].trim() === "none") return [];
  return [...match[1].matchAll(/([^,]+?)\s+\(([0-9.]+)\)/g)].map((source) => ({
    doc_id: source[1].trim(),
    title: source[1].trim(),
    score: Number(source[2]),
  }));
}

function confidenceFromResult(result, risk, coverage) {
  const text = String(result.justification || "").toLowerCase();
  if (result.request_type === "invalid" || text.includes("stage 1")) return 0.98;
  if (result.status === "escalated" && risk === "HIGH") return 0.94;
  if (result.status === "escalated") return 0.86;
  if (String(coverage).startsWith("fully covered")) return 0.88;
  if (String(coverage).startsWith("partially covered")) return 0.62;
  return 0.5;
}

function countBy(items, keyGetter) {
  return items.reduce((acc, item) => {
    const value = typeof keyGetter === "function" ? keyGetter(item) : item[keyGetter];
    const key = value || "unknown";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}

function riskValue(record) {
  return { HIGH: 3, MEDIUM: 2, LOW: 1 }[record.meta.risk_level] || 0;
}

function priorityValue(record) {
  return {
    "Security review": 5,
    High: 4,
    Medium: 3,
    Normal: 2,
    "No review needed": 1,
  }[record.meta.review_priority] || 0;
}

function averageConfidence(records) {
  if (!records.length) return 0;
  const total = records.reduce((sum, record) => sum + Number(record.meta.confidence || 0), 0);
  return total / records.length;
}

function animateNumber(el, value) {
  const start = Number(el.textContent) || 0;
  const duration = 460;
  const started = performance.now();
  function frame(now) {
    const progress = Math.min((now - started) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(start + (value - start) * eased);
    if (progress < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function setMode(mode) {
  state.mode = mode;
  els.dataMode.textContent = mode;
}

function renderMetrics() {
  const replied = state.records.filter((record) => record.status === "replied").length;
  const escalated = state.records.filter((record) => record.status === "escalated").length;
  const invalid = state.records.filter((record) => record.request_type === "invalid").length;
  animateNumber(els.metricTotal, state.records.length);
  animateNumber(els.metricReplied, replied);
  animateNumber(els.metricEscalated, escalated);
  animateNumber(els.metricInvalid, invalid);
  els.metricConfidence.textContent = `${Math.round(averageConfidence(state.records) * 100)}%`;
  if (state.readiness) {
    els.metricReadiness.textContent = `${state.readiness.score}/${state.readiness.total}`;
  }
  els.coverageBadge.textContent = `${state.records.length} decisions loaded`;
  els.coverageBadge.classList.remove("load-error");
}

function populateDomainFilter() {
  const selected = state.domain;
  const domains = [...new Set(state.records.map((record) => record.meta.domain).filter(Boolean))].sort();
  els.domainFilter.textContent = "";
  const all = document.createElement("option");
  all.value = "all";
  all.textContent = "All";
  els.domainFilter.appendChild(all);
  domains.forEach((domain) => {
    const option = document.createElement("option");
    option.value = domain;
    option.textContent = domain;
    els.domainFilter.appendChild(option);
  });
  els.domainFilter.value = domains.includes(selected) ? selected : "all";
  state.domain = els.domainFilter.value;
}

function renderReadiness() {
  if (!state.readiness) {
    els.readinessScore.textContent = "0/5";
    els.metricReadiness.textContent = "0/5";
    els.readinessList.innerHTML = '<p class="muted-copy">Checking local artifacts.</p>';
    return;
  }
  els.readinessScore.textContent = `${state.readiness.score}/${state.readiness.total}`;
  els.metricReadiness.textContent = `${state.readiness.score}/${state.readiness.total}`;
  els.readinessList.textContent = "";
  state.readiness.checks.forEach((check) => {
    const item = document.createElement("div");
    item.className = `readiness-item ${check.status}`;
    item.innerHTML = `
      <span>${check.status === "pass" ? "OK" : "Fix"}</span>
      <div>
        <strong>${escapeHtml(check.label)}</strong>
        <em>${escapeHtml(check.detail)}</em>
      </div>
    `;
    els.readinessList.appendChild(item);
  });
}

async function loadReadiness() {
  if (window.location.protocol === "file:") {
    state.readiness = null;
    renderReadiness();
    return;
  }
  try {
    const response = await fetch("/api/readiness", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.readiness = await response.json();
  } catch {
    state.readiness = null;
  }
  renderReadiness();
  renderMetrics();
}

function applyFilters() {
  const query = state.query.trim().toLowerCase();
  state.filtered = state.records.filter((record) => {
    const statusMatch = state.status === "all" || record.status === state.status;
    const domainMatch = state.domain === "all" || record.meta.domain === state.domain;
    const priorityMatch = state.priority === "all" || record.meta.review_priority === state.priority;
    const haystack = [
      record.status,
      record.product_area,
      record.request_type,
      record.response,
      record.draft_response,
      record.justification,
      record.meta.domain,
      record.meta.review_priority,
      record.meta.confidence_label,
      record.meta.corpus_coverage,
      record.ticket.issue,
      record.ticket.subject,
      record.ticket.company,
    ].join(" ").toLowerCase();
    return statusMatch && domainMatch && priorityMatch && (!query || haystack.includes(query));
  });
  sortFilteredRecords();
  if (!state.filtered[state.selected]) state.selected = 0;
  renderTickets();
  renderDetail();
}

function sortFilteredRecords() {
  const sorters = {
    queue: (a, b) => priorityValue(b) - priorityValue(a) || riskValue(b) - riskValue(a) || a.id - b.id,
    confidence: (a, b) => Number(a.meta.confidence || 0) - Number(b.meta.confidence || 0) || a.id - b.id,
    risk: (a, b) => riskValue(b) - riskValue(a) || priorityValue(b) - priorityValue(a) || a.id - b.id,
    domain: (a, b) => String(a.meta.domain).localeCompare(String(b.meta.domain)) || a.id - b.id,
  };
  state.filtered.sort(sorters[state.sort] || sorters.queue);
}

function renderTickets() {
  els.ticketList.textContent = "";
  els.visibleCount.textContent = `${state.filtered.length} shown`;

  state.filtered.forEach((record, index) => {
    const node = els.ticketTemplate.content.firstElementChild.cloneNode(true);
    node.classList.toggle("active", index === state.selected);
    node.style.animationDelay = `${Math.min(index * 22, 220)}ms`;
    node.querySelector(".ticket-title").textContent = `#${record.id} ${record.product_area}`;
    const status = node.querySelector(".status-pill");
    status.textContent = record.status;
    status.classList.add(record.status);
    node.dataset.priority = record.meta.review_priority;
    node.querySelector(".ticket-meta").textContent = `${record.meta.domain} | ${record.request_type} | ${record.meta.confidence_label} | ${record.meta.review_priority}`;
    node.querySelector(".ticket-response").textContent = record.ticket.issue || record.draft_response || record.response;
    node.addEventListener("click", () => {
      state.selected = index;
      renderTickets();
      renderDetail();
    });
    els.ticketList.appendChild(node);
  });
}

function renderDetail() {
  const record = state.filtered[state.selected];
  const hasRecord = Boolean(record);
  els.emptyState.classList.toggle("hidden", hasRecord);
  els.detailContent.classList.toggle("hidden", !hasRecord);
  if (!record) {
    els.selectedIndex.textContent = "No ticket";
    return;
  }

  els.selectedIndex.textContent = `Ticket #${record.id}`;
  els.detailStatus.textContent = record.status;
  els.detailArea.textContent = record.product_area;
  els.detailType.textContent = record.request_type;
  els.detailConfidence.textContent = `${record.meta.confidence_label} (${Math.round(record.meta.confidence * 100)}%)`;
  els.detailPriority.textContent = record.meta.review_priority;
  els.detailCoverage.textContent = record.meta.corpus_coverage;
  els.detailResponse.textContent = record.response;
  els.draftEditor.value = record.draft_response || record.response;
  els.detailJustification.textContent = record.justification;
  els.detailJson.textContent = JSON.stringify(strictResult(record), null, 2);
  renderSources(record);
  renderDecisionTimeline(record);
}

function renderSources(record) {
  els.sourceList.textContent = "";
  const sources = record.meta.sources || [];
  if (!sources.length) {
    const empty = document.createElement("p");
    empty.className = "muted-copy";
    empty.textContent = "No corpus source was needed or matched for this decision.";
    els.sourceList.appendChild(empty);
    return;
  }
  sources.forEach((source) => {
    const item = document.createElement("div");
    item.className = "source-item";
    const label = source.title || source.doc_id;
    const score = Number.isFinite(Number(source.score)) ? `Score ${Number(source.score).toFixed(3)}` : "Matched";
    item.innerHTML = `
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(score)}${source.product_area ? ` | ${escapeHtml(source.product_area)}` : ""}</span>
      ${source.url ? `<a href="${escapeAttribute(source.url)}" target="_blank" rel="noreferrer">Open source</a>` : ""}
    `;
    els.sourceList.appendChild(item);
  });
}

function renderDecisionTimeline(record) {
  els.decisionTimeline.textContent = "";
  const steps = [
    ["Domain", record.meta.domain],
    ["Risk", `${record.meta.risk_level} / ${record.meta.urgency_level}`],
    ["Coverage", record.meta.corpus_coverage],
    ["Decision", summarizeDecision(record.meta.decision)],
    ["Review", record.meta.review_priority],
  ];
  steps.forEach(([label, value], index) => {
    const item = document.createElement("div");
    item.className = "timeline-step";
    item.innerHTML = `
      <span>${index + 1}</span>
      <div>
        <strong>${escapeHtml(label)}</strong>
        <em>${escapeHtml(value)}</em>
      </div>
    `;
    els.decisionTimeline.appendChild(item);
  });
}

function renderCharts() {
  const domainCounts = countBy(state.records, (record) => record.meta.domain);
  const maxDomain = Math.max(...Object.values(domainCounts), 1);
  els.domainBars.textContent = "";
  Object.entries(domainCounts)
    .sort((a, b) => b[1] - a[1])
    .forEach(([domain, count]) => {
      const row = document.createElement("div");
      row.className = "bar-row";
      row.innerHTML = `
        <span>${escapeHtml(domain)}</span>
        <span class="bar-track"><span class="bar-fill"></span></span>
        <strong>${count}</strong>
      `;
      els.domainBars.appendChild(row);
      requestAnimationFrame(() => {
        row.querySelector(".bar-fill").style.width = `${(count / maxDomain) * 100}%`;
      });
    });

  const areaCounts = countBy(state.records, "product_area");
  els.areaCloud.textContent = "";
  Object.entries(areaCounts)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .forEach(([area, count], index) => {
      const chip = document.createElement("span");
      chip.className = "area-chip";
      chip.style.animationDelay = `${Math.min(index * 18, 220)}ms`;
      chip.textContent = `${area} ${count}`;
      els.areaCloud.appendChild(chip);
    });

  renderReviewQueue();
  renderReasons();
  renderConfidenceBands();
  renderCoverageBars();
}

function renderReviewQueue() {
  els.reviewQueue.textContent = "";
  const escalated = state.records.filter((record) => record.status === "escalated");
  if (!escalated.length) {
    els.reviewQueue.innerHTML = '<p class="muted-copy">No escalations in the current dataset.</p>';
    return;
  }
  escalated.slice(0, 8).forEach((record) => {
    const item = document.createElement("button");
    item.className = "queue-item";
    item.type = "button";
    item.innerHTML = `
      <strong>#${record.id} ${escapeHtml(record.product_area)}</strong>
      <span>${escapeHtml(record.meta.review_priority)} | ${escapeHtml(record.meta.risk_level)}</span>
    `;
    item.addEventListener("click", () => {
      state.status = "all";
      document.querySelectorAll(".segment").forEach((segment) => segment.classList.toggle("active", segment.dataset.status === "all"));
      applyFilters();
      const index = state.filtered.findIndex((candidate) => candidate.id === record.id);
      if (index >= 0) {
        state.selected = index;
        renderTickets();
        renderDetail();
        document.querySelector(".content-grid").scrollIntoView({ behavior: "smooth" });
      }
    });
    els.reviewQueue.appendChild(item);
  });
}

function renderReasons() {
  els.reasonList.textContent = "";
  const reasons = countBy(
    state.records.filter((record) => record.status === "escalated"),
    (record) => summarizeDecision(record.meta.decision)
  );
  Object.entries(reasons)
    .sort((a, b) => b[1] - a[1])
    .forEach(([reason, count]) => {
      const item = document.createElement("div");
      item.className = "reason-item";
      item.innerHTML = `<span>${escapeHtml(reason)}</span><strong>${count}</strong>`;
      els.reasonList.appendChild(item);
    });
  if (!els.reasonList.children.length) {
    els.reasonList.innerHTML = '<p class="muted-copy">No escalation reasons yet.</p>';
  }
}

function renderConfidenceBands() {
  els.confidenceBands.textContent = "";
  const bands = [
    ["High", state.records.filter((record) => Number(record.meta.confidence) >= 0.85).length],
    ["Medium", state.records.filter((record) => Number(record.meta.confidence) >= 0.65 && Number(record.meta.confidence) < 0.85).length],
    ["Low", state.records.filter((record) => Number(record.meta.confidence) < 0.65).length],
  ];
  const max = Math.max(...bands.map(([, count]) => count), 1);
  bands.forEach(([label, count]) => {
    const item = document.createElement("div");
    item.className = "band-row";
    item.innerHTML = `
      <span>${escapeHtml(label)}</span>
      <strong>${count}</strong>
      <i style="width: ${(count / max) * 100}%"></i>
    `;
    els.confidenceBands.appendChild(item);
  });
}

function renderCoverageBars() {
  els.coverageBars.textContent = "";
  const coverageCounts = countBy(state.records, (record) => record.meta.corpus_coverage || "unknown");
  const max = Math.max(...Object.values(coverageCounts), 1);
  Object.entries(coverageCounts)
    .sort((a, b) => b[1] - a[1])
    .forEach(([coverage, count]) => {
      const row = document.createElement("div");
      row.className = "bar-row coverage-row";
      row.innerHTML = `
        <span>${escapeHtml(coverage)}</span>
        <span class="bar-track"><span class="bar-fill"></span></span>
        <strong>${count}</strong>
      `;
      els.coverageBars.appendChild(row);
      requestAnimationFrame(() => {
        row.querySelector(".bar-fill").style.width = `${(count / max) * 100}%`;
      });
    });
}

function summarizeDecision(decision) {
  const text = String(decision || "Escalated").toLowerCase();
  if (text.includes("stage 1")) return "Threat filter";
  if (text.includes("always-escalate")) return "Always-escalate rule";
  if (text.includes("risk") || text.includes("urgency")) return "High risk or urgency";
  if (text.includes("corpus")) return "Insufficient corpus";
  if (text.includes("edge-case")) return "Edge-case routing";
  return "Manual review";
}

async function checkApi() {
  if (window.location.protocol === "file:") {
    state.apiOnline = false;
    els.apiHealth.textContent = "API offline";
    els.apiHealth.className = "health-pill offline";
    return false;
  }
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    state.apiOnline = response.ok;
  } catch {
    state.apiOnline = false;
  }
  els.apiHealth.textContent = state.apiOnline ? "API connected" : "API offline";
  els.apiHealth.className = `health-pill ${state.apiOnline ? "online" : "offline"}`;
  return state.apiOnline;
}

async function loadData(preferApi = false) {
  await checkApi();
  await loadReadiness();
  try {
    if ((preferApi || state.apiOnline) && state.apiOnline) {
      const response = await fetch("/api/preview", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      state.records = payload.records.map(normalizeRecord);
      setMode("Live API preview");
    } else if (window.location.protocol !== "file:") {
      const response = await fetch(`${DATA_URL}?t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.records = parseJsonl(await response.text());
      setMode("JSONL preview file");
    } else if (Array.isArray(window.PREVIEW_DATA)) {
      state.records = window.PREVIEW_DATA.map(normalizeRecord);
      setMode("Embedded preview mode");
    } else {
      throw new Error("No preview data available");
    }
    state.selected = 0;
    renderAll();
  } catch (error) {
    if (Array.isArray(window.PREVIEW_DATA)) {
      state.records = window.PREVIEW_DATA.map(normalizeRecord);
      setMode("Embedded preview mode");
      renderAll();
      return;
    }
    state.records = [];
    state.filtered = [];
    renderAll();
    setError(`Could not load preview data. ${error.message || error}`);
  }
}

function renderAll() {
  populateDomainFilter();
  renderMetrics();
  applyFilters();
  renderCharts();
  renderReadiness();
}

function setError(message) {
  els.coverageBadge.textContent = "Preview not loaded";
  els.coverageBadge.classList.add("load-error");
  els.ticketList.innerHTML = `
    <div class="empty-state">
      <p>${escapeHtml(message)}</p>
      <p>Run: python -m support_triage.webapp --port 8080</p>
    </div>
  `;
  els.visibleCount.textContent = "0 shown";
}

async function handleCsvUpload(file) {
  if (!file) return;
  const csvText = await file.text();
  if (!state.apiOnline) await checkApi();
  if (!state.apiOnline) {
    alert("CSV upload needs the local API. Run: python -m support_triage.webapp --port 8080, then open http://127.0.0.1:8080/ui/");
    return;
  }
  const response = await fetch("/api/triage", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ csv: csvText }),
  });
  const payload = await response.json();
  if (!response.ok) {
    alert(payload.error || "Upload failed");
    return;
  }
  state.records = payload.records.map(normalizeRecord);
  state.selected = 0;
  setMode(`Uploaded CSV: ${file.name}`);
  renderAll();
}

async function runLabTriage() {
  const issue = els.labIssue.value.trim();
  if (!issue) {
    els.labStatus.textContent = "Empty";
    els.labResult.innerHTML = '<p class="muted-copy">Add an issue before running triage.</p>';
    return;
  }
  if (!state.apiOnline) await checkApi();
  if (!state.apiOnline) {
    els.labStatus.textContent = "API offline";
    els.labResult.innerHTML = '<p class="muted-copy">Local API is offline.</p>';
    return;
  }
  els.labStatus.textContent = "Running";
  els.runLabButton.disabled = true;
  try {
    const response = await fetch("/api/triage", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tickets: [
          {
            issue,
            subject: els.labSubject.value.trim(),
            company: els.labCompany.value,
          },
        ],
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Triage failed");
    const record = normalizeRecord(payload.records[0], 0);
    els.labStatus.textContent = "Complete";
    renderLabResult(record);
  } catch (error) {
    els.labStatus.textContent = "Failed";
    els.labResult.innerHTML = `<p class="muted-copy">${escapeHtml(error.message || error)}</p>`;
  } finally {
    els.runLabButton.disabled = false;
  }
}

function renderLabResult(record) {
  els.labResult.innerHTML = `
    <div class="lab-result-head">
      <span class="status-pill ${escapeAttribute(record.status)}">${escapeHtml(record.status)}</span>
      <strong>${escapeHtml(record.product_area)}</strong>
      <em>${escapeHtml(record.meta.confidence_label)} ${Math.round(record.meta.confidence * 100)}%</em>
    </div>
    <p>${escapeHtml(record.response)}</p>
    <pre>${escapeHtml(JSON.stringify(strictResult(record), null, 2))}</pre>
  `;
}

function strictResult(record) {
  return {
    status: record.status,
    product_area: record.product_area,
    response: record.draft_response || record.response,
    justification: record.justification,
    request_type: record.request_type,
  };
}

function exportJsonl() {
  const content = state.records.map((record) => JSON.stringify(strictResult(record))).join("\n") + "\n";
  download("triage-results.jsonl", content, "application/x-ndjson");
}

function exportCsv() {
  const rows = [
    ["issue", "subject", "company", "status", "product_area", "request_type", "confidence", "review_priority", "response", "justification"],
    ...state.records.map((record) => [
      record.ticket.issue || "",
      record.ticket.subject || "",
      record.ticket.company || "",
      record.status,
      record.product_area,
      record.request_type,
      record.meta.confidence,
      record.meta.review_priority,
      record.draft_response || record.response,
      record.justification,
    ]),
  ];
  const content = rows.map((row) => row.map(csvCell).join(",")).join("\n") + "\n";
  download("triage-results.csv", content, "text/csv");
}

function csvCell(value) {
  const text = String(value ?? "");
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

function download(filename, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/`/g, "&#096;");
}

document.querySelectorAll(".segment").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".segment").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    state.status = button.dataset.status;
    state.selected = 0;
    applyFilters();
  });
});

document.querySelectorAll(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
    button.classList.add("active");
    const view = button.dataset.view;
    if (view === "overview") document.querySelector(".stage-panel").scrollIntoView({ behavior: "smooth" });
    if (view === "tickets") document.querySelector(".content-grid").scrollIntoView({ behavior: "smooth" });
    if (view === "json") document.querySelector(".json-box").scrollIntoView({ behavior: "smooth", block: "center" });
  });
});

els.searchInput.addEventListener("input", (event) => {
  state.query = event.target.value;
  state.selected = 0;
  applyFilters();
});

els.domainFilter.addEventListener("change", (event) => {
  state.domain = event.target.value;
  state.selected = 0;
  applyFilters();
});

els.priorityFilter.addEventListener("change", (event) => {
  state.priority = event.target.value;
  state.selected = 0;
  applyFilters();
});

els.sortSelect.addEventListener("change", (event) => {
  state.sort = event.target.value;
  state.selected = 0;
  applyFilters();
});

els.refreshButton.addEventListener("click", () => loadData(false));
els.loadApiButton.addEventListener("click", () => loadData(true));
els.uploadButton.addEventListener("click", () => els.csvInput.click());
els.csvInput.addEventListener("change", (event) => handleCsvUpload(event.target.files[0]));
els.exportCsvButton.addEventListener("click", exportCsv);
els.exportJsonButton.addEventListener("click", exportJsonl);
els.escalatedOnlyButton.addEventListener("click", () => {
  state.status = "escalated";
  document.querySelectorAll(".segment").forEach((segment) => segment.classList.toggle("active", segment.dataset.status === "escalated"));
  state.selected = 0;
  applyFilters();
  document.querySelector(".content-grid").scrollIntoView({ behavior: "smooth" });
});

els.runLabButton.addEventListener("click", runLabTriage);

els.saveDraftButton.addEventListener("click", () => {
  const record = state.filtered[state.selected];
  if (!record) return;
  record.draft_response = els.draftEditor.value;
  renderTickets();
  renderDetail();
});

els.resetDraftButton.addEventListener("click", () => {
  const record = state.filtered[state.selected];
  if (!record) return;
  record.draft_response = record.response;
  renderDetail();
});

loadData(false);
