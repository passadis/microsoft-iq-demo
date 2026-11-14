# Set up Contoso Service Intelligence

This guide recreates the **synthetic demo** in your own Azure and Microsoft 365 environment. The agent grounds policy answers in a Foundry IQ knowledge base, reads current case facts from Azure SQL, and proposes simulated credits that require an operator's approval. The approved request travels through a SQL outbox, Azure Service Bus and Azure Functions. A separate Fabric ontology knowledge base supplies business relationships.

**This is a guided deployment, not one-click provisioning.** The templates provision the original Foundry/Search resources and the additional integration resources. SharePoint or Blob ingestion, Fabric, SQL database setup, web hosting and Entra authentication require the steps below. Preview APIs, regional availability, model versions, quotas, tenant policies and portal screens can change. Azure and Fabric services incur charges. Do not deploy the sample unchanged for production.

## 1. Prerequisites and choices

- Azure subscription, Azure CLI with Bicep and Container Apps extension, PowerShell 7, Python 3.12 and permissions to create resources and role assignments. Sign in with `az login` and select the intended subscription with `az account set --subscription <subscription>`.
- Azure AI Search, Foundry project and compatible chat and embedding deployments in supported regions. Check [agentic retrieval prerequisites](https://learn.microsoft.com/en-us/azure/search/agentic-retrieval-overview) and [Function Flex Consumption regions](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-how-to). Model version and quota in the original template may need adjustment.
- A dedicated Azure SQL database and an Entra SQL administrator; permissions to configure network access and create database users. The sample data and credit records are fictional.
- For the **SharePoint path**, a Microsoft 365 site and library, supported SharePoint tenant configuration and permission to register/consent an Entra application. For the **Blob path**, access to a storage account. Choose one as the authoritative policy source for your demonstration.
- For the **Fabric path**, a Fabric capacity or trial, workspace, Warehouse, ontology and the permissions described in the [Fabric ontology knowledge-source prerequisites](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-fabric-ontology). This part is optional for policy and SQL demonstrations, but ontology questions will not work until configured.

Run commands from the repository root. Examples use placeholders: replace them with your own values. Storage, Service Bus, Function App and registry names must meet Azure naming rules and be globally unique. Do not commit local `.env` files, secrets, subscription IDs or generated configuration. `.gitignore` excludes `.env` files, including examples.

## 2. Foundry and Azure AI Search

**Use existing services:** If you already have a Foundry project, Search service and model deployments, use those. Record the project endpoint and resource ID, Search endpoint and model deployment names. Ensure the Foundry project has a managed identity; grant that identity **Search Index Data Reader** on Search and grant the Search managed identity **Cognitive Services User** on the model-hosting Foundry resource. Grant the deploying user the required Foundry and Search management/data roles. The resources can be in different resource groups; verify permissions and model connectivity in your tenant.

**Or create the original standalone resources:** Review [infra/main.bicep](infra/main.bicep) and [infra/README.md](infra/README.md), then run:

```powershell
./infra/deploy.ps1 -ResourceGroup '<resource-group>' -BaseName '<unique-short-base>' -Location '<region>'
```

Add `-DeployStorage` if using the bundled Blob scripts. The wrapper creates Foundry, a project, chat and embedding deployments and Search; it writes a local ignored `.env` and backs up an existing one. It does **not** create the complete solution. If reusing existing Foundry/Search, do not run this template against those resources: it creates its own. The template's Search/Foundry resources allow public network access and support local authentication by default; harden to your requirements.

For existing services, set the following in an ignored `.env` at the repository root (or export them as environment variables). Values are resource identifiers, not credentials:

```text
FOUNDRY_PROJECT_ENDPOINT=<your-project-endpoint>
FOUNDRY_PROJECT_RESOURCE_ID=<your-project-resource-id>
FOUNDRY_MODEL_DEPLOYMENT=<your-chat-deployment-name>
FOUNDRY_AGENT_NAME=contoso-service-intelligence-agent
AZURE_AI_SEARCH_ENDPOINT=<your-search-endpoint>
FOUNDRY_IQ_KNOWLEDGE_BASE=<your-policy-knowledge-base-name>
FOUNDRY_IQ_CONNECTION_NAME=contoso-service-kb-mcp
FOUNDRY_IQ_API_VERSION=2026-08-01-preview
FOUNDRY_CONNECTION_API_VERSION=2025-10-01-preview
```

Install the Python dependencies with `python -m venv .venv`, activate the environment and run `pip install -r requirements.txt`. Scripts authenticate through `DefaultAzureCredential`; run `az login` with the identity that has the required permissions.

## 3. Choose the policy knowledge source

### Option A: indexed SharePoint — the featured architecture

1. Put the approved policy documents in a dedicated SharePoint library. Review the [SharePoint indexer prerequisites and permissions matrix](https://learn.microsoft.com/en-us/azure/search/search-how-to-index-sharepoint-online#choose-your-permissions-setup). Choose delegated or application permissions, and grant the selected app access to the intended content. Restrict the indexed library using the documented custom query syntax rather than pasting a URL into the query field.
2. Follow [Create an indexed SharePoint knowledge source](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-sharepoint-indexed). Create the knowledge source, verify the indexer completes, and assign it to a knowledge base with a compatible model. Retrieve a policy answer and verify the attribution.
3. Set `FOUNDRY_IQ_KNOWLEDGE_BASE` to this policy knowledge base. The indexed source and the agent connection are separate: use [Connect agents to Foundry IQ](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/foundry-iq-connect) and step 5 below.

SharePoint indexing and related permission features are preview. This sample's project-identity MCP path has **not** been verified for per-user SharePoint document trimming. Do not treat it as an authorization boundary for sensitive documents without implementing and testing the documented security model. See [query-time permission enforcement](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-sharepoint-indexed#enforce-document-level-permissions).

### Option B: Azure Blob Storage — if SharePoint is unavailable

Blob can be the policy knowledge source instead. It still uses Foundry IQ and Azure AI Search; it does **not** demonstrate SharePoint integration. The bundled `scripts/create_knowledge_base.py` exists specifically for this alternative and is **not required** for the SharePoint path. It uploads three sample Markdown files, including a historical case fixture, to `demo-data`; SQL remains authoritative for current case facts. Avoid combining duplicate Blob and SharePoint copies as competing policy authorities.

For the original template, deploy with `-DeployStorage`, then run:

```powershell
python scripts/preflight.py
python scripts/create_knowledge_base.py
```

The script uses `STORAGE_ACCOUNT_NAME` and `EMBEDDING_MODEL_DEPLOYMENT` from the generated `.env`, creates the Blob knowledge source and knowledge base, and waits for ingestion. For existing services, provide those settings, the `demo-data` container, compatible embedding deployment, Search access and storage permissions explicitly. Its resource-ID construction assumes the storage account and Foundry resource are in the same subscription and resource group; otherwise adapt it or follow Microsoft's [Blob knowledge source guide](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-blob). Do not upload the restricted sample policy.

## 4. Azure SQL and integration resources

Create or use an Azure SQL server with an Entra administrator and create a **new dedicated** `ContosoServiceDemo` database. Allow the required Function and Container Apps network paths. In a SQL client connected to this database, run [01_create_and_seed.sql](sql/01_create_and_seed.sql). Do not run it against an existing application database.

Deploy the integration resources separately from Foundry. Edit all variables for your environment:

```powershell
$resourceGroup = '<resource-group>'
$location = '<region>'
$busName = '<globally-unique-service-bus-name>'
$storageName = '<globallyuniquestorage>'
$identityName = 'iq-demo-web-identity'
$queueName = 'approved-credit-requests'
$insightsName = 'contoso-credit-insights'
$functionName = '<globally-unique-function-app-name>'
$sqlServer = '<server>.database.windows.net'

az deployment group create -g $resourceGroup -n contoso-credit-services `
  -f infra/credit-services.bicep `
  -p location=$location serviceBusName=$busName functionStorageName=$storageName `
     identityName=$identityName queueName=$queueName appInsightsName=$insightsName
```

This creates a user-assigned managed identity, a **Standard** Service Bus namespace and queue, queue-scoped sender/receiver roles, Function storage, Log Analytics and Application Insights. It uses the same identity for web and Function for this demo; separate identities are preferable for a production boundary. Use new resource names and review changes with `az deployment group what-if` before reusing names: Bicep can update existing resources. Storage access for the Functions host/deployment can use platform-managed connection settings; do not assume it is fully identity-based.

As the database's Entra administrator, run [03_grant_app_access.sql](sql/03_grant_app_access.sql), [04_credit_requests.sql](sql/04_credit_requests.sql), and [05_credit_outbox.sql](sql/05_credit_outbox.sql), in that order. If you chose a different identity name, replace `iq-demo-web-identity` in all three scripts before running them. SQL **database permissions are necessary**; an Azure SQL Contributor role alone does not grant these table permissions. Review the database name guards and migration conditions in the scripts. See [the SQL guide](sql/README.md).

Create and publish a **new** Python 3.12 Flex Consumption Function App:

```powershell
./infra/deploy-credit-function.ps1 -ResourceGroup $resourceGroup -Location $location `
  -FunctionAppName $functionName -StorageAccountName $storageName `
  -IdentityName $identityName -ServiceBusName $busName -AppInsightsName $insightsName `
  -SqlServer $sqlServer -QueueName $queueName
```

The script refuses to replace an existing Function App, attaches the identity, sets SQL and identity-based Service Bus connection settings, and publishes the source with a Linux remote build. If interrupted after creation, inspect the existing app and finish configuration/deployment explicitly; do not assume rerunning this create-only script completes it. Check that all three Functions appear: `publish_credit_outbox`, `process_service_credit`, and `monitor_credit_requests`. Role propagation and telemetry can take time. See the [processor guide](credit-processor/README.md).

## 5. Policy connection and agent

Once the chosen policy knowledge base exists and `.env` points to it, run:

```powershell
python scripts/create_connection.py
python scripts/create_agent.py
```

The first script creates or updates the Foundry project MCP connection using the project managed identity; the second creates a Prompt Agent version with the policy MCP tool and the SQL, Fabric and credit-request function definitions. These scripts do not create the SharePoint knowledge source or Fabric ontology. Their preview API versions may require updates. The host web app executes function calls; merely adding a function definition to the agent does not execute it. The operator approval gate is enforced by the application.

## 6. Fabric ontology and separate knowledge base

1. Copy the relevant Azure SQL tables into a Fabric Warehouse using a Fabric copy job. Configure a suitable refresh strategy and validate updates and deletes; this demo uses a warehouse snapshot that can lag SQL. The original mirroring attempt was replaced by a copy job. See [Fabric copy job](https://learn.microsoft.com/en-us/fabric/data-factory/what-is-copy-job).
2. Create and publish an ontology, bind entities to warehouse tables and configure relationships. Use [CONTOSO-ONTOLOGY-GUIDE.md](CONTOSO-ONTOLOGY-GUIDE.md) as a starting mapping, and [Fabric ontology documentation](https://learn.microsoft.com/en-us/fabric/iq/ontology/overview) for current authoring and binding behavior. Test customers, regions and relationships in Fabric before connecting Search.
3. Create a **separate** Fabric ontology knowledge source and knowledge base in Search, following [Microsoft's Fabric ontology knowledge-source guide](https://learn.microsoft.com/en-us/azure/search/agentic-knowledge-source-how-to-fabric-ontology). Use the documented supported reasoning effort and test with a delegated user token. Record the Search endpoint, knowledge source name and knowledge base name for the web app.

Fabric queries require a signed-in user with access to Search and Fabric and an Azure AI Search audience token. The app forwards the token to the knowledge-base retrieve endpoint; it does not use the policy MCP connection for Fabric. Test user access and data freshness. Without this path, the agent can still handle SQL and policy questions, but ontology requests return an unavailable result.

## 7. Host and secure the web app

Build `webapp/Dockerfile` from the repository root and publish it to an Azure Container Registry. Create an Azure Container Apps environment and app, attach the **same user-assigned identity** created in step 4, and configure private-registry pull permissions. Follow [managed-identity image pull](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull). The sample uses port 8000 and one replica; its in-memory conversation state is intended for a single presenter.

For example, for a new demo environment and a non-ABAC registry, replace the placeholders and run:

```powershell
$registry = '<globally-unique-registry-name>'
$containerEnv = '<container-apps-environment-name>'
$webApp = '<container-app-name>'
$projectEndpoint = '<foundry-project-endpoint>'
$fabricEndpoint = '<fabric-knowledge-search-endpoint>'
$fabricKb = '<fabric-knowledge-base-name>'
$fabricSource = '<fabric-knowledge-source-name>'

$identity = az identity show -g $resourceGroup -n $identityName -o json | ConvertFrom-Json
az acr create -g $resourceGroup -n $registry --sku Basic
az acr build -r $registry -f webapp/Dockerfile -t contoso-web:v1 .
$registryId = az acr show -g $resourceGroup -n $registry --query id -o tsv
az role assignment create --assignee-object-id $identity.principalId `
  --assignee-principal-type ServicePrincipal --role AcrPull --scope $registryId
az containerapp env create -g $resourceGroup -n $containerEnv -l $location

az containerapp create -g $resourceGroup -n $webApp --environment $containerEnv `
  --image "$registry.azurecr.io/contoso-web:v1" --registry-server "$registry.azurecr.io" `
  --user-assigned $identity.id --registry-identity $identity.id `
  --ingress internal --target-port 8000 --min-replicas 1 --max-replicas 1 `
  --env-vars "FOUNDRY_PROJECT_ENDPOINT=$projectEndpoint" `
    'FOUNDRY_AGENT_NAME=contoso-service-intelligence-agent' "AZURE_CLIENT_ID=$($identity.clientId)" `
    "SQL_SERVER=$sqlServer" 'SQL_DATABASE=ContosoServiceDemo' `
    "FABRIC_IQ_SEARCH_ENDPOINT=$fabricEndpoint" "FABRIC_IQ_KNOWLEDGE_BASE=$fabricKb" `
    "FABRIC_IQ_KNOWLEDGE_SOURCE=$fabricSource"
```

RBAC changes may take time to propagate; retry a failed image pull after verifying the assignment. Omit the three Fabric settings if not demonstrating Fabric. This starts with internal ingress so it is not publicly exposed during authentication setup. After configuring and testing Entra authentication, change the ingress to external if required for your demo. Follow your organization's network rules; internal ingress requires a compatible access path for browser testing.

Set these app settings (using your values):

| Setting | Purpose |
|---|---|
| `FOUNDRY_PROJECT_ENDPOINT`, `FOUNDRY_AGENT_NAME` | Project and Prompt Agent |
| `AZURE_CLIENT_ID` | Client ID of the attached user-assigned identity |
| `SQL_SERVER`, `SQL_DATABASE` | Azure SQL host and `ContosoServiceDemo` |
| `FABRIC_IQ_SEARCH_ENDPOINT`, `FABRIC_IQ_KNOWLEDGE_BASE`, `FABRIC_IQ_KNOWLEDGE_SOURCE` | Separate Fabric knowledge source; omit only when not demonstrating Fabric |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Store as a Container Apps secret and reference it from the setting; do not commit or print it |

Give the app identity a Foundry role that permits agent invocation, such as the applicable **Azure AI User / Foundry User** role, at the project or resource scope. SQL permissions were granted in step 4. Configure [Container Apps authentication](https://learn.microsoft.com/en-us/azure/container-apps/authentication) with an Entra app registration, require sign-in, and restrict access to intended users **before** sharing the ingress URL. The app relies on platform-provided identity headers; do not expose it without authentication.

For Fabric, request the delegated Azure AI Search `user_impersonation` scope in the Entra app and authentication configuration, configure consent, and enable the [Container Apps token store](https://learn.microsoft.com/en-us/azure/container-apps/token-store) using a private Blob container and an identity with the required storage data access. Verify that a signed-in request provides `X-MS-TOKEN-AAD-ACCESS-TOKEN` for Search; users also need Fabric permissions. Never log or publish tokens. A browser end-to-end Fabric test is required in each deployment.

Connect the Foundry project to the same Application Insights component for server-side agent tracing, following [Foundry tracing setup](https://learn.microsoft.com/en-us/azure/foundry/tutorials/quickstart-create-foundry-resources?tabs=portal). Check access and retention for prompts and retrieved content.

## 8. Alerts and recovery

Create an Azure Monitor action group with your chosen notification receiver and verify the email address when requested. Deploy [infra/credit-monitoring.bicep](infra/credit-monitoring.bicep), supplying your Application Insights name, Service Bus namespace, queue name, **action group resource ID**, and Application Insights location:

```powershell
$actionGroupId = '<existing-action-group-resource-id>'
az deployment group create -g $resourceGroup -n contoso-credit-monitoring `
  -f infra/credit-monitoring.bicep -p appInsightsName=$insightsName `
  serviceBusNamespaceName=$busName queueName=$queueName actionGroupId=$actionGroupId location=$location
```

Rules detect a dead-lettered message, a request stuck for more than ten minutes, and a missing SQL-monitor heartbeat over 30 minutes. Check [the processor runbook](credit-processor/README.md#test-notifications-and-the-dead-letter-alert) for safe test and recovery steps. Alert configuration, firing, email delivery and replay must be tested in your deployment.

## 9. Verify the demonstration

Open your Container App's application URL from the Azure portal and sign in. Select `CASE-1042`, ask for case facts and applicable policy, and inspect the document attribution. Ask for an eligible credit, review the allocations, and approve or decline. For an approved request, allow the timer publisher to run and check request status and simulated credit history. No real refund is made. Then ask a question about customers and regions to test the separately configured Fabric path. See [demo prompts](demo-prompts.txt).

Use Application Insights to inspect agent, web and Function telemetry and the request ID to correlate processing. `sql/02_reset_demo_statuses.sql` resets only case statuses, not requests, outbox records or credit history. Existing issued or simulated appointment credits prevent another simulated credit; prepare fresh synthetic data for repeated action demonstrations.

Local tests are described in [the processor guide](credit-processor/README.md#local-tests); they use mocks and do not replace the signed-in Azure end-to-end checks above. Remove only resources you created for the demo when finished, after reviewing dependencies and retention requirements.
