# Web app

A FastAPI backend plus a single static chat page that runs the same demo as `scripts/run_demo.py`, with the approval gate as on-screen **Approve & submit / Decline** buttons — usually the stronger way to show governance to an audience.

Why this shape:

- **Not Static Web Apps**: the app must hold an Azure credential server-side (`DefaultAzureCredential` → Foundry project endpoint), so a pure static host cannot run it.
- **No Vite/Astro**: the frontend is one dependency-free HTML page; a Node build pipeline adds nothing.
- **Container Apps** is the recommended cloud target: system-assigned managed identity works with the existing auth code unchanged, and scale-to-zero keeps it nearly free.

## Endpoints

- `GET /api/cases` — list pending and resolved demo cases from SQL.
- `POST /api/cases/{case_id}/status` — mark a case `Pending` or `Resolved`.
- `POST /api/chat` — send a prompt; returns either a `message` or an `action_request` with the proposed function arguments.
- `POST /api/decision` — approve or decline a pending action; the backend enforces the €150 limit and writes the audit record, then lets the agent phrase the outcome.
- `GET /api/audit`, `GET /api/prompts`, `GET /api/status`, `POST /api/reset`.

The case list requires `SQL_SERVER` and `SQL_DATABASE`. The Container App uses its managed identity and the database grants in `sql/03_grant_app_access.sql`; local development uses an Azure CLI identity through `DefaultAzureCredential`. Select a case to start a new conversation grounded in current SQL records; the agent retrieves policy from Foundry IQ. A case status update does not submit a credit. To reset the five demo case statuses, run `sql/02_reset_demo_statuses.sql` in the database.

The agent can also request `query_fabric_ontology`, which the web app executes against the separate Foundry IQ Fabric ontology knowledge base. Configure `FABRIC_IQ_SEARCH_ENDPOINT`, `FABRIC_IQ_KNOWLEDGE_BASE` and `FABRIC_IQ_KNOWLEDGE_SOURCE`. Container Apps authentication must provide the signed-in user's delegated Azure AI Search access token; the user needs access to both Search and the Fabric ontology. The deployed app requests `https://search.azure.com/user_impersonation` and uses its managed-identity-backed authentication token store. Reauthenticate and consent if prompted. Fabric data is a warehouse snapshot; SQL remains authoritative for current case decisions. The standalone Foundry playground cannot execute this client-side function without a host that handles it.

## Run locally (recommended for the stage)

```powershell
pip install -r webapp/requirements.txt
az login
uvicorn webapp.app:app --port 8000
# open http://localhost:8000
```

Rehearsal mode — same UI, deterministic answers, zero Azure calls (the header badge shows **Rehearsal**):

```powershell
$env:DEMO_REHEARSAL = '1'; uvicorn webapp.app:app --port 8000
```

Keep a rehearsal-mode instance on a second port as your on-stage fallback.

## Run in Docker

```powershell
docker build -f webapp/Dockerfile -t iq-demo-web .
docker run -p 8000:8000 -e DEMO_REHEARSAL=1 iq-demo-web
```

The live path in a local container needs a credential; easiest is to test live locally with uvicorn (`az login`) and use containers for ACA.

## Deploy to Azure Container Apps (optional leave-behind)

```powershell
$RG = 'rg-iq-demo'; $ACR = 'iqdemoacr123'   # ACR name must be globally unique

az acr create -n $ACR -g $RG --sku Basic
az acr build -r $ACR -f webapp/Dockerfile -t iq-demo-web:latest .

az containerapp env create -n iq-demo-env -g $RG -l swedencentral

az containerapp create -n iq-demo-web -g $RG --environment iq-demo-env `
  --image "$ACR.azurecr.io/iq-demo-web:latest" `
  --registry-server "$ACR.azurecr.io" --registry-identity system `
  --system-assigned --target-port 8000 --ingress external `
  --min-replicas 0 --max-replicas 1 `
  --env-vars FOUNDRY_PROJECT_ENDPOINT='<from .env>' FOUNDRY_AGENT_NAME='contoso-service-intelligence-agent'

# Let the app's managed identity call the Foundry project:
$APP_MI = az containerapp show -n iq-demo-web -g $RG --query identity.principalId -o tsv
$FOUNDRY_ID = az cognitiveservices account show -n <baseName>-foundry -g $RG --query id -o tsv
# Use the role ID: tenants with the renamed Foundry roles reject the old "Azure AI User" name
az role assignment create --assignee-object-id $APP_MI --assignee-principal-type ServicePrincipal `
  --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope $FOUNDRY_ID
```

**Before sharing the URL**: `--ingress external` makes the chat public, and anyone reaching it can spend your model quota and approve demo actions. Either keep it for the session only and delete after, restrict access with Container Apps authentication (Entra ID via `az containerapp auth microsoft update`), or use `--ingress internal` behind your own network.

Also note the audit JSONL is written inside the container, so it resets on restart — fine for a demo, one more reason the production path replaces it with a real action service.
