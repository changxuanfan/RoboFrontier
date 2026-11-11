"""A vanished MCP owner must not leave a command writing to the workspace."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


class LifetimeTests(unittest.TestCase):
    def test_killing_owner_stops_its_detached_command(self):
        with tempfile.TemporaryDirectory() as folder:
            marker = Path(folder)/'orphan-write'
            command = [sys.executable, '-c',
                'import time,pathlib;print("started",flush=True);time.sleep(2);pathlib.Path(__import__("sys").argv[1]).touch()',
                str(marker)]
            owner_code = '''import os,subprocess,sys,time
r,w=os.pipe()
p=subprocess.Popen([sys.executable,'-m','robofrontier.engines.common.tool_guardian',str(r),sys.argv[1]],
                   pass_fds=(r,),start_new_session=True)
os.close(r)
time.sleep(30)
'''
            owner = subprocess.Popen([sys.executable, '-c', owner_code, json.dumps(command)], stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), 'started')
                owner.kill()
                owner.wait(timeout=5)
                # The guardian closes stdout only after stopping the command.
                out, err = owner.communicate(timeout=5)
                self.assertEqual(err, '')
                time.sleep(2.1)
                self.assertFalse(marker.exists())
            finally:
                if owner.poll() is None:
                    owner.kill()
                owner.communicate(timeout=5)


if __name__ == '__main__':
    unittest.main()
