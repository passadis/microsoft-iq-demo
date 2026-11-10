# Infrastructure as code

Bicep template plus a PowerShell wrapper that provisions everything the demo needs on Azure and writes the repo's `.env` from the deployment outputs.

## What it deploys

- **Microsoft Foundry resource** (`AIServices` kind, S0, project management enabled, system-assigned identity).
- **Foundry project** (current project type — not hub-based — as the demo requires).
- **Model deployment**: `gpt-4.1-mini` on GlobalStandard (version and capacity are parameters).
- **Azure AI Search** (basic tier, semantic ranking `standard`, AAD + key auth, system-assigned identity).
- **Role assignments**:
  - project identity → *Search Index Data Reader* on the search service (MCP retrieval);
  - search identity → *Cognitive Services User* on the Foundry resource (knowledge-base planning/synthesis);
  - presenter → *Azure AI User* + *Azure AI Project Manager* on Foundry, *Search Service Contributor* + *Search Index Data Contributor* on search. Tenants with the renamed Foundry roles show these as Foundry User / Foundry Project Manager.
- **Optional** (`-DeployStorage`): Standard_LRS storage account with a `demo-data` container and *Storage Blob Data Reader* for the search identity, for the production-aligned Blob knowledge source.

## What it deliberately does not deploy

These are data-plane or preview-portal steps that ARM does not cover; run them after deployment in this order:

1. Create the knowledge base `contoso-service-kb` in the Foundry portal and upload the three main `data/` files (see the root README's "Prepare the knowledge base" — never upload `restricted-executive-policy.md`).
2. `python scripts/create_connection.py` — the project MCP connection.
3. `python scripts/create_agent.py` — the agent version.

## Usage

```powershell
cd infra
./deploy.ps1 -ResourceGroup rg-iq-demo -BaseName contosoiq
```

Parameters:

- `-Location` (default `swedencentral`) — pick a region where `gpt-4.1-mini` GlobalStandard and Azure AI Search are available.
- `-PrincipalId` — defaults to the signed-in user's object ID; pass explicitly when deploying on behalf of another presenter.
- `-DeployStorage` — adds the Blob knowledge-source resources.
- `-SkipEnv` — deploy without touching `.env` (an existing `.env` is otherwise backed up first).

The deployment is idempotent — re-running updates in place.

## Teardown

```powershell
az group delete --name rg-iq-demo --yes --no-wait
```

## Notes

- Role assignments can take a few minutes to propagate; if `preflight.py` or the first agent run hits 401/403, wait and retry before debugging.
- `disableLocalAuth` on the Foundry resource defaults to `false` to keep demo-day portal flows friction-free; set it `true` for a hardened setup.
- Verify the built-in role GUIDs against your tenant if assignments fail (`az role definition list --name "Azure AI User"`); the Foundry role rename is still rolling out.
