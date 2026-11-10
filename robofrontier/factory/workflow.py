"""Configured Factory operations preserve the existing frozen-recording interface."""
from copy import deepcopy
from pathlib import Path

from ..configuration import ROOT, load_configuration, validate_configuration
from . import bundle
from . import server


def _path(value):
    path = Path(value).expanduser()
    return (path if path.is_absolute() else ROOT/path).resolve()


def add_arguments(subparsers):
    parser = subparsers.add_parser('factory', help='Configure frozen-motion replay and offline Cycles rendering')
    actions = parser.add_subparsers(dest='factory_action', required=True)
    for name in ('setup', 'verify', 'doctor', 'prepare', 'import-motion', 'project'):
        command = actions.add_parser(name)
        command.add_argument('--data-root')
        command.add_argument('--source', choices=('release', 'imported'))
        if name == 'setup':
            command.add_argument('--archive', type=Path)
        if name in ('doctor', 'prepare'):
            command.add_argument('--device', choices=('OPTIX', 'CUDA', 'METAL', 'CPU'))
            command.add_argument('--blender')
        if name in ('prepare', 'import-motion', 'project'):
            command.add_argument('--output', type=Path, required=True)
        if name == 'prepare':
            command.add_argument('--project', type=Path, help='Editable English tour project to freeze; omit for generated defaults')
            command.add_argument('--mode', choices=('desks', 'promo'))
            command.add_argument('--views', nargs='+', choices=('front', 'side'))
            command.add_argument('--width', type=int)
            command.add_argument('--height', type=int)
            command.add_argument('--samples', type=int)
            command.add_argument('--duration-s', type=float)
            command.add_argument('--families', nargs='+', choices=('transport', 'mosaic', 'relay', 'dial'))
            command.add_argument('--cases', nargs='+')
            command.add_argument('--level', type=int, choices=(1, 2, 3))
            command.add_argument('--min-arms', action='store_true', default=None)
        if name == 'import-motion':
            command.add_argument('recording', type=Path)
            command.add_argument('--speedup', type=float)
            command.add_argument('--keep-idle', action='store_true', help='Keep stationary intervals instead of cutting them')
            command.add_argument('--timeline', type=Path, help='motion-cut.json from scripts.render_policy_videos for this recording')
    edit = actions.add_parser('edit-video', help='Reuse a movie for text-only editorial changes; no scene identity claim')
    edit.add_argument('--project', type=Path, required=True)
    edit.add_argument('--input', type=Path, required=True)
    edit.add_argument('--output', type=Path, required=True)
    for name in ('run', 'status', 'submit'):
        command = actions.add_parser(name)
        command.add_argument('plan', type=Path)
        if name == 'run':
            command.add_argument('--index', type=int, required=True)
            command.add_argument('--scratch', type=Path)
            command.add_argument('--blender')
        elif name == 'submit':
            command.add_argument('--queue', action='store_true', help='Submit; omit to inspect the exact sbatch command')


def _configuration(args):
    updates = {}
    for field in ('data_root', 'source', 'device', 'blender', 'mode', 'views',
                  'width', 'height', 'samples', 'duration_s'):
        if getattr(args, field, None) is not None:
            updates[field] = getattr(args, field)
    if getattr(args, 'speedup', None) is not None:
        updates['import_speedup'] = args.speedup
    selection = {field: getattr(args, field) for field in ('families', 'cases', 'level', 'min_arms')
                 if getattr(args, field, None) is not None}
    overrides = {}
    if updates:
        overrides['factory'] = updates
    if selection:
        overrides['selection'] = selection
    return load_configuration(args.config, overrides)


def _data(config, archive=None, *, verify_existing=True):
    factory = config['factory']
    path = _path(factory['data_root'])
    if path.exists() and not verify_existing and archive is None:
        # The next server operation performs full verification. Avoid hashing
        # a 123k-file bundle twice immediately in one prepare/import command.
        if factory['source'] == 'release' and bundle.digest(path/'bundle.json') != bundle.read(_path(factory['asset_lock']))['bundle_sha256']:
            raise ValueError('Existing Factory bundle differs from the configured release lock')
        return path, {'status': 'available_for_verification'}
    if factory['source'] == 'release':
        receipt = bundle.setup(_path(factory['asset_lock']), path, archive=archive)
    else:
        if archive is not None:
            raise ValueError('Imported bundles are existing recording exports; no release archive is installed over them')
        receipt = bundle.verify(path)
    return path, receipt


def _cases(data_root, selection):
    """Select from the recording bundle, independently of current policy physics."""
    release = bundle.resolved_release(data_root)
    known = {spec['id'] for family in release['families'].values() for spec in family['oracle']}
    if set(selection['cases'])-known:
        raise ValueError('Unknown selected Factory task ID')
    if set(selection['families'])-set(release['families']):
        raise ValueError('Unknown selected Factory family')
    selected = []
    for name, family in release['families'].items():
        if selection['families'] and name not in selection['families']:
            continue
        rows = []
        for spec in family['oracle']:
            task = bundle.read(Path(spec['directory'])/'task.json')
            if selection['cases'] and spec['id'] not in selection['cases']:
                continue
            if selection['level'] and task['level'] != selection['level']:
                continue
            rows.append((spec['id'], len(task['arms']) if selection['min_arms'] else 0))
        if selection['min_arms'] and rows:
            minimum = min(arms for _, arms in rows)
            rows = [(case, arms) for case, arms in rows if arms == minimum]
        selected.extend(case for case, _ in rows)
    if not selected:
        raise ValueError('No selected Factory recordings')
    return selected


def _frozen(plan_path):
    path, plan = server.load_plan(plan_path)
    if 'effective_configuration' not in plan:
        raise ValueError('Legacy render plan without a frozen configuration; prepare it again with robofrontier factory prepare')
    config = plan['effective_configuration']
    validate_configuration(config)
    return path, plan, config


def execute(args):
    action = args.factory_action
    if action == 'edit-video':
        from .editorial import render
        return render(args.project, args.input, args.output)
    if action in ('run', 'status', 'submit'):
        if action == 'status':
            # Read-only status also remains usable if local source has changed.
            return server.status(args.plan)
        path, plan, config = _frozen(args.plan)
        factory = config['factory']
        if action == 'run':
            return server.run_job(path, args.index, blender=args.blender or factory['blender'] or None,
                                  scratch=args.scratch)
        queue = config['slurm']
        hours, seconds = divmod(queue['time_limit_s'], 3600)
        minutes, seconds = divmod(seconds, 60)
        return server.submit(path, queue['partition'], parallel=factory['parallel'],
            cpus=queue['cpus_per_task'], memory=str(queue['memory_gib'])+'G',
            wall_time=f'{hours}:{minutes:02d}:{seconds:02d}', blender=factory['blender'] or None,
            account=queue['account'], qos=queue['qos'], gpus=queue['gpus'],
            stop_warning_s=queue['stop_warning_s'], dry_run=not args.queue)
    config = _configuration(args)
    factory = config['factory']
    # Verify/doctor intentionally inspect existing bytes and never trigger an
    # unexpected multi-gigabyte download. Setup/prepare/import install as needed.
    if action in ('verify', 'doctor'):
        data = _path(factory['data_root'])
        if action == 'verify':
            result = bundle.verify(data)
        else:
            result = server.doctor(data, blender=factory['blender'] or None, device=factory['device'])
        if factory['source'] == 'release' and result['bundle_sha256'] != bundle.read(_path(factory['asset_lock']))['bundle_sha256']:
            raise ValueError('Existing Factory bundle differs from the configured release lock')
        return dict(result, model_calls=0)
    if action in ('prepare', 'import-motion', 'project') and args.output.resolve().exists():
        raise ValueError('Choose a new Factory output directory')
    if action == 'prepare' and factory['mode'] == 'promo' and any(config['selection'].values()):
        raise ValueError('Full Factory promo visits every station; remove selection filters')
    data, receipt = _data(config, getattr(args, 'archive', None), verify_existing=action=='setup')
    if action == 'setup':
        return dict(receipt, data_root=str(data), model_calls=0)
    if action == 'project':
        from .editorial import create
        return create(data, args.output)
    if action == 'import-motion':
        result = server.import_motion(data, args.recording, args.output, speedup=factory['import_speedup'] or None,
                                      keep_idle=args.keep_idle, timeline=args.timeline)
        return dict(result, model_calls=0, next_prepare=['factory', 'prepare', '--source', 'imported',
                    '--data-root', result['data_root'], '--output', str(args.output.with_name(args.output.name+'-render'))])
    cases = _cases(data, config['selection']) if factory['mode'] == 'desks' else None
    result = server.prepare(data, args.output, cases=cases, views=factory['views'],
        duration_s=factory['duration_s'] or None, width=factory['width'], height=factory['height'],
        samples=factory['samples'], mode=factory['mode'], device=factory['device'],
        project=args.project,
        effective_configuration=deepcopy(config),
        asset_lock_sha256=bundle.digest(_path(factory['asset_lock'])) if factory['source']=='release' else None)
    return dict(result, model_calls=0)
