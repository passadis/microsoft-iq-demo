-- Run in the dedicated ContosoServiceDemo database, not in master.
-- Creates and seeds the demo tables without overwriting existing records.
SET NOCOUNT ON;
SET XACT_ABORT ON;

IF DB_NAME() <> N'ContosoServiceDemo'
    THROW 50000, 'Connect to the ContosoServiceDemo database before running this script.', 1;

BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.Customers', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Customers (
        CustomerId varchar(20) NOT NULL CONSTRAINT PK_Customers PRIMARY KEY,
        DisplayName nvarchar(100) NOT NULL,
        Region nvarchar(50) NOT NULL,
        ServiceTier varchar(20) NOT NULL,
        AccountStatus varchar(20) NOT NULL,
        CONSTRAINT CK_Customers_AccountStatus CHECK (AccountStatus IN ('Active', 'Suspended'))
    );
END;

IF OBJECT_ID(N'dbo.Cases', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Cases (
        CaseId varchar(20) NOT NULL CONSTRAINT PK_Cases PRIMARY KEY,
        CustomerId varchar(20) NOT NULL CONSTRAINT FK_Cases_Customers REFERENCES dbo.Customers(CustomerId),
        Category nvarchar(60) NOT NULL,
        Summary nvarchar(500) NOT NULL,
        RequestedCreditEur decimal(10, 2) NULL,
        CaseStatus varchar(20) NOT NULL CONSTRAINT DF_Cases_Status DEFAULT 'Pending',
        OpenedAtUtc datetime2(0) NOT NULL,
        UpdatedAtUtc datetime2(0) NOT NULL CONSTRAINT DF_Cases_UpdatedAtUtc DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_Cases_Status CHECK (CaseStatus IN ('Pending', 'Resolved')),
        CONSTRAINT CK_Cases_Credit CHECK (RequestedCreditEur IS NULL OR RequestedCreditEur >= 0)
    );
END;

IF OBJECT_ID(N'dbo.Appointments', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.Appointments (
        AppointmentId varchar(20) NOT NULL CONSTRAINT PK_Appointments PRIMARY KEY,
        CaseId varchar(20) NOT NULL CONSTRAINT FK_Appointments_Cases REFERENCES dbo.Cases(CaseId),
        ScheduledDate date NOT NULL,
        IsConfirmed bit NULL,
        CustomerAvailable bit NULL,
        Outcome nvarchar(60) NOT NULL,
        ProviderCaused bit NULL
    );
END;

IF OBJECT_ID(N'dbo.CreditHistory', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.CreditHistory (
        CreditId varchar(20) NOT NULL CONSTRAINT PK_CreditHistory PRIMARY KEY,
        AppointmentId varchar(20) NOT NULL CONSTRAINT FK_CreditHistory_Appointments REFERENCES dbo.Appointments(AppointmentId),
        AmountEur decimal(10, 2) NOT NULL,
        CreditStatus varchar(20) NOT NULL,
        RecordedAtUtc datetime2(0) NOT NULL,
        CONSTRAINT CK_CreditHistory_Amount CHECK (AmountEur > 0),
        CONSTRAINT CK_CreditHistory_Status CHECK (CreditStatus IN ('Issued', 'Reversed'))
    );
END;

INSERT INTO dbo.Customers (CustomerId, DisplayName, Region, ServiceTier, AccountStatus)
SELECT v.CustomerId, v.DisplayName, v.Region, v.ServiceTier, v.AccountStatus
FROM (VALUES
    ('C-1042', N'Alex Morgan', N'EU South', 'Gold', 'Active'),
    ('C-1043', N'Robin Patel', N'EU West', 'Standard', 'Active'),
    ('C-1044', N'Jordan Lee', N'EU South', 'Silver', 'Active'),
    ('C-1045', N'Taylor Reed', N'EU West', 'Gold', 'Active'),
    ('C-1046', N'Sam Rivera', N'EU South', 'Standard', 'Active')
) AS v(CustomerId, DisplayName, Region, ServiceTier, AccountStatus)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Customers c WHERE c.CustomerId = v.CustomerId);

INSERT INTO dbo.Cases (CaseId, CustomerId, Category, Summary, RequestedCreditEur, CaseStatus, OpenedAtUtc)
SELECT v.CaseId, v.CustomerId, v.Category, v.Summary, v.RequestedCreditEur, v.CaseStatus, v.OpenedAtUtc
FROM (VALUES
    ('CASE-1042', 'C-1042', N'Missed appointment', N'Two provider no-shows; customer requests a credit and priority rescheduling.', CAST(180.00 AS decimal(10,2)), 'Pending', CAST('2026-08-09T09:00:00' AS datetime2(0))),
    ('CASE-1043', 'C-1043', N'Cancellation', N'Customer cancelled a confirmed plumbing visit and requests a credit.', CAST(75.00 AS decimal(10,2)), 'Pending', CAST('2026-08-10T09:00:00' AS datetime2(0))),
    ('CASE-1044', 'C-1044', N'Missed appointment', N'Customer requests another credit for a provider no-show already compensated.', CAST(75.00 AS decimal(10,2)), 'Pending', CAST('2026-08-11T09:00:00' AS datetime2(0))),
    ('CASE-1045', 'C-1045', N'Missed appointment', N'Customer reports a missed appointment; customer availability is not recorded.', CAST(75.00 AS decimal(10,2)), 'Pending', CAST('2026-08-12T09:00:00' AS datetime2(0))),
    ('CASE-1046', 'C-1046', N'Missed appointment', N'One confirmed provider-cancelled visit; the case has been resolved.', CAST(75.00 AS decimal(10,2)), 'Resolved', CAST('2026-08-13T09:00:00' AS datetime2(0)))
) AS v(CaseId, CustomerId, Category, Summary, RequestedCreditEur, CaseStatus, OpenedAtUtc)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Cases c WHERE c.CaseId = v.CaseId);

INSERT INTO dbo.Appointments (AppointmentId, CaseId, ScheduledDate, IsConfirmed, CustomerAvailable, Outcome, ProviderCaused)
SELECT v.AppointmentId, v.CaseId, v.ScheduledDate, v.IsConfirmed, v.CustomerAvailable, v.Outcome, v.ProviderCaused
FROM (VALUES
    ('A-7781', 'CASE-1042', CAST('2026-08-04' AS date), CAST(1 AS bit), CAST(1 AS bit), N'Provider no-show', CAST(1 AS bit)),
    ('A-7829', 'CASE-1042', CAST('2026-08-08' AS date), CAST(1 AS bit), CAST(1 AS bit), N'Provider no-show', CAST(1 AS bit)),
    ('A-7830', 'CASE-1043', CAST('2026-08-09' AS date), CAST(1 AS bit), CAST(NULL AS bit), N'Customer cancellation', CAST(0 AS bit)),
    ('A-7831', 'CASE-1044', CAST('2026-08-10' AS date), CAST(1 AS bit), CAST(1 AS bit), N'Provider no-show', CAST(1 AS bit)),
    ('A-7832', 'CASE-1045', CAST('2026-08-11' AS date), CAST(1 AS bit), CAST(NULL AS bit), N'Provider no-show', CAST(1 AS bit)),
    ('A-7833', 'CASE-1046', CAST('2026-08-12' AS date), CAST(1 AS bit), CAST(1 AS bit), N'Provider cancellation', CAST(1 AS bit))
) AS v(AppointmentId, CaseId, ScheduledDate, IsConfirmed, CustomerAvailable, Outcome, ProviderCaused)
WHERE NOT EXISTS (SELECT 1 FROM dbo.Appointments a WHERE a.AppointmentId = v.AppointmentId);

INSERT INTO dbo.CreditHistory (CreditId, AppointmentId, AmountEur, CreditStatus, RecordedAtUtc)
SELECT v.CreditId, v.AppointmentId, v.AmountEur, v.CreditStatus, v.RecordedAtUtc
FROM (VALUES
    ('CR-1001', 'A-7831', CAST(75.00 AS decimal(10,2)), 'Issued', CAST('2026-08-11T12:00:00' AS datetime2(0))),
    ('CR-1002', 'A-7833', CAST(75.00 AS decimal(10,2)), 'Issued', CAST('2026-08-13T12:00:00' AS datetime2(0)))
) AS v(CreditId, AppointmentId, AmountEur, CreditStatus, RecordedAtUtc)
WHERE NOT EXISTS (SELECT 1 FROM dbo.CreditHistory h WHERE h.CreditId = v.CreditId);

COMMIT TRANSACTION;

SELECT c.CaseId, c.CustomerId, u.DisplayName, c.CaseStatus, c.Summary
FROM dbo.Cases c JOIN dbo.Customers u ON u.CustomerId = c.CustomerId
ORDER BY c.CaseId;
