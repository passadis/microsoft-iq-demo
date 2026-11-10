-- Run in ContosoServiceDemo as its Entra database administrator.
-- This table tracks simulated requests; it does not issue actual credits.
IF DB_NAME() <> N'ContosoServiceDemo'
    THROW 50000, 'Connect to ContosoServiceDemo before running this script.', 1;

IF OBJECT_ID(N'dbo.ServiceCreditRequests', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ServiceCreditRequests (
        RequestId varchar(40) NOT NULL CONSTRAINT PK_ServiceCreditRequests PRIMARY KEY,
        CustomerId varchar(20) NOT NULL CONSTRAINT FK_ServiceCreditRequests_Customers REFERENCES dbo.Customers(CustomerId),
        AmountEur decimal(10,2) NOT NULL,
        Reason nvarchar(1000) NOT NULL,
        EvidenceJson nvarchar(max) NOT NULL,
        RequestStatus varchar(30) NOT NULL,
        CreatedAtUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
        UpdatedAtUtc datetime2(3) NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT CK_ServiceCreditRequests_Amount CHECK (AmountEur > 0 AND AmountEur <= 150),
        CONSTRAINT CK_ServiceCreditRequests_Status CHECK (RequestStatus IN ('PendingDispatch', 'Queued', 'DispatchFailed', 'Processed'))
    );
END;

-- Change this identity name for deployments using a different managed identity.
GRANT SELECT, INSERT ON OBJECT::dbo.ServiceCreditRequests TO [iq-demo-web-identity];
GRANT UPDATE (RequestStatus, UpdatedAtUtc) ON OBJECT::dbo.ServiceCreditRequests TO [iq-demo-web-identity];
