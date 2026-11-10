-- Restore ONLY the status of the five seeded demo cases.
-- Does not modify customers, appointments, credit history, or audit records.
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() <> N'ContosoServiceDemo'
    THROW 50000, 'Connect to the ContosoServiceDemo database before running this script.', 1;

BEGIN TRANSACTION;

UPDATE dbo.Cases
SET CaseStatus = CASE WHEN CaseId = 'CASE-1046' THEN 'Resolved' ELSE 'Pending' END,
    UpdatedAtUtc = SYSUTCDATETIME()
WHERE CaseId IN ('CASE-1042', 'CASE-1043', 'CASE-1044', 'CASE-1045', 'CASE-1046');

SELECT CaseId, CustomerId, CaseStatus, UpdatedAtUtc
FROM dbo.Cases
WHERE CaseId IN ('CASE-1042', 'CASE-1043', 'CASE-1044', 'CASE-1045', 'CASE-1046')
ORDER BY CaseId;

COMMIT TRANSACTION;
