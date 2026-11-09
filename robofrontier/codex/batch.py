"""Prepare and supervise independent Codex CLI policy tasks; never infer on prepare."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from robofrontier import run_layout
from robofrontier.launch_schedule import LaunchSchedule

from robofrontier.benchmark_common import load_env, select_cases
from robofrontier.codex.launch import codex_home, initialize_codex_home, launch_config, profile
from robofrontier.task_families import ROOT, read, prepare
from robofrontier.run_setup import write_json, verify_inputs
from robofrontier.run_segments import try_continue


def prepare_batch(output, names, families=None, cases=None, config=None, level=None, min_arms=False, wall_limit_s=86400, *, harness_overrides=None):
    if not names or len(set(names))!=len(names):raise ValueError('Choose distinct model profiles')
    profiles={n:profile(n,config) for n in names}
    selected=[row['case_id'] for row in select_cases(families,cases,level,min_arms)]
    output=Path(output).absolute();output.mkdir(parents=True,exist_ok=False)
    for name in run_layout.BATCH_FOLDERS:(output/name).mkdir()
    batch=dict(schema='robofrontier.cli-benchmark.v1',status='preparing',created_at=time.time(),
        cwd=str(ROOT),python=sys.executable,context_window=next(iter(profiles.values()))['context_window'],
        auto_compact_token_limit=next(iter(profiles.values()))['auto_compact_token_limit'],
        task_wall_limit_s=wall_limit_s,model_calls=0,jobs=[],**run_layout.batch_record())
    write_json(output/'batch.json',batch)
    # Match private Dial instances across model arms of this batch. These are
    # new secrets, never copied from an Oracle or exposed in public inputs.
    puzzles={}
    import secrets
    from robofrontier.task_families import policy_task
    from robofrontier.suite.dial_feedback import alphabet
    for case in selected:
        task=policy_task(case)
        if task.get('family')=='dial':
            target=output/'private/dial'/(case+'.json')
            write_json(target,{'code_symbols':[secrets.choice(alphabet(task)) for _ in task['dials']]})
            puzzles[case]=target
    for name,p in profiles.items():
        config_dir=output/'profiles'/name;config_dir.mkdir(parents=True)
        harness=read(ROOT/'configs/harnesses/policy.json')
        harness.update(model=p['model'],effort=p['effort'],observation_renderer='classic',record_realtime_video=False)
        if harness_overrides:
            allowed={'topology','startup_protocol','observation_image_profile','record_realtime_video','startup_timeout_s','render_device'}
            if set(harness_overrides)-allowed:raise ValueError('Unsupported harness overrides')
            harness.update(harness_overrides)
        if not harness_overrides and p.get('benchmark_topology') in ('hierarchical', 'peer'):
            harness.update(topology=p['benchmark_topology'], startup_protocol='direct_team_v3')
        harness_path=config_dir/'harness.json';write_json(harness_path,harness)
        for case in selected:
            run=output/name/case
            prepare(case,run,harness_path,puzzles.get(case),wall_limit_s=wall_limit_s)
            from .tool_backend import prepare as prepare_tools
            prepare_tools(run, p)
            launch=launch_config(p,run/'private/inputs',run)
            write_json(run/'private/inputs/codex.json',launch)
            # Host config/model catalog belong to immutable prepared inputs too.
            import hashlib
            manifest_path=run/'private/inputs/manifest.json';manifest=read(manifest_path)
            files = [run/'private/inputs'/name for name in ('codex.json','models.json','policy-access.json','codex-tools.json')]
            files += list((run/'private/inputs/bootstrap').glob('*.md'))
            for file in files:
                if file.exists():manifest['input_sha256'][str(file.relative_to(run))]=hashlib.sha256(file.read_bytes()).hexdigest()
            write_json(manifest_path,manifest)
            batch['jobs'].append(dict(profile=name,case_id=case,run_directory=str(run),status='prepared'))
            write_json(output/'batch.json',batch)
    batch['status']='prepared_not_started';write_json(output/'batch.json',batch)
    return output/'batch.json'


STOPPED_BETWEEN_SEGMENTS='stopped_between_segments'


def read_lifecycle(run):
    from robofrontier.runtime_store import RuntimeStore
    store=RuntimeStore(Path(run)/'private/state/runtime.sqlite')
    try:return store.get('lifecycle')
    finally:store.close()


def memory_snapshot():
    """Informational snapshot, not a safe concurrency estimate."""
    info={'parallel_memory_requirement_known':False}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemAvailable:'):
                info['host_available_bytes']=int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):pass
    # Typical cgroup v2/v1 mounts; nested limits or Slurm may be more restrictive.
    for base,limit,current in [(Path('/sys/fs/cgroup'),'memory.max','memory.current'),
                               (Path('/sys/fs/cgroup/memory'),'memory.limit_in_bytes','memory.usage_in_bytes')]:
        try:
            value=(base/limit).read_text().strip()
            if value!='max':
                n=int(value)
                if n < (1<<60):info['cgroup_limit_bytes']=n
            info['cgroup_current_bytes']=int((base/current).read_text().strip())
            break
        except (OSError,ValueError):continue
    return info


def run_batch(folder, parallel, continuing=False):
    """Run a prepared batch; with `continuing`, pick up a batch whose supervisor died.

    Continuing never restarts a world: a run that had started continues in its next
    segment, at most once (docs/running/run-segments.md); runs that never started start now.
    """
    folder=Path(folder).resolve();batch=read(folder/'batch.json')
    expected='running' if continuing else 'prepared_not_started'
    if batch['status']!=expected:raise ValueError('Never automatically restart a batch/world' if not continuing
                                                  else 'Only a batch whose supervisor stopped while running can continue')
    if not 1<=parallel<=36:raise ValueError('Parallel tasks must be 1..36')
    lock_path=run_layout.batch_path(folder,'supervisor_lock');lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        # Another supervisor may have changed the batch before the lock.
        batch=read(folder/'batch.json')
        if batch['status']!=expected:raise ValueError('Batch status changed before the lock')
        with ExitStack() as stack:
            return _run_batch_locked(folder, parallel, batch, continuing, stack=stack)


def _run_batch_locked(folder, parallel, batch, continuing=False, *, stack=None):
    # Continuing picks up the jobs that never reached a final status.
    jobs=[j for j in batch['jobs'] if j['status']=='prepared'] if continuing else batch['jobs']
    execution=batch.get('execution',{})
    schedule=LaunchSchedule(execution.get('startup_interval_s',.3))
    scope=execution.get('codex_home_scope','shared')
    if scope not in ('task','shared','job'):raise ValueError('Unknown Codex home scope')
    if scope=='job':
        if continuing:
            raise ValueError('A shared-engine job cannot automatically reconnect or replay turns; inspect sealed evidence')
        if stack is None or not os.environ.get('SLURM_JOB_ID') or not os.environ.get('ROBOFRONTIER_JOB_PRIVATE_ROOT'):
            raise ValueError('Job scope requires an admitted Slurm credential lease')
    environments={}
    for job in jobs:
        run=Path(job['run_directory']);launch=read(run/'private/inputs/codex.json')
        if verify_inputs(run):raise ValueError('Prepared code/inputs changed; prepare a new batch')
        key=launch['profile'].get('env_key')
        if key and not os.environ.get(key):raise ValueError('Missing credential environment variable: '+key)
        receipt=ROOT/'runs/engineering/model-compatibility'/job['profile']/'report.json'
        if not receipt.is_file():raise ValueError('Run benchmark preflight for '+job['profile']+' before scored trials')
        checked=read(receipt)
        expected=__import__('hashlib').sha256(json.dumps(launch['profile'],sort_keys=True).encode()).hexdigest()
        if not checked.get('passed') or checked.get('profile_sha256')!=expected:
            raise ValueError('Model compatibility preflight missing/failed or provider configuration changed')
        from robofrontier.preflight_probe import VERSION as PROBE_VERSION
        if checked.get('probe_version')!=PROBE_VERSION:
            raise ValueError('Model preflight predates the current image check; rerun preflight')
        catalog_sha=__import__('hashlib').sha256((run/'private/inputs/models.json').read_bytes()).hexdigest()
        version=subprocess.check_output(['codex','--version'],text=True).strip()
        if checked.get('catalog_sha256')!=catalog_sha or checked.get('codex_version')!=version:
            raise ValueError('Model catalog or Codex CLI changed; rerun preflight')
        from .tool_backend import selected, verify_receipt
        verify_receipt(launch, checked)
        if scope=='job':
            from .job_engine import BACKEND, fingerprint as gateway_fingerprint
            if (launch['profile'].get('runner_backend') != BACKEND
                    or checked.get('job_gateway_sha256') != gateway_fingerprint()):
                raise ValueError('Shared job gateway changed or was not qualified; rerun job preflight')
        env=dict(os.environ)
        if selected(launch['profile']) == 'landlock-v1' and launch['profile']['provider'] == 'openai':
            for key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
                env.pop(key, None)
        if execution.get('codex_home'):env['CODEX_HOME']=execution['codex_home']
        if scope=='task':
            if launch['profile'].get('provider')=='openai':
                raise ValueError('Native subscription auth with isolated homes needs qualification; use explicit shared home or an API profile')
            import hashlib
            key=hashlib.sha256(str(run).encode()).hexdigest()[:20]
            base=Path(execution.get('codex_home') or ROOT/'.robofrontier/codex')
            env['CODEX_HOME']=str((base/key).resolve())
        home=codex_home(env)
        if home.is_relative_to(folder):
            raise ValueError('Keep credential/configuration directories outside collected batch evidence')
        home.mkdir(parents=True,exist_ok=True,mode=0o700)
        borrowed = scope=='job' and env.get('ROBOFRONTIER_BORROWED_AUTH') == str(Path(env.get('ROBOFRONTIER_CREDENTIAL_STORE', '/absent'))/'current.json')
        if launch['profile'].get('provider')=='openai' and not (home/'auth.json').is_file() and not env.get('OPENAI_API_KEY') and not borrowed:
            raise ValueError('No Codex login in '+str(home)+'; run once: CODEX_HOME='+shlex.quote(str(home))+' codex login')
        env['CODEX_HOME']=str(home)
        environments[str(run)]=env
        write_json(run_layout.path(run,'codex_home_marker','codex'),{'schema':'robofrontier.codex-home.v1','codex_home':str(home),'scope':scope})
        # Validate configuration without inference before starting any task.
        if scope!='job':
            subprocess.run(['codex','app-server',*launch['args'],'--print-startup-config'],
                           check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,env=env)
    # Handshake is local and occurs before any task process or model turn.
    initialized=set()
    for job in ([] if scope=='job' else jobs):
        run=Path(job['run_directory']);env=environments[str(run)]
        if env['CODEX_HOME'] not in initialized:
            initialize_codex_home(read(run/'private/inputs/codex.json'),run_layout.path(run,'owner_log','codex').parent,env=env)
            initialized.add(env['CODEX_HOME'])
    if scope=='job':
        from .job_engine import engine, task_id
        manifest, gateway = stack.enter_context(engine(jobs, env=dict(os.environ)))
        for job in jobs:
            run=Path(job['run_directory'])
            environments[str(run)].update(ROBOFRONTIER_CODEX_GATEWAY=manifest['endpoint'],
                                          ROBOFRONTIER_CODEX_TASK=task_id(run))
        batch['job_gateway']={'backend':manifest['backend'],'sha256':manifest['fingerprint'],
                              'task_channels':len(jobs)}
    resources=memory_snapshot()
    batch['resource_snapshot']=resources
    print('Resource snapshot (not a concurrency guarantee): '+json.dumps(resources),file=sys.stderr)
    if continuing:batch.setdefault('continued_at',[]).append(time.time())
    else:batch.update(status='running',parallel=parallel,started_at=time.time(),model_calls=None,
                      model_calls_note='Per-task native usage events are recorded; aggregate API request count is not measured')
    write_json(folder/'batch.json',batch)
    def task(job):
        # An unexpected exit continues the same run once (docs/running/run-segments.md).
        run=Path(job['run_directory'])
        # Whether a continuation segment is prepared and not yet run.
        pending=False
        if continuing:
            lifecycle=read_lifecycle(run)
            pending=lifecycle=='resuming'
            # A segment prepared just before the supervisor died starts as it is.
            if lifecycle not in ('prepared','resuming'):
                continued,why=try_continue(run,'batch supervisor exited')
                job.setdefault('segments',[]).append({'host_exit_code':None,'continued':continued,'reason':why})
                write_json(folder/'batch.json',batch)
                if not continued:raise ValueError('Run cannot continue: '+why)
                pending=True
        while True:
            result=launch(job)
            # A stop before the first segment leaves the run unstarted; a stop after a
            # continuation was prepared leaves a run that ran and needs review.
            if result is None:return STOPPED_BETWEEN_SEGMENTS if pending else None
            # A shared-server failure is a job fault. Never automatically create
            # another shared manager or resend an uncertain turn/action.
            if scope=='job':return result
            # Even a clean host exit can follow a world that died; the eligibility
            # check tells normal ends (finish, stop, wall limit, live seal) apart.
            continued,why=try_continue(run,'host exit code '+str(result))
            job.setdefault('segments',[]).append({'host_exit_code':result,'continued':continued,'reason':why})
            write_json(folder/'batch.json',batch)
            if not continued:return result
            pending=True
    def launch(job):
        run=Path(job['run_directory'])
        stop,batch_stop=run_layout.path(run,'stop','codex'),run_layout.batch_path(folder,'stop')
        if stop.exists():return None
        log_path=run_layout.path(run,'supervisor_log','codex');log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('a') as log:
            proc=schedule.launch(lambda:subprocess.Popen(
                ['node',str(ROOT/'robofrontier/codex/codex_policy_host.js'),str(run),str(ROOT),sys.executable],
                cwd=ROOT,stdout=log,stderr=log,env=environments[str(run)]),
                stopped=lambda:stop.exists() or batch_stop.exists())
            if proc is None:return None
            write_json(run_layout.path(run,'host_process','codex'),dict(pid=proc.pid,started_at=time.time()))
            return proc.wait()
    with ThreadPoolExecutor(max_workers=parallel) as pool:
        futures={pool.submit(task,job):job for job in jobs}
        for future in as_completed(futures):
            job=futures[future]
            try:
                result=future.result()
                if result==STOPPED_BETWEEN_SEGMENTS:
                    job.update(status='needs_review',reason='Stopped after a continuation segment was prepared; it never ran')
                else:
                    job.update(status='stopped_before_start' if result is None else 'closed' if result==0 else 'needs_review')
                    if result is not None:job['host_exit_code']=result
            except Exception as error:job.update(status='needs_review',error=str(error))
            write_json(folder/'batch.json',batch)
    from .recover_task import wait_for_recoveries
    wait_for_recoveries(batch['jobs'])
    batch.update(status='needs_review' if any(j['status']=='needs_review' for j in batch['jobs']) else 'closed',
                 finished_at=time.time());write_json(folder/'batch.json',batch)


def main():
    load_env(ROOT/'.env')
    # Every child (app-server, policy host, runtime_cli) inherits this home.
    os.environ['CODEX_HOME']=str(codex_home())
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('models')
    a=sub.add_parser('preflight');a.add_argument('--models',nargs='+',default=['astra']);a.add_argument('--model-config',type=Path)
    a.add_argument('--smoke-only',action='store_true',help='Small image/tool round trip; does not qualify scored runs')
    for command in ('plan','prepare'):
        a=sub.add_parser(command)
        if command=='prepare':
            a.add_argument('--output',type=Path,required=True)
            a.add_argument('--wall-limit-s',type=float,default=86400,help='Per-task seconds after START, including initial model work')
        else:a.add_argument('--parallel',type=int,default=4)
        a.add_argument('--models',nargs='+',default=['astra']);a.add_argument('--families',nargs='+')
        a.add_argument('--cases',nargs='+');a.add_argument('--model-config',type=Path)
        a.add_argument('--level',type=int,choices=(1,2,3))
        a.add_argument('--min-arms',action='store_true',help='Smallest released arm count within each selected family')
    a=sub.add_parser('continue',help='Continue a batch whose supervisor died (docs/running/run-segments.md)')
    a.add_argument('batch',type=Path);a.add_argument('--parallel',type=int,default=9)
    a=sub.add_parser('run');a.add_argument('batch',type=Path);a.add_argument('--parallel',type=int,default=9)
    a=sub.add_parser('status');a.add_argument('batch',type=Path)
    a=sub.add_parser('stop');a.add_argument('batch',type=Path)
    args=p.parse_args()
    if args.command=='models':print(json.dumps(read(ROOT/'configs/models.json'),ensure_ascii=False,indent=2))
    elif args.command=='plan':
        catalog=read(args.model_config or ROOT/'configs/models.json')
        if not 1<=args.parallel<=36:raise ValueError('Parallel tasks must be 1..36')
        if not args.models or len(set(args.models))!=len(args.models):raise ValueError('Choose distinct model profiles')
        rows=select_cases(args.families,args.cases,args.level,args.min_arms)
        jobs=[dict(profile=name,model=catalog['profiles'][name]['model'],**row) for name in args.models for row in rows]
        print(json.dumps(dict(model_calls=0,simulator_started=False,parallel=args.parallel,
                              task_count=len(jobs),jobs=jobs),ensure_ascii=False,indent=2))
    elif args.command=='preflight':
        import hashlib
        from robofrontier import preflight_probe
        for name in args.models:
            selected=profile(name,args.model_config)
            key=selected.get('env_key')
            if key and not os.environ.get(key):raise ValueError('Set '+key+' before live preflight')
            scope='model-smoke' if args.smoke_only else 'model-compatibility'
            target=ROOT/'runs/engineering'/scope/name;target.mkdir(parents=True,exist_ok=True)
            write_json(target/'launch.json',launch_config(selected,target))
            # A failed/interrupted new check must not leave an older pass usable
            # under the new provider/model fingerprint.
            write_json(target/'report.json',{'passed':False,'error':'Preflight did not complete'})
            write_json(target/'probe.json',preflight_probe.write(target/'colors.png',*preflight_probe.choose()))
            from .tool_backend import selected as selected_backend, preflight_probe as broker_probe
            if selected_backend(selected) == 'landlock-v1':
                launch = read(target/'launch.json')
                launch['tool_probe'] = broker_probe(target, selected)
                write_json(target/'launch.json', launch)
            command=['node',str(ROOT/'robofrontier/codex/codex_preflight.js'),str(target)]
            if args.smoke_only:command.append('--smoke-only')
            environment={**os.environ, 'ROBOFRONTIER_PYTHON': sys.executable}
            if selected_backend(selected) == 'landlock-v1' and selected['provider'] == 'openai':
                for key in ('OPENAI_API_KEY', 'CODEX_API_KEY'):
                    environment.pop(key, None)
            job_scoped=selected.get('runner_backend')=='slurm-managed-v1'
            if job_scoped:
                from .job_engine import engine, task_id
                if not os.environ.get('SLURM_JOB_ID') or not os.environ.get('ROBOFRONTIER_JOB_PRIVATE_ROOT'):
                    raise ValueError('Job preflight requires an admitted Slurm credential lease')
                launch=read(target/'launch.json')
                jobs=[{'run_directory':launch['tool_probe']['run_dir'],'launch_file':str(target/'launch.json')}]
                with engine(jobs,env=environment,preflight=True) as (manifest,gateway):
                    environment.update(ROBOFRONTIER_CODEX_GATEWAY=manifest['endpoint'],
                                       ROBOFRONTIER_CODEX_TASK=task_id(jobs[0]['run_directory']))
                    result=subprocess.run(command,env=environment)
            else:
                result=subprocess.run(command, env=environment)
            receipt=read(target/'report.json');receipt['profile_sha256']=hashlib.sha256(json.dumps(selected,sort_keys=True).encode()).hexdigest()
            receipt['probe_version']=preflight_probe.VERSION
            if result.returncode:receipt['passed']=False
            if receipt.get('passed'):
                receipt['catalog_sha256']=hashlib.sha256((target/'models.json').read_bytes()).hexdigest()
                receipt['codex_version']=subprocess.check_output(['codex','--version'],text=True).strip()
                from .tool_backend import selected as selected_backend, fingerprint
                receipt['tool_backend']=selected_backend(selected)
                receipt['tool_backend_sha256']=fingerprint(selected)
                if job_scoped and not args.smoke_only:
                    from .job_engine import fingerprint as gateway_fingerprint
                    receipt['job_gateway_sha256']=gateway_fingerprint()
            write_json(target/'report.json',receipt)
            if result.returncode:raise SystemExit(result.returncode)
    elif args.command=='prepare':print(prepare_batch(args.output,args.models,args.families,args.cases,args.model_config,args.level,args.min_arms,args.wall_limit_s))
    elif args.command=='run':run_batch(args.batch,args.parallel)
    elif args.command=='continue':run_batch(args.batch,args.parallel,continuing=True)
    elif args.command=='status':
        batch=read(args.batch/'batch.json')
        for j in batch['jobs']:
            from robofrontier.runtime_store import RuntimeStore
            s=RuntimeStore(Path(j['run_directory'])/'private/state/runtime.sqlite')
            j.update(lifecycle=s.get('lifecycle'),actors={a:{k:v.get(k) for k in ('thread_id','session_status','kind')}
                     for a,v in s.agents().items()});s.close()
        print(json.dumps(batch,ensure_ascii=False,indent=2))
    else:
        for stop in [run_layout.batch_path(args.batch,'stop'),
                     *(run_layout.path(job['run_directory'],'stop','codex') for job in read(args.batch/'batch.json')['jobs'])]:
            stop.parent.mkdir(parents=True,exist_ok=True);stop.touch()


if __name__=='__main__':main()
