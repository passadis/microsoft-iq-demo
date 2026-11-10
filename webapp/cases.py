"""Database access for the synthetic customer service demo."""
from __future__ import annotations

import os
import struct
from datetime import date, datetime
from decimal import Decimal

from azure.identity import DefaultAzureCredential

_credential = DefaultAzureCredential()


def configured() -> bool:
    return bool(os.getenv('SQL_SERVER') and os.getenv('SQL_DATABASE'))


def connect():
    if not configured():
        raise RuntimeError('Case database is not configured.')
    import mssql_python

    token = _credential.get_token('https://database.windows.net/.default').token.encode('utf-16-le')
    token_struct = struct.pack('<I', len(token)) + token
    return mssql_python.connect(
        f"Server=tcp:{os.environ['SQL_SERVER']},1433;Database={os.environ['SQL_DATABASE']};"
        'Encrypt=yes;TrustServerCertificate=no;',
        attrs_before={1256: token_struct},
    )


def _rows(cursor):
    names = [column[0] for column in cursor.description]
    def value(v):
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, Decimal):
            return str(v)
        return v
    return [dict(zip(names, (value(v) for v in row))) for row in cursor.fetchall()]


def list_cases():
    with connect() as connection:
        cursor = connection.cursor()
        cursor.execute('''SELECT c.CaseId, c.CustomerId, u.DisplayName, c.Category,
                                 c.Summary, c.CaseStatus, c.OpenedAtUtc
                          FROM dbo.Cases c JOIN dbo.Customers u ON u.CustomerId = c.CustomerId
                          ORDER BY CASE WHEN c.CaseStatus = 'Pending' THEN 0 ELSE 1 END,
                                   c.OpenedAtUtc DESC, c.CaseId''')
        return _rows(cursor)


def get_case(case_id: str):
    with connect() as connection:
        cursor = connection.cursor()
        cursor.execute('''SELECT c.CaseId, c.CustomerId, u.DisplayName, u.Region, u.ServiceTier,
                                 u.AccountStatus, c.Category, c.Summary, c.RequestedCreditEur,
                                 c.CaseStatus, c.OpenedAtUtc, c.UpdatedAtUtc
                          FROM dbo.Cases c JOIN dbo.Customers u ON u.CustomerId = c.CustomerId
                          WHERE c.CaseId = ?''', (case_id,))
        matches = _rows(cursor)
        if not matches:
            return None
        cursor.execute('''SELECT AppointmentId, ScheduledDate, IsConfirmed, CustomerAvailable,
                                 Outcome, ProviderCaused FROM dbo.Appointments
                          WHERE CaseId = ? ORDER BY ScheduledDate, AppointmentId''', (case_id,))
        matches[0]['appointments'] = _rows(cursor)
        cursor.execute('''SELECT h.CreditId, h.AppointmentId, h.AmountEur, h.CreditStatus, h.RecordedAtUtc
                          FROM dbo.CreditHistory h JOIN dbo.Appointments a ON a.AppointmentId = h.AppointmentId
                          WHERE a.CaseId = ? ORDER BY h.RecordedAtUtc''', (case_id,))
        matches[0]['credit_history'] = _rows(cursor)
        return matches[0]


def set_status(case_id: str, status: str):
    if status not in ('Pending', 'Resolved'):
        raise ValueError('Invalid case status.')
    with connect() as connection:
        cursor = connection.cursor()
        cursor.execute('''UPDATE dbo.Cases SET CaseStatus = ?, UpdatedAtUtc = SYSUTCDATETIME()
                          OUTPUT inserted.CaseId WHERE CaseId = ?''', (status, case_id))
        updated = cursor.fetchone() is not None
        connection.commit()
        return updated
