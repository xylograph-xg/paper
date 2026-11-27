import sys
import unittest
from unittest.mock import MagicMock, patch
from core.api import paths__WorkspacePath as Path

from article.api import gpt_session


class ProviderAdapterTests(unittest.TestCase):
    def test_deepseek_is_explicit_and_uses_native_thinking(self):
        module=MagicMock()
        with patch('article.src.web_gpt_adapter.check_browser') as check, patch('article.src.web_gpt_adapter.importlib.import_module',return_value=module):
            with gpt_session('deepseek'):pass
        check.assert_called_once_with('deepseek')
        module.create_session.assert_called_once_with('deepseek',new_chat=True,site='international',model=None,thinking_high=True)
    def test_existing_session_keeps_gpt_and_legacy_effort(self):
        module = MagicMock()
        with patch('article.src.web_gpt_adapter.check_browser'), patch('article.src.web_gpt_adapter.importlib.import_module', return_value=module):
            with gpt_session():
                pass
        module.ChatGPTWeb.assert_called_once_with(new_chat=True, thinking_high=False)
        module.create_session.assert_not_called()

    def test_qwen_is_explicit_and_passes_exact_model(self):
        module = MagicMock()
        with patch('article.src.web_gpt_adapter.check_browser') as check, patch('article.src.web_gpt_adapter.importlib.import_module', return_value=module):
            with gpt_session('qwen', model='Qwen3.8-Max'):
                pass
        check.assert_called_once_with('qwen')
        module.create_session.assert_called_once_with('qwen', new_chat=True, site='international', model='Qwen3.8-Max', thinking_high=True)
        module.ChatGPTWeb.assert_not_called()
