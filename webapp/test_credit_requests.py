import unittest
from unittest.mock import patch
from webapp.credit_requests import submit
from webapp.app import _execute_credit_request


class CreditRequestTests(unittest.TestCase):
    def setUp(self):
        self.args = {'customer_id': 'C-1042', 'case_id': 'CASE-1042', 'amount_eur': 150,
                     'reason': 'demo', 'evidence': ['A-7781', 'A-7829'],
                     'allocations': [{'appointment_id': 'A-7781', 'amount_eur': 75},
                                     {'appointment_id': 'A-7829', 'amount_eur': 75}]}
        self.request_id = 'SCR-' + 'a' * 32

    @patch('webapp.app.credit_requests.submit')
    @patch('webapp.app.REHEARSAL', False)
    def test_decline_never_submits(self, submit_request):
        self.assertEqual(_execute_credit_request(self.args, False)['status'], 'rejected_by_operator')
        submit_request.assert_not_called()

    @patch('webapp.credit_requests.cases.connect')
    def test_rejects_invalid_allocations_before_writing(self, connect):
        for allocations in [[], [self.args['allocations'][0]],
                            [self.args['allocations'][0], self.args['allocations'][0]]]:
            result = submit(self.request_id, {**self.args, 'allocations': allocations})
            self.assertEqual(result['status'], 'invalid_request')
        connect.assert_not_called()

    @patch('webapp.credit_requests.cases.connect')
    def test_request_allocations_and_outbox_commit_together(self, connect):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [(True, True, True), None, (True, True, True), None]
        result = submit(self.request_id, self.args)
        self.assertEqual(result['status'], 'pending_dispatch')
        self.assertEqual(cursor.execute.call_count, 8)
        self.assertIn('CreditRequestOutbox', cursor.execute.call_args.args[0])
        connection.commit.assert_called_once()

    @patch('webapp.credit_requests.cases.connect')
    def test_previously_credited_appointment_is_rejected(self, connect):
        connection = connect.return_value.__enter__.return_value
        connection.cursor.return_value.fetchone.side_effect = [(True, True, True), ('CR-1',)]
        self.assertEqual(submit(self.request_id, self.args)['status'], 'invalid_request')
        connection.commit.assert_not_called()

    @patch('webapp.credit_requests.cases.connect')
    def test_unknown_availability_is_identified_without_assuming_false(self, connect):
        connection = connect.return_value.__enter__.return_value
        connection.cursor.return_value.fetchone.return_value = (True, None, True)
        result = submit(self.request_id, self.args)
        self.assertEqual(result['status'], 'invalid_request')
        self.assertIn('missing evidence: customer availability', result['message'])
        self.assertIn('No request was saved', result['message'])
        connection.commit.assert_not_called()

    @patch('webapp.credit_requests.cases.connect')
    def test_recorded_unavailability_is_distinct_from_unknown(self, connect):
        connection = connect.return_value.__enter__.return_value
        connection.cursor.return_value.fetchone.return_value = (True, False, True)
        result = submit(self.request_id, self.args)
        self.assertIn('does not meet the recorded conditions: customer availability', result['message'])
        connection.commit.assert_not_called()


if __name__ == '__main__':
    unittest.main()
