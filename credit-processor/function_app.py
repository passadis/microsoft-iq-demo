"""Publish the SQL outbox and process approved simulated credit requests."""
import hashlib
import json
import logging
import os
import re
import struct
import uuid
from decimal import Decimal

import azure.functions as func
from azure.identity import DefaultAzureCredential
from azure.servicebus import ServiceBusClient, ServiceBusMessage
import mssql_python

app = func.FunctionApp()
credential = DefaultAzureCredential()


def connect():
    token = credential.get_token('https://database.windows.net/.default').token.encode('utf-16-le')
    return mssql_python.connect(
        f"Server=tcp:{os.environ['SQL_SERVER']},1433;Database={os.environ['SQL_DATABASE']};Encrypt=yes;TrustServerCertificate=no;",
        attrs_before={1256: struct.pack('<I', len(token)) + token},
    )


@app.function_name(name='publish_credit_outbox')
@app.timer_trigger(schedule='0 */1 * * * *', arg_name='timer', run_on_startup=False, use_monitor=True)
def publish_credit_outbox(timer: func.TimerRequest) -> None:
    """Lease a small batch; expired leases recover after process or send failures."""
    lease = uuid.uuid4().hex
    with connect() as connection:
        cursor = connection.cursor()
        cursor.execute('''UPDATE TOP (20) dbo.CreditRequestOutbox WITH (UPDLOCK, READPAST, ROWLOCK, READCOMMITTEDLOCK)
            SET DispatchStatus='Leased', LeaseId=?, LeaseUntilUtc=DATEADD(minute, 2, SYSUTCDATETIME()),
                AttemptCount=AttemptCount+1
            OUTPUT inserted.RequestId
            WHERE (DispatchStatus='Pending' AND NextAttemptUtc <= SYSUTCDATETIME())
               OR (DispatchStatus='Leased' AND LeaseUntilUtc < SYSUTCDATETIME())''', (lease,))
        ids = [row[0] for row in cursor.fetchall()]
        connection.commit()
    if not ids:
        return
    for request_id in ids:
        try:
            message = ServiceBusMessage(json.dumps({'request_id': request_id}), message_id=request_id,
                                        content_type='application/json', subject='service-credit.approved')
            with ServiceBusClient(os.environ['SERVICEBUS_FULLY_QUALIFIED_NAMESPACE'], credential=credential) as client:
                with client.get_queue_sender(os.environ['SERVICEBUS_QUEUE_NAME']) as sender:
                    sender.send_messages(message)
            with connect() as connection:
                cursor = connection.cursor()
                cursor.execute('''UPDATE dbo.CreditRequestOutbox SET DispatchStatus='Published',
                    PublishedAtUtc=SYSUTCDATETIME(), LeaseId=NULL, LeaseUntilUtc=NULL
                    WHERE RequestId=? AND DispatchStatus='Leased' AND LeaseId=?''', (request_id, lease))
                cursor.execute('''UPDATE dbo.ServiceCreditRequests SET RequestStatus='Queued', UpdatedAtUtc=SYSUTCDATETIME()
                    WHERE RequestId=? AND RequestStatus='PendingDispatch' ''', (request_id,))
                connection.commit()
            logging.info('credit_outbox_published request_id=%s', request_id)
        except Exception:
            # A send may have succeeded even if acknowledgment failed; consumer idempotency is essential.
            logging.exception('credit_outbox_publish_failed request_id=%s', request_id)
            try:
                with connect() as connection:
                    cursor = connection.cursor()
                    cursor.execute('''UPDATE dbo.CreditRequestOutbox SET DispatchStatus='Pending', LeaseId=NULL,
                        LeaseUntilUtc=NULL, NextAttemptUtc=DATEADD(second, 30, SYSUTCDATETIME())
                        WHERE RequestId=? AND DispatchStatus='Leased' AND LeaseId=?''', (request_id, lease))
                    connection.commit()
            except Exception:
                logging.exception('credit_outbox_release_failed request_id=%s', request_id)


@app.function_name(name='process_service_credit')
@app.service_bus_queue_trigger(arg_name='message', queue_name='%SERVICEBUS_QUEUE_NAME%', connection='ServiceBus')
def process_service_credit(message: func.ServiceBusMessage) -> None:
    data = json.loads(message.get_body().decode('utf-8'))
    request_id = data.get('request_id', '')
    if not isinstance(request_id, str) or not re.fullmatch(r'SCR-[a-f0-9]{32}', request_id):
        raise ValueError('Invalid request identifier')
    with connect() as connection:
        try:
            cursor = connection.cursor()
            cursor.execute('''SELECT RequestStatus, CustomerId, CaseId, AmountEur FROM dbo.ServiceCreditRequests
                              WITH (UPDLOCK, HOLDLOCK) WHERE RequestId=?''', (request_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError('Request not found')
            status, customer_id, case_id, total = row
            if status == 'Processed':
                connection.commit()
                logging.info('service_credit_processed request_id=%s duplicate=True', request_id)
                return
            if status not in ('PendingDispatch', 'Queued', 'DispatchFailed') or not case_id:
                raise ValueError('Request has no processable structured allocations')
            cursor.execute('SELECT AppointmentId, AmountEur FROM dbo.CreditRequestAllocations WHERE RequestId=? ORDER BY AppointmentId', (request_id,))
            allocations = cursor.fetchall()
            if not allocations or sum(Decimal(str(a[1])) for a in allocations) != Decimal(str(total)):
                raise ValueError('Allocation total does not match approved request')
            for appointment_id, amount in allocations:
                # Lock appointment rows in a stable order so concurrent requests cannot both issue a simulated credit.
                cursor.execute('''SELECT a.AppointmentId FROM dbo.Appointments a WITH (UPDLOCK, HOLDLOCK)
                    JOIN dbo.Cases c ON c.CaseId=a.CaseId WHERE a.AppointmentId=? AND c.CaseId=?
                    AND c.CustomerId=? AND a.IsConfirmed=1 AND a.CustomerAvailable=1 AND a.ProviderCaused=1''',
                    (appointment_id, case_id, customer_id))
                if not cursor.fetchone():
                    raise ValueError('Appointment eligibility or ownership changed')
                cursor.execute("SELECT TOP 1 CreditId FROM dbo.CreditHistory WHERE AppointmentId=? AND CreditStatus IN ('Issued','Simulated')", (appointment_id,))
                if cursor.fetchone():
                    raise ValueError('Appointment already has an issued or simulated credit')
                credit_id = 'SC-' + hashlib.sha256(f'{request_id}:{appointment_id}'.encode()).hexdigest()[:16]
                cursor.execute('''INSERT INTO dbo.CreditHistory (CreditId, AppointmentId, AmountEur, CreditStatus, RecordedAtUtc, RequestId)
                                  VALUES (?, ?, ?, 'Simulated', SYSUTCDATETIME(), ?)''', (credit_id, appointment_id, amount, request_id))
            cursor.execute("UPDATE dbo.ServiceCreditRequests SET RequestStatus='Processed', UpdatedAtUtc=SYSUTCDATETIME() WHERE RequestId=?", (request_id,))
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    logging.info('service_credit_processed request_id=%s duplicate=False', request_id)
