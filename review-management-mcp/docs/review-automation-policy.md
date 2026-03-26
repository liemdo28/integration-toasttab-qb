# Policy: Automated Review Management

## 1) Scope
This policy applies to all automated workflows that read customer reviews, infer sentiment, profile reviewer behavior, and generate or post public replies.

## 2) Principles
1. **Human-first trust**: never publish harmful, deceptive, or manipulative content.
2. **Privacy by default**: do not expose personal data in generated responses.
3. **Platform compliance**: follow Google review policies and local regulations.
4. **Auditability**: every generated draft and posted reply must be logged.

## 3) Data handling
- Collect only required fields: review id, rating, text, timestamp, locale.
- Do not store raw tokens, passwords, or secrets in logs.
- Redact probable PII (phone, email, exact addresses) before model prompts.
- Retention recommendation: 180 days for operational logs unless legal requirement differs.

## 4) Reviewer scanning constraints
Allowed:
- Basic activity signals tied to review content (e.g., sentiment trend, repeated complaint pattern).

Not allowed:
- Sensitive trait inference (health, religion, ethnicity, political orientation).
- Doxing, social graph enrichment, or deanonymization.

## 5) AI response policy
Every draft reply must:
- Be respectful and non-confrontational.
- Avoid legal admission of fault unless approved template says otherwise.
- Avoid compensation/refund promise unless verified by business rules.
- Avoid fabricated facts.
- Invite offline resolution for complex/abusive threads.

## 6) Auto-post gates (must all pass)
1. Toxicity check = pass.
2. Hallucination risk check = pass.
3. Policy keyword checks = pass.
4. Risk level <= configured threshold (`AUTO_POST_MAX_RISK`).

If any gate fails -> queue as `manual_review`.

## 7) Security & access
- Use repository secrets for API keys.
- Restrict workflow permissions to least privilege.
- Require CODEOWNERS review for policy changes and auto-post changes.

## 8) Weekly operations
- Schedule: once per week (configurable cron).
- Emit summary artifact: fetched count, drafted count, auto-posted count, escalated count.
- Open issue automatically when error rate > threshold.

## 9) Incident response
- Immediate switch: set `REPLY_MODE=manual`.
- Disable workflow if repeated critical failures.
- Preserve logs, run root-cause analysis, and document corrective actions.

