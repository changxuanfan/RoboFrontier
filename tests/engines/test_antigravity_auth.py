"""Native keychain lookup must not import personal agent customization."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.engines.antigravity import auth
from robofrontier.batch.collect import _files


class AuthenticationIsolationTests(unittest.TestCase):
    def test_private_home_shares_only_keychain_lookup_and_is_never_collected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(auth.sys, 'platform', 'darwin'):
            base = Path(folder).resolve()
            original, run = base/'original', base/'run'
            (original/'Library/Keychains').mkdir(parents=True)
            (original/'Library/Keychains/token-test').write_text('not collected')
            (original/'Library/Preferences').mkdir()
            (original/'Library/Preferences/com.apple.security.KCN.plist').write_text('lookup')
            (original/'.gemini/config/rules').mkdir(parents=True)
            (original/'.gemini/config/rules/personal.md').write_text('Never import this instruction')
            selected = {'auth_mode': 'native_login'}
            home = auth.environment_home(run, selected, original)
            self.assertEqual(home, run/'private/engine/home')
            self.assertEqual((home/'Library/Keychains').resolve(), original/'Library/Keychains')
            self.assertFalse((home/'.gemini/config/rules').exists())
            self.assertEqual(json.loads((home/'.gemini/config/config.json').read_text()), auth.HOME_CONFIG)
            self.assertEqual(auth.environment_home(run, selected, original), home)
            self.assertFalse(any(p.is_relative_to(home) for p in _files(run)))

    def test_changed_keychain_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(auth.sys, 'platform', 'darwin'):
            base = Path(folder).resolve()
            original, run = base/'original', base/'run'
            (original/'Library/Keychains').mkdir(parents=True)
            home = auth.environment_home(run, {'auth_mode': 'native_login'}, original)
            (home/'Library/Keychains').unlink()
            (home/'Library/Keychains').symlink_to(base)
            with self.assertRaisesRegex(ValueError, 'bridge changed'):
                auth.environment_home(run, {'auth_mode': 'native_login'}, original)


if __name__ == '__main__':
    unittest.main()
