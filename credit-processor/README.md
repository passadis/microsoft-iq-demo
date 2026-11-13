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

The outbox prevents the application from committing an approved request without also recording the intent to publish, but SQL and Service Bus still do not share a distributed transaction. Duplicate sends can occur. The publisher retries indefinitely. `CreditHistory` entries inserted outside this workflow are not automatically reconciled. Legacy `Processed` requests have no allocation detail and are not backfilled.

## Monitoring and recovery

The `monitor_credit_requests` timer reads SQL every five minutes using the Function identity's existing SELECT permission. It logs `credit_monitor_heartbeat` even when the counts are zero and `credit_monitor_stuck` if a request has been awaiting dispatch for over ten minutes, or has been queued for over ten minutes. The threshold is illustrative. A SQL connection failure produces no successful heartbeat; it does not report a healthy zero.

The optional [monitoring template](../infra/credit-monitoring.bicep) configures a Service Bus dead-letter count alert, a stuck-request log alert and a missing-heartbeat alert. The latter detects loss of the SQL check for 30 minutes, including a stopped Function App or unavailable SQL, provided Application Insights ingestion and the alert service are working. It cannot distinguish these causes. Configure an action group with a real receiver; alerts without a receiver appear in Azure Monitor but do not notify an operator. Allow for telemetry and metric ingestion latency.

Deploy the template to the resource group containing the existing Application Insights component and Service Bus namespace, supplying their names, the queue name, an existing action group resource ID, and the Application Insights location. The Function code must also be deployed. Alerts and checks incur Azure costs. The action group's receivers are configured separately to avoid putting email addresses into the template.

### Test notifications and the dead-letter alert

These are two different tests. The first checks the notification channel; the second exercises the queue, Function, alert rule and email together. They have not yet been verified end to end in the demonstrated deployment.

**Email only:** In Azure Monitor, open **Alerts → Action groups**, select the credit operations action group and choose **Test**. Select a sample type and the email notification, run the test and check both the result in the portal and the mailbox. Complete any email-address verification requested by Azure. A successful action-group test does not exercise the alert rule or Service Bus. See [Test an action group](https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/action-groups#test-an-action-group-in-the-azure-portal).

**Dead-letter alert end to end:** Use only a dedicated demo environment and a test window. This intentionally causes Function failures and an alert email; it does not create a SQL request or simulated credit. Ensure the queue and its dead-letter subqueue have no unrelated messages before starting, and ensure the Function and alert rules are enabled.

1. Open the service credit queue in Azure portal → **Service Bus Explorer**. Send one message to the main queue with a unique message ID such as `alert-test-<your-unique-suffix>` and this JSON body:

   ```json
   {"request_id": "alert-test-invalid"}
   ```

2. The Function rejects this deliberately invalid ID before connecting to SQL. Service Bus retries it and eventually moves it to the dead-letter subqueue after the configured delivery limit. Timing varies. Peek the dead-letter subqueue and confirm the test message ID and the reason; `MaxDeliveryCountExceeded` indicates the delivery limit was reached. Check the Function's Application Insights logs for the underlying `Invalid request identifier` error.
3. In Azure Monitor → **Alerts**, look for `contoso-credit-dead-letters` and check the configured mailbox. The metric rule evaluates every five minutes; metric and email delivery can add delay. The alert proves that a dead-lettered message was detected; the email confirms the notification channel.
4. After recording the result, receive the **dead-letter** message in **PeekLock** mode, verify its unique ID and body, and complete **only that test message**. Never use ReceiveAndDelete or purge to clean up a shared queue. If another message is received, abandon its lock and investigate it separately. Confirm the test message is gone and allow time for the metric alert to resolve.

Do not replay this intentionally invalid message: it will fail again. To demonstrate *successful replay*, use a separate valid synthetic request with a controlled, corrected failure and follow the recovery steps below. Portal operations require appropriate Service Bus data permissions; for details on PeekLock and completion see [Service Bus Explorer](https://learn.microsoft.com/en-us/azure/service-bus-messaging/explorer).

When an alert fires:

1. Check Azure Monitor and Application Insights for `credit_monitor_stuck`, `credit_outbox_publish_failed`, Function exceptions and the request ID. Use the SQL queries below to inspect request and dispatch state. `PendingDispatch` points toward publication; `Queued` points toward downstream processing, although races and delayed telemetry can complicate the picture.
2. In the Service Bus queue's **Service Bus Explorer**, peek at dead-letter messages. Inspect their reason, description and request ID; compare SQL allocations, appointment evidence and existing credit history. A maximum-delivery reason alone does not identify the underlying Function error.
3. Fix the underlying configuration or data issue, then resend only the reviewed message using Service Bus Explorer. The Function revalidates the request and makes already-processed deliveries a no-op. Confirm `Processed` and the expected simulated history rows. Do not resend permanently invalid requests without resolving the business issue.
4. Confirm the dead-lettered original is removed after a successful replay; check the portal's behavior and do not delete it before the resend is confirmed. Resend and settlement may not be atomic, so duplicates remain possible. Never clear the queue in bulk for this demo.

The portal supplies the manual replay experience; there is no custom replay button or audit workflow. Restrict access to Service Bus data operations and the database. A repeated request is safe only within the current SQL consumer's guarantees; this demo does not execute an external payment.

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
