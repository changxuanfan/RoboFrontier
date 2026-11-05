"""What a policy script can and cannot do, as it runs inside an engine's sandbox.

scripts/check_policy_env.py copies this file into a throwaway run and has each engine's
real CLI run it as an ordinary shell command. It writes ok/denied results to a file, once
finished, and never records what a file contains.
"""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

FINISHED = 'PROBE-FINISHED'


def probe(fixtures):
    """Each named attempt's outcome: 'ok' if it succeeded, otherwise 'denied'."""
    results = {}
    home, run, env = Path(fixtures['real_home']), Path(fixtures['run']), Path(fixtures['env'])

    def attempt(name, action):
        try:
            action()
            results[name] = 'ok'
        except Exception:
            results[name] = 'denied'

    def shell(command):
        subprocess.run(['sh', '-c', command], check=True, capture_output=True, timeout=60)

    def importable(module):
        subprocess.run([sys.executable, '-c', 'import ' + module], check=True, capture_output=True, timeout=120)

    def write(path):
        Path(path).write_text('x')

    def connect(kind, address):
        with socket.socket(socket.AF_INET, kind) as sock:
            sock.settimeout(3)
            sock.connect(address)
            sock.send(b'x')

    def unix_socket():
        with socket.socket(socket.AF_UNIX) as sock:
            sock.bind(str(Path(fixtures['shared_tmp'])/'probe.sock'))

    def plot():
        script = ("import matplotlib.pyplot as p;p.plot([1,2]);p.savefig('plot.png');"
                  "import cv2,numpy,scipy,PIL;cv2.imwrite('array.png',numpy.zeros((4,4),'uint8'))")
        subprocess.run([sys.executable, '-c', script], check=True, capture_output=True, timeout=300)

    def expect(condition):
        if not condition:
            raise ValueError('unexpected')

    # Ordinary work that must keep working.
    attempt('python_is_environment', lambda: expect(Path(sys.prefix).resolve().is_relative_to(env)))
    attempt('python_on_path_is_environment',
            lambda: expect(Path(shutil.which('python') or '/missing').resolve().is_relative_to(env)))
    attempt('tmpdir_in_workspace', lambda: expect(Path(tempfile.gettempdir()).resolve().is_relative_to(run/'workspace')))
    attempt('home_in_workspace', lambda: expect(Path.home().resolve().is_relative_to(run/'workspace')))
    attempt('threads_not_limited', lambda: expect(not any(name.endswith('_NUM_THREADS') for name in os.environ)))
    attempt('host_variables_gone', lambda: expect(not any(name in os.environ for name in fixtures['host_only'])))
    attempt('libraries_and_plots', plot)
    attempt('tempfile', lambda: tempfile.NamedTemporaryFile().close())
    attempt('shell_heredoc', lambda: shell('cat <<EOF\nx\nEOF'))
    attempt('shell_sort', lambda: shell('seq 1 200000 | sort -r | head -1'))
    attempt('subprocess_system_tool', lambda: shell('/usr/bin/true && ls /usr/bin >/dev/null'))
    attempt('read_public', lambda: (run/'public/inputs/task.json').read_bytes())
    attempt('write_workspace', lambda: write(run/'workspace/probe.txt'))
    attempt('read_environment', lambda: (env/'policy-env.json').read_bytes())
    attempt('pip_install_store', lambda: shell(sys.executable + ' -m pip install -q networkx'))
    attempt('import_installed', lambda: importable('networkx'))
    attempt('venv', lambda: shell(sys.executable + ' -m venv --without-pip ' + str(run/'workspace/.tmp/venv')))
    attempt('read_shared_tmp', lambda: (Path(fixtures['shared_tmp'])/'canary.txt').read_bytes())
    attempt('write_shared_tmp', lambda: write(Path(fixtures['shared_tmp'])/'written.txt'))
    # What must stay closed.
    attempt('read_home', lambda: os.listdir(home))
    attempt('read_home_file', lambda: Path(fixtures['home_file']).read_bytes())
    attempt('read_users', lambda: os.listdir('/Users'))
    attempt('read_volumes', lambda: os.listdir('/Volumes'))
    attempt('read_keychains', lambda: os.listdir('/Library/Keychains'))
    attempt('read_private', lambda: (run/'private/inputs/secret.txt').read_bytes())
    attempt('read_run_root', lambda: (run/'root.txt').read_bytes())
    attempt('read_other_run', lambda: Path(fixtures['other_run_file']).read_bytes())
    attempt('read_repository', lambda: Path(fixtures['repo_file']).read_bytes())
    attempt('write_public', lambda: write(run/'public/inputs/written.txt'))
    attempt('write_run_root', lambda: write(run/'written.txt'))
    attempt('write_environment', lambda: write(env/'written.txt'))
    attempt('run_other_python', lambda: subprocess.run([fixtures['other_python'], '-c', 'pass'], check=True, capture_output=True))
    attempt('import_mujoco', lambda: importable('mujoco'))
    attempt('pip_install_absent_package', lambda: shell(sys.executable + ' -m pip install -q mujoco'))
    attempt('network_tcp', lambda: connect(socket.SOCK_STREAM, ('127.0.0.1', fixtures['listener_port'])))
    attempt('network_external', lambda: connect(socket.SOCK_STREAM, ('1.1.1.1', 443)))
    attempt('unix_socket_shared', unix_socket)
    attempt('list_processes', lambda: shell('/bin/ps ax'))
    return results


if __name__ == '__main__':
    target = Path(sys.argv[2])
    part = target.with_suffix('.part')
    part.write_text(json.dumps(probe(json.loads(Path(sys.argv[1]).read_text()))))
    part.rename(target)
    print(FINISHED)
