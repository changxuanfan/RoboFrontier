"""Prepare immutable render jobs and execute them locally or through Slurm."""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid

from .bundle import digest, inside, read, resolved_release, verify, write

ROOT = Path(__file__).resolve().parents[2]
PLAN_SCHEMA = 'robofrontier.factory-render-plan.v1'


def code_hashes():
    # The code a Factory render runs: Factory itself, media edits, task and physics models.
    files = {ROOT/'robofrontier/io.py'}
    for package in ('factory', 'media', 'tasks', 'physics'):
        files.update((ROOT/'robofrontier'/package).rglob('*.py'))
    return {p.relative_to(ROOT).as_posix():digest(p) for p in sorted(files) if p.is_file()}


def blender_path(value=None):
    value = value or os.environ.get('BLENDER_BIN') or shutil.which('blender')
    if not value and platform.system() == 'Darwin':
        value = '/Applications/Blender.app/Contents/MacOS/Blender'
    if not value or not Path(value).is_file() or not os.access(value, os.X_OK):
        raise ValueError('Set BLENDER_BIN or --blender to an executable Blender installation')
    return str(Path(value).resolve())


def doctor(data_root, blender=None, device=None):
    result = verify(data_root)
    import mujoco
    import numpy
    result.update(python=sys.version.split()[0], mujoco=mujoco.__version__, numpy=numpy.__version__)
    for command in ('ffmpeg', 'ffprobe'):
        path = shutil.which(command)
        if not path:
            raise ValueError('Missing executable: '+command)
        result[command] = subprocess.check_output([path, '-version'], text=True).splitlines()[0]
    executable = blender_path(blender)
    device = device or ('METAL' if platform.system() == 'Darwin' else 'OPTIX')
    expression = "import bpy,json; p=bpy.context.preferences.addons['cycles'].preferences; "
    if device != 'CPU':
        expression += f"p.compute_device_type={device!r}; p.get_devices(); devices=[dict(name=d.name,type=d.type) for d in p.devices if d.type=={device!r}]; assert devices, 'Requested GPU backend unavailable'; "
    else:
        expression += "devices=[]; "
    expression += "print('FACTORY_PROBE='+json.dumps(dict(blender=bpy.app.version_string,devices=devices)))"
    completed = subprocess.run([executable, '--background', '--factory-startup', '--python-exit-code', '1',
                                '--python-expr', expression], text=True, capture_output=True, timeout=120)
    lines = [line for line in completed.stdout.splitlines() if line.startswith('FACTORY_PROBE=')]
    if completed.returncode or not lines:
        raise ValueError('Blender device check failed: '+(completed.stderr+completed.stdout)[-3000:])
    result.update(readiness='offline render inputs and software; no model calls', device=device,
                  **json.loads(lines[-1].split('=',1)[1]))
    return result


def import_motion(data_root, recording, output, speedup=None, keep_idle=False, timeline=None):
    """Bind a closed benchmark recording to a newly composed factory display.

    Other desks are static background. The desk shows the states kept by timeline,
    a motion-edit of this recording such as the motion-cut.json that
    robofrontier/media/render.py checked on the simple background; without one
    it keeps robofrontier.media.motion_cut's meaningful motion, and with keep_idle every
    state. Speedup None plays at the family's release speedup. This is not an
    Oracle edit or a benchmark qualification, and changes no source evidence.
    """
    import numpy as np
    from .scene import build_factory
    from .workstations import compose
    from ..media.motion_recording import MotionReader
    from robofrontier.factory.blender.export import export as export_blender
    from .bundle import export as export_bundle
    data_root, recording, output=Path(data_root).resolve(),Path(recording).resolve(),Path(output).resolve()
    verify(data_root)
    reader=MotionReader(recording)
    if reader.meta['status']=='recording' or reader.meta['frames']<1:
        raise ValueError('Import only a closed, nonempty recording after all writers have stopped')
    if speedup is not None and (not math.isfinite(speedup) or speedup<=0):
        raise ValueError('Positive finite playback speed required')
    release=resolved_release(data_root)
    entries=[(name,spec) for name,family in release['families'].items() for spec in family['oracle']]
    matches=[(name,spec) for name,spec in entries if spec['id']==reader.meta['case_id']]
    if len(matches)!=1:
        raise ValueError('Recording must match one published factory task ID')
    name,spec=matches[0]
    if speedup is None:speedup=float(release['families'][name]['speedup'])
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.factory-import-',dir=output.parent) as tmp:
        tmp=Path(tmp)
        sources={s['id']:s['directory'] for _,s in entries}
        sources[spec['id']]=str(recording/'source')
        cases=[dict(read(Path(directory)/'workstation.json')['case'],directory=directory)
               for directory in sources.values()]
        write(tmp/'catalog.json',dict(cases=cases))
        shell,_=build_factory(output=tmp/'shell',workstation_catalog=tmp/'catalog.json')
        base=read(inside(data_root,read(data_root/'bundle.json')['scene']).parent/'manifest.json')
        placements={p['case_id']:dict(translation_m=p['translation_m'],yaw_rad=p['yaw_rad']) for p in base['placements']}
        scene=compose(shell,tmp/'catalog.json',tmp/'scene',source_overrides=sources,placement_overrides=placements)
        export_blender(scene,tmp/'asset')
        edit_dir=tmp/'edit';edit_dir.mkdir()
        clocks=[]
        for chunk in reader.meta['chunks']:
            with np.load(recording/chunk['file'],allow_pickle=False) as data:clocks.append(data['time_s'].copy())
        times=np.concatenate(clocks)
        if len(times)!=reader.meta['frames'] or not np.isfinite(times).all() or np.any(np.diff(times)<=0):
            raise ValueError('Recorded motion clock differs')
        keep=np.ones(len(times),dtype=bool)
        if timeline is not None:
            from ..media.motion_timeline import MotionTimeline
            cut=MotionTimeline(timeline,reader)
            if not np.array_equal(cut.times,times):raise ValueError('Timeline clock differs from the recording')
            keep=cut.keep.astype(bool).copy()
        elif not keep_idle:
            from ..media.motion_cut import meaningful_keep
            keep=meaningful_keep(recording)[1]
        np.savez_compressed(edit_dir/'selection.npz',source_time_s=times,keep=keep)
        write(edit_dir/'edit.json',dict(schema='robofrontier.station-edit.v2',case_id=spec['id'],
            source_scene_sha256=reader.meta['source_scene_sha256'],source_stream_sha256=digest(recording/'stream.json'),
            events_sha256=digest(recording/'events.jsonl'),source_frames=len(times),source_hz=reader.meta['sample_hz'],
            source_end_frame=len(times)-1,input_evidence_sha256={},selection_file='selection.npz',
            selection_sha256=digest(edit_dir/'selection.npz'),scope=('Uncut' if keep_idle and timeline is None else 'Still, jittering and drifting intervals cut from the')+' closed benchmark recording; no inferred completion or semantic cuts'))
        replacement=dict(id=spec['id'],level=read(recording/'source/task.json')['level'],directory=str(recording/'source'),
            recording=str(recording),edit=str(edit_dir/'edit.json'),edit_sha256=digest(edit_dir/'edit.json'),
            qualification='recorded_benchmark_presentation_only',table_opening_scale=1.)
        release['families']={name:dict(speedup=speedup,fps=30,oracle=[replacement])}
        write(tmp/'release.json',release)
        result=export_bundle(output,scene,tmp/'release.json',inside(data_root,read(data_root/'bundle.json')['cameras']),tmp/'asset',ROOT)
    return dict(**result,data_root=str(output),case_id=spec['id'],speedup=speedup)


def prepare(data_root, output, families=None, levels=None, views=('front', 'side'), cases=None,
            duration_s=None, width=1920, height=1080, samples=64, mode='desks', device=None,
            effective_configuration=None, asset_lock_sha256=None, project=None):
    from ..media.motion_recording import MotionReader
    from ..media.station_edit import StationEdit
    from ..tasks.families import oracle_recording
    initial_code=code_hashes()
    data_root, output = Path(data_root).resolve(), Path(output).resolve()
    verified = verify(data_root)
    if output.exists():
        raise FileExistsError('Choose a new render batch directory')
    if min(width, height, samples) <= 0 or width%2 or height%2 or (duration_s is not None and (not math.isfinite(duration_s) or duration_s <= 0)):
        raise ValueError('Positive resolution, samples and finite duration required')
    if len(set(views)) != len(views) or not views or set(views)-{'front','side'}:
        raise ValueError('Choose distinct front/side views')
    if project is not None and mode != 'promo':
        raise ValueError('An editorial project is only used for the full Factory tour')
    editorial = None
    if project is not None:
        from .editorial import load
        editorial = load(project, data_root)
    release = resolved_release(data_root)
    known_cases={s['id'] for f in release['families'].values() for s in f['oracle']}
    if cases and set(cases)-known_cases:raise ValueError('Unknown selected task ID')
    if families and set(families)-release['families'].keys():
        raise ValueError('Unknown task family')
    if levels and set(levels)-{1,2,3}:
        raise ValueError('Unknown task level')
    jobs = []
    fps = release['presentation']['fps']
    if fps != 30:
        raise ValueError('Current Cycles encoder requires the reviewed 30-fps presentation')
    if mode == 'promo':
        if families or levels or cases:
            raise ValueError('The factory-tour camera visits all published workstations')
        full_duration = editorial['project']['duration_s'] if editorial else 210.5
        if duration_s is not None and duration_s > full_duration:
            raise ValueError('Preview cap exceeds the full editorial project')
        jobs.append(dict(index=0, id='promo', frames=math.ceil((duration_s or full_duration)*fps)))
    elif mode == 'desks':
        for name, family in release['families'].items():
            if families and name not in families:
                continue
            for spec in family['oracle']:
                if cases and spec['id'] not in cases:continue
                level = spec.get('level', read(Path(spec['directory'])/'task.json')['level'])
                if levels and level not in levels:
                    continue
                reader = MotionReader(oracle_recording(spec['recording']))
                edit = StationEdit(spec['edit'], reader)
                frames = len(edit.select(family['speedup'], fps))
                if duration_s is not None:
                    frames = min(frames, math.ceil(duration_s*fps))
                for view in views:
                    jobs.append(dict(index=len(jobs), id=spec['id']+'--'+view,
                        case_id=spec['id'], recorded_case_id=spec.get('recorded_case_id',spec['id']),
                        family=name, level=level, view=view, frames=frames))
    else:
        raise ValueError('Unknown render mode')
    if not jobs:
        raise ValueError('No selected render jobs')
    if code_hashes()!=initial_code:
        raise ValueError('Rendering code changed during prepare; run prepare again')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.factory-plan-', dir=output.parent) as temporary:
        staged = Path(temporary)
        frozen_editorial = None
        if mode == 'promo':
            from .editorial import _create_verified, freeze, load
            if project is None:
                _create_verified(data_root, staged/'editorial')
                loaded = load(staged/'editorial/project.json', data_root)
                frozen_editorial = {'project':'project.json', 'files':loaded['files']}
            else:
                frozen_editorial = freeze(project, staged/'editorial', data_root)
                if frozen_editorial['files'] != editorial['files']:
                    raise ValueError('Editorial input changed during preparation')
        write(staged/'release.json', release)
        manifest = read(data_root/'bundle.json')
        plan = dict(schema=PLAN_SCHEMA, data_root=str(data_root), bundle_sha256=verified['bundle_sha256'],
            scene=str(inside(data_root,manifest['scene'])),asset=str(inside(data_root,manifest['asset'])),
            cameras=str(inside(data_root,manifest['cameras'])), release_sha256=digest(staged/'release.json'),
            code_hashes=initial_code, mode=mode, fps=fps, width=width, height=height, samples=samples,
            device=device or ('METAL' if platform.system()=='Darwin' else 'OPTIX'), jobs=jobs,
            scope='Offline recorded-state rendering; no model calls, physics execution or task scores')
        if frozen_editorial is not None:
            plan['editorial'] = frozen_editorial
        if effective_configuration is not None:
            plan['effective_configuration'] = deepcopy(effective_configuration)
            plan['asset_lock_sha256'] = asset_lock_sha256
        write(staged/'plan.json', plan)
        (staged/'plan.sha256').write_text(digest(staged/'plan.json')+'\n')
        if code_hashes() != initial_code:
            raise ValueError('Rendering code changed during prepare; run prepare again')
        staged.rename(output)
    return dict(plan=str(output/'plan.json'), jobs=len(jobs), scope=plan['scope'])


def load_plan(path, check_inputs=True):
    path = Path(path).resolve()
    plan = read(path)
    if plan.get('schema') != PLAN_SCHEMA:
        raise ValueError('Unknown factory render plan')
    if digest(path)!=(path.parent/'plan.sha256').read_text().strip():
        raise ValueError('Prepared render plan changed')
    if not check_inputs:
        return path,plan
    if code_hashes() != plan['code_hashes']:
        raise ValueError('Rendering code changed after prepare; prepare a new batch')
    if digest(path.parent/'release.json') != plan['release_sha256']:
        raise ValueError('Prepared release changed')
    if digest(Path(plan['data_root'])/'bundle.json') != plan['bundle_sha256']:
        raise ValueError('Prepared data release changed')
    if 'editorial' in plan:
        from .editorial import load
        editorial = plan['editorial']
        loaded = load(inside(path.parent/'editorial', editorial['project']), plan['data_root'])
        if loaded['files'] != editorial['files']:
            raise ValueError('Prepared editorial inputs changed')
    return path, plan


def completed(job_dir, verify_video=False, *, plan=None):
    marker = Path(job_dir)/'complete.json'
    if not marker.exists():
        return None
    data = read(marker)
    if plan is not None and 'editorial' in plan and 'editorial' not in data:
        raise ValueError('Completed tour is missing its required editorial output')
    attempt = inside(job_dir, data['attempt'])
    video, report = attempt/'render/factory.mp4', attempt/'render/report.json'
    if digest(video) != data['video_sha256'] or digest(report) != data['report_sha256']:
        raise ValueError('Completed output changed')
    if read(report).get('animation',{}).get('full_decode_passed') is not True:
        raise ValueError('Completed video was not verified')
    editorial = data.get('editorial')
    if editorial is not None:
        final = inside(attempt, editorial['video'])
        final_report = inside(attempt, editorial['report'])
        if digest(final) != editorial['video_sha256'] or digest(final_report) != editorial['report_sha256']:
            raise ValueError('Completed editorial output changed')
        review = read(final_report)
        if review.get('full_decode_passed') is not True or review.get('video_sha256') != digest(final):
            raise ValueError('Completed editorial movie was not verified')
        if plan is not None and 'editorial' in plan:
            from .editorial import load
            retained = load(inside(final.parent/'project',plan['editorial']['project']))
            if (review.get('project_files') != plan['editorial']['files']
                    or retained['files'] != plan['editorial']['files']):
                raise ValueError('Completed editorial project differs from the prepared plan')
            if (review.get('source_video_sha256') != data['video_sha256']
                    or review.get('media',{}).get('width') != plan['width']
                    or review.get('media',{}).get('height') != plan['height']
                    or review.get('media',{}).get('fps') != plan['fps']
                    or review.get('media',{}).get('frames') != read(report)['animation']['frames']):
                raise ValueError('Completed editorial media differs from the source render')
    if verify_video:
        subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
        if editorial is not None:
            subprocess.run(['ffmpeg','-v','error','-i',str(final),'-f','null','-'],check=True)
    return data


def run_job(plan_path, index, blender=None, scratch=None):
    path, plan = load_plan(plan_path)
    if index < 0 or index >= len(plan['jobs']):
        raise ValueError('Render job index outside plan')
    job = plan['jobs'][index]
    selected=None
    if plan['mode']=='desks':
        release=resolved_release(plan['data_root'])
        selected=[s['id'] for s in release['families'][job['family']]['oracle']
                  if s.get('level',read(Path(s['directory'])/'task.json')['level'])==job['level']]
    verify(plan['data_root'],cases=selected)
    job_dir = path.parent/'jobs'/job['id']
    job_dir.mkdir(parents=True, exist_ok=True)
    # A process that is killed cannot leave a stale advisory lock on POSIX.
    import fcntl
    with (job_dir/'run.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('This render job is already running')
        if completed(job_dir, verify_video=True, plan=plan):
            if read(job_dir/'complete.json')['plan_sha256']!=digest(path):
                raise ValueError('Completed output belongs to a different plan')
            return dict(status='already_complete',job=job['id'])
        executable = blender_path(blender)
        if scratch is not None:
            Path(scratch).mkdir(parents=True, exist_ok=True)
        attempt_id = 'attempt-'+uuid.uuid4().hex
        work = Path(tempfile.mkdtemp(prefix=attempt_id+'-', dir=scratch))
        stopped = []
        active = [None]
        def stop(signum, frame):
            stopped.append(signum)
            if active[0] is not None and active[0].poll() is None:
                os.killpg(active[0].pid, signal.SIGTERM)
        handlers = {s:signal.signal(s,stop) for s in (signal.SIGTERM,signal.SIGINT)}
        started = time.time()
        write(job_dir/'running.json',dict(pid=os.getpid(),host=platform.node(),attempt=attempt_id,started_unix_s=started,work_dir=str(work)))
        error = None
        def command(argv, *, cwd=ROOT):
            if stopped:
                raise InterruptedError('Render interrupted')
            with (work/'render.log').open('a') as log:
                log.write(json.dumps([str(a) for a in argv])+'\n');log.flush()
                active[0] = subprocess.Popen([str(a) for a in argv],cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                while True:
                    try:
                        code = active[0].wait(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        if stopped:
                            try: active[0].wait(timeout=30)
                            except subprocess.TimeoutExpired: os.killpg(active[0].pid,signal.SIGKILL)
                if stopped:
                    raise InterruptedError('Render interrupted; this attempt is not complete')
                if code:
                    raise subprocess.CalledProcessError(code,argv)
        try:
            if plan['mode']=='promo':
                arguments = [sys.executable,'-m','robofrontier.factory.tour','--output',work/'poses',
                    '--scene',plan['scene'],'--cameras',plan['cameras'],'--release',path.parent/'release.json',
                    '--duration',str(job['frames']/plan['fps']),'--preview-fps','30']
                if 'editorial' in plan:
                    project = read(path.parent/'editorial'/plan['editorial']['project'])
                    arguments.extend(['--camera-plan', inside(path.parent/'editorial', project['camera_plan'])])
                command(arguments)
            else:
                command([sys.executable,'-m','robofrontier.factory.commands','poses','--scene',plan['scene'],
                    '--release',path.parent/'release.json','--output',work/'poses',
                    '--duration',str((job['frames']-.5)/plan['fps']),
                    '--camera','desk-'+job['view'],'--station',job['case_id'],
                    '--desk-cameras',plan['cameras'],'--families',job['family'],'--levels',str(job['level'])])
            animation = read(work/'poses/animation.json')
            if len(animation['frames']) != job['frames']:
                raise ValueError('Exported pose count differs from plan')
            argv=[executable,'--background','--python-exit-code','1','--python',ROOT/'robofrontier/factory/blender/render.py','--',
                '--asset',plan['asset'],'--animation',work/'poses/animation.json','--output',work/'render',
                '--engine','cycles','--profile','fast','--device',plan['device'],
                '--width',str(plan['width']),'--height',str(plan['height']),'--samples',str(plan['samples']),
                '--min-samples',str(min(4,plan['samples'])),'--noise-threshold','0.1']
            if plan['device']!='CPU':
                argv.append('--require-single-gpu')
            command(argv)
            report=read(work/'render/report.json')
            if (report.get('animation',{}).get('full_decode_passed') is not True
                    or report['animation']['frames']!=job['frames'] or report['animation']['fps']!=plan['fps']):
                raise ValueError('Video decode validation did not pass')
            if 'editorial' in plan:
                from .editorial import render
                render(path.parent/'editorial'/plan['editorial']['project'], work/'render/factory.mp4',
                       work/'editorial', run_command=command)
            if code_hashes()!=plan['code_hashes']:
                raise ValueError('Rendering code changed during execution; output is not sealed')
            # Check again after rendering: a camera or subtitle edit during an
            # attempt must never acquire the original frozen plan's seal.
            load_plan(path)
            if 'editorial' in plan and read(work/'editorial/report.json')['project_files'] != plan['editorial']['files']:
                raise ValueError('Rendered editorial project differs from the prepared plan')
        except Exception as exc:
            error = exc
        finally:
            active[0] = None
            write(work/'attempt.json',dict(job=job,status='interrupted' if stopped else 'failed' if error else 'complete',
                started_unix_s=started,ended_unix_s=time.time(),signals=stopped,error=str(error) if error else None,
                bundle_sha256=plan['bundle_sha256'],plan_sha256=digest(path)))
            destination=job_dir/attempt_id
            staging=job_dir/('.stage-'+attempt_id)
            try:
                shutil.copytree(work,staging)
                for file in work.rglob('*'):
                    if file.is_file() and digest(file)!=digest(staging/file.relative_to(work)):
                        raise ValueError('Result stage-out checksum mismatch')
                staging.rename(destination)
                if error is None and not stopped:
                    marker = dict(attempt=attempt_id,video_sha256=digest(destination/'render/factory.mp4'),
                        report_sha256=digest(destination/'render/report.json'),plan_sha256=digest(path))
                    if 'editorial' in plan:
                        marker['editorial'] = dict(video='editorial/factory.mp4',report='editorial/report.json',
                            video_sha256=digest(destination/'editorial/factory.mp4'),
                            report_sha256=digest(destination/'editorial/report.json'))
                    write(job_dir/'complete.json', marker)
                shutil.rmtree(work)
                (job_dir/'running.json').unlink(missing_ok=True)
            except Exception:
                print('Stage-out incomplete; preserve local data at '+str(work),file=sys.stderr)
                raise
            finally:
                for s,handler in handlers.items(): signal.signal(s,handler)
        if error:
            raise error
        if stopped:
            raise InterruptedError('Render interrupted during result collection')
        return dict(status='complete',job=job['id'],output=str(destination))


def status(plan_path):
    path, plan = load_plan(plan_path,check_inputs=False)
    rows=[]
    for job in plan['jobs']:
        folder=path.parent/'jobs'/job['id']
        done=completed(folder, plan=plan)
        attempts=sorted(folder.glob('attempt-*/attempt.json'),key=lambda p:p.stat().st_mtime) if folder.exists() else []
        row=dict(index=job['index'],id=job['id'],status='complete' if done else read(attempts[-1])['status'] if attempts else 'pending')
        if not done and (folder/'running.json').exists():
            row['runtime']=read(folder/'running.json')
            import fcntl
            with (folder/'run.lock').open('a') as lock:
                try:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    row['status']='interrupted_unsealed'
                except BlockingIOError:row['status']='running'
        if done:
            row['video']=str(folder/done['attempt']/done.get('editorial',{}).get('video','render/factory.mp4'))
            if 'editorial' in done:
                row['source_video']=str(folder/done['attempt']/'render/factory.mp4')
        rows.append(row)
    result=dict(jobs=rows,complete=sum(r['status']=='complete' for r in rows),total=len(rows))
    write(path.parent/'summary.json',result)
    return result


def submit(plan_path, partition, parallel=1, cpus=20, memory='64G', wall_time='24:00:00', blender=None, dry_run=False,
           account='', qos='', gpus=None, stop_warning_s=180):
    path,plan=load_plan(plan_path)
    if min(parallel,cpus)<=0:
        raise ValueError('Positive concurrency and CPU count required')
    if type(stop_warning_s) is not int or stop_warning_s<120:
        raise ValueError('Factory stop warning must be at least 120 seconds')
    logs=path.parent/'logs';logs.mkdir(exist_ok=True)
    gpus = (0 if plan['device']=='CPU' else 1) if gpus is None else gpus
    if gpus != (0 if plan['device']=='CPU' else 1):
        raise ValueError('Factory renders require zero GPUs for CPU or one GPU for CUDA/OPTIX')
    if plan['device']=='METAL':
        raise ValueError('Metal rendering is native macOS; choose CPU, CUDA or OPTIX for Slurm')
    command=['sbatch','--parsable','--nodes=1','--ntasks=1',
        '--cpus-per-task',str(cpus),'--mem',memory,'--time',wall_time,'--no-requeue','--signal=B:TERM@'+str(stop_warning_s),
        '--array',f'0-{len(plan["jobs"])-1}%{parallel}','--output',str(logs/'%A_%a.out'),
        '--chdir',str(ROOT),'--export=ALL,RF_FACTORY_PYTHON='+sys.executable,
        str(ROOT/'robofrontier/factory/slurm_factory.sbatch'),str(path),'--blender',blender_path(blender)]
    options=[]
    for name,value in (('partition',partition),('account',account),('qos',qos)):
        if value:options.extend(['--'+name,value])
    if gpus:options.append('--gres=gpu:1')
    command[2:2]=options
    if dry_run:
        return dict(command=command,submitted=False)
    result=subprocess.check_output(command,cwd=ROOT,text=True).strip()
    write(path.parent/('submission-'+uuid.uuid4().hex+'.json'),dict(job_id=result,command=command))
    return dict(job_id=result,batch=str(path.parent),jobs=len(plan['jobs']),parallel=parallel)
