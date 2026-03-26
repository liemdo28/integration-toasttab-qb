# Yelp strategy: safest + effective path

## Decision
For a no-cost, low-risk implementation:
1. **Phase 1 (recommended now): Email ingestion** from Yelp review notification emails.
2. **Phase 2 (optional): Manual assist fallback** for edge cases.
3. **Phase 3 (only if required): Browser automation (Playwright/Puppeteer)** with strict rate limits and legal review.

## Why this order
- Yelp official partner API is not broadly available.
- Email ingestion is usually more stable than scraping and cheaper to operate.
- Browser scraping can break frequently and carries policy/compliance risks.

## Email ingestion flow
1. Create dedicated mailbox (e.g., `reviews@...`).
2. Forward Yelp notifications to this mailbox.
3. Parse subject/body -> extract store, rating, text, date, url.
4. Build deterministic `review_key = yelp:{location}:{hash(text+date)}`.
5. Send to same decision engine as Google.

## Safety controls
- Keep Yelp in `manual_review` by default for first rollout.
- Require owner approval for <=3 stars and any complaint keywords.
- Limit auto-replies to positive, low-risk patterns only.

