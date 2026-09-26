/**
 * LegalLens — Evidence-First Legal Document Navigator
 * Frontend Application Logic
 *
 * Architecture:
 * - State management via AppState object
 * - View rendering via dedicated render functions
 * - API communication via fetch with error handling
 * - Accessibility: keyboard navigation, ARIA, screen reader announcements
 */

"use strict";

/* ── State ──────────────────────────────────────────────────────────────────── */

const AppState = {
  currentView: "home",          // home | analyze | compare | results | compare-results
  selectedConcerns: [],
  customConcern: "",
  language: "en",
  documentId: null,
  documentName: null,
  analysis: null,
  comparison: null,
  qaMessages: [],
  isLoading: false,
  loadingStage: "Ready",
  fileA: null,
  fileB: null,
};

function formatUserError(rawMsg) {
  if (!rawMsg) return "We couldn't reach the analysis service.";
  const str = String(rawMsg).toLowerCase();
  if (str.includes("leaked") || str.includes("not configured") || str.includes("unauthorized") || str.includes("credentials missing") || str.includes("clienterror")) {
    return "AI service is not configured yet. Check server diagnostics.";
  }
  if (str.includes("quota") || str.includes("429") || str.includes("exhausted")) {
    return "Google AI quota is temporarily unavailable. Please try again shortly.";
  }
  if (str.includes("index") || str.includes("corrupt") || str.includes("could not be indexed")) {
    return "Your document could not be indexed. Please try again.";
  }
  if (str.includes("reach") || str.includes("network") || str.includes("failed to fetch") || str.includes("502")) {
    return "We couldn't reach the analysis service.";
  }
  if (str.includes("high demand") || str.includes("503") || str.includes("overloaded")) {
    return "Google AI service is currently experiencing high demand. Please try again shortly.";
  }
  return rawMsg;
}

const CONCERN_CHIPS = {
  employment: [
    { id: "salary_compensation", label: "💰 Salary / Compensation" },
    { id: "notice_period", label: "📅 Notice Period" },
    { id: "termination", label: "🚫 Termination" },
    { id: "probation", label: "⏳ Probation" },
    { id: "non_compete", label: "🔒 Non-Compete" },
    { id: "confidentiality", label: "🤫 Confidentiality" },
    { id: "intellectual_property", label: "💡 Intellectual Property" },
    { id: "working_hours", label: "⏰ Working Hours" },
    { id: "leave", label: "🌴 Leave" },
    { id: "bond_repayment", label: "⚠️ Bond / Repayment" },
    { id: "stock_options", label: "📈 Stock / Options" },
  ],
  general: [
    { id: "money_payment", label: "💵 Money / Payment" },
    { id: "deadlines", label: "⏰ Deadlines" },
    { id: "obligations", label: "📋 Obligations" },
    { id: "cancellation", label: "❌ Cancellation" },
    { id: "penalties", label: "⚖️ Penalties" },
    { id: "renewal", label: "🔄 Renewal" },
    { id: "privacy", label: "🔐 Privacy" },
    { id: "liability", label: "📌 Liability" },
    { id: "dispute_resolution", label: "🏛️ Dispute Resolution" },
    { id: "unusual_restrictions", label: "🚩 Unusual Restrictions" },
  ],
};

/* ── Utilities ──────────────────────────────────────────────────────────────── */

function $(selector) { return document.querySelector(selector); }
function $$(selector) { return document.querySelectorAll(selector); }

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function showToast(message, type = "error") {
  const container = $("#toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.setAttribute("role", "alert");
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 5000);
}

function announce(message) {
  const el = $("#sr-announcer");
  if (el) { el.textContent = message; }
}

function getBadgeClass(status) {
  const map = {
    SUPPORTED: "badge-supported",
    PARTIALLY_SUPPORTED: "badge-partial",
    NOT_FOUND: "badge-not-found",
    AMBIGUOUS: "badge-ambiguous",
  };
  return map[status] || "badge-ambiguous";
}

function getBadgeLabel(status) {
  const map = {
    SUPPORTED: "Supported",
    PARTIALLY_SUPPORTED: "Partially Supported",
    NOT_FOUND: "Not Found",
    AMBIGUOUS: "Ambiguous",
  };
  return map[status] || status;
}

function getChangeClass(type) {
  const map = {
    ADDED: "change-added",
    REMOVED: "change-removed",
    CHANGED: "change-changed",
    UNCHANGED: "change-unchanged",
    CANNOT_DETERMINE: "change-unchanged",
  };
  return map[type] || "";
}

/* ── Evidence Rendering ─────────────────────────────────────────────────────── */

function renderEvidence(evidence) {
  if (!evidence || evidence.length === 0) return "";
  return evidence.map((e, i) => {
    const id = `evidence-${Date.now()}-${i}`;
    return `
      <button class="evidence-btn" onclick="toggleEvidence('${id}')" aria-expanded="false" aria-controls="${id}">
        View evidence
      </button>
      <div id="${id}" class="evidence-drawer hidden" role="region" aria-label="Evidence details">
        <div class="evidence-label">Source</div>
        <div class="evidence-meta">
          <span>📄 ${escapeHtml(e.document_name)}</span>
          ${e.page_number ? `<span>📃 Page ${e.page_number}</span>` : '<span>📃 Page unavailable</span>'}
          ${e.section ? `<span>§ ${escapeHtml(e.section)}</span>` : ''}
        </div>
        <div class="evidence-excerpt">"${escapeHtml(e.excerpt)}"</div>
        <span class="badge ${getBadgeClass(e.support_status)}">${getBadgeLabel(e.support_status)}</span>
      </div>
    `;
  }).join("");
}

function toggleEvidence(id) {
  const el = document.getElementById(id);
  const btn = el.previousElementSibling;
  const isHidden = el.classList.contains("hidden");
  el.classList.toggle("hidden");
  btn.setAttribute("aria-expanded", isHidden ? "true" : "false");
}

/* ── Navigation ─────────────────────────────────────────────────────────────── */

function navigateTo(view) {
  AppState.currentView = view;
  renderApp();
  announce(`Navigated to ${view} view`);
}

/* ── Render App ─────────────────────────────────────────────────────────────── */

function renderApp() {
  const main = $("#main-content");
  // Update nav with aria-current for accessibility
  $$("nav button").forEach(btn => {
    const isActive = btn.dataset.view === AppState.currentView;
    btn.classList.toggle("active", isActive);
    if (isActive) {
      btn.setAttribute("aria-current", "page");
    } else {
      btn.removeAttribute("aria-current");
    }
  });

  switch (AppState.currentView) {
    case "home": main.innerHTML = renderHome(); break;
    case "analyze": main.innerHTML = renderAnalyze(); break;
    case "compare": main.innerHTML = renderCompare(); break;
    case "results": main.innerHTML = renderResults(); break;
    case "compare-results": main.innerHTML = renderCompareResults(); break;
    default: main.innerHTML = renderHome();
  }
}

/* ── Home View ──────────────────────────────────────────────────────────────── */

function renderHome() {
  return `
    <div class="hero">
      <h1>LegalLens</h1>
      <p class="subtitle">
        Upload a legal document and understand what matters, with every important answer linked back to its evidence.
      </p>
      <div class="hero-ctas">
        <button class="btn btn-primary" onclick="navigateTo('analyze')" id="cta-analyze">
          📄 Analyze a Document
        </button>
        <button class="btn btn-secondary" onclick="navigateTo('compare')" id="cta-compare">
          🔍 Compare Documents
        </button>
      </div>
    </div>

    <div class="trust-grid">
      <div class="trust-card">
        <div class="trust-icon">📎</div>
        <h3>Evidence Attached</h3>
        <p>Every finding links to the exact excerpt and page in your document.</p>
      </div>
      <div class="trust-card">
        <div class="trust-icon">❓</div>
        <h3>Missing Info Acknowledged</h3>
        <p>We tell you what's NOT in the document, so you know what to ask.</p>
      </div>
      <div class="trust-card">
        <div class="trust-icon">💬</div>
        <h3>Plain-Language Explanations</h3>
        <p>Complex legal terms explained in simple, clear language.</p>
      </div>
      <div class="trust-card">
        <div class="trust-icon">ℹ️</div>
        <h3>Information, Not Legal Advice</h3>
        <p>Helps you understand and prepare — not replace a legal professional.</p>
      </div>
    </div>

    <div class="privacy-notice">
      <strong>Privacy:</strong> Uploaded documents are processed using configured Google AI services for analysis.
      Do not upload highly sensitive documents unless you are comfortable with this processing.
      This is an informational assistance tool.
    </div>
  `;
}

/* ── Analyze View ───────────────────────────────────────────────────────────── */

function renderAnalyze() {
  const chipHtml = (chips) => chips.map(c => `
    <button type="button" class="chip ${AppState.selectedConcerns.includes(c.id) ? 'selected' : ''}"
            onclick="toggleConcern('${c.id}')"
            aria-pressed="${AppState.selectedConcerns.includes(c.id)}"
            id="chip-${c.id}">
      ${c.label}
    </button>
  `).join("");

  return `
    <div style="max-width: 700px; margin: 0 auto;">
      <h1 style="font-size: 1.5rem; font-weight: 700; margin-bottom: var(--space-lg);">Analyze a Document</h1>

      <div class="section">
        <label for="file-upload-input" style="font-weight: 600; margin-bottom: var(--space-sm); display: block;">
          Step 1: Upload your PDF
        </label>
        <div class="upload-area ${AppState.fileA ? 'has-file' : ''}"
             id="upload-area-analyze"
             ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)"
             ondrop="handleDrop(event, 'A')" onclick="document.getElementById('file-upload-input').click()"
             role="button" tabindex="0" aria-label="Upload PDF document"
             onkeydown="handleUploadKeydown(event, 'file-upload-input')">
          <div class="upload-icon">📄</div>
          <p>${AppState.fileA ? '' : 'Drop your PDF here or click to upload'}</p>
          ${AppState.fileA ? `<div class="upload-filename">✅ ${escapeHtml(AppState.fileA.name)}</div>` : ''}
          <p style="font-size: 0.8rem; color: var(--color-text-muted); margin-top: var(--space-sm);">Maximum 10 MB · PDF only</p>
        </div>
        <input type="file" id="file-upload-input" accept=".pdf,application/pdf" class="sr-only"
               onchange="handleFileSelect(event, 'A')" aria-label="Select PDF file">
      </div>

      <div class="section">
        <h2 style="font-size: 1.1rem; font-weight: 600; margin-bottom: var(--space-sm);">
          Step 2: What matters most to you?
        </h2>
        <p style="font-size: 0.85rem; color: var(--color-text-secondary); margin-bottom: var(--space-md);">
          Select your concerns to get personalized findings.
        </p>

        <h3 style="font-size: 0.85rem; font-weight: 600; color: var(--color-text-muted); margin-bottom: var(--space-sm);">Employment</h3>
        <div class="chips">${chipHtml(CONCERN_CHIPS.employment)}</div>

        <h3 style="font-size: 0.85rem; font-weight: 600; color: var(--color-text-muted); margin: var(--space-md) 0 var(--space-sm);">General</h3>
        <div class="chips">${chipHtml(CONCERN_CHIPS.general)}</div>

        <div style="margin-top: var(--space-md);">
          <label for="custom-concern">Anything specific you're worried about?</label>
          <input type="text" id="custom-concern" placeholder="e.g., What happens to my IP if I leave?"
                 value="${escapeHtml(AppState.customConcern)}"
                 onchange="AppState.customConcern = this.value" maxlength="500">
        </div>
      </div>

      <div class="section">
        <div class="lang-selector" role="group" aria-labelledby="language-label">
          <span id="language-label" style="display: block; font-weight: 500; margin-bottom: var(--space-xs);">Explanation Language</span>
          <button type="button" class="lang-btn ${AppState.language === 'en' ? 'active' : ''}"
                  aria-pressed="${AppState.language === 'en' ? 'true' : 'false'}"
                  onclick="setLanguage('en')">English</button>
          <button type="button" class="lang-btn ${AppState.language === 'ta' ? 'active' : ''}"
                  aria-pressed="${AppState.language === 'ta' ? 'true' : 'false'}"
                  lang="ta"
                  onclick="setLanguage('ta')">தமிழ்</button>
          <button type="button" class="lang-btn ${AppState.language === 'hi' ? 'active' : ''}"
                  aria-pressed="${AppState.language === 'hi' ? 'true' : 'false'}"
                  lang="hi"
                  onclick="setLanguage('hi')">हिन्दी</button>
        </div>
      </div>

      <button class="btn btn-primary" onclick="submitAnalysis()" id="btn-analyze"
              ${!AppState.fileA || AppState.isLoading ? 'disabled' : ''}
              aria-busy="${AppState.isLoading}">
        ${AppState.isLoading ? `<span class="spinner" role="status" aria-label="Loading"></span> <span id="loading-stage-label" aria-live="polite">${escapeHtml(AppState.loadingStage || 'Analyzing...')}</span>` : '🔍 Analyze Document'}
      </button>
    </div>
  `;
}

/* ── Compare View ───────────────────────────────────────────────────────────── */

function renderCompare() {
  const chipHtml = (chips) => chips.map(c => `
    <button type="button" class="chip ${AppState.selectedConcerns.includes(c.id) ? 'selected' : ''}"
            onclick="toggleConcern('${c.id}')"
            aria-pressed="${AppState.selectedConcerns.includes(c.id)}"
            id="chip-cmp-${c.id}">
      ${c.label}
    </button>
  `).join("");

  return `
    <div style="max-width: 700px; margin: 0 auto;">
      <h1 style="font-size: 1.5rem; font-weight: 700; margin-bottom: var(--space-lg);">Compare Documents</h1>

      <div class="doc-columns" style="margin-bottom: var(--space-lg);">
        <div>
          <label for="file-a-input" style="font-weight: 600;">Document A (Original)</label>
          <div class="upload-area ${AppState.fileA ? 'has-file' : ''}"
               onclick="document.getElementById('file-a-input').click()"
               role="button" tabindex="0" aria-label="Upload Document A"
               onkeydown="handleUploadKeydown(event, 'file-a-input')">
            <div class="upload-icon">📄</div>
            ${AppState.fileA ? `<div class="upload-filename">✅ ${escapeHtml(AppState.fileA.name)}</div>` : '<p>Upload PDF A</p>'}
          </div>
          <input type="file" id="file-a-input" accept=".pdf" class="sr-only"
                 onchange="handleFileSelect(event, 'A')">
        </div>
        <div>
          <label for="file-b-input" style="font-weight: 600;">Document B (Revised)</label>
          <div class="upload-area ${AppState.fileB ? 'has-file' : ''}"
               onclick="document.getElementById('file-b-input').click()"
               role="button" tabindex="0" aria-label="Upload Document B"
               onkeydown="handleUploadKeydown(event, 'file-b-input')">
            <div class="upload-icon">📄</div>
            ${AppState.fileB ? `<div class="upload-filename">✅ ${escapeHtml(AppState.fileB.name)}</div>` : '<p>Upload PDF B</p>'}
          </div>
          <input type="file" id="file-b-input" accept=".pdf" class="sr-only"
                 onchange="handleFileSelect(event, 'B')">
        </div>
      </div>

      <div class="section">
        <h2 style="font-size: 1rem; font-weight: 600; margin-bottom: var(--space-sm);">Focus areas</h2>
        <div class="chips">${chipHtml([...CONCERN_CHIPS.employment, ...CONCERN_CHIPS.general])}</div>
      </div>

      <button class="btn btn-primary" onclick="submitComparison()" id="btn-compare"
              ${!AppState.fileA || !AppState.fileB || AppState.isLoading ? 'disabled' : ''}
              aria-busy="${AppState.isLoading}">
        ${AppState.isLoading ? '<span class="spinner" role="status" aria-label="Comparing"></span> Comparing...' : '🔍 Compare Documents'}
      </button>
    </div>
  `;
}

/* ── Results View ───────────────────────────────────────────────────────────── */

function renderResults() {
  const a = AppState.analysis;
  if (!a) return '<p>No analysis available.</p>';

  return `
    <div class="flex justify-between items-center" style="margin-bottom: var(--space-lg); flex-wrap: wrap; gap: var(--space-md);">
      <div>
        <h1 style="font-size: 1.5rem; font-weight: 700;">📄 ${escapeHtml(AppState.documentName || 'Document')}</h1>
        <p style="font-size: 0.9rem; color: var(--color-text-secondary);">${escapeHtml(a.document_type)}</p>
      </div>
      <div style="display: flex; gap: var(--space-sm); flex-wrap: wrap;">
        <button class="btn btn-secondary btn-sm" onclick="navigateTo('analyze')">← New Analysis</button>
        <button class="btn btn-secondary btn-sm" onclick="prepareQuestions()">📝 Prepare Questions</button>
        <button class="btn btn-secondary btn-sm" onclick="toggleResearch()">🌐 External Legal Context</button>
        <button class="btn btn-secondary btn-sm" style="color: #ef4444; border-color: #ef4444;" onclick="deleteCurrentDocument()">🗑️ Delete Document</button>
      </div>
    </div>

    <div class="tabs" role="tablist" aria-label="Analysis sections">
      <button class="tab active" data-tab="overview" onclick="switchTab('overview')" role="tab" aria-selected="true">Overview</button>
      <button class="tab" data-tab="obligations" onclick="switchTab('obligations')" role="tab">Obligations</button>
      <button class="tab" data-tab="dates-money" onclick="switchTab('dates-money')" role="tab">Dates & Money</button>
      <button class="tab" data-tab="ask" onclick="switchTab('ask')" role="tab">Ask</button>
      <button class="tab" data-tab="missing" onclick="switchTab('missing')" role="tab">⚠️ Clarify</button>
    </div>

    <div id="tab-overview" class="tab-panel active" role="tabpanel">
      ${renderOverviewTab(a)}
    </div>
    <div id="tab-obligations" class="tab-panel" role="tabpanel">
      ${renderObligationsTab(a)}
    </div>
    <div id="tab-dates-money" class="tab-panel" role="tabpanel">
      ${renderDatesMoneyTab(a)}
    </div>
    <div id="tab-ask" class="tab-panel" role="tabpanel">
      ${renderAskTab()}
    </div>
    <div id="tab-missing" class="tab-panel" role="tabpanel">
      ${renderMissingTab(a)}
    </div>

    <div id="research-panel" class="hidden" style="margin-top: var(--space-xl);">
      ${renderResearchPanel()}
    </div>

    <div id="prep-modal" class="hidden"></div>
  `;
}

function renderOverviewTab(a) {
  return `
    <div class="card mb-md">
      <p style="font-size: 0.95rem; line-height: 1.7;">${escapeHtml(a.summary)}</p>
    </div>

    ${a.key_facts && a.key_facts.length > 0 ? `
      <div class="section">
        <h2 class="section-title">📋 Key Facts</h2>
        <div class="facts-grid">
          ${a.key_facts.map(f => `
            <div class="fact-card">
              <div class="fact-label">${escapeHtml(f.label)}</div>
              <div class="fact-value">${escapeHtml(f.value)}</div>
              ${renderEvidence(f.evidence)}
            </div>
          `).join("")}
        </div>
      </div>
    ` : ''}

    ${a.findings && a.findings.length > 0 ? `
      <div class="section">
        <h2 class="section-title">🔎 What Matters to You</h2>
        ${a.findings.map(f => `
          <div class="card mb-md">
            <div class="card-header">
              <h3>${escapeHtml(f.title)}</h3>
              <span class="badge ${getBadgeClass(f.support_status)}">${getBadgeLabel(f.support_status)}</span>
            </div>
            <p style="font-size: 0.9rem; margin-bottom: var(--space-sm);">${escapeHtml(f.plain_language)}</p>
            <p style="font-size: 0.85rem; color: var(--color-text-secondary); font-style: italic;">
              ${escapeHtml(f.why_it_matters)}
            </p>
            ${renderEvidence(f.evidence)}
          </div>
        `).join("")}
      </div>
    ` : ''}
  `;
}

function renderObligationsTab(a) {
  if (!a.obligations || a.obligations.length === 0) {
    return '<div class="card"><p>No specific obligations were identified in this document.</p></div>';
  }
  return `
    <div class="table-container">
      <table>
        <thead>
          <tr>
            <th>Who</th><th>Must Do What</th><th>When</th><th>Consequence</th><th>Evidence</th>
          </tr>
        </thead>
        <tbody>
          ${a.obligations.map(o => `
            <tr>
              <td>${escapeHtml(o.actor)}</td>
              <td>${escapeHtml(o.action)}</td>
              <td>${o.deadline ? escapeHtml(o.deadline) : '—'}</td>
              <td>${o.consequence ? escapeHtml(o.consequence) : '—'}</td>
              <td>${renderEvidence(o.evidence)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
    </div>
  `;
}

function renderDatesMoneyTab(a) {
  let html = '';

  if (a.dates && a.dates.length > 0) {
    html += `
      <div class="section">
        <h2 class="section-title">📅 Dates & Deadlines</h2>
        ${a.dates.map(d => `
          <div class="card mb-md" style="padding: var(--space-md);">
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <span style="font-weight: 600;">${escapeHtml(d.description)}</span>
              <span style="color: var(--color-primary); font-weight: 700;">${escapeHtml(d.date_text)}</span>
            </div>
            ${renderEvidence(d.evidence)}
          </div>
        `).join("")}
      </div>
    `;
  }

  if (a.monetary_terms && a.monetary_terms.length > 0) {
    html += `
      <div class="section">
        <h2 class="section-title">💰 Monetary Terms</h2>
        ${a.monetary_terms.map(m => `
          <div class="card mb-md" style="padding: var(--space-md);">
            <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: var(--space-sm);">
              <span style="font-weight: 600;">${escapeHtml(m.description)}</span>
              <span style="color: var(--color-supported); font-weight: 700; font-size: 1.1rem;">${escapeHtml(m.amount)}</span>
            </div>
            ${m.details ? `<p style="font-size: 0.85rem; color: var(--color-text-secondary); margin-top: var(--space-xs);">${escapeHtml(m.details)}</p>` : ''}
            ${renderEvidence(m.evidence)}
          </div>
        `).join("")}
      </div>
    `;
  }

  if (!html) html = '<div class="card"><p>No explicit dates or monetary terms were identified.</p></div>';
  return html;
}

function renderAskTab() {
  return `
    <div class="qa-container">
      <h2 class="section-title">💬 Ask About Your Document</h2>
      <p style="font-size: 0.85rem; color: var(--color-text-secondary); margin-bottom: var(--space-md);">
        Ask any question. Answers will be based only on your document — with evidence attached.
        If the answer can't be found, we'll tell you.
      </p>
      <div class="qa-input-group">
        <input type="text" class="qa-input" id="qa-question-input"
               placeholder="e.g., What is my notice period?" maxlength="1000"
               onkeydown="if(event.key==='Enter')askQuestion()"
               aria-label="Ask a question about your document">
        <button class="btn btn-primary" onclick="askQuestion()" id="btn-ask"
                ${AppState.isLoading ? 'disabled' : ''}>
          Ask
        </button>
      </div>
      <div class="qa-messages" id="qa-messages" aria-live="polite">
        ${AppState.qaMessages.map(renderQAMessage).join("")}
      </div>
    </div>
  `;
}

function renderQAMessage(msg) {
  if (msg.role === "user") {
    return `<div class="qa-message qa-message-user">${escapeHtml(msg.text)}</div>`;
  }
  const a = msg.data;
  return `
    <div class="qa-message qa-message-assistant">
      <div style="display: flex; align-items: center; gap: var(--space-sm); margin-bottom: var(--space-sm);">
        <span class="badge ${getBadgeClass(a.support_status)}">${getBadgeLabel(a.support_status)}</span>
      </div>
      <p style="font-size: 0.9rem; line-height: 1.7;">${escapeHtml(a.answer)}</p>
      ${renderEvidence(a.evidence)}
      ${a.suggested_questions && a.suggested_questions.length > 0 ? `
        <div style="margin-top: var(--space-md); font-size: 0.85rem; color: var(--color-text-secondary);">
          <strong>You might also ask:</strong>
          <ul style="margin-top: var(--space-xs); padding-left: var(--space-lg);">
            ${a.suggested_questions.map(q => `<li>${escapeHtml(q)}</li>`).join("")}
          </ul>
        </div>
      ` : ''}
    </div>
  `;
}

function renderMissingTab(a) {
  if (!a.missing_information || a.missing_information.length === 0) {
    return '<div class="card"><p>No significant missing information was identified.</p></div>';
  }
  return `
    <div class="missing-info">
      <h3>⚠️ Information Not Found in This Document</h3>
      <p style="font-size: 0.85rem; color: #78350f; margin-bottom: var(--space-md);">
        These topics are commonly important but are absent or unclear in your document.
        Consider clarifying them with the other party or a legal professional.
      </p>
      ${a.missing_information.map(m => `
        <div class="missing-item">
          <span class="missing-item-icon">❓</span>
          <div class="missing-item-content">
            <h4>${escapeHtml(m.topic)}</h4>
            <p>${escapeHtml(m.explanation)}</p>
            <p class="missing-item-question">💡 Ask: "${escapeHtml(m.suggested_question)}"</p>
          </div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderResearchPanel() {
  return `
    <div class="card">
      <div class="card-header">
        <h2>🌐 Research General Legal Context</h2>
        <button class="btn btn-sm btn-secondary" onclick="toggleResearch()">Close</button>
      </div>
      <div class="privacy-notice" style="margin-bottom: var(--space-md);">
        <strong>⚠️ External Information:</strong> Results below come from web sources, NOT from your uploaded document.
        This is general informational context — not professional legal advice.
      </div>
      <div class="qa-input-group">
        <input type="text" id="research-query" class="qa-input"
               placeholder="e.g., What are typical notice period rules in India?"
               maxlength="500" aria-label="Research topic"
               onkeydown="if(event.key==='Enter')submitResearch()">
        <button class="btn btn-primary" onclick="submitResearch()" id="btn-research">Research</button>
      </div>
      <div id="research-results" aria-live="polite"></div>
    </div>
  `;
}

/* ── Compare Results ────────────────────────────────────────────────────────── */

function renderCompareResults() {
  const c = AppState.comparison;
  if (!c) return '<p>No comparison available.</p>';

  return `
    <div class="flex justify-between items-center" style="margin-bottom: var(--space-lg); flex-wrap: wrap; gap: var(--space-md);">
      <h1 style="font-size: 1.5rem; font-weight: 700;">📊 Document Comparison</h1>
      <button class="btn btn-secondary btn-sm" onclick="navigateTo('compare')">← New Comparison</button>
    </div>

    <div class="card mb-md">
      <p style="font-size: 0.95rem; line-height: 1.7;">${escapeHtml(c.summary)}</p>
    </div>

    ${c.items && c.items.length > 0 ? c.items.map(item => `
      <div class="comparison-item">
        <div class="comparison-header">
          <span class="change-badge ${getChangeClass(item.change_type)}">${item.change_type}</span>
          <strong>${escapeHtml(item.category)}</strong>
          <span class="badge ${getBadgeClass(item.support_status)}">${getBadgeLabel(item.support_status)}</span>
        </div>
        <div class="doc-columns">
          <div class="doc-column">
            <h4>Document A</h4>
            <p>${escapeHtml(item.document_a_text)}</p>
            ${renderEvidence(item.evidence_a)}
          </div>
          <div class="doc-column">
            <h4>Document B</h4>
            <p>${escapeHtml(item.document_b_text)}</p>
            ${renderEvidence(item.evidence_b)}
          </div>
        </div>
        <p style="margin-top: var(--space-md); font-size: 0.9rem;">${escapeHtml(item.explanation)}</p>
        <p style="font-size: 0.85rem; color: var(--color-text-secondary); font-style: italic;">
          ${escapeHtml(item.why_it_matters)}
        </p>
      </div>
    `).join("") : '<div class="card"><p>No differences detected.</p></div>'}

    ${c.missing_in_a && c.missing_in_a.length > 0 ? `
      <div class="card mb-md">
        <h3 style="font-size: 0.9rem; font-weight: 600; margin-bottom: var(--space-sm);">Missing in Document A</h3>
        <ul style="padding-left: var(--space-lg);">
          ${c.missing_in_a.map(m => `<li>${escapeHtml(m)}</li>`).join("")}
        </ul>
      </div>
    ` : ''}

    ${c.missing_in_b && c.missing_in_b.length > 0 ? `
      <div class="card mb-md">
        <h3 style="font-size: 0.9rem; font-weight: 600; margin-bottom: var(--space-sm);">Missing in Document B</h3>
        <ul style="padding-left: var(--space-lg);">
          ${c.missing_in_b.map(m => `<li>${escapeHtml(m)}</li>`).join("")}
        </ul>
      </div>
    ` : ''}
  `;
}

/* ── Tab Switching ──────────────────────────────────────────────────────────── */

function switchTab(tabName) {
  $$(".tab").forEach(t => {
    t.classList.toggle("active", t.dataset.tab === tabName);
    t.setAttribute("aria-selected", t.dataset.tab === tabName ? "true" : "false");
  });
  $$(".tab-panel").forEach(p => p.classList.toggle("active", p.id === `tab-${tabName}`));
  announce(`Switched to ${tabName} tab`);
}

/* ── Event Handlers ─────────────────────────────────────────────────────────── */

function toggleConcern(id) {
  const idx = AppState.selectedConcerns.indexOf(id);
  if (idx === -1) {
    AppState.selectedConcerns.push(id);
  } else {
    AppState.selectedConcerns.splice(idx, 1);
  }
  const isSelected = AppState.selectedConcerns.includes(id);
  // Re-render just the chip
  const chip = document.getElementById(`chip-${id}`);
  if (chip) {
    chip.classList.toggle("selected", isSelected);
    chip.setAttribute("aria-pressed", isSelected.toString());
  }
  const chipCmp = document.getElementById(`chip-cmp-${id}`);
  if (chipCmp) {
    chipCmp.classList.toggle("selected", isSelected);
    chipCmp.setAttribute("aria-pressed", isSelected.toString());
  }
}

function setLanguage(lang) {
  AppState.language = lang;
  const langNames = { en: "English", ta: "தமிழ்", hi: "हिन्दी" };
  $$(".lang-btn").forEach(btn => {
    const isActive = btn.textContent.trim() === langNames[lang];
    btn.classList.toggle("active", isActive);
    btn.setAttribute("aria-pressed", isActive ? "true" : "false");
  });
}

function handleUploadKeydown(event, inputId) {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    const input = document.getElementById(inputId);
    if (input) input.click();
  }
}

function handleFileSelect(event, slot) {
  const file = event.target.files[0];
  if (!file) return;
  if (file.size > 10 * 1024 * 1024) {
    showToast("File too large. Maximum size is 10 MB.");
    return;
  }
  if (!file.type.includes("pdf") && !file.name.toLowerCase().endsWith(".pdf")) {
    showToast("Only PDF files are accepted.");
    return;
  }
  if (slot === "A") AppState.fileA = file;
  else AppState.fileB = file;
  renderApp();
  announce(`${file.name} selected`);
}

function handleDragOver(event) {
  event.preventDefault();
  event.currentTarget.classList.add("dragover");
}

function handleDragLeave(event) {
  event.currentTarget.classList.remove("dragover");
}

function handleDrop(event, slot) {
  event.preventDefault();
  event.currentTarget.classList.remove("dragover");
  const file = event.dataTransfer.files[0];
  if (file) {
    if (slot === "A") AppState.fileA = file;
    else AppState.fileB = file;
    renderApp();
  }
}

function toggleResearch() {
  const panel = document.getElementById("research-panel");
  if (panel) panel.classList.toggle("hidden");
}

/* ── API Calls ──────────────────────────────────────────────────────────────── */

async function submitAnalysis() {
  if (!AppState.fileA || AppState.isLoading) return;

  AppState.isLoading = true;
  AppState.loadingStage = "Uploading securely...";
  renderApp();
  announce(AppState.loadingStage);

  const stages = [
    { delay: 1000, text: "Preparing document..." },
    { delay: 2500, text: "Indexing evidence..." },
    { delay: 4500, text: "Analyzing selected concerns..." },
    { delay: 7500, text: "Verifying citations..." },
  ];

  const timers = stages.map(s => setTimeout(() => {
    if (AppState.isLoading) {
      AppState.loadingStage = s.text;
      const el = document.getElementById("loading-stage-label");
      if (el) el.textContent = s.text;
      announce(s.text);
    }
  }, s.delay));

  const formData = new FormData();
  formData.append("file", AppState.fileA);
  formData.append("concerns", JSON.stringify(AppState.selectedConcerns));
  formData.append("custom_concern", AppState.customConcern);
  formData.append("language", AppState.language);

  try {
    const res = await fetch("/api/documents/analyze", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Analysis failed" }));
      throw new Error(err.detail || err.error || `Error ${res.status}`);
    }
    const data = await res.json();
    AppState.documentId = data.document_id;
    AppState.documentName = data.document_name;
    AppState.analysis = data.analysis;
    AppState.qaMessages = [];
    AppState.currentView = "results";
    announce("Analysis complete. Ready.");
  } catch (err) {
    showToast(formatUserError(err.message));
    announce("Analysis failed");
  } finally {
    timers.forEach(t => clearTimeout(t));
    AppState.isLoading = false;
    AppState.loadingStage = "Ready";
    renderApp();
  }
}

async function askQuestion() {
  const input = document.getElementById("qa-question-input");
  const question = input ? input.value.trim() : "";
  if (!question || !AppState.documentId || AppState.isLoading) return;

  AppState.qaMessages.push({ role: "user", text: question });
  AppState.isLoading = true;
  if (input) input.value = "";

  // Re-render Q&A messages
  const msgContainer = document.getElementById("qa-messages");
  if (msgContainer) msgContainer.innerHTML = AppState.qaMessages.map(renderQAMessage).join("") +
    '<div class="loading" role="status" aria-label="Processing question"><span class="spinner"></span> Finding evidence...</div>';

  announce("Processing question...");

  try {
    const res = await fetch("/api/documents/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question: question,
        document_id: AppState.documentId,
        language: AppState.language,
      }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Question failed" }));
      throw new Error(err.detail || err.error || `Error ${res.status}`);
    }
    const data = await res.json();
    AppState.qaMessages.push({ role: "assistant", data: data.answer });
    announce("Answer received");
  } catch (err) {
    const friendly = formatUserError(err.message);
    showToast(friendly);
    AppState.qaMessages.push({
      role: "assistant",
      data: { answer: friendly, support_status: "AMBIGUOUS", evidence: [] },
    });
  } finally {
    AppState.isLoading = false;
    const mc = document.getElementById("qa-messages");
    if (mc) mc.innerHTML = AppState.qaMessages.map(renderQAMessage).join("");
  }
}

async function deleteCurrentDocument() {
  if (!AppState.documentId) return;
  if (!confirm("Are you sure you want to permanently delete this document and all its indexed data across Google Cloud Storage, Firestore, and Gemini File Search?")) return;

  try {
    const res = await fetch(`/api/documents/${AppState.documentId}`, { method: "DELETE" });
    if (res.ok) {
      showToast("Document permanently deleted from all Google services and server storage.", "success");
      AppState.documentId = null;
      AppState.documentName = null;
      AppState.analysis = null;
      AppState.qaMessages = [];
      navigateTo("home");
    } else {
      showToast("Failed to delete document.");
    }
  } catch (err) {
    showToast("Error deleting document: " + err.message);
  }
}

async function submitComparison() {
  if (!AppState.fileA || !AppState.fileB || AppState.isLoading) return;

  AppState.isLoading = true;
  renderApp();
  announce("Comparing documents, please wait...");

  const formData = new FormData();
  formData.append("file_a", AppState.fileA);
  formData.append("file_b", AppState.fileB);
  formData.append("concerns", JSON.stringify(AppState.selectedConcerns));
  formData.append("custom_concern", AppState.customConcern);
  formData.append("language", AppState.language);

  try {
    const res = await fetch("/api/documents/compare", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Comparison failed" }));
      throw new Error(err.detail || err.error || `Error ${res.status}`);
    }
    const data = await res.json();
    AppState.comparison = data.comparison;
    AppState.currentView = "compare-results";
    announce("Comparison complete");
  } catch (err) {
    showToast(err.message);
    announce("Comparison failed");
  } finally {
    AppState.isLoading = false;
    renderApp();
  }
}

async function submitResearch() {
  const input = document.getElementById("research-query");
  const query = input ? input.value.trim() : "";
  if (!query) return;

  const resultsDiv = document.getElementById("research-results");
  if (resultsDiv) resultsDiv.innerHTML = '<div class="loading"><span class="spinner"></span> Researching...</div>';

  try {
    const res = await fetch("/api/legal-context", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, jurisdiction: "" }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Research failed" }));
      throw new Error(err.detail || err.error || `Error ${res.status}`);
    }
    const data = await res.json();
    const r = data.result;
    if (resultsDiv) {
      resultsDiv.innerHTML = `
        <div class="card mt-md">
          <div class="privacy-notice" style="margin-bottom: var(--space-md);">
            ⚠️ General informational context from web sources — not professional legal advice.
            This information does NOT come from your uploaded document.
          </div>
          <p style="font-size: 0.9rem; line-height: 1.7; white-space: pre-wrap;">${escapeHtml(r.context)}</p>
          ${r.citations && r.citations.length > 0 ? `
            <div style="margin-top: var(--space-md);">
              <strong style="font-size: 0.85rem;">Sources:</strong>
              <ul style="padding-left: var(--space-lg); margin-top: var(--space-xs);">
                ${r.citations.map(c => `
                  <li style="font-size: 0.85rem;">
                    <a href="${escapeHtml(c.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(c.title || c.url)}</a>
                  </li>
                `).join("")}
              </ul>
            </div>
          ` : ''}
        </div>
      `;
    }
  } catch (err) {
    if (resultsDiv) resultsDiv.innerHTML = `<div class="toast toast-error">${escapeHtml(err.message)}</div>`;
  }
}

async function prepareQuestions() {
  if (!AppState.documentId) return;
  announce("Preparing questions for professional consultation...");

  try {
    const formData = new FormData();
    formData.append("document_id", AppState.documentId);
    formData.append("language", AppState.language);

    const res = await fetch("/api/documents/prepare", { method: "POST", body: formData });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: "Preparation failed" }));
      throw new Error(err.detail || err.error);
    }
    const data = await res.json();
    showPrepModal(data.preparation);
  } catch (err) {
    showToast(err.message);
  }
}

function showPrepModal(prep) {
  const renderList = (items) => items && items.length > 0
    ? `<ul class="prep-list">${items.map(i => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`
    : '<p style="font-size: 0.85rem; color: var(--color-text-muted);">None identified.</p>';

  const modal = document.getElementById("prep-modal");
  if (!modal) return;

  modal.className = "modal-overlay";
  modal.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-label="Preparation Sheet">
      <button class="modal-close" onclick="closePrepModal()" aria-label="Close">&times;</button>
      <h2 style="font-size: 1.25rem; font-weight: 700; margin-bottom: var(--space-lg);">
        📝 Questions for Professional Consultation
      </h2>

      <div class="prep-section">
        <h3>✅ What I Understand</h3>
        ${renderList(prep.what_i_understand)}
      </div>

      <div class="prep-section">
        <h3>❓ What is Unclear</h3>
        ${renderList(prep.what_is_unclear)}
      </div>

      <div class="prep-section">
        <h3>⚠️ Missing From Document</h3>
        ${renderList(prep.missing_from_document)}
      </div>

      <div class="prep-section">
        <h3>💬 Questions to Ask</h3>
        ${renderList(prep.questions_to_ask)}
      </div>

      <div class="prep-section">
        <h3>📄 Important Sections</h3>
        ${renderList(prep.important_sections)}
      </div>

      <div style="margin-top: var(--space-lg); display: flex; gap: var(--space-md);">
        <button class="btn btn-primary" onclick="window.print()">🖨️ Print</button>
        <button class="btn btn-secondary" onclick="closePrepModal()">Close</button>
      </div>
    </div>
  `;
  modal.querySelector('.modal').focus();
}

function closePrepModal() {
  const modal = document.getElementById("prep-modal");
  if (modal) { modal.className = "hidden"; modal.innerHTML = ""; }
}

/* ── Init ───────────────────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", () => {
  renderApp();
});
