"""Atomically record approved simulated requests, allocations, and an outbox event."""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from webapp import cases


def _money(value, maximum):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount > maximum or amount.as_tuple().exponent < -2:
            return None
        return amount
    except (InvalidOperation, ValueError, TypeError):
        return None


def submit(request_id: str, arguments: dict) -> dict:
    total = _money(arguments.get('amount_eur'), 150)
    if total is None:
        return {'status': 'blocked_by_action_policy', 'message': 'Credit must be between EUR 0.01 and EUR 150.00.'}
    customer_id, case_id = arguments.get('customer_id'), arguments.get('case_id')
    reason, evidence, allocations = arguments.get('reason'), arguments.get('evidence'), arguments.get('allocations')
    if (not isinstance(customer_id, str) or not re.fullmatch(r'C-[A-Za-z0-9-]{1,18}', customer_id)
        or not isinstance(case_id, str) or not re.fullmatch(r'CASE-[A-Za-z0-9-]{1,15}', case_id)
        or not isinstance(reason, str) or not reason.strip() or len(reason) > 1000
        or not isinstance(evidence, list) or not all(isinstance(e, str) for e in evidence)
        or not isinstance(allocations, list) or not 1 <= len(allocations) <= 10):
        return {'status': 'invalid_request', 'message': 'A case, customer, reason, evidence and appointment allocations are required.'}
    parsed = []
    for item in allocations:
        if not isinstance(item, dict):
            return {'status': 'invalid_request', 'message': 'Invalid appointment allocation.'}
        appointment = item.get('appointment_id')
        amount = _money(item.get('amount_eur'), 75)
        if not isinstance(appointment, str) or not re.fullmatch(r'A-[A-Za-z0-9-]{1,18}', appointment) or amount is None:
            return {'status': 'invalid_request', 'message': 'Each allocation requires an appointment and an amount up to EUR 75.'}
        parsed.append((appointment, amount))
    if len({x[0] for x in parsed}) != len(parsed) or sum(x[1] for x in parsed) != total:
        return {'status': 'invalid_request', 'message': 'Appointments must be unique and allocations must sum to the request amount.'}

    with cases.connect() as connection:
        cursor = connection.cursor()
        for appointment, amount in parsed:
            cursor.execute('''SELECT a.IsConfirmed, a.CustomerAvailable, a.ProviderCaused FROM dbo.Appointments a
                JOIN dbo.Cases c ON c.CaseId=a.CaseId
                WHERE a.AppointmentId=? AND c.CaseId=? AND c.CustomerId=?''',
                (appointment, case_id, customer_id))
            facts = cursor.fetchone()
            if not facts:
                return {'status': 'invalid_request', 'message': f'Appointment {appointment} does not match the specified case and customer. No request was saved.'}
            missing = [label for label, value in zip(('appointment confirmation', 'customer availability', 'provider responsibility'), facts) if value is None]
            if missing:
                return {'status': 'invalid_request', 'message': f"Appointment {appointment} has missing evidence: {', '.join(missing)}. Verify and record the missing facts before preparing a credit. No request was saved."}
            unmet = [label for label, value in zip(('appointment confirmation', 'customer availability', 'provider responsibility'), facts) if not value]
            if unmet:
                return {'status': 'invalid_request', 'message': f"Appointment {appointment} does not meet the recorded conditions: {', '.join(unmet)}. No request was saved."}
            cursor.execute("SELECT TOP 1 CreditId FROM dbo.CreditHistory WHERE AppointmentId=? AND CreditStatus IN ('Issued','Simulated')", (appointment,))
            if cursor.fetchone():
                return {'status': 'invalid_request', 'message': 'An appointment already has an issued or simulated credit.'}
        cursor.execute('''INSERT INTO dbo.ServiceCreditRequests
            (RequestId, CustomerId, CaseId, AmountEur, Reason, EvidenceJson, RequestStatus)
            VALUES (?, ?, ?, ?, ?, ?, 'PendingDispatch')''',
            (request_id, customer_id, case_id, total, reason, json.dumps(evidence, ensure_ascii=False)))
        for appointment, amount in parsed:
            cursor.execute('INSERT INTO dbo.CreditRequestAllocations (RequestId, AppointmentId, AmountEur) VALUES (?, ?, ?)',
                           (request_id, appointment, amount))
        cursor.execute('INSERT INTO dbo.CreditRequestOutbox (RequestId) VALUES (?)', (request_id,))
        connection.commit()
    return {'status': 'pending_dispatch', 'action_id': request_id,
            'message': 'Approved simulated request and outbox event saved. Processing is pending; no refund was issued.'}


def recent() -> list[dict]:
    with cases.connect() as connection:
        cursor = connection.cursor()
        cursor.execute('''SELECT TOP 30 RequestId AS action_id, CustomerId AS customer_id,
                          AmountEur AS amount_eur, RequestStatus AS status, UpdatedAtUtc AS updated_at
                          FROM dbo.ServiceCreditRequests ORDER BY CreatedAtUtc DESC''')
        return cases._rows(cursor)
