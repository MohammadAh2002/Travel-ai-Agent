import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock, patch

from app.chat.flow import chat_flow
from app.core.models import ChatRequest


@asynccontextmanager
async def fake_connection():
    yield object()


class RecallTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        p = patch('app.services.memory.SESSION_DB_PATH', Path(directory.name) / 'sessions.sqlite3')
        p.start()
        self.addCleanup(p.stop)

    def recall(self, message, result=None, error=None):
        tool = AsyncMock(return_value=result, side_effect=error)
        with patch('app.chat.flow.connection', fake_connection), \
                patch('app.chat.flow.call_tool', tool), \
                patch('app.chat.flow.coordinate', new=AsyncMock()) as coordinator, \
                patch('app.chat.flow.answer_general', new=AsyncMock()) as general:
            response = asyncio.run(chat_flow(ChatRequest(
                session_id='new-chat', message=message, user={'traveller_id': 'TRV-person-1'})))
            coordinator.assert_not_awaited()
            general.assert_not_awaited()
        tool.assert_awaited_once_with(unittest.mock.ANY, 'get_preferences', {'traveller_id': 'TRV-person-1'})
        self.assertEqual(response['citations'], [])
        self.assertIsNone(response['pending_action'])
        return response

    def test_recall_in_new_chat_uses_saved_preferences(self):
        result = self.recall('what do you know about me?', {'preferences': {
            'dietary': ['vegetarian'], 'interests': ['museums', 'history']}})
        self.assertIn('vegetarian', result['reply'])
        self.assertIn('museums, history', result['reply'])

    def test_arabic_recall(self):
        self.assertIn('vegetarian', self.recall('شو بتتذكر عني؟', {
            'preferences': {'dietary': ['vegetarian']}})['reply'])

    def test_not_found_is_distinct_from_outage(self):
        self.assertIn("don't have any saved", self.recall('Show my saved preferences',
            error=RuntimeError('traveller_not_found: No saved preferences'))['reply'])
        self.assertIn("couldn't load", self.recall('Show my saved preferences',
            error=RuntimeError('service_unavailable: offline'))['reply'])

    def test_mcp_wrapped_not_found_is_not_a_service_failure(self):
        missing = RuntimeError('traveller_not_found: No saved preferences')
        wrapped = ExceptionGroup('task group', [ExceptionGroup('inner group', [missing])])
        result = self.recall('what do you know about me?', error=wrapped)
        self.assertIn("don't have any saved", result['reply'])
        self.assertTrue(result['tool_calls'][0]['ok'])

    def test_mixed_mcp_failures_are_not_hidden(self):
        wrapped = ExceptionGroup('task group', [
            RuntimeError('traveller_not_found: No saved preferences'),
            RuntimeError('service_unavailable: offline'),
        ])
        self.assertIn("couldn't load", self.recall('what do you know about me?',
            error=wrapped)['reply'])

    def test_explicit_remember_cannot_be_routed_to_general(self):
        # Exercise the real coordinator and flow, including a wrong model intent.
        extracted = {'intent': 'general', 'preference_updates': {
            'dietary': ['vegetarian'], 'interests': ['museums', 'history']}}
        with patch('app.agents.coordinator.run_crew', new=AsyncMock(
                return_value=(extracted, {'cost_usd': 0}, []))) as crew, \
                patch('app.chat.flow.answer_general', new=AsyncMock()) as general, \
                patch('app.chat.flow.connection') as connection:
            result = asyncio.run(chat_flow(ChatRequest(session_id='save-preferences',
                message='Remember that I am vegetarian and enjoy museums and history.',
                user={'traveller_id': 'TRV-person-1'})))
        general.assert_not_awaited()
        connection.assert_not_called()
        self.assertIn('explicit request to save', crew.await_args.args[0][0].instructions)
        self.assertEqual(result['pending_action']['type'], 'save_preferences')
        self.assertEqual(result['pending_action']['payload']['preferences'], extracted['preference_updates'])
        self.assertEqual(result['pending_action']['payload']['traveller_id'], 'TRV-person-1')
