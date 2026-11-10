"""Offline checks: fake services, robot/contact physics and real encoder recovery."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import py_compile
import re
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import unquote
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'tests'))


def documentation_links(root, documents):
    """Require local links to remain usable inside an independent checkout."""
    root=Path(root).resolve()
    broken=[]
    for document in documents:
        for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',document.read_text()):
            if '://' in target or target.startswith(('#','mailto:')):continue
            path=unquote(target.split('#')[0].strip('<>'))
            if not path:continue
            resolved=(document.parent/path).resolve()
            if Path(path).is_absolute() or not resolved.is_relative_to(root):
                reason='Local link must be relative and stay inside the checkout'
            elif not resolved.exists():
                reason='Local link target does not exist'
            else:continue
            broken.append({'file':str(document.relative_to(root)),'target':target,'reason':reason})
    return broken


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path)
    p.add_argument('--skill-validator',type=Path)
    p.add_argument('--skill-python',default=sys.executable,help='Interpreter with the optional validator dependencies installed')
    p.add_argument('--protocol-only',action='store_true',help='Run explicit non-physics contracts; prohibit physics-world creation/stepping')
    args=p.parse_args()
    guard=None
    if args.protocol_only:
        import mujoco
        def forbidden(*args,**kwargs):raise AssertionError('Physics execution prohibited by --protocol-only')
        class NoPhysicsModel:
            from_xml_path=staticmethod(forbidden)
            from_xml_string=staticmethod(forbidden)
            from_binary_path=staticmethod(forbidden)
        guard=patch.multiple(mujoco,MjModel=NoPhysicsModel,MjData=forbidden,mj_step=forbidden,mj_forward=forbidden)
        guard.start()
        modules=('runtime.test_action_batch','runtime.test_sync_groups','runtime.test_pipeline','runtime.test_pipeline_client',
                 'runtime.test_runtime_store','runtime.test_run_setup','runtime.test_scheduling','runtime.test_centralized','runtime.test_delegation',
                 'runtime.test_delegate_callbacks','tasks.test_private_evaluation','runtime.test_run_seal','batch.test_run_report',
                 'media.test_recording','repo.test_harness_checker','repo.test_policy_batch_viewer',
                 'oracle.test_oracle_protocol','oracle.test_oracle_terminal_recovery')
        suite=unittest.defaultTestLoader.loadTestsFromNames(modules)
    else:suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    try:result=unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        if guard:guard.stop()
    node=subprocess.run(['node',str(ROOT/'tests/engines/test_meta_dispatcher.cjs')],capture_output=True,text=True,cwd=ROOT)
    print(node.stdout,end='');print(node.stderr,end='',file=sys.stderr)
    # Every Node host test (Codex RPC, preflight, restart, seal, wall limit, tool errors...).
    node_tests={}
    for source in sorted((ROOT/'tests').rglob('test_*.js')):
        ran=subprocess.run(['node','--test',str(source)],capture_output=True,text=True,cwd=ROOT)
        print(ran.stdout,end='');print(ran.stderr,end='',file=sys.stderr)
        node_tests[str(source.relative_to(ROOT))]=ran.returncode==0
    js_syntax=[]
    for source in sorted(p for folder in ('robofrontier','scripts','tests') for p in (ROOT/folder).rglob('*') if p.suffix in ('.js','.cjs')):
        parsed=subprocess.run(['node','--check',str(source)],capture_output=True,text=True,cwd=ROOT)
        js_syntax.append({'file':str(source.relative_to(ROOT)),'passed':parsed.returncode==0,'error':parsed.stderr or None})
    compilation=[]
    for source in sorted(p for folder in ('robofrontier','scripts','tests') for p in (ROOT/folder).rglob('*.py')):
        py_compile.compile(str(source),doraise=True);compilation.append(str(source.relative_to(ROOT)))
    # Parse the inline UI scripts without executing a browser or opening a port.
    ui_script="const fs=require('fs'),vm=require('vm');for(const f of process.argv.slice(1)){const s=fs.readFileSync(f,'utf8');for(const m of s.matchAll(/<script>([\\s\\S]*?)<\\/script>/g))new vm.Script(m[1]);}"
    ui=subprocess.run(['node','-e',ui_script,str(ROOT/'assets/pipeline_dashboard.html')],capture_output=True,text=True)
    # Validate runnable documentation as syntax, without executing its tools.
    doc_js="const fs=require('fs');const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;const s=fs.readFileSync(process.argv[1],'utf8');for(const m of s.matchAll(/```javascript\\n([\\s\\S]*?)```/g))new AsyncFunction(m[1]);"
    runbook=subprocess.run(['node','-e',doc_js,str(ROOT/'docs/meta-runbook.md')],capture_output=True,text=True)
    tool_docs=subprocess.run(['node','-e',doc_js,str(ROOT/'prompts/skills/robot-collaboration/references/tools.md')],capture_output=True,text=True)
    # Tracked Markdown only: ignored local renders under docs/generated are not documentation.
    tracked=subprocess.run(['git','ls-files','-z','*.md'],capture_output=True,text=True,cwd=ROOT).stdout.split('\0')
    documents=[ROOT/name for name in tracked if name]
    broken_links=documentation_links(ROOT,documents)
    validator=None
    if args.skill_validator:
        validator=subprocess.run([args.skill_python,str(args.skill_validator),str(ROOT/'prompts/skills/robot-collaboration')],capture_output=True,text=True)
        print(validator.stdout,end='');print(validator.stderr,end='',file=sys.stderr)
    dispatcher_count=re.search(r'^PASS: (\d+) dispatcher scenarios:',node.stdout,re.MULTILINE)
    dispatcher_passed=node.returncode==0 and dispatcher_count is not None
    passed=result.wasSuccessful() and dispatcher_passed and all(node_tests.values()) and all(s['passed'] for s in js_syntax) and ui.returncode==0 and runbook.returncode==0 and tool_docs.returncode==0 and not broken_links and (validator is None or validator.returncode==0)
    report={'checked_at':datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(),'passed':passed,
            'scope':('Protocol-only engineering: FakeWorld/HTTP, private scoring on synthetic records, frozen inputs and encoder recovery. Physics creation/stepping prohibited; no native sessions, model inference or GUI.' if args.protocol_only else 'Offline engineering; FakeWorld/HTTP, robot kinematics/contacts, source/evidence verification and FFmpeg regressions. Installed native CLIs may run against synthetic loopback model endpoints in isolated test sessions. No real provider inference, GUI or model task-solving qualification.'),
            'physics_entrypoints_blocked':args.protocol_only,
            'python_tests':{'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)},
            'dispatcher_js':{'passed':dispatcher_passed,'scenarios':int(dispatcher_count[1]) if dispatcher_count else None,'error':node.stderr or None},
            'node_host_tests':node_tests,
            'javascript_syntax':{'passed':all(s['passed'] for s in js_syntax),'files':js_syntax},
            'ui_script_syntax':{'passed':ui.returncode==0,'error':ui.stderr or None},
            'runbook_script_syntax':{'passed':runbook.returncode==0,'error':runbook.stderr or None},
            'tool_example_script_syntax':{'passed':tool_docs.returncode==0,'error':tool_docs.stderr or None},
            'documentation_links':{'passed':not broken_links,'broken':broken_links},
            'skill_format':{'checked':validator is not None,'passed':validator.returncode==0 if validator else None,'interpreter':args.skill_python if validator else None},
            'compiled_modules':compilation,
            'source_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in (ROOT/'robofrontier').rglob('*.py')},
            'not_verified':['new live multi-agent MuJoCo policy trial','new live Codex adapter roundtrip','coordination/parallelism improvement']}
    if args.report:
        args.report.parent.mkdir(parents=True,exist_ok=True)
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('compiled_modules','source_sha256')},ensure_ascii=False,indent=2))
    return 0 if passed else 1

if __name__=='__main__':raise SystemExit(main())
