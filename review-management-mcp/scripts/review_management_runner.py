#!/usr/bin/env python3
"""Weekly review automation runner with policy gates."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class Review:
    review_id: str
    rating: int
    text: str
    locale: str = "en"


def fetch_reviews() -> list[Review]:
    """TODO: Replace with Google review source integration."""
    # Baseline stub so workflow can validate policy path end-to-end.
    return [
        Review(review_id="sample-1", rating=2, text="Service was slow and food was cold."),
        Review(review_id="sample-2", rating=5, text="Great staff and very quick support!"),
    ]


def classify_risk(review: Review) -> str:
    lowered = review.text.lower()
    if any(x in lowered for x in ["lawyer", "sue", "fraud", "illegal"]):
        return "high"
    if review.rating <= 2:
        return "medium"
    return "low"


def generate_reply(review: Review) -> str:
    """TODO: Replace with AI model call, after pii redaction."""
    if review.rating <= 2:
        return (
            "Thank you for your feedback. We're sorry your experience missed the mark. "
            "Please contact us directly so we can make this right."
        )
    return "Thank you for your support. We appreciate your feedback and hope to serve you again soon."


def policy_checks(reply: str) -> dict[str, Any]:
    banned = ["guarantee refund", "your data is public", "we are never wrong"]
    text = reply.lower()
    violations = [term for term in banned if term in text]
    return {
        "pass": len(violations) == 0,
        "violations": violations,
    }


def post_reply(review_id: str, reply: str) -> None:
    """TODO: Replace with official Google reply endpoint."""
    print(f"[AUTO_POST] review={review_id} reply={reply}")


def should_auto_post(risk: str, check_pass: bool) -> bool:
    mode = os.getenv("REPLY_MODE", "manual").strip().lower()
    max_risk = os.getenv("AUTO_POST_MAX_RISK", "low").strip().lower()

    if mode != "auto_post" or not check_pass:
        return False

    order = {"low": 1, "medium": 2, "high": 3}
    return order.get(risk, 3) <= order.get(max_risk, 1)


def main() -> int:
    reviews = fetch_reviews()
    report: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(reviews),
        "drafted": 0,
        "auto_posted": 0,
        "manual_review": 0,
        "items": [],
    }

    for review in reviews:
        risk = classify_risk(review)
        reply = generate_reply(review)
        checks = policy_checks(reply)
        report["drafted"] += 1

        item = {
            "review_id": review.review_id,
            "rating": review.rating,
            "risk": risk,
            "checks": checks,
            "reply": reply,
            "action": "manual_review",
        }

        if should_auto_post(risk=risk, check_pass=checks["pass"]):
            post_reply(review.review_id, reply)
            item["action"] = "auto_posted"
            report["auto_posted"] += 1
        else:
            report["manual_review"] += 1

        report["items"].append(item)

    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/review_run_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(json.dumps({k: v for k, v in report.items() if k != "items"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

