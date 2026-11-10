# Service operations runbook

Runbook ID: SOR-22
Owner: Service Operations
Version: 3.1
Effective date: 2026-07-15
Status: Approved

## Service-credit workflow

1. Verify the customer ID and the appointment records.
2. Confirm the provider-failure status for each incident.
3. Retrieve the current Service Credit Policy and calculate the maximum amount.
4. Prepare a request containing the evidence, proposed amount, and policy reference.
5. Show the proposed action and arguments to the operator.
6. Obtain explicit operator approval.
7. Submit through the service-credit action endpoint.
8. Record the action ID, operator identity, timestamp, evidence references, and result.

## Approval routing

- Requests of €150 or less may be approved by a frontline service agent.
- Requests above €150 must be routed to a Customer Operations Manager.
- An AI agent may prepare a request but may not approve on behalf of a person.

## Customer communication

Before confirmation, say that a request has been prepared or submitted for review. Only say that a credit was issued after the downstream system confirms completion.

## Audit minimum

Retain the user question, source references, calculated amount, tool arguments, approval decision, action result, and correlation ID.

