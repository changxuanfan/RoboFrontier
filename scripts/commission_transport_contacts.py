"""Isolated contact-candidate commissioning; never a full-task witness."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import time
import xml.etree.ElementTree as ET


def read(path):
    return json.loads(Path(path).read_text())


def write(path, data):
    Path(path).write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate(source, destination, variant):
    import mujoco
    import numpy as np
    from robofrontier.suite.v2 import physical_summary
    if variant not in ('released', 'elliptic-30mm', 'elliptic-1mm'):
        raise ValueError('Unknown contact candidate')
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination == source or destination.is_relative_to(source):
        raise ValueError('Candidate must be separate from the source scene')
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns('assets'))
    def link(a, b):
        try: os.link(a, b)
        except OSError: shutil.copyfile(a, b)
    shutil.copytree(source/'assets', destination/'assets', copy_function=link)
    original = mujoco.MjModel.from_xml_path(str(source/'scene.xml'))
    root = ET.parse(destination/'scene.xml')
    selected = [g for g in root.findall('.//geom') if '_item' in g.get('name', '')
                and g.get('name', '').endswith('_geom') and g.get('type') == 'cylinder']
    if not selected: raise ValueError('No material cylinders in this case')
    if variant != 'released':
        root.find('option').set('cone', 'elliptic')
        for g in selected:
            friction = g.get('friction').split()
            friction[2] = '.001' if variant == 'elliptic-1mm' else '.03'
            g.set('friction', ' '.join(friction)); g.set('condim', '6')
        root.write(destination/'scene.xml', encoding='unicode')
    model = mujoco.MjModel.from_xml_path(str(destination/'scene.xml'))
    # Compare the compiled model before any simulation. Only cone and selected
    # rolling coefficients may change; fixture copies never reuse qualification.
    ids = [model.geom(g.get('name')).id for g in selected]
    for attr in dir(original):
        a, b = getattr(original, attr), getattr(model, attr)
        if not isinstance(a, np.ndarray): continue
        if attr == 'geom_friction':
            expected = a.copy()
            if variant != 'released': expected[ids, 2] = .001 if variant == 'elliptic-1mm' else .03
            np.testing.assert_array_equal(b, expected, err_msg=attr)
        else: np.testing.assert_array_equal(a, b, err_msg=attr)
    for attr in dir(original.opt):
        if attr.startswith('_'): continue
        a, b = getattr(original.opt, attr), getattr(model.opt, attr)
        if callable(a): continue
        if attr == 'cone':
            expected = a if variant == 'released' else mujoco.mjtCone.mjCONE_ELLIPTIC
            if b != expected: raise ValueError('Candidate has the wrong contact cone')
        else: np.testing.assert_array_equal(a, b, err_msg='option.'+attr)
    summary = physical_summary(model)
    summary['solver'].update(cone=int(model.opt.cone), noslip_tolerance=float(model.opt.noslip_tolerance))
    summary_hash = hashlib.sha256(json.dumps(summary, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    provenance = dict(variant=variant, source_directory=str(source), parent_scene_sha256=sha(source/'scene.xml'),
        scene_sha256=sha(destination/'scene.xml'), physics_sha256=summary_hash,
        fingerprint_scope='Legacy compiled summary extended with contact cone and NoSlip tolerance; separate from the source manifest fingerprint',
        scope='Independent engineering candidate; compiled arrays unchanged except declared cone/rolling; no inherited physical qualification',
        changed_cylinder_geoms=[model.geom(i).name for i in ids] if variant != 'released' else [],
        contact_cone=int(model.opt.cone), rolling_friction_m=float(model.geom_friction[ids[0], 2]),
        noslip_iterations=int(model.opt.noslip_iterations), noslip_tolerance=float(model.opt.noslip_tolerance))
    if variant != 'released':
        task = read(destination/'task.json')
        task.update(scene_sha256=provenance['scene_sha256'], scene_asset=str(destination))
        task['engineering_physics_candidate'] = provenance
        write(destination/'task.json', task)
        env = read(destination/'environment.json'); env['engineering_physics_candidate'] = provenance
        write(destination/'environment.json', env)
        manifest = read(destination/'workstation.json')
        manifest.update(scene_sha256=provenance['scene_sha256'], physics_sha256=summary_hash,
                        engineering_physics_candidate=provenance)
        manifest['case']['directory'] = str(destination)
        write(destination/'workstation.json', manifest)
        write(destination/'compiled-physics.json', summary)
    write(destination/'candidate.json', provenance)
    return provenance


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--case', required=True); p.add_argument('--output', type=Path, required=True)
    p.add_argument('--variant', choices=['released', 'elliptic-30mm', 'elliptic-1mm'], required=True)
    p.add_argument('--object', required=True)
    p.add_argument('--operation', choices=['delivery', 'pickup-release'], default='delivery')
    p.add_argument('--wall-s', type=float, default=180)
    a = p.parse_args()
    import math
    if not math.isfinite(a.wall_s) or a.wall_s <= 0:
        p.error('--wall-s must be positive and finite')
    from robofrontier.suite.source_snapshot import MARKER, reexec_entry
    if not os.environ.get(MARKER):
        import subprocess
        root = Path(__file__).resolve().parents[1]
        if subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip():
            raise ValueError('Commissioning requires committed source')
        reexec_entry(root, a.output, Path(__file__), sys.argv[1:],
                     root/'configs/harness-frontier-v2-servo2.json', root/'benchmark/transport/catalog.json')
    root = Path(os.environ[MARKER]); snapshot = read(root/'snapshot.json')
    source_root = Path(snapshot['source_root'])
    case = next(c for c in read(root/'inputs/catalog.json')['cases'] if c['id'] == a.case)
    out = a.output.resolve(); out.mkdir(parents=True, exist_ok=False)
    source = source_root/case['directory']
    inventory = ['scene.xml', 'task.json', 'environment.json', 'workstation.json']
    inventory += [entry['path'] for entry in read(source/'workstation.json')['assets']]
    source_hashes = {name:sha(source/name) for name in inventory}
    receipt = candidate(source, out/'candidate-scene', a.variant)
    import mujoco
    import numpy as np
    from robofrontier.suite.oracle import Trial, ReferenceStopped
    from robofrontier.suite import transport_oracle_v2 as ref
    from robofrontier.suite import transport_full_oracle as full
    from robofrontier.suite.placement_oracle import clear_idle_arms, park
    from robofrontier.suite.transport_runtime import TransportRuntime, sampled_motion_admission
    files = {name:(root/name).read_bytes() for name in snapshot['files']}
    t = Trial(out/'candidate-scene', out/'trial', sources=files, controller_cfg=read(root/'inputs/harness.json'))
    t.abort_on_process_violation = True; t.reference_inter_robot_clearance_m = .006
    t.transport_grasp_force_n = 50.; t.transport_grasp_epsilon_inner_m = .008; t.transport_guarded_pickups = True
    began = time.monotonic(); stopped = [False]
    signal.signal(signal.SIGTERM, lambda *_:stopped.__setitem__(0, True))
    t.stop_requested = lambda:stopped[0] or time.monotonic()-began > a.wall_s or (out/'STOP').exists()
    report = dict(passed=False, local_passed=False, full_task_attempt=False, commissioning_only=True,
                  candidate=receipt, operation=a.operation, object=a.object, llm_used=False,
                  scope='One selected material-cylinder operation; full task and all poses are not qualified',
                  engine=dict(mujoco=mujoco.__version__, numpy=np.__version__), stages=[])
    runtime = None
    try:
        obj = next(o for o in t.env['objects'] if o['id'] == a.object)
        if obj.get('shape') != 'cylinder': raise ValueError('Select a cylinder, not a cube')
        t.wait(.6); clear_idle_arms(t)
        report['stages'].append('initial-arms-parked')
        if a.operation == 'pickup-release':
            robot = a.object.split('_')[0]; before = t.data.body(a.object).xpos.copy()
            rotation = t.data.body(a.object).xmat.reshape(3, 3).copy()
            height = ref._pickup_height(t.task, rotation, .006, 'cylinder')
            ref._pick_side_cylinder(t, robot, a.object, height, 50.)
            report['stages'].append('bilateral-pick-and-guarded-lift')
            t.place(robot, before, rotation, precise=False)
            park(t, robot)
            report['stages'].append('release-and-withdraw')
        else:
            jobs = full.plan_jobs(t)
            job = next(j for j in jobs if j['object'] == a.object)
            report['job'] = {k:v for k,v in job.items() if k != 'goal'}
            runtime = TransportRuntime(t, admission=sampled_motion_admission,
                payload_contacts=lambda robot,name:ref._robot_payload_contacts(t,robot,name))
            previous_execute = t.execute
            objects = {o['id']:o for o in t.env['objects']}
            def execute(label, commands, allow_failure=False):
                adjusted = ref.cylinder_commands(commands, t.held, objects)
                for r,(op,data) in adjusted.items():
                    if op == 'move' and (r in t.held or t.arms[r].grasp_force is not None):
                        for key,limit in [('joint_speed_rad_s',.18),('speed_m_s',.025),('angular_speed_rad_s',.25)]:
                            if key in data: data[key] = min(data[key],limit)
                return previous_execute(label,adjusted,allow_failure=allow_failure)
            t.execute = execute
            if t.task['level'] > 1:
                from robofrontier.suite.transport_socket_motion import guard_contact_moves
                guard_contact_moves(t, lambda _robot:runtime._current()[1]['goal']['board'])
            runtime.add(job['id'], set(t.arms), lambda:full.execute_job(t,runtime,job))
            runtime.jobs[job['id']].update(object=job['object'],goal=job['goal'])
            while runtime.active: runtime.cycle()
            result = runtime.jobs[job['id']]
            if result['status'] != 'done':
                error = result.get('error')
                if isinstance(error, BaseException): raise error
                raise RuntimeError(str(error))
            runtime.close(); runtime = None
            report['stages'].append('original-goal-accepted-after-delivery')
        t.wait(1.)
        samples = []
        for _ in range(50):
            t.wait(.1)
            velocity = np.zeros(6)
            mujoco.mj_objectVelocity(t.model,t.data,mujoco.mjtObj.mjOBJ_BODY,t.model.body(a.object).id,velocity,0)
            samples.append(dict(time_s=t.time,position=t.data.body(a.object).xpos.tolist(),velocity=velocity.tolist()))
        tail = samples[-20:]
        report['settling'] = dict(samples=samples, max_final_linear_m_s=max(float(np.linalg.norm(s['velocity'][3:])) for s in tail),
            max_final_angular_rad_s=max(float(np.linalg.norm(s['velocity'][:3])) for s in tail))
        report['local_passed'] = report['settling']['max_final_linear_m_s'] < 1e-5 and report['settling']['max_final_angular_rad_s'] < 1e-4
        if a.operation == 'delivery':
            report['final_goal_retained'] = t.monitor.result().get('assignments', {}).get(job['id']) == a.object
            report['local_passed'] = report['local_passed'] and report['final_goal_retained']
        else:
            report['released_near_original_position'] = bool(
                t.monitor.released(t.monitor.geoms[a.object]) and
                np.linalg.norm(t.data.body(a.object).xpos-before) < .02)
            report['local_passed'] = report['local_passed'] and report['released_near_original_position']
    except (Exception,KeyboardInterrupt) as error:
        report['error'] = type(error).__name__+': '+str(error)
        if isinstance(error,(ReferenceStopped,KeyboardInterrupt)): report['interrupted'] = True
    finally:
        report['elapsed_wall_s'] = time.monotonic()-began
        report['unresolved_robot_actions'] = [r for r,arm in t.arms.items() if arm.job is not None or arm.uncertainty_reported]
        report['evaluation'] = t.monitor.result()
        report['original_sources_unchanged'] = all(sha(source/n) == h for n,h in source_hashes.items())
        if report['unresolved_robot_actions'] or report['evaluation']['violations'] or not report['original_sources_unchanged']:
            report['local_passed'] = False
        if runtime is not None:
            report['retained_resources'] = dict(runtime.leases)
            report['job_states'] = {n:dict(status=j['status'],error=str(j.get('error'))) for n,j in runtime.jobs.items()}
        t.close(report)
        write(out/'result.json',report)
    print(json.dumps({k:report.get(k) for k in ['passed','local_passed','stages','error','elapsed_wall_s','unresolved_robot_actions','original_sources_unchanged']}),flush=True)
    return 0 if report['local_passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
