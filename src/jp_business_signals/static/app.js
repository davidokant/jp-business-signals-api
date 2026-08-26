const companyCount = document.querySelector("#company-count");
const signalCount = document.querySelector("#signal-count");
const sourceCount = document.querySelector("#source-count");
const searchForm = document.querySelector("#search-form");
const searchInput = document.querySelector("#signal-search");
const signalGrid = document.querySelector("#signal-grid");
const resultStatus = document.querySelector("#result-status");

const numberFormatter = new Intl.NumberFormat("en-US");
const dateFormatter = new Intl.DateTimeFormat("en", {
  month: "short",
  day: "2-digit",
  year: "numeric",
  timeZone: "UTC",
});

function appendTextElement(parent, tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}

function renderSignals(items) {
  signalGrid.replaceChildren();
  if (!items.length) {
    appendTextElement(
      signalGrid,
      "div",
      "empty-card",
      "No matching procurement signals. Try a company name or a broader term.",
    );
    return;
  }

  items.forEach((signal) => {
    const card = document.createElement("article");
    card.className = "signal-card";

    const meta = document.createElement("div");
    meta.className = "signal-meta";
    appendTextElement(
      meta,
      "span",
      "",
      dateFormatter.format(new Date(signal.occurred_on + "T00:00:00Z")).toUpperCase(),
    );
    appendTextElement(meta, "span", "signal-score", "+" + signal.score_delta);
    card.appendChild(meta);

    appendTextElement(card, "h3", "", signal.title);
    const companyLine = [signal.company_name, signal.prefecture]
      .filter(Boolean)
      .join(" · ");
    appendTextElement(card, "p", "", companyLine);

    const sourceLink = document.createElement("a");
    sourceLink.className = "source-line";
    sourceLink.href = signal.source_url;
    sourceLink.target = "_blank";
    sourceLink.rel = "noopener noreferrer";
    const sourceDot = document.createElement("span");
    sourceDot.className = "source-dot";
    sourceLink.appendChild(sourceDot);
    sourceLink.append("Official source ↗");
    card.appendChild(sourceLink);
    signalGrid.appendChild(card);
  });
}

async function loadStats() {
  try {
    const response = await fetch("/demo/stats");
    if (!response.ok) throw new Error("Stats unavailable");
    const stats = await response.json();
    companyCount.textContent = numberFormatter.format(stats.companies);
    signalCount.textContent = numberFormatter.format(stats.procurement_signals);
    sourceCount.textContent = numberFormatter.format(stats.official_sources);
  } catch {
    companyCount.textContent = "—";
    signalCount.textContent = "—";
    sourceCount.textContent = "—";
  }
}

async function loadSignals(query = "") {
  resultStatus.textContent = "Loading procurement signals…";
  const params = new URLSearchParams({ limit: "6" });
  if (query) params.set("q", query);

  try {
    const response = await fetch("/demo/signals?" + params.toString());
    if (!response.ok) throw new Error("Signals unavailable");
    const payload = await response.json();
    renderSignals(payload.items);
    resultStatus.textContent = payload.count
      ? "Showing " + payload.count + " source-traceable signals."
      : "No matching signals.";
  } catch {
    signalGrid.replaceChildren();
    appendTextElement(
      signalGrid,
      "div",
      "empty-card",
      "The live explorer is temporarily unavailable. The API documentation remains online.",
    );
    resultStatus.textContent = "Live data unavailable.";
  }
}

searchForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = searchInput.value.trim();
  if (query.length === 1) {
    resultStatus.textContent = "Enter at least two characters.";
    return;
  }
  loadSignals(query);
});

loadStats();
loadSignals();
