# Contoso Service Intelligence: project log and backlog

Last updated: 2026-11-14. This is a working record of decisions, activities and follow-up work for the synthetic live demo. Azure and preview-service details can change; verify live settings before an event or a new deployment.

- Added and deployed a five-minute, read-only SQL monitor for credit request age, with a healthy heartbeat and a ten-minute stuck threshold. Azure Monitor rules watch stuck requests, missing heartbeats over 30 minutes, and the Service Bus dead-letter count; an action group has an email receiver. Application Insights recorded a successful heartbeat with zero stuck requests. Alert firing, notification delivery and dead-letter replay still need an end-to-end exercise. See the credit processor runbook and `infra/credit-monitoring.bicep`.
- Added runbook instructions to test email separately and to trigger and clean up a deliberately invalid dead-letter test message in a dedicated demo environment. These are instructions, not a record of a completed test.
- Refactored the web application's two read-tool dispatch paths into one allowlist and tested mixed read/action calls. This web change is local; it was not part of the Function deployment.

- Updated the README to direct readers to their own deployed Container App instead of a temporary hosted demo URL; the original infrastructure scripts do not deploy the complete integration.

## Purpose and scenario

Contoso Home Services is a fictional field-service company. The demo shows an operator asking about customer cases, an agent combining current case data with approved policy, and an operator reviewing a proposed service-credit action. All customer and case data is synthetic. See `data/contoso-company-overview.md` for the company story.

Customer `C-1042` and case `CASE-1042` are different identifiers. The case has two provider no-shows, `A-7781` and `A-7829`. Under the demo policy CSP-014 v4.2, an eligible missed appointment may receive up to €75, the frontline combined-request threshold is €150, and requests over that threshold require manager approval. The example customer requests €180. These are fictional demo policy rules.

## Current demo architecture

```text
Operator -> Container Apps web UI -> Foundry Prompt Agent
                         |                  |
                         |                  +-> MCP connection -> Foundry IQ knowledge base
                         |                                          -> indexed SharePoint policy source
                         +-> SQL lookup function -> Azure SQL cases and appointments
                         +-> Fabric function -> Foundry IQ -> Fabric ontology and warehouse
                         +-> operator case-status changes -> Azure SQL
                         +-> approval-gated request -> Azure SQL -> Service Bus -> Azure Function
                         +-> web telemetry and Foundry/Function traces -> Application Insights
```

- **Web app:** `iq-demo-web` in Container Apps, with Microsoft Entra sign-in. It lists SQL cases, lets an operator choose a case and set it to Pending or Resolved, and starts a new conversation on case selection.
- **Agent:** managed Foundry Prompt Agent `contoso-service-intelligence-agent` in project `ai-service-iq` on Foundry resource `aiservices-kp`. Version 5 uses SharePoint policies; version 6 adds a client-executed Fabric tool; version 8 adds case and appointment allocations; version 10 clarifies missing-evidence handling and attribution. It is not an implementation using Microsoft Agent Framework.
- **Current case facts:** Azure SQL Database `ContosoServiceDemo`. It contains Customers, Cases, Appointments and CreditHistory, initially seeded with five synthetic cases. `get_case_details` is a client-executed, parameterized lookup: the agent requests it and the Container App executes it.
- **Current agent policy source:** Search service `iqdemo7f3c9-search`, indexed SharePoint source `knowledgesource-1794233986722`, knowledge base `contoso-sharepoint-test-kb`, and project MCP connection `contoso-sharepoint-kb-mcp`. The test-named knowledge base is now the agent's active policy source.
- **Preserved Blob path:** `contoso-service-kb`, Blob-backed source `contoso-service-src-v2`, and project connection `contoso-service-kb-mcp` remain intact as a fallback. The original `contoso-service-src` also remains from the earlier deployment. The Blob corpus contains a static case document, but it is not in the agent's current SharePoint knowledge base; SQL is authoritative for current case facts.
- **Fabric ontology:** `contosoiq` in Fabric workspace `Datalycs`, queried through Search source `knowledgesource-fabiq` and the isolated `contoso-fabric-ontology-test-kb`. The `query_fabric_ontology` function is requested by the agent and executed by the web app using the current user's delegated Search token. The user needs access to Search and Fabric. Fabric is a warehouse snapshot, while SQL remains authoritative for current case decisions.
- **Identities:** the Container App's user-assigned identity `iq-demo-web-identity` calls Foundry and runs SQL queries. It has SELECT on the four demo tables and UPDATE only on `dbo.Cases.CaseStatus` and `UpdatedAtUtc`. The Foundry project identity accesses Search via the MCP connection. The SharePoint indexer uses its own application/identity configuration; these are distinct permission paths.
- **Credit action:** the agent proposes `create_service_credit_request`; the app requires explicit operator approval, validates per-appointment allocations, and enforces the demo's €150 request and €75 appointment limits. A SQL transaction saves the request, allocations and outbox record. A timer-triggered Function publishes the request ID to Service Bus; a queue-triggered Function atomically records `Simulated` appointment credits and marks the request `Processed`. Duplicate deliveries of a processed request are no-ops. No payment or actual refund occurs. Offline rehearsal still writes local JSONL.
- **Observability:** Application Insights `iq-demo-insights` is connected to the Foundry project and used by the web app and Function. Foundry model telemetry and a synthetic Function processing event were observed; signed-in browser-to-Function correlation remains to be verified. The request ID is the current cross-component correlation key.

Useful operating notes: `webapp/README.md`, `sql/README.md`, `sql/02_reset_demo_statuses.sql`, and `sql/03_grant_app_access.sql`. The status reset changes only the five seeded case statuses; it does not remove credit history or audit records. The web app's New conversation button resets chat state, not SQL case statuses.

## Decisions

| Decision | Rationale and boundaries |
| --- | --- |
| Keep the agent as a Foundry Prompt Agent. | The agent should be visible in Foundry; the existing app executes custom functions requested by it. |
| Use SQL for current cases and appointment history. | Structured, current case facts should not depend on an indexed snapshot. Missing facts remain unknown, not assumed false. |
| Keep policy retrieval and case lookup separate. | Foundry IQ supplies policy evidence and citations; the SQL lookup supplies current operational facts. |
| Keep a person in the credit-action loop. | The agent proposes; the app requires operator approval and enforces the demo's €150 frontline limit. Marking a case resolved is a separate status update and does not issue a credit. |
| Move toward SharePoint as the authoritative policy home. | Business users maintain approved Word/PDF documents there. Use Blob and SharePoint for different purposes if needed, but avoid presenting competing copies of the same active policy as equally authoritative. |
| Switch the agent to the separate SharePoint knowledge base for testing. | Preserve the existing Blob knowledge base and connection intact as a fallback while the agent uses the SharePoint source. |
| Keep a separate SharePoint test knowledge base. | It isolates SharePoint documents from the preserved Blob-backed `contoso-service-kb` and avoids duplicate policy sources in the active agent path. |
| Do not assume document-level permissions are enforced. | The current app/project managed-identity setup is not evidence of per-user SharePoint security trimming. Indexed SharePoint ACL ingestion and user-token passthrough require separate configuration and tests. |
| Keep the policy-preparation agent optional. | Direct SharePoint indexing can process Word/PDF policies. A future agent could review, structure or compare policy versions, with human approval before publication. |
| Use the Fabric copy job and warehouse for the ontology. | The user abandoned mirroring after an ontology binding issue. The warehouse can lag Azure SQL, so current case decisions still use SQL. |
| Prefer natural business questions when evaluating the agent. | Source-specific prompts remain useful for troubleshooting; future tests should assess whether the agent selects the appropriate tools without being told their names. |

## Activity and verification

### Initial live demo and recovery

- Built and deployed the Foundry/AI Search service-credit demo with a managed Prompt Agent, read-only MCP retrieval, a web UI and an approval-gated simulated credit action.
- Foundry project provisioning failed in the original Sweden Central account. A later East US 2 retry returned `InternalServerError` for project creation. Model quota was not established as the cause. The user created project `ai-service-iq` in the existing `aiservices-kp` resource, and the demo was connected to it.
- The original Blob knowledge source was tied to the deleted Foundry account and Azure rejected changing its embedding-model configuration. Created `contoso-service-src-v2` in the existing Search service; its first verified ingestion processed three documents without errors. Connected the current knowledge base and agent to that source.
- Tested a direct agent conversation: it returned the €150 frontline threshold and cited the policy/runbook. Updated the web app to display document names from citation metadata instead of raw citation markers; the user confirmed the presentation looked good.
- Added a short fictional company overview in `data/contoso-company-overview.md`. It was created locally and was not confirmed as uploaded to the active knowledge base.

### SQL cases and web UI

- Prepared `sql/01_create_and_seed.sql` and `sql/02_reset_demo_statuses.sql`; the user created the database and ran the seed queries.
- Added SQL case retrieval, a case list, case selection, Pending/Resolved controls and a read-only `get_case_details` agent function. The active Prompt Agent was updated to version 2 and the Container App image to `cases-v2`.
- Executed `sql/03_grant_app_access.sql` as the configured Entra administrator. Tested the deployed Container App identity reading five cases and updating `CASE-1042` to its existing Pending status. A separate agent conversation retrieved appointment IDs `A-7781` and `A-7829`. The web revision was healthy and receiving traffic; a signed-in browser end-to-end test was not recorded.

### SharePoint preview test

- Chose application permissions for unattended indexing and discussed a federated credential using the Search identity. A SharePoint ingestion connection is distinct from the agent's existing MCP connection; indexing access does not automatically enforce each user's SharePoint permissions.
- The user created indexed SharePoint source `knowledgesource-1794233986722`. Its first observed synchronization processed four items with zero failures. The indexed documents were Advanced Hardware Replacement, Customer Account Authentication, Field Service Site Safety and Service Credit Issuance, all `.docx`.
- Created `contoso-sharepoint-test-kb` with that source only and the existing `gpt-4.1-mini` deployment. A direct knowledge-base answer-synthesis test reported the €75 per-appointment and €150 frontline limits and referenced `Service Credit Issuance.docx`. The response included a Search citation URL and SharePoint document identifier; a direct browser link to the original document was not verified.
- Initially this was a direct knowledge-base test. The user subsequently requested a switch: created `contoso-sharepoint-kb-mcp`, updated the existing Prompt Agent to use the SharePoint knowledge base, and kept the Blob path intact. Agent version 5 adds clear instructions that an operator must approve a request even when manager approval is not required.
- Tested a read-only case conversation using the web app's response handling: current SQL case facts and the SharePoint policy were returned, with `Service Credit Issuance.docx` displayed as the policy source. Added filename handling for SharePoint citation paths and deployed Container App image `sharepoint-v1`. The user still needs to test the signed-in web UI. The current SharePoint source does not contain the former Blob runbook; the agent must not claim to have retrieved it.

### Fabric ontology preview test

- The user reported that a Fabric copy job to a new warehouse worked around an empty mirrored-database picker when binding ontology data. The cause was not established.
- The user created Fabric ontology knowledge source `knowledgesource-fabiq` with an initially incorrect workspace reference. Created isolated knowledge base `contoso-fabric-ontology-test-kb`, using low reasoning and the existing model; neither the active SharePoint knowledge base nor the agent was changed at that point.
- Two direct retrievals on 2026-11-10 failed with 502 and a generic Fabric ontology connection error; no answer or citation was verified. The signed-in Azure CLI identity's Fabric API returned WorkspaceNotFound for the configured workspace and listed only My workspace. An inaccessible workspace, different identity or tenant, or incorrect identifier are possibilities, not established causes. Verify the Fabric workspace and ontology IDs and caller access, then retry.
- After the user granted workspace Admin, Fabric listed the intended workspace and ontology `contosoiq`. Corrected `knowledgesource-fabiq` to that workspace; a subsequent retrieval returned a Fabric reference and correctly associated CASE-1042 with C-1042/Alex Morgan. The first query immediately after the update still used the old workspace ID; subsequent queries used the corrected ID.
- Retrieval returned 290 customers and five repeated rows for C-1042, unlike the five-customer original seed. The cause is unverified; compare warehouse total and distinct IDs before changing data. The ontology definition connects Customer.CustomerId to Service Case.CaseId, which should be examined and corrected to Service Case.CustomerId; Region has no keyProperty in the returned definition. Test entity keys, bindings and relationship results after corrections. The ontology is not connected to the active web agent.
- The user subsequently confirmed 295 customer rows in the warehouse and identified the copy job as the duplication issue. Mirroring has been abandoned; the active ingestion approach is the copy job to the warehouse. Review its destination write mode and clean/reload the copied tables before validating the ontology again.
- A later direct retrieval test returned five customers, with all names and regions matching the original seed, and correctly associated CASE-1042 with Alex Morgan and Pending status. Each response included a Fabric ontology reference. As of this test, the Customer-to-Case relationship still targets CaseId and Region still has no entity key in the definition; correct and validate these separately. A scheduled refresh and end-to-end web-agent use were not verified.
- The user corrected the customer-to-case binding and configured the RegionName key; the updated ontology definition was verified. Added agent version 6 and a web-hosted function to retrieve from the isolated Fabric knowledge base using the user's delegated Search token. A live agent call invoked that function and returned five customers with Fabric source attribution. This was a programmatic test using a delegated CLI token; a signed-in browser test and user consent remain to be verified.
- Added Azure AI Search delegated permission to the web app registration and configured Container Apps authentication to request it. Enabled the authentication token store using a private blob container in the existing storage account; the web identity has Blob Data Contributor scoped to this container. No tenant-wide consent was granted. Existing users must reauthenticate and may need to consent. The app's single in-process conversation is reset when the signed-in user changes; it is still a single-presenter demo, not multi-user session storage.
- The final web image `fabric-iq-v2`, revision `iq-demo-web--0000006`, was healthy after deployment. Direct Fabric tests returned the three seeded EU South customers and both seeded appointments for CASE-1042. They verify the returned facts, not independently that the graph relationships were traversed. A browser end-to-end test is still required.
- The user confirmed that the ontology knowledge base works. The confirmation did not specify whether the signed-in web app, consent, or combined-source workflow was tested, so those checks remain open.

### Documentation and agent routing

- Rewrote `README.md` for a broad audience using the structure of the user's reference project: introduction, features, scenario, walkthrough, technology stack, architecture, documentation, local verification, and boundaries. Preserved the Contoso narrative and distinguished the current deployed integration from the original provisioning path. Checked that its local links resolve.
- Added Fabric and combined-source examples to `demo-prompts.txt`. Discussed evaluating natural-language prompts and tool selection without naming sources; no routing changes or formal evaluation were made as part of that discussion.
- Refined the README for a repository-based blog workflow: the introduction and question-to-action walkthrough now connect agent reasoning, SharePoint and Fabric knowledge, current SQL facts, human approval, Service Bus, Functions and telemetry. The existing architecture and reliability details remain the primary technical references.
- Prepared the project for GitHub: expanded `.gitignore` to exclude environment files and backups, credentials, local outputs and build artifacts, and superseded mirroring scripts. Removed environment-specific workspace IDs and the SQL server hostname from tracked documentation. Built-in Azure role-definition IDs in the infrastructure remain public constants, not subscription IDs.

### Approved-credit integration and telemetry

- Added SQL script `04_credit_requests.sql`, a read/write request table, a Standard Service Bus queue with five delivery attempts, and a Python Azure Function on Flex Consumption. The existing user-assigned demo identity sends and receives queue messages and has the necessary SQL permissions. The Function processes only a simulated request; duplicate messages for a processed request do not issue a second action.
- Deployed the web application with queue settings and Application Insights instrumentation, updated the agent to version 7, and added status display for the SQL-backed requests. The app records approved requests before sending their IDs to the queue. An unconfirmed send is surfaced for review rather than claimed as successful.
- Created Application Insights in the demo resource group using the existing Log Analytics workspace and connected the Foundry project via managed identity. Observed a successful Foundry model dependency in Application Insights. A clearly labelled EUR 1 synthetic request went from SQL through Service Bus to the Function and reached `Processed`; the queue had no active or dead-lettered messages afterward, and the Function's processing log appeared in Application Insights. The temporary test-user queue role was removed.
- Automated tests passed for the web app, request submission, validation, and Function duplicate handling. The synthetic end-to-end test used a signed-in CLI user for the sender, not the web app's identity or browser approval flow. A signed-in browser test and screenshot review remain pending. The synthetic verification row remains in the request table and is labelled as a test.
- The user subsequently reported that all components were verified. Specific test steps and screenshots were not supplied; detailed failure, duplicate-delivery, and trace-correlation evidence remains to be recorded.
- Added `05_credit_outbox.sql`, preserving existing issued history and processed requests while introducing structured allocations, simulated credit history and a transactional outbox. Agent version 8 requests case and allocation details. A scheduled Function leases and publishes outbox records; the queue consumer locks records, validates eligibility and existing credits, and commits history and request status together.
- An isolated synthetic request with two appointments passed from `PendingDispatch` through the outbox and Service Bus to `Processed`, creating exactly two €75 `Simulated` history entries. Replaying the same message on the queue did not add entries; Application Insights recorded both `duplicate=False` and `duplicate=True`. An artificially expired publisher lease was reclaimed and republished on a later timer run without adding credits. The queue's built-in duplicate detection is disabled, so these tests demonstrate consumer idempotency. The temporary sender role and the isolated SQL test fixture were removed. Legacy processed requests were not backfilled; the two original `Issued` history records were preserved.
- A programmatic agent test produced an approval card with the correct case ID and €75 allocation for each of the two CASE-1042 appointments. The action was not approved or executed in that test. The signed-in browser approval and follow-up history question remain to be verified.
- Deployed the final outbox-enabled web revision and confirmed it was healthy. Refreshed the README, processor guide, SQL guide and demo prompts to explain status transitions, the timer, duplicate delivery, test queries and remaining operational work. Local web and processor tests passed.
- Investigated the user's CASE-1045 approval failure: appointment A-7832 is confirmed and provider-caused, but `CustomerAvailable` is NULL (unknown), as intentionally seeded. The demo action requires recorded positive availability; the previous generic validation error and the agent's suggestion of a system mismatch were misleading. The SharePoint policy requires verified eligibility and says no recorded evidence of unavailability, while also requiring the customer to have been present or accessible; it does not explicitly specify how to handle an unrecorded availability field. The action's requirement for recorded positive availability is a conservative demo rule, not a verbatim policy instruction. Added specific missing/false-evidence validation messages and instructed the agent not to propose approval when required facts are unknown. No request is saved when this validation fails.
- Deployed agent version 10 and the evidence-feedback web revision. A direct agent test identified the missing availability as an application validation requirement and did not present an approval request. A direct CASE-1045 validation test returned the specific missing-evidence message without saving a request; 19 local tests passed. The user can retest in a fresh browser conversation.

## Backlog

### Next: validate SharePoint as the policy source

- [x] Connect the existing agent to the SharePoint-backed knowledge base, keeping the Blob knowledge base and connection intact.
- [ ] Validate citations and readable document names in the signed-in web UI, including whether a citation resolves to the original document or a Search index URL.
- [ ] Confirm indexing scope, preview registration, application permissions, federated-credential configuration, and indexing refresh behavior. Test a policy update and verify the new version becomes searchable.
- [ ] Decide how approved versus draft/retired policies are separated. Review the four Word policies for conflicts, effective dates, scope and consistency with the synthetic cases.
- [ ] Confirm the SharePoint-backed agent and approval workflow end to end in the browser. The Blob policies and static case snapshot are no longer in the active agent retrieval path; keep the preserved Blob fallback until the user decides otherwise.
- [ ] Design and test per-user authorization only if the demo needs it. Indexed SharePoint ACL synchronization is preview, requires explicit configuration and user-token handling, and has limitations. Do not claim current sign-in alone enforces document-level SharePoint access.

### Future demo extensions discussed, not implemented

- [ ] Test the Fabric-enabled agent in the signed-in web app, including consent, access failure, policy citations, case details and user isolation; validate copy-job and ontology-graph refresh lag. The corrected ontology relationships need direct relationship tests.
- [ ] Test the approved-credit flow in the signed-in web UI, including decline, queue/processed status, policy limits and corresponding Application Insights logs. Demonstrate retries and dead-letter handling safely.
- [x] Implement transactional outbox publishing, per-appointment simulated history and idempotent consumption. Verify an actual duplicate delivery against an isolated synthetic request.
- [ ] Verify the new allocation approval and history flow in the signed-in web UI; test live publisher send failure and dead-letter handling. Add alerting and an operational replay procedure for persistent failures. Evaluate separate managed identities and stronger per-user session isolation. Confirm distributed trace propagation across Service Bus separately from request-ID correlation. Expired-lease recovery and duplicate delivery have been tested with an isolated fixture.
- [ ] Develop 4–5 consistent policies and more synthetic cases. Decide whether the hardware-replacement policy fits an expanded managed-device business or should be adapted to Contoso's field-service offering.
- [ ] Add a policy-preparation agent that reviews or compares policy versions, flags ambiguity, and prepares a human-reviewed brief. Word-to-Markdown conversion is not required for direct SharePoint indexing.
- [ ] Add a technician/tablet scenario: record a field report and link two synthetic site photos to a case; use Content Understanding to produce observations for an operator. Photos are evidence for review, not automatic proof of unsafe conditions. Allow an exception when taking photos is unsafe.
- [ ] Define separate safety and refund policies before recommending a denied or partial refund; require human review and avoid treating image analysis as the final decision.
- [ ] Add a simulated appointment update, then consider Event Hubs only if demonstrating an actual stream adds value. SQL remains the current case system of record.
- [ ] Consider durable storage for approved demo actions and review session isolation before use beyond a single-presenter demo; current chat state and pending approvals are process-local and shared.

## Operational follow-ups

- The SQL server's existing firewall rule permits Azure services; it was not changed for this demo. Review the network model before using real data.
- During an earlier ACR build, existing local `.env` files may have been included in the temporary uploaded build context; the Dockerfile did not copy them into the image. `.dockerignore` exclusions were added and the later case-app build used a sanitized context. Review and rotate any credentials in those files as appropriate.
- Failed or unused Foundry resources and the old knowledge source may still exist and may have costs. Inventory before cleanup; the working agent uses the existing `aiservices-kp` resource, so do not delete shared resources as part of demo cleanup without confirming ownership and dependencies.
- The local `.env` may refer to an earlier deployment. Do not treat it as authoritative for the live Container App; inspect the deployed settings without exposing secrets.
- Preview features, region availability, tenant permissions and costs should be rechecked before an event. The historical verification above is a snapshot, not a continuous health guarantee.
