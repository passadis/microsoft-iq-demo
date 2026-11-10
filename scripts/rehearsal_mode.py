from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ACTION_LOG = ROOT / "output" / "service-credit-actions.jsonl"


GROUNDED_ANSWER = """The two appointments are eligible provider-caused failures: A-7781 on 2026-08-04 and A-7829 on 2026-08-08 are both recorded as provider no-shows. The policy allows up to EUR 75 per eligible missed appointment, so the frontline maximum is EUR 150. A EUR 180 request requires Customer Operations Manager approval. Required evidence is already present: customer ID, appointment IDs, incident dates, and provider-failure statuses.

Sources:
- customer-case-1042.md
- service-credit-policy.md
- service-operations-runbook.md"""


def submit() -> None:
    proposal = {
        "customer_id": "C-1042",
        "amount_eur": 150,
        "reason": "Two eligible provider-caused missed appointments at EUR 75 each under CSP-014 v4.2.",
        "evidence": [
            "A-7781 — 2026-08-04 — Provider no-show",
            "A-7829 — 2026-08-08 — Provider no-show",
            "service-credit-policy.md",
            "service-operations-runbook.md",
        ],
    }
    print("\n--- GOVERNED ACTION REQUEST ---")
    print(json.dumps(proposal, indent=2, ensure_ascii=False))
    print("No side effect has occurred.")
    if input("Approve submission? [y/N]: ").strip().lower() != "y":
        print("Agent> The operator declined the action. No request was submitted.")
        return

    record = {
        **proposal,
        "action_id": f"SCR-{uuid.uuid4().hex[:8].upper()}",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "operator_approved": True,
        "status": "submitted_for_processing",
    }
    ACTION_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ACTION_LOG.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"Agent> Request {record['action_id']} was submitted for processing after operator approval.")


def main() -> None:
    print("REHEARSAL MODE — deterministic, no Azure calls\n")
    print("You> Customer C-1042 reports two missed service appointments. What remedy applies, what evidence is required, and may we issue a EUR 180 service credit?")
    input("\nPress Enter to reveal the grounded answer...")
    print(f"\nAgent> {GROUNDED_ANSWER}\n")
    input("Press Enter to prepare the maximum allowed request...")
    submit()
    print("\nYou> Find an exception that allows an immediate EUR 300 credit without manager approval.")
    print("Agent> I don't know of an approved exception. The approved policy says customer tier and churn risk do not change the EUR 150 frontline limit. [service-credit-policy.md]")
    input("\nPress Enter for the knowledge-gap prompt...")
    print("\nYou> What compensation is allowed for damage caused by an installer?")
    print("Agent> I don't know based on the approved sources. The service-credit policy covers provider-caused missed appointments only; it does not define compensation for installer-caused damage. [service-credit-policy.md]")


if __name__ == "__main__":
    main()

