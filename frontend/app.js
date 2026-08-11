const API_BASE = "const API_BASE = "https://codelint-awmb.onrender.com/api";

// ---------------- tabs ----------------
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const name = tab.dataset.tab;
    document.getElementById(`panel-${name}`).classList.add("active");
    document.getElementById("active-path").textContent =
      { analyze: "analyze", history: "history", dashboard: "dashboard" }[name];
    if (name === "history") loadHistory();
    if (name === "dashboard") loadDashboard();
  });
});

// ---------------- backend health ----------------
async function checkBackend() {
  const el = document.getElementById("conn-status");
  try {
    const res = await fetch(`${API_BASE.replace("/api", "")}/`);
    if (res.ok) {
      el.textContent = "● backend connected";
      el.classList.remove("offline");
    } else throw new Error();
  } catch {
    el.textContent = "● backend offline — start the server";
    el.classList.add("offline");
  }
}
checkBackend();

// ---------------- analyze ----------------
const analyzeBtn = document.getElementById("analyze-btn");
const codeInput = document.getElementById("code-input");
const filenameInput = document.getElementById("filename");
const errorText = document.getElementById("analyze-error");
const resultEmpty = document.getElementById("result-empty");
const resultContent = document.getElementById("result-content");

function severityClass(sev) {
  return { high: "sev-high", medium: "sev-medium", low: "sev-low" }[sev] || "sev-low";
}

function scoreColor(score) {
  if (score >= 80) return "var(--sev-good)";
  if (score >= 55) return "var(--sev-medium)";
  return "var(--sev-high)";
}

function renderResult(data) {
  resultEmpty.style.display = "none";
  resultContent.style.display = "block";

  const color = scoreColor(data.score);
  let html = `
    <div class="score-row">
      <div class="score-ring" style="border-color:${color}; color:${color};">${data.score}</div>
      <div class="score-meta">
        <span class="score-meta-title">${data.filename || "untitled.py"}</span>
        <span class="score-meta-stats">${data.lines_of_code} lines · ${data.num_functions} functions · ${data.num_classes} classes · avg complexity ${data.avg_complexity}</span>
      </div>
    </div>
  `;

  if (!data.issues || data.issues.length === 0) {
    html += `<div class="no-issues">✓ No issues found — clean analysis.</div>`;
  } else {
    html += `<div class="issue-list">`;
    for (const issue of data.issues) {
      html += `
        <div class="issue-row ${severityClass(issue.severity)}">
          <span class="issue-line">L${issue.line}</span>
          <span class="issue-msg"><span class="issue-cat">${issue.category}</span>${issue.message}</span>
        </div>
      `;
    }
    html += `</div>`;
  }

  resultContent.innerHTML = html;
}

analyzeBtn.addEventListener("click", async () => {
  const code = codeInput.value;
  errorText.textContent = "";
  if (!code.trim()) {
    errorText.textContent = "Paste some code first.";
    return;
  }
  analyzeBtn.disabled = true;
  analyzeBtn.textContent = "Analyzing…";
  try {
    const res = await fetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        code,
        filename: filenameInput.value || "untitled.py",
        language: "python",
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      errorText.textContent = data.detail || "Analysis failed.";
      return;
    }
    renderResult(data);
  } catch (e) {
    errorText.textContent = "Could not reach the backend. Is it running?";
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.textContent = "Run analysis →";
  }
});

// ---------------- history ----------------
async function loadHistory() {
  const body = document.getElementById("history-body");
  const empty = document.getElementById("history-empty");
  try {
    const res = await fetch(`${API_BASE}/history`);
    const rows = await res.json();
    if (rows.length === 0) {
      body.innerHTML = "";
      empty.style.display = "block";
      return;
    }
    empty.style.display = "none";
    body.innerHTML = rows
      .map((r) => {
        const color = scoreColor(r.score);
        const date = new Date(r.created_at).toLocaleString();
        return `
        <tr>
          <td><span class="score-pill" style="background:${color}22;color:${color};">${r.score}</span></td>
          <td>${r.filename}</td>
          <td>${r.lines_of_code}</td>
          <td>${r.num_functions}</td>
          <td>${date}</td>
          <td><button class="del-btn" data-id="${r.id}">delete</button></td>
        </tr>`;
      })
      .join("");
    body.querySelectorAll(".del-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        await fetch(`${API_BASE}/analysis/${btn.dataset.id}`, { method: "DELETE" });
        loadHistory();
      });
    });
  } catch {
    empty.textContent = "Could not load history — is the backend running?";
    empty.style.display = "block";
  }
}

// ---------------- dashboard ----------------
let trendChart, categoryChart;

async function loadDashboard() {
  try {
    const res = await fetch(`${API_BASE}/stats`);
    const stats = await res.json();

    document.getElementById("stat-total").textContent = stats.total_analyses;
    document.getElementById("stat-avg").textContent = stats.avg_score;

    const totals = stats.issue_category_totals || {};
    const topCategory = Object.entries(totals).sort((a, b) => b[1] - a[1])[0];
    document.getElementById("stat-common").textContent =
      topCategory && topCategory[1] > 0 ? topCategory[0] : "—";

    const trendLabels = (stats.score_trend || []).map((_, i) => `#${i + 1}`);
    const trendData = (stats.score_trend || []).map((t) => t.score);

    const trendCtx = document.getElementById("trend-chart");
    if (trendChart) trendChart.destroy();
    trendChart = new Chart(trendCtx, {
      type: "line",
      data: {
        labels: trendLabels,
        datasets: [
          {
            label: "score",
            data: trendData,
            borderColor: "#e8b339",
            backgroundColor: "#e8b33922",
            tension: 0.3,
            fill: true,
            pointRadius: 3,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { min: 0, max: 100, ticks: { color: "#8d8fa8" }, grid: { color: "#22242f" } },
          x: { ticks: { color: "#8d8fa8" }, grid: { display: false } },
        },
      },
    });

    const catCtx = document.getElementById("category-chart");
    if (categoryChart) categoryChart.destroy();
    categoryChart = new Chart(catCtx, {
      type: "bar",
      data: {
        labels: Object.keys(totals),
        datasets: [
          {
            data: Object.values(totals),
            backgroundColor: ["#f16d78", "#eeae4a", "#6fa1e0", "#5fcf96"],
            borderRadius: 4,
          },
        ],
      },
      options: {
        plugins: { legend: { display: false } },
        scales: {
          y: { ticks: { color: "#8d8fa8" }, grid: { color: "#22242f" } },
          x: { ticks: { color: "#8d8fa8" }, grid: { display: false } },
        },
      },
    });
  } catch {
    // silently ignore if backend is offline; stat boxes just show placeholders
  }
}
