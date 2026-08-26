# EU Tender Signals API — feasibility brief

## Decision

This is the next API to evaluate after Japan Business Signals. It is a separate
product, not a feature of the Japan API.

Target buyer: English-speaking procurement, supplier-research, B2B sales, and
market-entry teams that need a usable view of European public tenders.

Primary source: the official TED Search API. Each returned record must preserve
the source notice URL and the time our service retrieved it.

## One-week feasibility MVP

Build only these capabilities:

1. Search notices by keyword, country, CPV code, and publication-date range.
2. Normalize results into a stable English schema: notice ID, title, buyer,
   country, CPV codes, publication date, deadline, estimated value when
   supplied, source URL, and retrieved-at time.
3. Return pagination and explicit source metadata.

Do not promise real-time coverage, award prediction, email alerts, or
all-European historical completeness in version 1.

## API surface to validate

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/tenders/search` | Find tender opportunities using buyer-facing filters. |
| `GET /v1/tenders/{notice_id}` | Retrieve normalized notice details and its TED source link. |
| `GET /v1/tenders/summary` | Return aggregate counts for a query, only after search is reliable. |

## Pass / stop gates

Start the one-week build only after the Japan API completes a 14-day live
validation period with at least ten non-owner calls and no source-access or
cost anomaly.

The feasibility MVP passes only if:

- Official TED access returns reproducible results for representative queries.
- The normalized schema covers the fields above without inventing missing data.
- A small Railway deployment can answer typical searches within an acceptable
  interactive wait.
- The source terms permit the planned display and reuse.

Stop or defer if source terms do not permit the product, key buyer fields are
not available reliably, or the required operations are materially more complex
than the Japan API.

## Success metric

The goal is not a second listing. The goal is evidence that a buyer can search
for a concrete opportunity and receive a clean result that is faster to use
than the official interface alone.

## Evidence

- TED Search API: <https://docs.ted.europa.eu/api/latest/search.html>
- TED API introduction: <https://docs.ted.europa.eu/api/latest/intro.html>
