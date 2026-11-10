# Simulated credit processor

One Azure Function publishes approved request IDs from a SQL transactional outbox to Service Bus. A second receives them and records simulated credits per appointment before setting the request to `Processed`. Neither issues a credit or contacts the customer. The agent proposes; the web application validates the amount and requires an operator decision before saving a request.

## Components and configuration

- Apply [the request-table script](../sql/04_credit_requests.sql), then [the allocations and outbox migration](../sql/05_credit_outbox.sql) in the dedicated demo database. Resolve old unprocessed requests first and adjust the managed identity name if needed. The scripts do not backfill earlier completed requests into credit history.
- Create a Service Bus queue and set a suitable delivery limit and dead-letter policy. The Function identity needs **Azure Service Bus Data Sender** for the outbox publisher and **Azure Service Bus Data Receiver** for the queue consumer. The web app no longer sends queue messages directly. The demonstrated deployment currently reuses one user-assigned identity for web and Function; separate identities would provide a cleaner production boundary.
- Deploy this folder as a Python Azure Function with remote dependency installation. The Function requires `SERVICEBUS_QUEUE_NAME`, `SERVICEBUS_FULLY_QUALIFIED_NAMESPACE`, `SQL_SERVER`, `SQL_DATABASE`, and an Application Insights connection. Its identity-based trigger uses `ServiceBus__fullyQualifiedNamespace`, `ServiceBus__credential=managedidentity`, and, for a user-assigned identity, `ServiceBus__clientId`. `AZURE_CLIENT_ID` selects the user-assigned identity for SQL.
- The web application uses `APPLICATIONINSIGHTS_CONNECTION_STRING` for application telemetry. Use deployment secrets/settings, not source-controlled environment files, for connection strings.

The demonstrated Function uses Flex Consumption and the existing demo storage account for host and deployment storage. Hosting and telemetry incur costs. Managed identity is used for Service Bus and SQL; do not assume every platform storage connection is identity-based.

## Behavior and limits

The web app validates the customer, case, eligible appointments, existing history, per-appointment amount and total. On approval it commits the `PendingDispatch` request, allocations and outbox record in one SQL transaction. The publisher runs once per minute, leases up to 20 pending or expired records, and sends only the request ID. It records `Published` and moves a still-pending request to `Queued`. Failed or uncertain sends are retried; an expired lease is recovered. Stable message IDs and idempotent SQL processing remain necessary because a send can succeed without an acknowledgement.

The consumer locks the request and appointment rows, rechecks the evidence and credit history, and inserts one `Simulated` history entry per allocation and updates the request to `Processed` in one transaction. Duplicate delivery of a processed request is a no-op. Failure rolls back the history entries and status; the Function raises so Service Bus can retry and eventually dead-letter. A permanently invalid request requires operational review. No real refund is issued.

The outbox prevents the application from committing an approved request without also recording the intent to publish, but SQL and Service Bus still do not share a distributed transaction. Duplicate sends can occur. The publisher retries indefinitely; monitoring/alerts and a dead-letter replay interface are future work. `CreditHistory` entries inserted outside this workflow are not automatically reconciled. Legacy `Processed` requests have no allocation detail and are not backfilled.

## Telemetry

The Function logs `service_credit_processed` with the request ID and whether the message was a duplicate. Example Application Insights query:

```kusto
traces
| where timestamp > ago(24h)
| where message has 'service_credit_processed' or message has 'service_credit_submission' or message has 'credit_outbox_'
| project timestamp, cloud_RoleName, message, operation_Id
| order by timestamp desc
```

The request ID is the demonstrated cross-component correlation key. A single distributed trace spanning the queue and both applications has not yet been verified. Foundry server-side traces can contain prompt or retrieved content; restrict access and review retention.

To inspect dispatch state without changing data:

```sql
SELECT r.RequestId, r.CaseId, r.RequestStatus, o.DispatchStatus,
       o.AttemptCount, o.NextAttemptUtc, o.LeaseUntilUtc
FROM dbo.ServiceCreditRequests AS r
JOIN dbo.CreditRequestOutbox AS o ON o.RequestId = r.RequestId
ORDER BY r.CreatedAtUtc DESC;

SELECT h.RequestId, h.AppointmentId, h.AmountEur, h.CreditStatus
FROM dbo.CreditHistory AS h
WHERE h.RequestId IS NOT NULL
ORDER BY h.RecordedAtUtc DESC;
```

For a demo, compare the request ID in SQL, `credit_outbox_published`, the Service Bus trigger details, and `service_credit_processed`. Replaying an already processed message should produce `duplicate=True` without adding history. The current queue has broker duplicate detection disabled, so this example demonstrates the consumer's idempotency, not broker-side deduplication. A failed handler is retried and can be dead-lettered after the configured delivery limit; inspect the dead-letter reason before replay. Do not blindly replay or alter production records.

## Local tests

Install the Function and web app requirements, plus `httpx` for the web tests, then run:

```powershell
python -m unittest webapp.test_cases webapp.test_credit_requests
python credit-processor/test_processor.py
```

These tests mock Azure services. They do not verify deployed identity permissions, delivery, or telemetry ingestion.
