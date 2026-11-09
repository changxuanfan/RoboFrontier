import unittest
from pathlib import Path
from unittest import mock

from scripts import factory_server


class FactoryServerCliTests(unittest.TestCase):
    def call(self, *extra):
        argv = ['factory_server', 'import-motion', '--recording', '/r/motion', '--output', '/o', *extra]
        with mock.patch('sys.argv', argv), mock.patch.object(factory_server.server, 'import_motion',
                                                             return_value={}) as imported, mock.patch('builtins.print'):
            factory_server.main()
        return imported.call_args.kwargs

    def test_import_motion_defaults_to_the_family_speedup_and_meaningful_motion(self):
        args = self.call()
        self.assertIsNone(args['speedup'])
        self.assertFalse(args['keep_idle'])
        self.assertIsNone(args['timeline'])

    def test_import_motion_forwards_keep_idle_timeline_and_speedup(self):
        args = self.call('--keep-idle', '--timeline', '/t/motion-cut.json', '--speedup', '2')
        self.assertEqual((args['keep_idle'], args['timeline'], args['speedup']), (True, Path('/t/motion-cut.json'), 2.0))


if __name__ == '__main__':
    unittest.main()
