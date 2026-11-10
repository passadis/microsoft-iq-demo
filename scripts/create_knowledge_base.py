"""Create the Foundry IQ knowledge base end to end, without the portal.

Steps:
1. Upload the three approved data/ files to the demo-data blob container
   (never restricted-executive-policy.md).
2. Create a blob knowledge source on Azure AI Search (2026-08-01-preview),
   which generates the data source, skillset, index, and indexer.
3. Poll ingestion until the initial synchronization completes.
4. Create the knowledge base that the MCP endpoint serves.

Auth is keyless: your signed-in identity needs Search Service Contributor +
Search Index Data Contributor on the search service and Storage Blob Data
Contributor (or Owner) on the storage account. The search service's managed
identity reads blobs and calls the embedding model (roles assigned by infra).
"""
from __future__ import annotations

import json
import sys
import time

import requests
from azure.identity import DefaultAzureCredential

from common import ROOT, setting, validate_settings

SEARCH_API_VERSION = "2026-08-01-preview"
KNOWLEDGE_SOURCE_NAME = "contoso-service-src"
CONTAINER = "demo-data"
DATA_FILES = (
    "customer-case-1042.md",
    "service-credit-policy.md",
    "service-operations-runbook.md",
)


def _parse_project_resource_id() -> dict:
    # /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.CognitiveServices
    # /accounts/<account>/projects/<project>
    parts = setting("FOUNDRY_PROJECT_RESOURCE_ID").strip("/").split("/")
    return {
        "subscription": parts[1],
        "resource_group": parts[3],
        "account": parts[7],
    }


def _token(credential: DefaultAzureCredential, scope: str) -> str:
    return credential.get_token(scope).token


def upload_data(credential: DefaultAzureCredential, storage_account: str) -> None:
    token = _token(credential, "https://storage.azure.com/.default")
    for name in DATA_FILES:
        content = (ROOT / "data" / name).read_bytes()
        url = f"https://{storage_account}.blob.core.windows.net/{CONTAINER}/{name}"
        response = requests.put(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "x-ms-version": "2023-11-03",
                "x-ms-blob-type": "BlockBlob",
                "Content-Type": "text/markdown",
            },
            data=content,
            timeout=60,
        )
        response.raise_for_status()
        print(f"Uploaded {name} ({len(content)} bytes)")


def create_knowledge_source(credential: DefaultAzureCredential, ids: dict, storage_account: str) -> None:
    search_endpoint = setting("AZURE_AI_SEARCH_ENDPOINT").rstrip("/")
    storage_resource_id = (
        f"/subscriptions/{ids['subscription']}/resourceGroups/{ids['resource_group']}"
        f"/providers/Microsoft.Storage/storageAccounts/{storage_account}"
    )
    payload = {
        "name": KNOWLEDGE_SOURCE_NAME,
        "kind": "azureBlob",
        "description": "Approved Contoso service-credit documents (case record, policy, runbook).",
        "azureBlobParameters": {
            "connectionString": f"ResourceId={storage_resource_id}",
            "containerName": CONTAINER,
            "isADLSGen2": False,
            "ingestionParameters": {
                "contentExtractionMode": "minimal",
                "disableImageVerbalization": True,
                "embeddingModel": {
                    "kind": "azureOpenAI",
                    "azureOpenAIParameters": {
                        "resourceUri": f"https://{ids['account']}.openai.azure.com",
                        "deploymentId": setting("EMBEDDING_MODEL_DEPLOYMENT", "text-embedding-3-small"),
                        "modelName": setting("EMBEDDING_MODEL_DEPLOYMENT", "text-embedding-3-small"),
                    },
                },
            },
        },
    }
    token = _token(credential, "https://search.azure.com/.default")
    response = requests.put(
        f"{search_endpoint}/knowledgesources/{KNOWLEDGE_SOURCE_NAME}?api-version={SEARCH_API_VERSION}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Knowledge source failed ({response.status_code}): {response.text}")
    print(f"Knowledge source '{KNOWLEDGE_SOURCE_NAME}' created or updated.")


def wait_for_ingestion(credential: DefaultAzureCredential, timeout_minutes: int = 20) -> None:
    search_endpoint = setting("AZURE_AI_SEARCH_ENDPOINT").rstrip("/")
    url = (
        f"{search_endpoint}/knowledgesources/{KNOWLEDGE_SOURCE_NAME}/status"
        f"?api-version={SEARCH_API_VERSION}"
    )
    deadline = time.monotonic() + timeout_minutes * 60
    while time.monotonic() < deadline:
        token = _token(credential, "https://search.azure.com/.default")
        status = requests.get(
            url, headers={"Authorization": f"Bearer {token}"}, timeout=60
        ).json()
        last = status.get("lastSynchronizationState") or {}
        processed = last.get("itemUpdatesProcessed")
        failed = last.get("itemsUpdatesFailed")
        if last.get("endTime"):
            if failed:
                raise RuntimeError(f"Ingestion finished with failures: {json.dumps(last, indent=2)}")
            print(f"Ingestion complete: {processed} item(s) processed.")
            return
        print(f"  ingestion running (processed so far: {processed})...")
        time.sleep(20)
    raise TimeoutError("Ingestion did not complete in time. Check the indexer in the Azure portal.")


def create_knowledge_base(credential: DefaultAzureCredential, ids: dict) -> None:
    search_endpoint = setting("AZURE_AI_SEARCH_ENDPOINT").rstrip("/")
    kb_name = setting("FOUNDRY_IQ_KNOWLEDGE_BASE")
    # The MCP retrieve path requires a knowledge-base model for any reasoning
    # effort above minimal; the search managed identity calls it for query
    # planning (Cognitive Services User role assigned by infra).
    payload = {
        "name": kb_name,
        "description": "Contoso service-credit decisions: case record, approved policy, and runbook.",
        "knowledgeSources": [{"name": KNOWLEDGE_SOURCE_NAME}],
        "retrievalInstructions": (
            "Prioritize approved policy and runbook documents over informal case notes. "
            "Reconcile facts across sources. If sources conflict, identify the conflict. "
            "Return source references with every material conclusion. "
            "Do not infer approval or authorization from customer tier."
        ),
        "models": [
            {
                "kind": "azureOpenAI",
                "azureOpenAIParameters": {
                    "resourceUri": f"https://{ids['account']}.openai.azure.com",
                    "deploymentId": setting("FOUNDRY_MODEL_DEPLOYMENT"),
                    "modelName": setting("FOUNDRY_MODEL_DEPLOYMENT"),
                },
            }
        ],
    }
    token = _token(credential, "https://search.azure.com/.default")
    response = requests.put(
        f"{search_endpoint}/knowledgebases/{kb_name}?api-version={SEARCH_API_VERSION}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Knowledge base failed ({response.status_code}): {response.text}")
    print(f"Knowledge base '{kb_name}' created or updated.")


def main() -> None:
    missing = validate_settings()
    if missing:
        raise RuntimeError(f"Complete .env first. Missing: {', '.join(missing)}")
    storage_account = setting("STORAGE_ACCOUNT_NAME")
    ids = _parse_project_resource_id()
    credential = DefaultAzureCredential()

    upload_data(credential, storage_account)
    create_knowledge_source(credential, ids, storage_account)
    wait_for_ingestion(credential)
    create_knowledge_base(credential, ids)
    print("\nDone. Next: python scripts/create_connection.py, then python scripts/create_agent.py")


if __name__ == "__main__":
    sys.exit(main())
