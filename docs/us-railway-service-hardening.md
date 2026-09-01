# US Federal Signals — independent Railway service hardening

This is a deployment-preparation checklist, not deployment authorization. The
US feasibility app must run as a separate service inside the existing Railway
workspace. It must not replace, restart, reconfigure, share secrets with, or
attach a volume to the Japan production service.

## Repository boundary

- Japan service: root `Dockerfile`, `jp_business_signals.main:app`, existing
  database volume and production domain.
- US service: `Dockerfile.us`, `us_federal_signals.main:app`, no volume, separate
  variables and separate domain.
- Use one US replica. Do not horizontally scale while the SAM budget and cache
  are process-local.
- Railway's legacy `railway.toml`/`railway.json` Config-as-Code is deprecated
  for new services. Configure the service-specific Dockerfile, readiness path,
  replica count and resource limits in the US service settings. A future
  organization-wide IaC migration should use `.railway/railway.ts` after the
  live project is explicitly authorized for import and planning.

## US service settings

Create a new empty service only after explicit authorization, then connect the
same repository and the reviewed branch or commit. Configure:

```text
Service name: us-federal-signals
Dockerfile path: Dockerfile.us
Healthcheck path: /ready
Healthcheck timeout: 60 seconds
Replicas: 1
Volume: none
Public domain: none during private smoke
```

Railway supports a non-standard Dockerfile through the service build setting or
the non-secret service variable `RAILWAY_DOCKERFILE_PATH=Dockerfile.us`. Keep
that variable scoped to the US service. Do not add it to shared variables.

Start with conservative per-replica ceilings and adjust from observed metrics:

```text
Memory limit: 512 MB
CPU limit: 0.5 vCPU
```

Do not lower the workspace compute hard limit for this experiment: reaching a
workspace hard limit can stop the Japan service too. Prefer US service replica
limits, a workspace email alert, and a manual stop rule for the US service.

## Required service-only variables

Secrets must be entered directly in the Railway US service Variables panel and
must never appear in chat, Git, screenshots, logs or shared variables.

```text
US_APP_ENV=production
US_APP_API_KEYS=<independent-long-random-key>
US_RAPIDAPI_PROXY_SECRET=<unset until separately authorized>
US_RATE_LIMIT_PER_MINUTE=10
SAM_API_KEY=<owner-supplied-personal-or-system-key>
SAM_OPPORTUNITIES_BASE_URL=https://api.sam.gov/opportunities/v2/search
USASPENDING_BASE_URL=https://api.usaspending.gov
US_SOURCE_TIMEOUT_SECONDS=30
US_SAM_DAILY_REQUEST_BUDGET=8
US_SAM_CACHE_TTL_SECONDS=900
US_SAM_CACHE_MAX_ENTRIES=256
```

Do not set Japan variables (`APP_*`, `GBIZ_*`, `KKJ_*`, database paths or refresh
tokens) on the US service. Do not reference shared secrets.

## Runtime controls and known limits

- Direct and RapidAPI consumers are independently limited per minute. Stored
  limiter identities are one-way hashes, not plaintext keys or consumer names.
- Identical SAM searches are cached for a configurable TTL; cache hits do not
  consume the local daily budget.
- The default local daily budget is eight upstream SAM searches, leaving a
  small margin under a ten-request personal-account allowance.
- The daily budget and cache are process-local. Deploys, crashes, serverless
  restarts and replica changes reset them. SAM.gov remains the authoritative
  quota enforcement layer.
- `GET /health` proves that the process is alive. `GET /ready` proves that the
  required SAM credential is configured without making an external request.
- A SAM upstream 429 is returned as a safe 503 with `Retry-After`; URLs, keys
  and upstream response bodies are not returned to consumers.

## Private smoke sequence

Before generating a public domain, use Railway's service diagnostics or an
explicitly authorized temporary domain to verify:

```text
GET /health                                 -> 200
GET /ready                                  -> 200
GET /v1/opportunities/search                -> 401 without customer auth
GET /v1/awards/search                       -> 200 with customer auth
GET /v1/opportunities/search?limit=1        -> 200 with customer auth
repeat identical opportunity search        -> 200 from cache
different searches beyond daily budget     -> 503 with Retry-After
```

Never print Railway variables or exception URLs during smoke testing.

## Rollback and stop conditions

Rollback affects only `us-federal-signals`:

1. Remove or disable its public domain first.
2. Stop the US deployment or roll back to its last reviewed deployment.
3. Revoke or rotate the US customer key and SAM key if exposure is suspected.
4. Confirm the Japan service health, deployment ID, domain and volume were not
   changed.

Stop the US service without touching Japan when any of these occurs:

- unexpected Railway resource growth;
- repeated upstream 429, 401 or 403 responses;
- a secret appears in logs or screenshots;
- the process-local budget resets frequently because of crashes or deploys;
- SAM.gov terms, response schema or account allowance changes;
- the US service cannot remain operationally isolated from Japan.

Actual service creation, variable submission, domain generation, deployment,
RapidAPI configuration, payment or plan changes require separate owner approval.
