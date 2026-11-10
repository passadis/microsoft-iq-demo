-- Run as Entra database administrator in the dedicated ContosoServiceDemo database.
-- Existing requests and issued credit history are preserved; no records are backfilled.
SET XACT_ABORT ON;
IF DB_NAME() <> N'ContosoServiceDemo'
    THROW 50000, 'Connect to ContosoServiceDemo before running this script.', 1;
IF EXISTS (SELECT 1 FROM dbo.ServiceCreditRequests WHERE RequestStatus <> 'Processed')
    THROW 50001, 'Resolve existing unprocessed credit requests before migrating.', 1;

BEGIN TRANSACTION;
IF COL_LENGTH('dbo.ServiceCreditRequests', 'CaseId') IS NULL
    ALTER TABLE dbo.ServiceCreditRequests ADD CaseId varchar(20) NULL REFERENCES dbo.Cases(CaseId);
IF COL_LENGTH('dbo.CreditHistory', 'RequestId') IS NULL
    ALTER TABLE dbo.CreditHistory ADD RequestId varchar(40) NULL REFERENCES dbo.ServiceCreditRequests(RequestId);

IF EXISTS (SELECT 1 FROM sys.check_constraints WHERE parent_object_id = OBJECT_ID('dbo.CreditHistory') AND name = 'CK_CreditHistory_Status')
    ALTER TABLE dbo.CreditHistory DROP CONSTRAINT CK_CreditHistory_Status;
ALTER TABLE dbo.CreditHistory WITH CHECK ADD CONSTRAINT CK_CreditHistory_Status
    CHECK (CreditStatus IN ('Issued', 'Reversed', 'Simulated'));
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE object_id = OBJECT_ID('dbo.CreditHistory') AND name = 'UX_CreditHistory_RequestAppointment')
    EXEC(N'CREATE UNIQUE INDEX UX_CreditHistory_RequestAppointment ON dbo.CreditHistory(RequestId, AppointmentId) WHERE RequestId IS NOT NULL');

IF OBJECT_ID(N'dbo.CreditRequestAllocations', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CreditRequestAllocations (
        RequestId varchar(40) NOT NULL REFERENCES dbo.ServiceCreditRequests(RequestId),
        AppointmentId varchar(20) NOT NULL REFERENCES dbo.Appointments(AppointmentId),
        AmountEur decimal(10,2) NOT NULL CHECK (AmountEur > 0 AND AmountEur <= 75),
        CONSTRAINT PK_CreditRequestAllocations PRIMARY KEY (RequestId, AppointmentId)
    );
END;
IF OBJECT_ID(N'dbo.CreditRequestOutbox', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CreditRequestOutbox (
        RequestId varchar(40) NOT NULL PRIMARY KEY REFERENCES dbo.ServiceCreditRequests(RequestId),
        DispatchStatus varchar(20) NOT NULL DEFAULT 'Pending' CHECK (DispatchStatus IN ('Pending','Leased','Published')),
        AttemptCount int NOT NULL DEFAULT 0,
        NextAttemptUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
        LeaseId varchar(32) NULL,
        LeaseUntilUtc datetime2(3) NULL,
        PublishedAtUtc datetime2(3) NULL
    );
END;

-- Change the identity name for other deployments. This sample shares the web/Function identity.
GRANT SELECT, INSERT ON OBJECT::dbo.CreditRequestAllocations TO [iq-demo-web-identity];
GRANT SELECT, INSERT, UPDATE ON OBJECT::dbo.CreditRequestOutbox TO [iq-demo-web-identity];
GRANT INSERT ON OBJECT::dbo.CreditHistory TO [iq-demo-web-identity];
COMMIT TRANSACTION;
