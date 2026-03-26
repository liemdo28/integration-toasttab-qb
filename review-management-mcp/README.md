# Review Management MCP (Weekly Automation Baseline)

This folder contains a hardened baseline to run **weekly** automated review-management jobs from GitHub Actions.

## Goal
- Pull new Google reviews.
- Score sentiment and risk profile.
- Generate AI-assisted reply drafts.
- Apply policy gates before posting any public reply.

## Why this exists
The upstream repository could not be fetched in this environment (GitHub connectivity returned `403`), so this baseline provides:
1. A weekly scheduler (`.github/workflows/weekly-review-automation.yml`).
2. A policy document (`docs/review-automation-policy.md`).
3. A runner script (`scripts/review_management_runner.py`) with hard safety checks and dry-run support.

## Quick start
1. Configure repository secrets:
   - `GOOGLE_API_KEY`
   - `OPENAI_API_KEY`
   - `REVIEW_SOURCE_ID`
2. Optional variables:
   - `REPLY_MODE` = `manual` (default) or `auto_post`
   - `AUTO_POST_MAX_RISK` = `low` (default)
3. Run workflow manually from Actions tab first.
4. Keep `manual` until QA sign-off.

## Safety model
- Default is **manual** mode.
- Auto-post only if policy passes:
  - no abusive language,
  - no legal/medical/financial claim,
  - no refund promise,
  - risk <= threshold.

## Integration points
- Replace `fetch_reviews()` with Google review API integration.
- Replace `generate_reply()` with your AI provider call.
- Replace `post_reply()` with your official reply endpoint.


## Applied fixes from technical review
The following high-priority review points were validated and implemented:
- Stable tracker path in `logs/response-history.json` (no `process.cwd()` drift).
- Pending markdown now always appends/creates file.
- `unanswered_only` checks both Google reply state and local tracker.
- Idempotency key upgraded to `platform:location:reviewId`.
- Posting now uses `reviewName` directly, avoiding full-list scan for a single review.
- Startup env validation added.
- DRY_RUN support added.
- Google API client now includes timeout + retry/backoff for 429/5xx.
- Notification script uses `dotenv` and HTML escaping.
