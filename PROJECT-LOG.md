# Contoso Service Intelligence: project log and backlog

Last updated: 2026-11-10. This is a working record of decisions, activities and follow-up work for the synthetic live demo. Azure and preview-service details can change; verify live settings before an event or a new deployment.

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
                         +-> approval-gated credit request -> container-local JSONL audit
```

- **Web app:** `iq-demo-web` in Container Apps, with Microsoft Entra sign-in. It lists SQL cases, lets an operator choose a case and set it to Pending or Resolved, and starts a new conversation on case selection.
- **Agent:** managed Foundry Prompt Agent `contoso-service-intelligence-agent` in project `ai-service-iq` on Foundry resource `aiservices-kp`. Version 5 uses SharePoint policies; version 6 adds a client-executed read-only Fabric ontology tool. It is not an implementation using Microsoft Agent Framework.
- **Current case facts:** Azure SQL Database `ContosoServiceDemo`. It contains Customers, Cases, Appointments and CreditHistory, initially seeded with five synthetic cases. `get_case_details` is a client-executed, parameterized lookup: the agent requests it and the Container App executes it.
- **Current agent policy source:** Search service `iqdemo7f3c9-search`, indexed SharePoint source `knowledgesource-1794233986722`, knowledge base `contoso-sharepoint-test-kb`, and project MCP connection `contoso-sharepoint-kb-mcp`. The test-named knowledge base is now the agent's active policy source.
- **Preserved Blob path:** `contoso-service-kb`, Blob-backed source `contoso-service-src-v2`, and project connection `contoso-service-kb-mcp` remain intact as a fallback. The original `contoso-service-src` also remains from the earlier deployment. The Blob corpus contains a static case document, but it is not in the agent's current SharePoint knowledge base; SQL is authoritative for current case facts.
- **Fabric ontology:** `contosoiq` in Fabric workspace `Datalycs`, queried through Search source `knowledgesource-fabiq` and the isolated `contoso-fabric-ontology-test-kb`. The `query_fabric_ontology` function is requested by the agent and executed by the web app using the current user's delegated Search token. The user needs access to Search and Fabric. Fabric is a warehouse snapshot, while SQL remains authoritative for current case decisions.
- **Identities:** the Container App's user-assigned identity `iq-demo-web-identity` calls Foundry and runs SQL queries. It has SELECT on the four demo tables and UPDATE only on `dbo.Cases.CaseStatus` and `UpdatedAtUtc`. The Foundry project identity accesses Search via the MCP connection. The SharePoint indexer uses its own application/identity configuration; these are distinct permission paths.
- **Credit action:** the agent proposes `create_service_credit_request`; the app requires explicit operator approval and blocks frontline amounts above €150. A successful demo action writes a JSONL record inside the container. It is a simulation, not a billing integration, and the file is not durable across container restarts.

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
- Prepared the project for GitHub: expanded `.gitignore` to exclude environment files and backups, credentials, local outputs and build artifacts, and superseded mirroring scripts. Removed environment-specific workspace IDs and the SQL server hostname from tracked documentation. Built-in Azure role-definition IDs in the infrastructure remain public constants, not subscription IDs.

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
