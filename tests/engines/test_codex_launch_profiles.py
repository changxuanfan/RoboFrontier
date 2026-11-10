"""Codex launch profiles: provider, credential variable, wire API and effort."""
import json
from pathlib import Path
import tempfile
import unittest

from robofrontier.engines.codex.launch import profile, launch_config


class CodexLaunchProfileTests(unittest.TestCase):
    def test_openlux_luna_has_separate_provider_and_high_effort(self):
        p = profile('openlux-luna')
        with tempfile.TemporaryDirectory() as folder:
            launch = launch_config(p, Path(folder))
            self.assertEqual((p['model'], p['effort']), ('gpt-6-luna', 'high'))
            self.assertIn('model_providers.openlux.env_key="OPENLUX_API_KEY"', launch['args'])
            self.assertIn('model_providers.openlux.wire_api="responses"', launch['args'])

    def test_openlux_profile_uses_responses_and_separate_credential(self):
        p = profile('openlux-terra')
        with tempfile.TemporaryDirectory() as folder:
            launch = launch_config(p, Path(folder))
            self.assertEqual((p['model'], p['effort']), ('gpt-6.1-terra', 'high'))
            self.assertIn('model_providers.openlux.env_key="OPENLUX_API_KEY"', launch['args'])
            self.assertIn('model_providers.openlux.base_url="https://api.openlux.ai/v1"', launch['args'])
            self.assertIn('model_providers.openlux.wire_api="responses"', launch['args'])
            self.assertFalse(json.loads((Path(folder)/'models.json').read_text())['models'][0]['use_responses_lite'])

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
