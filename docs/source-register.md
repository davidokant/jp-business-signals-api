# Data source register

Every production source must appear here before ingestion is enabled. Recheck terms when the source announces a policy change.

| Source | Status | Access method | Commercial use | Required controls |
|---|---|---|---|---|
| Synthetic MVP Dataset | Enabled for tests | Bundled JSON | Unrestricted synthetic data | Mark every record as synthetic |
| gBizINFO company profile updates | Enabled; token required | Official REST API v2 | Official FAQ says commercial use is permitted | Declare the actual use when applying, keep the token secret, use serial requests, retain attribution, monitor policy changes |
| gBizINFO procurement updates | Enabled; token required | Official REST API v2 period endpoint | Same as above | Import dated procurement signals and preserve source URLs |
| gBizINFO subsidy updates | Disabled after live verification | Official v2 endpoint returned HTTP 404 for both daily and monthly ranges on 2026-08-26 | Same as above | Do not represent the 404 response as zero records; recheck after upstream changes |
| gBizINFO patent updates | Disabled after live verification | Official v2 endpoint returned HTTP 404 for both daily and monthly ranges on 2026-08-26 | Same as above | Do not represent the 404 response as zero records; recheck after upstream changes |
| JETRO website and procurement database | Disabled | None | General terms restrict reproduction, sale, publication, and distribution without permission | Obtain written permission or use an independently licensed original source |
| Arbitrary company websites | Disabled | None | Varies by site | Review terms and robots rules per domain; do not bypass login, CAPTCHA, paywall, or rate limits |

## gBizINFO field policy

Imported:

- Corporate number and company name
- Company name kana, headquarters location, industry, and company URL
- Counts and dated signals derived from procurement, subsidy, patent, certification, and profile updates
- Source URL, license statement, source update date, and collection time

Excluded from this MVP:

- Representative names
- Workplace information about individuals
- Free-text personal contact information
- Financial or employment decisions about natural persons

Terms and endpoint behavior reviewed: 2026-08-26.
