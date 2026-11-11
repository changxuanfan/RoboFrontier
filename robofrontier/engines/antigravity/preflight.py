"""Explicit live checks of text, robot images, resume and blocked-parent fork.

This calls the selected provider only when invoked by the unified preflight
command with --confirm-spend. The robot service is a synthetic local fixture.
"""
import hashlib
import http.server
import json
import os
from pathlib import Path
import threading
import time
import uuid

from robofrontier.configuration import ROOT, runs_root
from robofrontier.engines.claude.preflight import World
from robofrontier.runtime import access, policy_env, preflight_probe, versions
from robofrontier.runtime.setup import write_json
from robofrontier.runtime.store import RuntimeStore
from .driver import Driver
from .profile import fingerprint, profile
from .provenance import steps, verify

REQUIRED = frozenset(('id_before_input', 'text', 'tool_image', 'resume_same_session',
                      'blocked_parent', 'native_fork_prefix', 'fork_recall_no_tools', 'parent_continues'))


def implementation_sha256():
    digest = hashlib.sha256()
    for directory in ('robofrontier/engines/antigravity', 'robofrontier/engines/common'):
        for path in sorted((ROOT/directory).glob('*.py')):
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(path.read_bytes())
    return digest.hexdigest()


def receipt_path(name, runs=None):
    return Path(runs or runs_root())/'engineering/antigravity-precheck'/name/'receipt.json'


def require_ready(name, selected, runs=None):
    path = receipt_path(name, runs)
    saved = json.loads(path.read_text())
    if (saved.get('schema') != 'robofrontier.antigravity-precheck.v1' or saved.get('passed') is not True
            or saved.get('profile_sha256') != fingerprint(selected)
            or saved.get('cli_version') != versions.engine_version('antigravity')
            or saved.get('implementation_sha256') != implementation_sha256()
            or not all(saved.get('checks', {}).get(key) is True for key in REQUIRED)):
        raise ValueError('Antigravity requires a matching full provider preflight receipt')
    return path


def setup_run(run):
    for folder in ('workspace', 'public/inputs', 'private/inputs/bootstrap', 'private/state/connections'):
        (run/folder).mkdir(parents=True, exist_ok=True)
    environment = policy_env.apply_default()
    policy_env.prepare_run(run, environment)
    write_json(run/'private/inputs/policy-access.json', access.record(run, environment=environment))
    from .settings import prepare_tools
    prepare_tools(run)
    (run/'private/inputs/bootstrap/system.md').write_text('You are a RoboFrontier compatibility probe. Follow the user request.\n')
    image = run/'public/observations/top.png'
    image.parent.mkdir(parents=True)
    probe = preflight_probe.write(image, *preflight_probe.choose())
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), World)
    server.image, server.probe = image, probe
    server.challenge = preflight_probe.answer(probe)
    server.request_count = server.observe_count = 0
    server.request_lock = threading.Lock()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    write_json(run/'private/state/connections/Controller.json', {'schema_version': 3, 'run_id': run.name,
        'actor': 'Controller', 'url': 'http://127.0.0.1:' + str(server.server_port), 'token': 'local-probe'})
    cfg = json.loads((ROOT/'configs/harnesses/policy.json').read_text())
    cfg.update(engine='antigravity', topology='centralized')
    store = RuntimeStore(run/'private/state/runtime.sqlite')
    store.initialize(run.name, cfg, ['Arm1'])
    store.put('lifecycle', 'running')
    return store, server


def run_precheck(name, *, catalog=None, smoke_only=False):
    selected = profile(name, catalog)
    output = runs_root()/'engineering/antigravity-precheck'/name/uuid.uuid4().hex
    output.mkdir(parents=True)
    run = output/'run'
    store, server = setup_run(run)
    driver = Driver(run, 'Controller', selected, os.environ)
    checks, records = {}, []
    child = None
    worker = None
    receipt = {'schema': 'robofrontier.antigravity-precheck.v1', 'profile': name,
        'profile_sha256': fingerprint(selected), 'cli_version': versions.engine_version('antigravity'),
        'implementation_sha256': implementation_sha256(), 'checks': checks, 'passed': False,
        'auth_mode': selected['auth_mode'], 'reported_cost_usd': None, 'smoke_only': smoke_only}
    def turn(transport, text):
        value = transport(selected, selected['model'], selected['effort'], None, text, run, os.environ,
            timeout=180, events_name=uuid.uuid4().hex+'.jsonl')
        records.append(value)
        return value['summary']
    def answer(summary, text):
        return summary.get('turn_status') == 'ended' and preflight_probe.normalize(summary.get('response')) == text
    try:
        versions.require('antigravity')
        sid = driver.open()
        checks['id_before_input'] = server.request_count == 0 and len(steps(driver.home, sid)) == 0
        store.update_agent('Controller', thread_id=sid)
        checks['text'] = answer(turn(driver, 'Reply with exactly the word ready and nothing else. Do not call tools.'), 'ready')
        before = server.observe_count
        result = turn(driver, 'Call robot with op observe, data {}, views ["top"]. Look at the returned image. '
            'Reply only with the two color names from left to right, separated by a space. Remember them.')
        checks['tool_image'] = server.observe_count == before + 1 and answer(result, server.challenge)
        driver.close()
        driver.open()
        before = server.request_count
        result = turn(driver, 'Without tools, repeat only the two colors you saw, in the same order.')
        checks['resume_same_session'] = (driver.session == sid and server.request_count == before
                                         and answer(result, server.challenge))
        if not smoke_only:
            server.blocked_entered = threading.Event()
            server.blocked_release = threading.Event()
            worker = threading.Thread(target=lambda: turn(driver,
                'Call robot observe once with data {} and views ["top"], then reply only the two words parent done, without punctuation.'), daemon=True)
            worker.start()
            checks['blocked_parent'] = server.blocked_entered.wait(120)
            if not checks['blocked_parent']:
                raise ValueError('Parent did not enter the blocked robot call')
            at = len(steps(driver.home, sid)) - 1
            child_sid = driver.fork(at)
            proof = verify(driver.home, sid, child_sid, at)
            checks['native_fork_prefix'] = proof['source_thread_id'] == sid
            child = Driver(run, 'ForkProbe', selected, os.environ, session=child_sid)
            child.open()
            # The synthetic probe grants no new role/tool connection to the child.
            # Any tool attempt fails routing and is also counted from native events.
            result = turn(child, 'This is a fork. Without tools, repeat only the two colors seen earlier, in order.')
            children_events = list((run/'private/engine/turns').glob('*.jsonl'))
            tool_attempt = any(json.loads(line).get('step_update', {}).get('step_type') == 'tool'
                for path in children_events for line in path.read_text().splitlines()
                if json.loads(line).get('step_update', {}).get('conversation_id') == child_sid)
            checks['fork_recall_no_tools'] = answer(result, server.challenge) and not tool_attempt
            server.blocked_release.set()
            worker.join(180)
            checks['parent_continues'] = not worker.is_alive() and answer(records[-1]['summary'], 'parent done')
        receipt['passed'] = not smoke_only and all(checks.get(k) is True for k in REQUIRED)
    except Exception as error:
        receipt['error_type'] = type(error).__name__
    finally:
        if hasattr(server, 'blocked_release'):
            server.blocked_release.set()
        driver.close()
        if child:
            child.close()
        if worker:
            worker.join(10)
        server.shutdown()
        server.server_close()
        store.close()
        write_json(output/'receipt.json', receipt)
        if receipt['passed']:
            write_json(receipt_path(name), receipt)
    return {**receipt, 'receipt': str(output/'receipt.json')}
