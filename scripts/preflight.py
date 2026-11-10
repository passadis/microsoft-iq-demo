from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys

from common import ROOT, validate_settings


def check(label: str, passed: bool, detail: str) -> bool:
    marker = "PASS" if passed else "FAIL"
    print(f"[{marker}] {label}: {detail}")
    return passed


def main() -> int:
    results: list[bool] = []
    results.append(check("Python", sys.version_info >= (3, 10), sys.version.split()[0]))

    packages = ("azure.identity", "azure.ai.projects", "openai", "dotenv", "requests")
    missing_packages = [name for name in packages if importlib.util.find_spec(name) is None]
    results.append(
        check(
            "Python packages",
            not missing_packages,
            "installed" if not missing_packages else f"missing: {', '.join(missing_packages)}",
        )
    )

    az_path = shutil.which("az")
    results.append(check("Azure CLI", bool(az_path), az_path or "not found"))
    if az_path:
        account = subprocess.run(
            [az_path, "account", "show", "--query", "name", "-o", "tsv"],
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            check(
                "Azure sign-in",
                account.returncode == 0,
                account.stdout.strip() if account.returncode == 0 else "run az login",
            )
        )

    env_path = ROOT / ".env"
    results.append(check(".env file", env_path.exists(), str(env_path)))
    missing_settings = validate_settings()
    results.append(
        check(
            "Configuration",
            not missing_settings,
            "complete" if not missing_settings else f"missing: {', '.join(missing_settings)}",
        )
    )

    data_files = (
        ROOT / "data" / "customer-case-1042.md",
        ROOT / "data" / "service-credit-policy.md",
        ROOT / "data" / "service-operations-runbook.md",
    )
    missing_data = [path.name for path in data_files if not path.exists()]
    results.append(
        check(
            "Demo data",
            not missing_data,
            "ready" if not missing_data else f"missing: {', '.join(missing_data)}",
        )
    )

    output_dir = ROOT / "output"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        probe = output_dir / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        results.append(check("Output directory", True, "writable"))
    except OSError as error:
        results.append(check("Output directory", False, str(error)))

    search_endpoint = os.getenv("AZURE_AI_SEARCH_ENDPOINT", "").strip()
    if search_endpoint:
        try:
            import requests

            # Any HTTP response (including 401/403 without credentials) proves
            # DNS, TLS, and firewall reachability from this machine.
            reply = requests.get(search_endpoint, timeout=10)
            results.append(
                check("Search endpoint reachable", True, f"HTTP {reply.status_code} from {search_endpoint}")
            )
        except Exception as error:
            results.append(check("Search endpoint reachable", False, str(error)))

    print()
    if all(results):
        print("Preflight passed. Confirm knowledge-source indexing in the Foundry portal before the event.")
        return 0
    print("Preflight failed. Fix the items above before running the live Azure path.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

