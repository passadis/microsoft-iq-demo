"""Clear rehearsal output so the audience sees a clean audit log on stage."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTION_LOG = ROOT / "output" / "service-credit-actions.jsonl"


def main() -> None:
    if not ACTION_LOG.exists():
        print(f"Nothing to clear: {ACTION_LOG} does not exist.")
        return
    with ACTION_LOG.open(encoding="utf-8") as handle:
        count = sum(1 for line in handle if line.strip())
    ACTION_LOG.unlink()
    print(f"Removed {ACTION_LOG.name} ({count} record(s)). The audit log is clean.")


if __name__ == "__main__":
    main()
