# RapidAPI listing draft

## Name

JP Business Signals API

## One-line description

Search source-traceable Japanese company profiles and monitor public procurement, subsidy, patent, and profile-change signals.

## Overview

JP Business Signals API turns permitted public and licensed sources into normalized company profiles and time-ordered business activity signals. Every returned record includes provenance fields so users can inspect the source, collection time, and applicable license.

Good for:

- B2B sales intelligence and account prioritization
- Procurement and supplier research
- Japan market-entry products
- Company monitoring and internal research tools

The activity score is a transparent product metric based on observed public business activity. It is not a credit score and must not be used for decisions about individuals, employment, insurance, housing, or other high-impact purposes.

## Suggested plans

| Plan | Monthly price | Included requests | Overage | Intended use |
|---|---:|---:|---:|---|
| BASIC | $0 | 100 | Disabled | Evaluation |
| PRO | $29 | 5,000 | $0.008/request | Hobby and prototypes |
| ULTRA | $99 | 50,000 | $0.003/request | Production applications |
| MEGA | $299 | 250,000 | $0.0015/request | Data products and teams |

Recheck unit economics and current marketplace minimums before publishing. Do not promise update frequency or source coverage until production ingestion has been measured for at least 30 days.

## Authentication

RapidAPI consumers use the headers issued by RapidAPI. Direct customers use `X-API-Key`. The backend should validate `X-RapidAPI-Proxy-Secret` so callers cannot bypass marketplace billing.

## Support promise for the MVP

- Public status endpoint at `/health`
- Source provenance on every company and signal
- No CAPTCHA, login, or paywall bypass
- Corrections accepted through a published support address

