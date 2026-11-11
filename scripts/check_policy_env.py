"""Check a policy environment and each engine's sandbox before a batch uses them.

Runs each real CLI against a local stub model in a throwaway run, with the access table and
variables a real run freezes. No provider is contacted and no credential is used. Prints
ok/denied per attempt and never prints file contents; exits nonzero on any difference. A pass
on both engines records a receipt beside the environment, which preparing a run requires. The
receipt lists each engine with the sandbox and CLI version it ran, and preparation refuses any
other combination. Give --scratch where batches will really run, since where a run sits changes
what can be opened.

    .venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id>
"""
import argparse
import http.server
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

from robofrontier.runtime import access as policy_access, policy_env, policy_env_probe
from robofrontier.runtime.layout import manifest_record

ROOT = Path(__file__).resolve().parents[1]
MUST_WORK = ('python_is_environment', 'python_on_path_is_environment', 'tmpdir_in_workspace', 'home_in_workspace',
             'threads_not_limited', 'host_variables_gone', 'libraries_and_plots', 'tempfile', 'shell_heredoc', 'shell_sort',
             'subprocess_system_tool', 'read_public', 'write_workspace', 'read_environment', 'pip_install_store',
             'import_installed', 'venv', 'shell_reports_success', 'read_shared_tmp', 'write_shared_tmp', 'create_in_tmp',
             'process_pool', 'process_executor', 'core_versions')
MUST_FAIL = ('read_host_shared_memory', 'read_home', 'read_home_file', 'read_people', 'read_disks', 'read_system_secrets', 'read_var_tmp', 'read_private', 'read_run_root',
             'read_other_run', 'read_repository', 'tool_write_shared_tmp', 'write_public', 'write_run_root',
             'write_environment', 'run_other_python', 'import_mujoco', 'pip_install_absent_package', 'network_tcp',
             'network_external', 'unix_socket_shared', 'unix_socket_connect', 'network_udp', 'signal_other_process',
             'see_host_processes', 'read_parent_environ', 'ps_parent_environment')
HOST_ONLY = 'ROBOFRONTIER_PROBE_HOST_ONLY'
# What the parent-environment probes look for: a subscription credential in any ancestor's
# environment. The local stub's fake API key stays in the CLI's environment; Claude API-key
# profiles are refused where the sandbox shows other processes (claude_prepare.prepare_batch).
CREDENTIALS = ('CLAUDE_CODE_OAUTH_TOKEN', 'OPENAI_API_KEY', 'ROBOFRONTIER_OFFLINE_STUB_TOKEN')
CLOSED_FOLDERS = {'darwin': {'read_people': '/Users', 'read_disks': '/Volumes', 'read_system_secrets': '/Library/Keychains', 'read_var_tmp': '/var/tmp'},
                  'linux': {'read_people': '/home', 'read_disks': '/raid', 'read_system_secrets': '/root', 'read_var_tmp': '/var/tmp'}}
FEW_PROCESSES = 15
# Claude's macOS sandbox refuses the system limit that ProcessPoolExecutor reads first; Pool works.
KNOWN_LIMITS = {('darwin', 'claude'): ('process_executor',)}
# Python's process pools keep their locks in /dev/shm, which is shared with other runs. Where the
# host forbids user namespaces (RunPod pods) no command can get a private one, so it stays closed
# and process pools fail; threads and plain subprocesses still work.
SHARED_MEMORY_LIMITS = ('process_pool', 'process_executor')
# Landlock cannot hide processes: a policy shell lists them, but cannot read their environments or
# trace or signal them (the read_parent_environ, ps_parent_environment and signal probes).
LANDLOCK_LIMITS = ('see_host_processes',)
OTHER_PYTHONS = ('/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3')
OUTPUT_TYPES = ('function_call_output', 'custom_tool_call_output')
PROBE_LIMIT_S = 280
RUNNING = re.compile(r'Process running with session ID (\d+)')
RESULT = 'probe-result.json'


def _stream(self, data):
    self.send_response(200)
    self.send_header('Content-Type', 'text/event-stream')
    self.send_header('Content-Length', str(len(data)))
    self.end_headers()
    self.wfile.write(data)


def claude_stub(command, seen, shared):
    """An Anthropic Messages stub: one Bash call, then Write on the shared folder."""
    tools = [('Bash', {'command': command, 'description': 'probe', 'timeout': 600000}),
             ('Write', {'file_path': str(shared/'tool-written.txt'), 'content': 'x'})]
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            done = [item for message in body.get('messages', []) if isinstance(message.get('content'), list)
                    for item in message['content'] if isinstance(item, dict) and item.get('type') == 'tool_result']
            seen.extend(item for item in done if item not in seen)
            if len(done) < len(tools):
                tool, data = tools[len(done)]
                block = {'type': 'tool_use', 'id': 'toolu_%d' % len(done), 'name': tool, 'input': {}}
                delta, reason = {'type': 'input_json_delta', 'partial_json': json.dumps(data)}, 'tool_use'
            else:
                block, delta, reason = {'type': 'text', 'text': ''}, {'type': 'text_delta', 'text': 'done'}, 'end_turn'
            message = {'id': 'msg_probe', 'type': 'message', 'role': 'assistant', 'model': 'claude-opus-5-5', 'content': [],
                       'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 1, 'output_tokens': 1}}
            events = [('message_start', {'type': 'message_start', 'message': message}),
                      ('content_block_start', {'type': 'content_block_start', 'index': 0, 'content_block': block}),
                      ('content_block_delta', {'type': 'content_block_delta', 'index': 0, 'delta': delta}),
                      ('content_block_stop', {'type': 'content_block_stop', 'index': 0}),
                      ('message_delta', {'type': 'message_delta', 'delta': {'stop_reason': reason, 'stop_sequence': None},
                                         'usage': {'output_tokens': 1}}),
                      ('message_stop', {'type': 'message_stop'})]
            _stream(self, ''.join('event: %s\ndata: %s\n\n' % (name, json.dumps(data)) for name, data in events).encode())
    return Handler


def codex_stub(command, seen):
    """A Responses stub: one exec_command call, polled until it exits, then the end of the turn."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            done = [item for item in body.get('input', []) if isinstance(item, dict) and item.get('type') in OUTPUT_TYPES]
            seen.extend(item for item in done if item not in seen)
            running = RUNNING.search(json.dumps(done[-1]['output'])) if done else None
            if running:
                item = dict(id='fc_%d' % len(done), type='function_call', call_id='call_%d' % len(done), name='write_stdin', status='completed',
                            arguments=json.dumps({'session_id': int(running.group(1)), 'chars': '', 'yield_time_ms': 30000}))
            elif done:
                item = dict(id='msg_probe', type='message', role='assistant', status='completed',
                            content=[dict(type='output_text', text='DONE', annotations=[])])
            else:
                item = dict(id='fc_probe', type='function_call', call_id='call_probe', name='exec_command', status='completed',
                            arguments=json.dumps({'cmd': command, 'login': False, 'yield_time_ms': 30000}))
            response = dict(id='resp_probe', object='response', created_at=int(time.time()), status='completed',
                            model=body.get('model'), output=[item],
                            usage=dict(input_tokens=1, output_tokens=1, total_tokens=2, input_tokens_details={'cached_tokens': 0},
                                       output_tokens_details={'reasoning_tokens': 0}))
            events = [('response.created', {'response': {**response, 'status': 'in_progress', 'output': []}}),
                      ('response.output_item.added', {'output_index': 0, 'item': {**item, 'status': 'in_progress'}}),
                      ('response.output_item.done', {'output_index': 0, 'item': item}),
                      ('response.completed', {'response': response})]
            _stream(self, ''.join('event: %s\ndata: %s\n\n' % (kind, json.dumps({'type': kind, 'sequence_number': i, **data}))
                                  for i, (kind, data) in enumerate(events)).encode())
    return Handler


CODEX_DRIVER = r'''
const fs=require('fs'),{CodexRpc}=require(process.argv[1]+'/robofrontier/engines/codex/codex_rpc');
const out=process.argv[2],launch=JSON.parse(fs.readFileSync(out+'/launch.json')),run=fs.readFileSync(out+'/cwd.txt','utf8');
process.env.ROBOFRONTIER_OFFLINE_STUB_TOKEN='local-stub-no-credential';
(async()=>{let done;
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(out+'/server.log','w'),
  onEvent:m=>{if(m.method==='turn/completed'&&done)done();},onRequest:async()=>{throw new Error('no host tools');}});
await rpc.initialize();
const thread=(await rpc.call('thread/start',{model:launch.model,modelProvider:launch.provider,cwd:run,approvalPolicy:'never',ephemeral:false})).thread.id;
const finished=new Promise(r=>done=r);
await rpc.call('turn/start',{threadId:thread,model:launch.model,effort:launch.effort,input:[{type:'text',text:'go'}]});
await Promise.race([finished,new Promise((_,j)=>setTimeout(()=>j(new Error('turn timeout')),600000))]);
await rpc.close();process.exit(0);})().catch(e=>{console.error(e.stack);process.exit(1);});'''


def run_claude(run, command, scratch, seen, shared):
    from robofrontier.engines.claude.runner import build_command, confine, policy_settings, start_cli
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), claude_stub(command, seen, shared))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = run/'private/engine/config'
    config.mkdir(parents=True, exist_ok=True)
    settings, extra = confine(run, policy_settings(run), config)
    argv = build_command('claude-opus-5-5', 'high', '{"mcpServers":{}}', 'go', auth_mode='oauth_token', settings=settings)
    env = {'PATH': os.environ.get('PATH', ''), 'HOME': str(scratch/'cli-home'), HOST_ONLY: '1',
           'ANTHROPIC_BASE_URL': 'http://127.0.0.1:%d' % server.server_port, 'ANTHROPIC_API_KEY': 'local-fake-key',
           'CLAUDE_CODE_OAUTH_TOKEN': 'local-fake-token',
           'CLAUDE_CONFIG_DIR': str(config), 'DISABLE_TELEMETRY': '1', 'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
           'ENABLE_TOOL_SEARCH': 'false', 'ENABLE_CLAUDEAI_MCP_SERVERS': 'false', **extra}
    try:
        # Launched as a run launches it: the token goes to the CLI on a pipe, not in its environment.
        cli = start_cli(argv, env, cwd=run/'workspace', stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        try: _, err = cli.communicate(timeout=PROBE_LIMIT_S)
        except subprocess.TimeoutExpired:
            cli.kill(); cli.communicate(); raise
        if cli.returncode: raise subprocess.CalledProcessError(cli.returncode, argv, stderr=err)
    finally:
        server.shutdown()
        server.server_close()


def run_codex(run, command, scratch, seen, shared):
    from robofrontier.engines.codex.launch import launch_config
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), codex_stub(command, seen))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    out = scratch/'codex-host'
    out.mkdir()
    (scratch/'codex-home').mkdir()
    stub = dict(model='offline-protocol', provider='offline_protocol', effort='high', vision=True, context_window=272000,
                auto_compact_token_limit=258400, env_key='ROBOFRONTIER_OFFLINE_STUB_TOKEN',
                base_url='http://127.0.0.1:%d' % server.server_port)
    env = {**os.environ, 'CODEX_HOME': str(scratch/'codex-home'), 'HOME': str(scratch/'cli-home'), HOST_ONLY: '1'}
    previous = os.environ.get('CODEX_HOME')
    os.environ['CODEX_HOME'] = str(scratch/'codex-home')
    try:
        launch = launch_config(stub, out, run_dir=run)
    finally:
        if previous is None:
            del os.environ['CODEX_HOME']
        else:
            os.environ['CODEX_HOME'] = previous
    (out/'launch.json').write_text(json.dumps(launch))
    (out/'cwd.txt').write_text(str(run/'workspace'))
    try:
        subprocess.run(['node', '-e', CODEX_DRIVER, str(ROOT), str(out)], env=env, capture_output=True, timeout=PROBE_LIMIT_S, check=True)
    finally:
        server.shutdown()
        server.server_close()


def run_codex_landlock(run, command, scratch, seen, shared):
    """The Linux Codex path: its tools run in a confined worker, with no shell in the CLI."""
    from robofrontier.engines.codex import tool_backend
    tool_backend.prepare(run, {'tool_backend': 'landlock-v1', 'runner_backend': 'slurm-managed-v1'})
    done = tool_backend.execute(run, {'tool': 'policy_exec', 'command': command}, timeout=PROBE_LIMIT_S)
    seen.append({'content': done.stdout + done.stderr, 'is_error': done.returncode != 0})


ENGINES = {'codex': run_codex_landlock if sys.platform == 'linux' else run_codex, 'claude': run_claude}


def isolation(name):
    """The sandbox the check runs `name` in, which a run prepared on this host would freeze."""
    if name == 'codex':
        return 'landlock-v1' if ENGINES['codex'] is run_codex_landlock else 'native'
    from robofrontier.engines.common.landlock import choose
    return choose()


def throwaway_run(scratch, name, environment):
    """A run laid out as preparation lays it out, with the table a real run would freeze."""
    run = scratch/name/'run'
    other = scratch/name/'other-run'
    for folder in ('public/inputs', 'workspace', 'private/inputs'):
        (run/folder).mkdir(parents=True)
    (other/'private/inputs').mkdir(parents=True)
    (other/'private/inputs/task.json').write_text('OTHER-RUN')
    (run/'public/inputs/task.json').write_text('PUBLIC')
    (run/'private/inputs/secret.txt').write_text('PRIVATE')
    (run/'root.txt').write_text('ROOT')
    (run/'private/inputs/manifest.json').write_text(json.dumps(manifest_record(name)))
    policy_env.prepare_run(run, environment)
    access = policy_access.record(run, environment=environment, unchecked=True)
    (run/'private/inputs/policy-access.json').write_text(json.dumps(access))
    shutil.copy(policy_env_probe.__file__, run/'public/inputs/probe.py')
    return run, other


def shell_succeeded(seen):
    """Whether the engine's own shell wrapper returned the command's output and exit code 0.

    A script can succeed while the wrapper around it fails, as when the CLI cannot write
    its working-directory record or capture standard output.
    """
    text = json.dumps(seen)
    return (policy_env_probe.FINISHED in text and 'not permitted' not in text and 'exited with code 1' not in text
            and not any(item.get('is_error') for item in seen))


def check_engine(name, environment, scratch, mode):
    """Run the probe through one engine in sandbox `mode`; returns its results, or raises when it did not report."""
    run, other = throwaway_run(scratch, name, environment)
    if name == 'claude':
        # Read by claude.runner.confine, as a prepared run's launch record is.
        (run/'private/inputs/claude.json').write_text(json.dumps({'bash_isolation': mode}))
    shared = Path('/tmp')/('robofrontier-probe-' + scratch.name)
    shared.mkdir()
    shared_memory = Path('/dev/shm')/('robofrontier-probe-' + scratch.name)
    if shared_memory.parent.is_dir():
        shared_memory.write_text('SHARED')
    (shared/'canary.txt').write_text('SHARED')
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    host_socket = socket.socket(socket.AF_UNIX)
    host_socket.bind(str(shared/'host.sock'))
    host_socket.listen()
    datagrams = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    datagrams.bind(('127.0.0.1', 0))
    datagrams.setblocking(False)
    bystander = subprocess.Popen(['sleep', '900'])
    other_python = next((path for path in OTHER_PYTHONS if Path(path).exists()), '/missing/python3')
    fixtures = {'credentials': list(CREDENTIALS), 'real_home': str(Path.home().resolve()), 'run': str(run), 'env': str(environment), 'host_only': [HOST_ONLY, 'CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_API_KEY', 'CLAUDE_CONFIG_DIR', 'CODEX_HOME', 'ROBOFRONTIER_OFFLINE_STUB_TOKEN'],
                'home_file': next((str(p) for p in (Path.home()/'.zshrc', Path.home()/'.bashrc', Path.home()/'.profile') if p.is_file()), '/missing'),
                'shared_memory_file': str(shared_memory), 'closed_folders': CLOSED_FOLDERS[sys.platform], 'few_processes': FEW_PROCESSES,
                'core_packages': policy_env.load(environment)['packages'],
                'tmp_file': str(Path('/tmp')/('robofrontier-probe-new-' + scratch.name)),
                'other_run_file': str(other/'private/inputs/task.json'), 'repo_file': str(ROOT/'pyproject.toml'),
                'shared_tmp': str(shared), 'other_python': other_python, 'listener_port': listener.getsockname()[1],
                'host_socket': str(shared/'host.sock'), 'udp_port': datagrams.getsockname()[1], 'host_pid': bystander.pid}
    (run/'public/inputs/probe.json').write_text(json.dumps(fixtures))
    # A here-document in the engine's own shell, which may not take its temporary file from TMPDIR.
    # Here-documents and the CLI's own records need /tmp, so a closed /tmp fails shell_reports_success.
    command = ("cat > /dev/null <<'EOF'\nx\nEOF\npython %s %s %s"
               % (run/'public/inputs/probe.py', run/'public/inputs/probe.json', run/'workspace'/RESULT))
    (scratch/'cli-home').mkdir(exist_ok=True)
    try:
        seen = []
        ENGINES[name](run, command, scratch, seen, shared)
        if not (run/'workspace'/RESULT).is_file():
            raise ValueError(name + ' did not finish the probe')
        results = json.loads((run/'workspace'/RESULT).read_text())
        # A masked folder can accept a write and discard it, so ask the real disk.
        for attempt, written in (('write_run_root', run/'written.txt'), ('write_public', run/'public/inputs/written.txt'),
                                 ('write_environment', environment/'written.txt')):
            if results.get(attempt) == 'ok' and not written.exists():
                results[attempt] = 'denied'
        # Claude's file tools follow permission rules, not the sandbox, so try writing with them too.
        results['tool_write_shared_tmp'] = 'ok' if (shared/'tool-written.txt').exists() else 'denied'
        try: results['network_udp'] = 'ok' if datagrams.recv(64) == b'probe' else 'denied'
        except BlockingIOError: results['network_udp'] = 'denied'
        results['shell_reports_success'] = 'ok' if shell_succeeded(seen[:1] if name == 'claude' else seen) else 'denied'
        return results
    finally:
        listener.close()
        host_socket.close()
        datagrams.close()
        bystander.kill()
        bystander.wait()
        shutil.rmtree(shared, ignore_errors=True)
        shared_memory.unlink(missing_ok=True)


def private_shared_memory_possible():
    """Whether a command here can get an empty /dev/shm of its own, as a Codex command does."""
    probe = 'from robofrontier.engines.codex.tool_worker import private_shared_memory as p; p()'
    return subprocess.run([sys.executable, '-c', probe], cwd=ROOT, capture_output=True, timeout=60).returncode == 0


def known_limits(name, mode):
    """The probe items that cannot work for engine `name` in sandbox `mode` on this host."""
    known = KNOWN_LIMITS.get((sys.platform, name), ())
    # Claude's Landlock prefix never makes a private /dev/shm; Codex's worker does where it can.
    if mode == 'landlock-v1' and (name == 'claude' or not private_shared_memory_possible()):
        known += SHARED_MEMORY_LIMITS
    if mode == 'landlock-v1':
        known += LANDLOCK_LIMITS
    return known


def differences(results, known=()):
    wrong = [name + ' should work' for name in MUST_WORK if results.get(name) != 'ok' and name not in known]
    wrong += [name + ' should be denied' for name in MUST_FAIL if results.get(name) != 'denied' and name not in known]
    return wrong


def receipt_record(manifest, modes):
    """What a pass records: each engine with the sandbox and CLI version it ran.

    Per build: host and platform say where it ran, and preparation compares only `checked`.
    """
    return {'schema': policy_env.RECEIPT_SCHEMA, 'passed': True, 'tree_sha256': manifest['tree_sha256'],
            'checked': [policy_env.combination(name, mode) for name, mode in sorted(modes.items())],
            'host': socket.gethostname(), 'platform': sys.platform, 'at': time.time()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('environment', type=Path)
    parser.add_argument('--engine', choices=sorted(ENGINES), action='append')
    parser.add_argument('--scratch', type=Path, help='Where to put throwaway runs, as a batch would; default beside the environment')
    args = parser.parse_args(argv)
    environment = args.environment.resolve()
    manifest = policy_env.verify(environment)
    print('environment ok: Python', manifest['python'], manifest['packages'])
    failed = False
    # Beside the environment, so nothing here sits in a shared temporary folder.
    scratch = Path(tempfile.mkdtemp(prefix='check-', dir=args.scratch or environment.parent)).resolve()
    names = args.engine or sorted(ENGINES)
    modes = {name: isolation(name) for name in names}
    try:
        for name in names:
            results = check_engine(name, environment, scratch, modes[name])
            wrong = differences(results, known_limits(name, modes[name]))
            print(json.dumps({'engine': name, policy_env.ISOLATION[name]: modes[name], 'attempts': len(results), 'differences': wrong}))
            failed = failed or bool(wrong)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if failed:
        sys.exit(1)
    # Each entry names its engine, sandbox and CLI version, and preparation asks for its exact
    # combination; a check of some engines adds them to what an earlier pass of this build recorded.
    receipt = policy_env.receipt_path(environment)
    record = receipt_record(manifest, modes)
    # Checks of different engines may finish together: merge under a lock, publish atomically.
    import fcntl
    with open(receipt.with_name(receipt.name + '.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try: earlier = json.loads(receipt.read_text())
        except (OSError, ValueError): earlier = {}
        if (args.engine and earlier.get('schema') == policy_env.RECEIPT_SCHEMA and earlier.get('passed')
                and earlier.get('tree_sha256') == manifest['tree_sha256']):
            kept = [item for item in earlier.get('checked', []) if item.get('engine') not in modes]
            record['checked'] = sorted(kept + record['checked'], key=lambda item: json.dumps(item, sort_keys=True))
        fd, temporary = tempfile.mkstemp(prefix=receipt.name + '.', suffix='.tmp', dir=receipt.parent)
        with os.fdopen(fd, 'w') as output:
            output.write(json.dumps(record) + '\n')
        os.replace(temporary, receipt)
    print('recorded', receipt)


if __name__ == '__main__':
    main()
