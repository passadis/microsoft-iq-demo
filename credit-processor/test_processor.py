import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('credit_processor', Path(__file__).with_name('function_app.py'))
processor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(processor)


class ProcessorTests(unittest.TestCase):
    def message(self):
        message = MagicMock()
        message.get_body.return_value = json.dumps({'request_id': 'SCR-' + 'a' * 32}).encode()
        return message

    @patch.object(processor, 'connect')
    def test_duplicate_message_is_safe(self, connect):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value
        cursor.fetchone.return_value = ('Processed', 'C-1042', 'CASE-1042', 150)
        processor.process_service_credit(self.message())
        connection.commit.assert_called_once()
        self.assertEqual(cursor.execute.call_count, 1)

    @patch.object(processor, 'connect')
    def test_records_allocations_and_status_in_one_transaction(self, connect):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [('Queued', 'C-1042', 'CASE-1042', 150), ('A-7781',), None, ('A-7829',), None]
        cursor.fetchall.return_value = [('A-7781', 75), ('A-7829', 75)]
        processor.process_service_credit(self.message())
        statements = [c.args[0] for c in cursor.execute.call_args_list]
        self.assertEqual(sum('INSERT INTO dbo.CreditHistory' in s for s in statements), 2)
        self.assertIn('Processed', statements[-1])
        connection.commit.assert_called_once()

    @patch.object(processor, 'connect')
    def test_existing_credit_rolls_back(self, connect):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value
        cursor.fetchone.side_effect = [('Queued', 'C-1042', 'CASE-1042', 75), ('A-7781',), ('CR-1',)]
        cursor.fetchall.return_value = [('A-7781', 75)]
        with self.assertRaises(ValueError):
            processor.process_service_credit(self.message())
        connection.rollback.assert_called_once()
        connection.commit.assert_not_called()

    @patch.object(processor, 'connect')
    def test_invalid_message_is_rejected(self, connect):
        message = MagicMock()
        message.get_body.return_value = b'{"request_id":"invalid"}'
        with self.assertRaises(ValueError):
            processor.process_service_credit(message)
        connect.assert_not_called()

    @patch.dict(os.environ, {'SERVICEBUS_FULLY_QUALIFIED_NAMESPACE': 'example.servicebus.windows.net', 'SERVICEBUS_QUEUE_NAME': 'credits'})
    @patch.object(processor, 'ServiceBusClient')
    @patch.object(processor, 'connect')
    def test_outbox_sends_stable_request_id_and_marks_published(self, connect, servicebus):
        connection = connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value
        request_id = 'SCR-' + 'a' * 32
        cursor.fetchall.return_value = [(request_id,)]
        sender = servicebus.return_value.__enter__.return_value.get_queue_sender.return_value.__enter__.return_value
        processor.publish_credit_outbox(MagicMock())
        message = sender.send_messages.call_args.args[0]
        self.assertEqual(message.message_id, request_id)
        self.assertEqual(connection.commit.call_count, 2)
        self.assertTrue(any("Published" in c.args[0] for c in cursor.execute.call_args_list))


if __name__ == '__main__':
    unittest.main()
