const companyCount = document.querySelector("#company-count");
const signalCount = document.querySelector("#signal-count");
const sourceCount = document.querySelector("#source-count");
const searchForm = document.querySelector("#search-form");
const searchInput = document.querySelector("#signal-search");
const signalGrid = document.querySelector("#signal-grid");
const resultStatus = document.querySelector("#result-status");
const readinessForm = document.querySelector("#readiness-form");
const readinessInput = document.querySelector("#capability-search");
const readinessGrid = document.querySelector("#readiness-grid");
const readinessStatus = document.querySelector("#readiness-status");
const readinessButton = readinessForm.querySelector('button[type="submit"]');
const capabilityExamples = document.querySelectorAll("[data-capability]");

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

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

function renderLoadingCards() {
  readinessGrid.replaceChildren();
  readinessGrid.setAttribute("aria-busy", "true");
  for (let index = 0; index < 3; index += 1) {
    const card = document.createElement("div");
    card.className = "readiness-card readiness-card-loading";
    card.setAttribute("aria-hidden", "true");
    for (let line = 0; line < 4; line += 1) {
      appendTextElement(card, "span", "loading-line", "");
    }
    readinessGrid.appendChild(card);
  }
}

function renderReadiness(items) {
  readinessGrid.replaceChildren();
  readinessGrid.setAttribute("aria-busy", "false");

  if (!items.length) {
    appendTextElement(
      readinessGrid,
      "div",
      "empty-card",
      "No tender matches found. Try a broader capability such as cloud services or cybersecurity.",
    );
    return;
  }

  items.slice(0, 3).forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "readiness-card";

    const cardTop = document.createElement("div");
    cardTop.className = "readiness-card-top";
    appendTextElement(
      cardTop,
      "span",
      "match-rank",
      "MATCH " + String(index + 1).padStart(2, "0"),
    );
    appendTextElement(
      cardTop,
      "strong",
      "match-score",
      Number(item.match_score || 0) + "%",
    );
    card.appendChild(cardTop);

    appendTextElement(card, "h3", "", item.title_ja || "Untitled public tender");
    appendTextElement(
      card,
      "p",
      "readiness-buyer",
      item.buyer || "Buyer not listed",
    );

    const metrics = document.createElement("dl");
    metrics.className = "readiness-metrics";
    const urgency = String(item.deadline_urgency || "unknown").toLowerCase();
    const urgencyRow = document.createElement("div");
    appendTextElement(urgencyRow, "dt", "", "Deadline");
    appendTextElement(
      urgencyRow,
      "dd",
      "urgency urgency-" + urgency,
      urgency.replaceAll("_", " "),
    );
    metrics.appendChild(urgencyRow);
    const completenessRow = document.createElement("div");
    appendTextElement(completenessRow, "dt", "", "Data completeness");
    appendTextElement(
      completenessRow,
      "dd",
      "",
      Number(item.data_completeness || 0) + "%",
    );
    metrics.appendChild(completenessRow);
    card.appendChild(metrics);

    const actions = Array.isArray(item.next_actions)
      ? item.next_actions.slice(0, 3)
      : [];
    if (actions.length) {
      appendTextElement(card, "p", "action-label", "NEXT ACTIONS");
      const actionList = document.createElement("ul");
      actionList.className = "action-list";
      actions.forEach((action) =>
        appendTextElement(actionList, "li", "", action),
      );
      card.appendChild(actionList);
    }

    const sourceUrl = safeExternalUrl(item.source_url);
    if (sourceUrl) {
      const sourceLink = document.createElement("a");
      sourceLink.className = "source-line";
      sourceLink.href = sourceUrl;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      const sourceDot = document.createElement("span");
      sourceDot.className = "source-dot";
      sourceLink.appendChild(sourceDot);
      sourceLink.append("Review official tender ↗");
      card.appendChild(sourceLink);
    }
    readinessGrid.appendChild(card);
  });
}

let readinessRequest;

async function loadReadiness(query) {
  if (readinessRequest) readinessRequest.abort();
  const request = new AbortController();
  readinessRequest = request;
  readinessStatus.textContent =
    "Matching English capability to Japanese public tenders…";
  readinessButton.disabled = true;
  renderLoadingCards();

  try {
    const params = new URLSearchParams({ q: query });
    const response = await fetch(
      "/demo/tender-readiness?" + params.toString(),
      { signal: request.signal },
    );
    if (!response.ok) throw new Error("Tender readiness unavailable");
    const payload = await response.json();
    const items = Array.isArray(payload.items) ? payload.items : [];
    renderReadiness(items);
    readinessStatus.textContent = items.length
      ? "Showing " +
        Math.min(items.length, 3) +
        " readiness-ranked tender matches for “" +
        query +
        "”."
      : "No readiness matches for “" + query + "”.";
  } catch (error) {
    if (error.name === "AbortError") return;
    readinessGrid.replaceChildren();
    readinessGrid.setAttribute("aria-busy", "false");
    appendTextElement(
      readinessGrid,
      "div",
      "empty-card",
      "The readiness preview is temporarily unavailable. You can still explore live procurement signals below.",
    );
    readinessStatus.textContent = "Tender readiness preview unavailable.";
  } finally {
    if (readinessRequest === request) {
      readinessButton.disabled = false;
    }
  }
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

    const sourceUrl = safeExternalUrl(signal.source_url);
    if (sourceUrl) {
      const sourceLink = document.createElement("a");
      sourceLink.className = "source-line";
      sourceLink.href = sourceUrl;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      const sourceDot = document.createElement("span");
      sourceDot.className = "source-dot";
      sourceLink.appendChild(sourceDot);
      sourceLink.append("Official source ↗");
      card.appendChild(sourceLink);
    }
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

readinessForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const query = readinessInput.value.trim();
  if (query.length < 2) {
    readinessStatus.textContent = "Enter at least two characters.";
    readinessInput.focus();
    return;
  }
  loadReadiness(query);
});

capabilityExamples.forEach((button) => {
  button.addEventListener("click", () => {
    readinessInput.value = button.dataset.capability;
    loadReadiness(button.dataset.capability);
  });
});

loadStats();
loadSignals();
loadReadiness(readinessInput.value);
