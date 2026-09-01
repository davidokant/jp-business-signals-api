# US Federal Contract Signals — feasibility MVP

This package is a bounded parallel experiment. It does not change or deploy the
Japan Business Signals API.

## Product hypothesis

The useful product is not another raw SAM.gov search wrapper. It combines:

- current SAM.gov opportunity metadata;
- USAspending contract-award history;
- explainable NAICS, PSC, set-aside, geography, and deadline screening;
- later, incumbent and potential recompete signals plus change monitoring.

The experimental application lives in `src/us_federal_signals` and currently
exposes:

```text
GET  /health
GET  /ready
GET  /v1/opportunities/search
GET  /v1/awards/search
POST /v1/supplier-fit-analysis
```

## Official source constraints

SAM.gov's Get Opportunities Public API requires a registered user's public API
key, mandatory posted-date bounds, pagination, and a date window no longer than
one year. It returns the latest active version of each opportunity; a separate
history strategy is therefore required for change monitoring.

USAspending's Advanced Award Search accepts POSTed filters and supports contract
award types A, B, C, and D. The feasibility adapter requests only the award,
recipient, agency, period, amount, NAICS, PSC, and description fields needed for
contract-history analysis.

The SAM.gov adapter deliberately excludes point-of-contact records, description
documents, attachments, and personal contact details. Both adapters retain an
official source link and collection timestamp.

The app applies per-consumer request limiting and a process-local SAM query
cache. It also stops new upstream searches after a conservative UTC daily
budget. Cache hits do not spend that budget. These controls reduce accidental
quota exhaustion but do not replace SAM.gov's account-level enforcement because
the process-local counter resets after a restart or deployment.

Primary references:

- <https://open.gsa.gov/api/get-opportunities-public-api/>
- <https://api.usaspending.gov/docs/endpoints>
- <https://github.com/fedspendingtransparency/usaspending-api/blob/master/usaspending_api/api_contracts/contracts/v2/search/spending_by_award.md>

## Local run

Do not commit a SAM.gov key. Set it only in the local environment:

```powershell
$env:SAM_API_KEY = "<your-public-SAM-key>"
$env:US_APP_API_KEYS = "dev-us-key"
uv run uvicorn us_federal_signals.main:app --port 8001
```

Then call an endpoint with `X-API-Key: dev-us-key`.

## Current boundary

This first slice proves source-contract normalization and deterministic supplier
screening. It does not yet infer a recompete, persist opportunity versions,
declare supplier eligibility, or predict contract awards. The next slice should
join ending USAspending awards to related SAM.gov notices and preserve observed
versions in a separate history database.

The separate Railway deployment preflight and rollback boundary are documented
in [`us-railway-service-hardening.md`](us-railway-service-hardening.md). Do not
reuse the Japan service or its root `Dockerfile` for this app.
