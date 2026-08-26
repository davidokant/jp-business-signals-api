# Railway deployment runbook

This runbook prepares a small, self-serve production deployment. It does not
create a Railway account, purchase a plan, or publish the service.

Before creating the Railway service, publish the local project with
`scripts/publish_to_github.ps1`. The script runs lint, tests, and a build first,
then refuses to stage `.env` or `production.db`.

## Architecture

Run one Railway service from the repository's `Dockerfile` and attach one
Railway Volume at `/app/data`. The service reads its SQLite database from
`/app/data/production.db`, so the database survives code deployments. Railway
assigns the `PORT` variable; the container uses it automatically and exposes
`/health` for the platform health check.

Start with a Hobby plan and one service. Do not use a free service for the
production database: persistent volumes require a paid plan.

## Create the service

1. Create an empty Railway project and add a service from this repository, or
   run `railway up` after signing in and linking the intended project.
2. Attach a Volume to that service with mount path `/app/data`.
3. Enable a Railway-provided public domain. A custom domain is optional until
   there is evidence of paid demand.
4. Set the health-check path to `/health`.

Railway detects the root `Dockerfile`. No start-command override is needed.

## Required production variables

Set these in Railway's service Variables panel. Do not upload `.env` and do
not put secrets in Git.

```text
APP_ENV=production
APP_DATABASE_PATH=/app/data/production.db
APP_AUTO_SEED_SAMPLE=false
APP_RATE_LIMIT_PER_MINUTE=120
APP_API_KEYS=<a-long-random-direct-api-key>
GBIZ_API_TOKEN=<your-gBizINFO-token>
GBIZ_BASE_URL=https://api.info.gbiz.go.jp/hojin
GBIZ_TIMEOUT_SECONDS=30
GBIZ_REQUEST_INTERVAL_SECONDS=0.25
```

Leave `APP_RAPIDAPI_PROXY_SECRET` unset until RapidAPI supplies the production
proxy secret. Add it only in Railway Variables, never in source code.

## Upload the initial database

After linking the Railway CLI to the service and attaching its volume, upload
the locally validated database to the volume. The `--overwrite` flag is
intentional: the service may have created an empty database during its first
startup.

```powershell
railway volume files upload .\data\production.db /production.db --overwrite
railway volume files list /
railway service restart
```

Check that `production.db` appears in the list before restarting. Future
ingestion writes to the same volume. Download a backup before any manual
replacement:

```powershell
railway volume files download /production.db .\backups\production.db
```

## Verify before RapidAPI listing

Replace `YOUR_RAILWAY_DOMAIN` with the Railway-provided domain.

```powershell
Invoke-RestMethod https://YOUR_RAILWAY_DOMAIN/health
Invoke-RestMethod https://YOUR_RAILWAY_DOMAIN/demo/stats
Invoke-WebRequest https://YOUR_RAILWAY_DOMAIN/
```

The stats must show real data, not zero records or sample data. Only then add
the public base URL and production proxy secret in RapidAPI.

## Refresh workflow

The repository includes a GitHub Actions workflow at
`.github/workflows/refresh-gbiz.yml`. It runs once per day at 18:17 UTC
(approximately 03:17 JST the following day; GitHub may delay scheduled jobs)
and can also be started manually. The job is serialized so two refreshes cannot
run at the same time.

Use the existing GitHub `resourceful-recreation / production` environment and
add these environment secrets:

```text
RAILWAY_TOKEN=<project-scoped Railway token>
RAILWAY_PROJECT_ID=<Railway project ID>
RAILWAY_SERVICE_ID=<Railway API service ID>
GBIZ_API_TOKEN=<your-gBizINFO-token>
```

The workflow downloads the current production database, copies the previous
version to `/production.backup.db` on the same Railway Volume, imports an
overlapping eight-day window of official data, checks SQLite integrity and
non-empty coverage, uploads the refreshed database, restarts the API, and
validates the public `/status` endpoint. The overlap helps catch delayed source
updates. A failed import or integrity check stops before the production database
is overwritten. The rolling backup is overwritten only after the next scheduled
run starts.

For unattended refreshes, do not add a required-reviewer protection rule to the
GitHub `resourceful-recreation / production` environment; such a rule leaves scheduled jobs waiting for
manual approval. Pause the schedule if the token purpose, current gBizINFO
terms, or desired update cadence changes.

## Cost and safety controls

- Start with one service and one small volume. A volume prevents horizontal
  replicas, which is appropriate for this SQLite MVP.
- Set a Railway monthly usage alert and hard cap before enabling public traffic.
- Retain a database backup before data refreshes and before changing the schema.
- Migrate to managed Postgres and a shared rate limiter before adding replicas
  or materially increasing paid traffic.
