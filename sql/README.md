# Contoso service demo data

Create a **new, dedicated** Azure SQL Database named `ContosoServiceDemo` on the intended server using the Azure portal or your preferred SQL tooling. Select a suitable pricing tier and verify access before running the scripts. The scripts do not create a database or configure access.

Connect your SQL client to your Azure SQL server, select `ContosoServiceDemo`, and run `01_create_and_seed.sql`. It creates four tables and inserts five synthetic cases. Rerunning it inserts missing demo rows but does not overwrite existing records or migrate existing table definitions.

The identifiers intentionally differ: `C-1042` is the customer ID and `CASE-1042` is the case ID. Two appointment records connect to that case. `NULL` for a confirmation or availability field means the fact is unknown, not false.

To restore only the five demo case statuses, run `02_reset_demo_statuses.sql`. This leaves credit history and other data intact. Resolving a case is an operator status change; it does not itself issue or reverse a credit.

The web app can list cases, update their status, and provide current case details to the Foundry agent. Set `SQL_SERVER` and `SQL_DATABASE` in the app environment and give its managed identity the database permissions in `03_grant_app_access.sql`. The agent uses the `get_case_details` function for current case facts and Foundry IQ for policies. To deploy the updated agent, run `scripts/create_agent.py` with the correct project settings.

Example read queries:

```sql
-- Active cases for a future web-app list
SELECT c.CaseId, c.CustomerId, u.DisplayName, c.Category, c.Summary, c.CaseStatus
FROM dbo.Cases AS c
JOIN dbo.Customers AS u ON u.CustomerId = c.CustomerId
WHERE c.CaseStatus = 'Pending'
ORDER BY c.OpenedAtUtc DESC;

-- Review one case's appointment evidence
SELECT a.AppointmentId, a.ScheduledDate, a.IsConfirmed, a.CustomerAvailable,
       a.Outcome, a.ProviderCaused, h.CreditId, h.AmountEur, h.CreditStatus
FROM dbo.Appointments AS a
LEFT JOIN dbo.CreditHistory AS h ON h.AppointmentId = a.AppointmentId
WHERE a.CaseId = 'CASE-1042'
ORDER BY a.ScheduledDate;

-- Demonstrate an operator resolving a case
UPDATE dbo.Cases SET CaseStatus = 'Resolved', UpdatedAtUtc = SYSUTCDATETIME()
WHERE CaseId = 'CASE-1042';
```

The old Blob-backed case document remains in the preserved Blob knowledge base, but the agent now uses a separate SharePoint-backed knowledge base that does not include it. The agent is instructed to use SQL as the current source for case facts.
