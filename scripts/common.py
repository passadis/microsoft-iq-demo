from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


REQUIRED_SETTINGS = (
    "FOUNDRY_PROJECT_ENDPOINT",
    "FOUNDRY_PROJECT_RESOURCE_ID",
    "FOUNDRY_MODEL_DEPLOYMENT",
    "FOUNDRY_AGENT_NAME",
    "AZURE_AI_SEARCH_ENDPOINT",
    "FOUNDRY_IQ_KNOWLEDGE_BASE",
    "FOUNDRY_IQ_CONNECTION_NAME",
)


def setting(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or not value.strip():
        raise RuntimeError(f"Missing required setting: {name}")
    return value.strip()


def validate_settings() -> list[str]:
    return [name for name in REQUIRED_SETTINGS if not os.getenv(name, "").strip()]


def mcp_endpoint() -> str:
    search_endpoint = setting("AZURE_AI_SEARCH_ENDPOINT").rstrip("/")
    kb_name = setting("FOUNDRY_IQ_KNOWLEDGE_BASE")
    api_version = setting("FOUNDRY_IQ_API_VERSION", "2026-08-01-preview")
    return f"{search_endpoint}/knowledgebases/{kb_name}/mcp?api-version={api_version}"


def connection_id() -> str:
    """Full ARM resource ID of the project connection created by create_connection.py."""
    resource_id = setting("FOUNDRY_PROJECT_RESOURCE_ID").rstrip("/")
    return f"{resource_id}/connections/{setting('FOUNDRY_IQ_CONNECTION_NAME')}"

