import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from webapp.app import app, _citation_text, _handle_response, _query_fabric


class CaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch('webapp.app.cases.list_cases', return_value=[{'CaseId': 'CASE-1042', 'CaseStatus': 'Pending'}])
    @patch('webapp.app.cases.configured', return_value=True)
    def test_case_list(self, configured, listing):
        response = self.client.get('/api/cases')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0]['CaseId'], 'CASE-1042')

    @patch('webapp.app.cases.set_status', return_value=True)
    def test_status_requires_supported_value(self, update):
        self.assertEqual(self.client.post('/api/cases/CASE-1042/status', json={'status': 'Deleted'}).status_code, 400)
        update.assert_not_called()
        self.assertEqual(self.client.post('/api/cases/CASE-1042/status', json={'status': 'Resolved'}).status_code, 200)
        update.assert_called_once_with('CASE-1042', 'Resolved')

    @patch('webapp.app.cases.get_case', return_value={'CaseId': 'CASE-1042', 'CaseStatus': 'Pending'})
    def test_agent_receives_database_tool_result(self, lookup):
        call = SimpleNamespace(type='function_call', name='get_case_details', call_id='call1', arguments=json.dumps({'case_id': 'CASE-1042'}))
        response = SimpleNamespace(output=[call])
        final = SimpleNamespace(output=[], output_text='Case found')
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: final))
        with patch('webapp.app._state', {'conversation_id': 'conv', 'pending': {}}):
            self.assertEqual(_handle_response(client, response)['text'], 'Case found')
        lookup.assert_called_once_with('CASE-1042')

    def test_sharepoint_citation_uses_filename(self):
        text = 'Policy【0:0†source】'
        path = '/drives/example/root:/Policies/Service Credit Issuance.docx'
        citation = SimpleNamespace(type='url_citation', start_index=6, end_index=len(text), title=path, url=path)
        content = SimpleNamespace(type='output_text', text=text, annotations=[citation])
        response = SimpleNamespace(output=[SimpleNamespace(type='message', content=[content])])
        self.assertEqual(_citation_text(response), 'Policy [Service Credit Issuance.docx]')

    def test_fabric_requires_user_token(self):
        call = SimpleNamespace(arguments=json.dumps({'question': 'How many customers?'}))
        self.assertIn('signed-in user', _query_fabric(call, None)['error'])

    def test_approval_cannot_be_taken_by_another_user(self):
        pending = {'p1': {'calls': []}}
        with patch('webapp.app.REHEARSAL', False), patch('webapp.app._state', {'user_id': 'owner', 'pending': pending}):
            response = self.client.post('/api/decision', headers={'x-ms-client-principal-id': 'other'}, json={'pending_id': 'p1', 'approved': True})
        self.assertEqual(response.status_code, 403)
        self.assertIn('p1', pending)

    @patch('webapp.app._handle_response', return_value={'type': 'message', 'text': 'Misleading model explanation'})
    @patch('webapp.app._execute_credit_request', return_value={'status': 'invalid_request', 'message': 'Customer availability is missing. No request was saved.'})
    @patch('webapp.app._openai_client')
    def test_validation_result_is_shown_instead_of_model_guess(self, client_factory, execute, handle):
        call = SimpleNamespace(name='create_service_credit_request', call_id='call1', arguments='{}')
        state = {'user_id': 'owner', 'pending': {'p1': {'calls': [call]}}, 'conversation_id': 'c1'}
        with patch('webapp.app.REHEARSAL', False), patch('webapp.app._state', state):
            response = self.client.post('/api/decision', headers={'x-ms-client-principal-id': 'owner'}, json={'pending_id': 'p1', 'approved': True})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['text'], 'Customer availability is missing. No request was saved.')

    @patch('requests.post')
    @patch.dict('os.environ', {'FABRIC_IQ_SEARCH_ENDPOINT': 'https://example.search.windows.net', 'FABRIC_IQ_KNOWLEDGE_BASE': 'fabric-kb', 'FABRIC_IQ_KNOWLEDGE_SOURCE': 'fabric-source'})
    def test_fabric_forwards_user_token_and_preserves_reference(self, post):
        post.return_value.json.return_value = {'references': [{'type': 'fabricOntology', 'sourceData': {'fabricAnswer': 'Five customers', 'fabricRawData': 'count\n5'}}]}
        call = SimpleNamespace(arguments=json.dumps({'question': 'How many customers?'}))
        result = _query_fabric(call, 'test-user-token')
        self.assertEqual(post.call_args.kwargs['headers']['x-ms-query-source-authorization'], 'test-user-token')
        self.assertEqual(result['references'][0]['data'], 'count\n5')
        self.assertNotIn('test-user-token', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
