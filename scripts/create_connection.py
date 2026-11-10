from __future__ import annotations

import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from common import mcp_endpoint, setting, validate_settings


def main() -> None:
    missing = validate_settings()
    if missing:
        raise RuntimeError(f"Complete .env first. Missing: {', '.join(missing)}")

    credential = DefaultAzureCredential()
    token_provider = get_bearer_token_provider(credential, "https://management.azure.com/.default")

    project_resource_id = setting("FOUNDRY_PROJECT_RESOURCE_ID")
    connection_name = setting("FOUNDRY_IQ_CONNECTION_NAME")
    api_version = setting("FOUNDRY_CONNECTION_API_VERSION", "2025-10-01-preview")
    url = (
        f"https://management.azure.com{project_resource_id}/connections/"
        f"{connection_name}?api-version={api_version}"
    )

    payload = {
        "name": connection_name,
        "type": "Microsoft.MachineLearningServices/workspaces/connections",
        "properties": {
            "authType": "ProjectManagedIdentity",
            "category": "RemoteTool",
            "target": mcp_endpoint(),
            "isSharedToAll": True,
            "audience": "https://search.azure.com/",
            "metadata": {"ApiType": "Azure"},
        },
    }
    response = requests.put(
        url,
        headers={"Authorization": f"Bearer {token_provider()}"},
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    print(f"Connection '{connection_name}' created or updated.")
    print(f"Target: {mcp_endpoint()}")


if __name__ == "__main__":
    main()

