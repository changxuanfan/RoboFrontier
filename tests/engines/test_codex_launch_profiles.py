"""Codex launch profiles: provider, credential variable, wire API and effort."""
import json
from pathlib import Path
import tempfile
import unittest

from roboteam.engines.codex.launch import profile, launch_config


class CodexLaunchProfileTests(unittest.TestCase):
    def test_a_third_party_profile_has_its_own_provider_and_credential(self):
        p = profile('kimi')
        with tempfile.TemporaryDirectory() as folder:
            launch = launch_config(p, Path(folder))
            self.assertEqual((p['model'], p['effort']), ('kimi-k3.1-pro', 'high'))
            self.assertIn('model_providers.kimi.env_key="KIMI_API_KEY"', launch['args'])
            self.assertIn('model_providers.kimi.base_url="https://api.moonshot.cn/v1"', launch['args'])
            self.assertIn('model_providers.kimi.wire_api="responses"', launch['args'])
            self.assertFalse(json.loads((Path(folder)/'models.json').read_text())['models'][0]['use_responses_lite'])

    def test_the_default_profile_is_gpt_6_1_sol_with_an_api_key(self):
        p = profile('sol')
        with tempfile.TemporaryDirectory() as folder:
            launch = launch_config(p, Path(folder))
            self.assertEqual((p['model'], p['effort']), ('gpt-6.1-sol', 'high'))
            self.assertIn('model_providers.openai_api.env_key="OPENAI_API_KEY"', launch['args'])
            self.assertIn('model_providers.openai_api.base_url="https://api.openai.com/v1"', launch['args'])

    def test_profile_requires_openai_api_and_high(self):
        p = profile('luna')
        with tempfile.TemporaryDirectory() as folder:
            launch = launch_config(p, Path(folder))
            self.assertEqual((p['model'], p['effort']), ('gpt-6-luna', 'high'))
            self.assertIn('model_providers.openai_api.env_key="OPENAI_API_KEY"', launch['args'])
            self.assertIn('model_providers.openai_api.base_url="https://api.openai.com/v1"', launch['args'])
            self.assertIn('model_providers.openai_api.wire_api="responses"', launch['args'])


if __name__ == '__main__':
    unittest.main()
