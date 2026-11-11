"""Host-bound file tools: Seatbelt on macOS and the Codex Landlock worker on Linux."""
import base64
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

TOOLS = [
    {'name': 'policy_exec', 'description': 'Run a shell command within your run file permissions. Read public inputs and edit workspace notes. No network access. Commands time out after at most 60 seconds.',
     'inputSchema': {'type': 'object', 'properties': {'command': {'type': 'string'}, 'timeout_s':
        {'type': 'number', 'minimum': 1, 'maximum': 60}}, 'required': ['command'], 'additionalProperties': False}},
    {'name': 'policy_image', 'description': 'View a permitted PNG or JPEG by absolute path or relative to the run workspace. File access is enforced inside the isolated worker.',
     'inputSchema': {'type': 'object', 'properties': {'path': {'type': 'string'}}, 'required': ['path'], 'additionalProperties': False}},
]


def seatbelt(table):
    """Specific paths override ancestors, including paths created after preparation.

    A deny rule excludes every explicitly reopened descendant. Nested denies
    remain separate rules, so workspace/.agents stays closed inside workspace.
    No enumeration of the host filesystem is needed.
    """
    def subpath(path):
        return '(subpath ' + json.dumps(path) + ')'
    def denied_region(path, allowed):
        exceptions = [other for other in allowed if other != path and Path(other).is_relative_to(path)]
        return ('(require-all ' + subpath(path) + ''.join(' (require-not '+subpath(p)+')' for p in exceptions) + ')')
    readable = [p for p, m in table.items() if m in ('read', 'write')]
    writable = [p for p, m in table.items() if m == 'write'] + ['/dev/null']
    rules = ['(version 1)', '(allow default)', '(deny network*)',
             '(deny process-info* (target others))', '(deny signal (target others))']
    for path, mode in table.items():
        if mode == 'deny':
            rules.append('(deny file-read* ' + denied_region(path, readable) + ')')
    rules.append('(deny file-write* ' + denied_region('/', writable) + ')')
    for path, mode in table.items():
        if mode != 'write':
            rules.append('(deny file-write* ' + denied_region(path, writable) + ')')
    rules.append('(allow file-write* (literal "/dev/null"))')
    return '\n'.join(rules)


def execute(run, tool, args, *, timeout=None):
    run = Path(run).resolve()
    if not isinstance(args, dict) or tool not in ('policy_exec', 'policy_image'):
        raise ValueError('Invalid file tool')
    allowed = {'command', 'timeout_s'} if tool == 'policy_exec' else {'path'}
    value = args.get('command' if tool == 'policy_exec' else 'path')
    limit = timeout if timeout is not None else args.get('timeout_s', 30)
    if (set(args) - allowed or not isinstance(value, str) or not 0 < len(value.encode()) <= 131000
            or type(limit) not in (int, float) or not math.isfinite(limit) or not 1 <= limit <= (300 if timeout is not None else 60)):
        raise ValueError('Invalid file tool arguments or timeout')
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    table = dict(access['filesystem'])
    table[str(run/'workspace/.agents')] = 'deny'
    if access.get('network') is not False or not access.get('policy_env'):
        raise ValueError('File tools require the frozen policy environment and network off')
    request = {'tool': tool, 'command' if tool == 'policy_exec' else 'path': value}
    payload = None
    env = dict(access['policy_env']['variables'])
    if sys.platform == 'linux':
        code = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                'from robofrontier.engines.common.tool_worker import main;main()')
        command = [sys.executable, '-I', '-c', code, str(Path(__file__).resolve().parents[3]), '--run-dir', str(run)]
        payload = json.dumps(request).encode()
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8'}
    elif sys.platform == 'darwin':
        if tool == 'policy_exec':
            inner = ['/bin/bash', '--noprofile', '--norc', '-c', value]
        else:
            code = ('import base64,json,sys; p=open(sys.argv[1],"rb").read(8388609); '
                    'm="image/png" if p.startswith(b"\\x89PNG\\r\\n\\x1a\\n") else "image/jpeg" if p.startswith(b"\\xff\\xd8\\xff") else None; '
                    'assert m and len(p)<=8388608; print(json.dumps({"mime":m,"data":base64.b64encode(p).decode()}))')
            inner = [env['PATH'].split(':')[0]+'/python', '-I', '-c', code, value]
        command = ['/usr/bin/sandbox-exec', '-p', seatbelt(table), *inner]
    else:
        raise ValueError('File tools require Linux or macOS')
    lease_read, lease_write = os.pipe()
    guardian = ('import sys;sys.path.insert(0,sys.argv.pop(1));'
                'from robofrontier.engines.common.tool_guardian import main;sys.exit(main())')
    guarded = [sys.executable, '-I', '-c', guardian, str(Path(__file__).resolve().parents[3]),
               str(lease_read), json.dumps(command)]
    try:
        process = subprocess.Popen(guarded, cwd=run/'workspace', env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
            close_fds=True, pass_fds=(lease_read,))
    except BaseException:
        os.close(lease_write)
        raise
    finally:
        os.close(lease_read)
    chunks = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    try:
        if payload:
            process.stdin.write(payload)
        process.stdin.close()
        for stream in chunks:
            selector.register(stream, selectors.EVENT_READ)
        deadline = time.monotonic() + limit
        while selector.get_map():
            if time.monotonic() >= deadline:
                raise TimeoutError('File tool timed out; inspect workspace before retrying')
            for key, _ in selector.select(.1):
                block = os.read(key.fd, 65536)
                if not block:
                    selector.unregister(key.fileobj)
                else:
                    chunks[key.fileobj].extend(block)
                    if sum(map(len, chunks.values())) > 12 * 1024 * 1024:
                        raise ValueError('File tool output limit exceeded')
        code = process.wait(timeout=max(.01, deadline-time.monotonic()))
        out, err = (bytes(chunks[stream]).decode(errors='replace') for stream in (process.stdout, process.stderr))
        if tool == 'policy_image' and code == 0:
            image = json.loads(out)
            return {'content': [{'type': 'image', 'mimeType': image['mime'], 'data': image['data']}]}
        return {'isError': code != 0, 'content': [{'type': 'text', 'text': json.dumps(
            {'exit_code': code, 'stdout': out, 'stderr': err})}]}
    finally:
        os.close(lease_write)
        selector.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)
        process.stdout.close()
        process.stderr.close()
