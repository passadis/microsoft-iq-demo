-- Run as an Entra administrator in the dedicated ContosoServiceDemo database.
-- Grants the Container App identity read access and permission to update case status.
IF DB_NAME() <> N'ContosoServiceDemo'
    THROW 50000, 'Connect to ContosoServiceDemo before running this script.', 1;

IF DATABASE_PRINCIPAL_ID(N'iq-demo-web-identity') IS NULL
    CREATE USER [iq-demo-web-identity] FROM EXTERNAL PROVIDER;

GRANT SELECT ON OBJECT::dbo.Customers TO [iq-demo-web-identity];
GRANT SELECT ON OBJECT::dbo.Cases TO [iq-demo-web-identity];
GRANT SELECT ON OBJECT::dbo.Appointments TO [iq-demo-web-identity];
GRANT SELECT ON OBJECT::dbo.CreditHistory TO [iq-demo-web-identity];
GRANT UPDATE (CaseStatus, UpdatedAtUtc) ON OBJECT::dbo.Cases TO [iq-demo-web-identity];
