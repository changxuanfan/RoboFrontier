"""Check the release physics and the Franka limits on the released scenes.

Every scenario runs a released case in the policy runtime's own World, controller and
step settings, and reports measurements with a pass or fail against the criteria of the
release (docs/physics.md):

    rest      every case at rest for 60 s: nothing drifts, hanging weights stay hung
    carry     a grasped object through fast joint turns, Cartesian moves at up to 2 m/s
              and 13 m/s2, and a 60 s still hold: it neither slips nor turns in the hand
    place     a carried cube set down and released: it settles within 1 s and stays
    push      a cube pushed along the table: it stops when the push stops
    collide   two arms driven into each other at full speed: the simulation stays valid
    relay     an airborne two-arm timber handover: no drop, no slide, no push when closing
    dial      a Dial knob grasped and turned: the dial follows the hand
    timing    the step time of the largest case of each family

    python -m scripts.validate_physics [SCENARIO ...] [--cases ID ...] [--workers N]

Results go to runs/engineering/validate-physics/<time>.json.
"""
import argparse
import json
import math
import os
import sys
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Pass criteria.
ROT_RESIDUAL_DEG, ROT_PEAK_DEG, SLIP_MM = 1., 2., 2.
REST_DRIFT_MM = .2         # after the first 5 s
PLACE_SETTLE_S, STILL_MM_S = 1., 1.
STEP_BUDGET_MS = 20.

FAST = dict(speed_m_s=2., acceleration_m_s2=13., angular_speed_rad_s=2.5, angular_acceleration_rad_s2=25.)
GENTLE = dict(speed_m_s=.1, acceleration_m_s2=1., angular_speed_rad_s=.5, angular_acceleration_rad_s2=5.)


class Bench:
    """One prepared run of a released case and its World."""

    def __init__(self, case_id, folder):
        from robofrontier.tasks.families import prepare
        from robofrontier.runtime.pipeline import World
        run = Path(folder)/'run'
        prepare(case_id, run)
        self.task = json.loads((run/'private/inputs/task.json').read_text())
        self.cfg = json.loads((run/'private/inputs/harness.json').read_text())
        self.world = World(run, self.task)
        self.model, self.data = self.world.model, self.world.data
        self.step_ms = []
        import mujoco; self.mujoco = mujoco

    # ---- stepping and actions ----
    def step(self, n=1, each=None):
        for _ in range(n):
            t = time.perf_counter(); self.world.step(); self.step_ms.append(1000*(time.perf_counter()-t))
            if each: each()

    def act(self, commands, timeout=60., each=None):
        """{arm: (op, parameters)}; runs until every action ends; returns {arm: result}."""
        lower = np.full(3, -9.); upper = np.full(3, 9.)
        for arm, (op, p) in commands.items():
            a = self.world.arms[arm]; a.start(arm+'-'+op, a.validate(op, p, self.cfg, lower, upper), self.data.time)
        results = {}; start = self.data.time
        while len(results) < len(commands):
            self.step(each=each)
            for arm in commands:
                if arm not in results:
                    r = self.world.arms[arm].poll(self.data.time, timeout)
                    if r: results[arm] = r
            if self.data.time-start > timeout+5: raise RuntimeError('actions did not end')
        return results

    def tcp(self, arm):
        a = self.world.arms[arm]
        return self.data.site_xpos[a.site].copy(), self.data.site_xmat[a.site].reshape(3, 3).copy()

    def body(self, name):
        b = self.data.body(name); return b.xpos.copy(), b.xmat.reshape(3, 3).copy()

    def free_bodies(self):
        m = self.model
        return [m.body(int(m.jnt_bodyid[j])).name for j in range(m.njnt) if int(m.jnt_type[j]) == 0]

    def in_hand(self, arm, body):
        p, R = self.tcp(arm); q, Q = self.body(body)
        return R.T@(q-p)*1000, R.T@Q

    def teleport_grasp(self, arm, body, width, force=40., offset=(0, 0, 0), yaw=0.):
        """Put the object between the open fingers, float it there while the hand grasps,
        then let gravity act. Returns the grasp result."""
        m, d = self.model, self.data
        self.act({arm: ('gripper', dict(width_m=self.world.arms[arm].grip_max, speed_m_s=.1))})
        p, R = self.tcp(arm); c, s = math.cos(yaw), math.sin(yaw)
        Rb = R@np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
        joint = m.body(body).jntadr[0]; qa, va = m.jnt_qposadr[joint], m.jnt_dofadr[joint]
        q = np.empty(4); self.mujoco.mju_mat2Quat(q, Rb.ravel())
        d.qpos[qa:qa+3] = p+R@np.asarray(offset); d.qpos[qa+3:qa+7] = q; d.qvel[va:va+6] = 0
        bid = m.body(body).id; d.xfrc_applied[bid, 2] = float(m.body_subtreemass[bid])*9.81
        self.mujoco.mj_forward(m, d)
        result = self.act({arm: ('gripper', dict(mode='grasp', width_m=width, force_n=force, speed_m_s=.05))})[arm]
        self.step(10); d.xfrc_applied[bid] = 0
        self.step(25)
        return result


def angle_deg(R):
    return math.degrees(math.acos(max(-1., min(1., (np.trace(R)-1)/2))))


def task_dir():
    return tempfile.TemporaryDirectory(prefix='rf-physics-')


# ---- scenarios ----
def rest(case_id):
    with task_dir() as folder:
        b = Bench(case_id, folder); names = b.free_bodies()
        start = {n: b.body(n)[0] for n in names}; after5 = {}
        hangers = [n for n in names if n.endswith('_weight')]
        b.step(250); after5 = {n: b.body(n)[0] for n in names}
        b.step(2750)
        moved = lambda a, z: max([float(np.linalg.norm(b.body(n)[0]-a[n]))*1000 for n in names] or [0.])
        first = max([float(np.linalg.norm(after5[n]-start[n]))*1000 for n in names] or [0.])
        drift = moved(after5, None)
        hung = all(b.body(n)[0][2] > start[n][2]-.005 for n in hangers)
        ms = np.array(b.step_ms)
        return dict(case=case_id, free_bodies=len(names), first_5s_mm=round(first, 3), drift_after_5s_mm=round(drift, 4),
                    weights=len(hangers), weights_hung=hung, step_ms_mean=round(float(ms.mean()), 2),
                    passed=drift < REST_DRIFT_MM and hung)


CARRY = {  # case, arm, body, grasp width, offset of the object centre in the hand
    'mosaic-cube': ('mosaic-a04-6x12-d1', 'A', 'A_stock01', .06, (0, 0, 0)),
    'transport-cube': ('transport-a04-d1', 'A', 'A_item1', .06, (0, 0, 0)),
    'transport-cylinder': ('transport-a08-d1', 'A', None, .06, (0, 0, 0)),
}


def find_cylinder(b):
    m = b.model
    for n in b.free_bodies():
        gs = [g for g in range(m.ngeom) if int(m.geom_bodyid[g]) == m.body(n).id and int(m.geom_type[g]) == 5]
        if gs and n.startswith('A_'): return n
    return next(n for n in b.free_bodies() if any(int(b.model.geom_type[g]) == 5 for g in range(b.model.ngeom) if int(b.model.geom_bodyid[g]) == b.model.body(n).id))


def carry(name, motion):
    case_id, arm, body, width, offset = CARRY[name]
    with task_dir() as folder:
        b = Bench(case_id, folder); body = body or find_cylinder(b)
        grasp = b.teleport_grasp(arm, body, width, offset=offset)
        if grasp['status'] != 'completed': return dict(name=name, motion=motion, passed=False, grasp=grasp)
        p0, R0 = b.in_hand(arm, body); peak = dict(slip=0., rot=0.)
        def track():
            p, R = b.in_hand(arm, body)
            peak['slip'] = max(peak['slip'], float(np.linalg.norm(p-p0))); peak['rot'] = max(peak['rot'], angle_deg(R0.T@R))
        a = b.world.arms[arm]; q0 = b.data.qpos[a.qids].copy(); kind, value = motion
        track_err = []
        def each():
            track(); track_err.append(float(np.max(np.abs(a.qref-b.data.qpos[a.qids]))))
        if kind == 'hold':
            b.step(int(value/.02), each)
        elif kind in ('joint1', 'joint7'):
            i = 0 if kind == 'joint1' else 6; swing = 1. if i == 0 else 1.5
            speed = [value]*7 if i == 6 else value
            for sign in (1, -1, 0):
                goal = q0.copy(); goal[i] += sign*swing
                goal = np.clip(goal, a.ik.limits[:, 0]+.02, a.ik.limits[:, 1]-.02)
                b.act({arm: ('move', dict(joint_rad=goal.tolist(), joint_speed_rad_s=np.minimum(speed, [2.175]*4+[2.61]*3).tolist() if i == 6 else value,
                                          joint_acceleration_rad_s2=[15., 7.5, 10., 12.5, 15., 20., 20.]))}, each=each)
        elif kind == 'cartesian':
            start, R = b.tcp(arm); c, s = math.cos(math.pi/2), math.sin(math.pi/2)
            turned = R@np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]]); qt = np.empty(4); b.mujoco.mju_mat2Quat(qt, turned.ravel())
            q_home = np.empty(4); b.mujoco.mju_mat2Quat(q_home, R.ravel())
            rates = dict(FAST, speed_m_s=value)
            for target, quat in ((start+[0, 0, -.12], qt), (start+[.1, 0, 0], q_home), (start, q_home)):
                b.act({arm: ('move', dict(target_m=target.tolist(), quaternion_wxyz=quat.tolist(), **rates))}, each=each)
        b.step(25, each); p1, R1 = b.in_hand(arm, body)
        residual_rot = angle_deg(R0.T@R1); slip = float(np.linalg.norm(p1-p0))
        held = bool(a.observe()['is_grasped']) and b.body(body)[0][2] > b.task['table_height_m']+.05
        return dict(name=name, motion=f'{kind} {value}', grasp_width_m=round(a.observe()['gripper_width_m'], 4),
                    slip_mm=round(slip, 3), peak_slip_mm=round(peak['slip'], 3), residual_rot_deg=round(residual_rot, 3),
                    peak_rot_deg=round(peak['rot'], 3), max_tracking_rad=round(max(track_err or [0]), 4), held=held,
                    step_ms_mean=round(float(np.mean(b.step_ms)), 2),
                    passed=held and slip < SLIP_MM and residual_rot < ROT_RESIDUAL_DEG and peak['rot'] < ROT_PEAK_DEG)


def place(name='transport-cube'):
    """Pick the cube up from where it starts, lift it, set it back down and release it."""
    case_id, arm, body, width, _ = CARRY[name]
    with task_dir() as folder:
        b = Bench(case_id, folder); table = b.task['table_height_m']; half = .03
        start, _ = b.body(body)
        b.act({arm: ('gripper', dict(width_m=.08, speed_m_s=.1))})
        b.act({arm: ('move', dict(target_m=(start+[0, 0, .10]).tolist(), **GENTLE))})
        b.act({arm: ('move', dict(target_m=start.tolist(), **GENTLE))})
        grasp = b.act({arm: ('gripper', dict(mode='grasp', width_m=width, force_n=40., speed_m_s=.05))})[arm]
        b.act({arm: ('move', dict(target_m=(start+[0, 0, .10]).tolist(), **dict(FAST, speed_m_s=.5)))})
        lifted = b.body(body)[0][2]-start[2]
        b.act({arm: ('move', dict(target_m=(start+[0, 0, .002]).tolist(), **dict(FAST, speed_m_s=.5)))})
        b.act({arm: ('gripper', dict(width_m=.08, speed_m_s=.05))})
        b.act({arm: ('move', dict(delta_m=[0, 0, .08], **GENTLE))})
        released = b.data.time; history = []
        for _ in range(int(10/.02)):
            b.step(); history.append((b.data.time-released, b.body(body)[0].copy()))
        speeds = [float(np.linalg.norm(history[k+1][1]-history[k][1]))/.02*1000 for k in range(len(history)-1)]
        moving = [k for k, v in enumerate(speeds) if v >= STILL_MM_S]
        settled = round(history[moving[-1]+1][0], 2) if moving else 0.
        drift = float(np.linalg.norm(history[-1][1]-history[50][1]))*1000
        return dict(name=name, grasp=grasp['status'], lifted_mm=round(lifted*1000, 1), settled_after_s=settled,
                    drift_1_to_10s_mm=round(drift, 4), resting_height_mm=round((history[-1][1][2]-half-table)*1000, 3),
                    passed=grasp['status'] == 'completed' and lifted > .08 and settled <= PLACE_SETTLE_S and drift < REST_DRIFT_MM)


def push():
    """Push a cube 5 cm along the table with the closed hand, in the first direction the arm reaches."""
    from robofrontier.physics.robot_control import IKNoSolution
    with task_dir() as folder:
        b = Bench('transport-a04-d1', folder); arm = 'A'; body = 'A_item1'
        base = b.data.body(arm+'_link0').xpos.copy(); item, _ = b.body(body)
        radial = np.array([item[0]-base[0], item[1]-base[1], 0.]); radial /= np.linalg.norm(radial)
        tangent = np.array([-radial[1], radial[0], 0.])
        b.act({arm: ('gripper', dict(state='close', speed_m_s=.1))})
        for direction in (tangent, -tangent, radial, -radial):
            start = item-direction*.07; start[2] = item[2]+.01
            try:
                b.act({arm: ('move', dict(target_m=(start+[0, 0, .1]).tolist(), **GENTLE))})
                b.act({arm: ('move', dict(target_m=start.tolist(), **GENTLE))})
                end = start+direction*.09; b.world.arms[arm].validate('move', dict(target_m=end.tolist(), **GENTLE), b.cfg, np.full(3, -9.), np.full(3, 9.))
                break
            except IKNoSolution:
                continue
        before = b.body(body)[0]
        b.act({arm: ('move', dict(target_m=end.tolist(), **dict(GENTLE, speed_m_s=.1)))})
        b.act({arm: ('move', dict(delta_m=(-direction*.03+[0, 0, .1]).tolist(), **GENTLE))})
        pushed = b.body(body)[0]; b.step(500); after = b.body(body)[0]
        return dict(name='push', pushed_mm=round(float(np.linalg.norm(pushed-before))*1000, 2),
                    drift_10s_mm=round(float(np.linalg.norm(after-pushed))*1000, 4),
                    passed=bool(np.linalg.norm(pushed-before) > .01 and np.linalg.norm(after-pushed)*1000 < REST_DRIFT_MM))


def collide():
    with task_dir() as folder:
        b = Bench('transport-a04-d1', folder)
        pa, _ = b.tcp('A'); pb, _ = b.tcp('B'); middle = (pa+pb)/2
        failure = None
        try:
            b.act({'A': ('move', dict(target_m=(middle+[0, 0, .0]).tolist(), **FAST)),
                   'B': ('move', dict(target_m=(middle+[0, 0, .0]).tolist(), **FAST))}, timeout=10.)
            b.step(100)
        except Exception as error:
            failure = f'{type(error).__name__}: {error}'
        deepest = min([b.data.contact[i].dist for i in range(b.data.ncon)]+[0.])
        finite = bool(np.isfinite(b.data.qpos).all())
        return dict(name='collide', failure=failure, deepest_contact_mm=round(-deepest*1000, 3), finite=finite,
                    passed=finite and (failure is None or 'Numerical' not in failure))


def relay(force=40.):
    """An airborne Relay handover of a 1.46 kg timber: senders A and B lift it from the
    table, receivers C and D close on it, the senders let go and leave, and the receivers
    carry it and set it down. The timber must not move when a receiver closes, drop, or
    slide in a hand."""
    with task_dir() as folder:
        b = Bench('relay-a08-d1', folder); m, d = b.model, b.data; P = 'payload_01'; width = .045
        def rotz(angle): c, s = math.cos(angle), math.sin(angle); return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
        def frames(stations, arms):
            """The two equivalent top-down jaw frames on the timber at each station; take the one
            nearer the arm's current hand."""
            p, R = b.body(P); out = []
            for (sign, station), arm in zip(stations, arms):
                point = p+R@np.array([0., sign*station, .006]); y = -sign*R[:, 0]; z = -R[:, 2]
                J = np.column_stack((np.cross(y, z), y, z)); J2 = J@rotz(math.pi)
                out.append((point, min((J, J2), key=lambda X: angle_deg(b.tcp(arm)[1].T@X))))
            return out
        quat = lambda R: (lambda q: (b.mujoco.mju_mat2Quat(q, R.ravel()), q)[1])(np.empty(4)).tolist()
        go = lambda targets, rates=GENTLE, **k: b.act({arm: ('move', dict(target_m=list(map(float, p)), quaternion_wxyz=quat(R), **rates)) for arm, (p, R) in targets.items()}, **k)
        local = lambda arm: (lambda p, R: R.T@(b.tcp(arm)[0]-p)*1000)(*b.body(P))
        senders, receivers = ['A', 'B'], ['C', 'D']; out = {}
        b.act({arm: ('gripper', dict(width_m=.065, speed_m_s=.1)) for arm in senders+receivers})
        targets = dict(zip(senders, frames([(-1, .30), (1, .30)], senders)))
        go({arm: (p+[0, 0, .08], R) for arm, (p, R) in targets.items()}); go(targets)
        grasp = b.act({arm: ('gripper', dict(mode='grasp', width_m=width, force_n=force, speed_m_s=.05)) for arm in senders})
        out['sender_grasp'] = {arm: r['status'] for arm, r in grasp.items()}
        ref = {arm: local(arm) for arm in senders}
        go({arm: (np.r_[b.tcp(arm)[0][:2], 1.27], b.tcp(arm)[1]) for arm in senders}, dict(GENTLE, speed_m_s=.3))
        go({arm: (b.tcp(arm)[0]+[.74, 0, 0], b.tcp(arm)[1]) for arm in senders}, dict(GENTLE, speed_m_s=.3))
        b.step(50); out['carry_slip_mm'] = {arm: round(float(np.linalg.norm(local(arm)-ref[arm])), 2) for arm in senders}
        targets = dict(zip(receivers, frames([(-1, .55), (1, .55)], receivers)))
        go({arm: (b.tcp(arm)[0]+[0, 0, .12], b.tcp(arm)[1]) for arm in receivers})
        go({arm: (p+[0, 0, .08], R) for arm, (p, R) in targets.items()}); go(targets, dict(GENTLE, speed_m_s=.05))
        before, _ = b.body(P)
        grasp = b.act({arm: ('gripper', dict(mode='grasp', width_m=width, force_n=force, speed_m_s=.05)) for arm in receivers})
        out['receiver_grasp'] = {arm: r['status'] for arm, r in grasp.items()}
        out['timber_moved_by_receivers_mm'] = round(float(np.linalg.norm(b.body(P)[0]-before))*1000, 3)
        b.step(50); ref = {arm: local(arm) for arm in receivers}; held = b.body(P)[0]
        b.act({arm: ('gripper', dict(width_m=.075, speed_m_s=.05)) for arm in senders})
        go({arm: (b.tcp(arm)[0]+[0, 0, .10], b.tcp(arm)[1]) for arm in senders})
        out['drop_at_release_mm'] = round(float(held[2]-b.body(P)[0][2])*1000, 3)
        go({arm: (b.tcp(arm)[0]+[.30, 0, .05], b.tcp(arm)[1]) for arm in receivers}, dict(GENTLE, speed_m_s=.3))
        b.step(50); out['receiver_carry_slip_mm'] = {arm: round(float(np.linalg.norm(local(arm)-ref[arm])), 2) for arm in receivers}
        out['airborne'] = bool(b.body(P)[0][2] > b.task['table_height_m']+.1)
        out['step_ms_mean'] = round(float(np.mean(b.step_ms)), 2)
        slips = list(out['carry_slip_mm'].values())+list(out['receiver_carry_slip_mm'].values())
        out['passed'] = (all(v == 'completed' for v in {**out['sender_grasp'], **out['receiver_grasp']}.values()) and out['airborne']
                         and out['timber_moved_by_receivers_mm'] < 1. and out['drop_at_release_mm'] < 1. and max(slips) < SLIP_MM)
        return dict(name='relay', **out)


def dial(case_id='dial-best5-n04-d1', speed=1.):
    with task_dir() as folder:
        b = Bench(case_id, folder); arm = 'A'; m, d = b.model, b.data
        knob = d.geom_xpos[m.geom('D01_red_knob').id].copy(); hinge = m.joint('D01_hinge')
        angle = lambda: float(d.qpos[m.jnt_qposadr[hinge.id]])
        _, R = b.tcp(arm)
        b.act({arm: ('gripper', dict(width_m=.08, speed_m_s=.1))})
        b.act({arm: ('move', dict(target_m=(knob+[0, 0, .08]).tolist(), **GENTLE))})
        b.act({arm: ('move', dict(target_m=(knob+[0, 0, .0]).tolist(), **GENTLE))})
        grasp = b.act({arm: ('gripper', dict(mode='grasp', width_m=.054, force_n=30., speed_m_s=.05, epsilon_inner_m=.01, epsilon_outer_m=.01))})[arm]
        a = b.world.arms[arm]; q = b.data.qpos[a.qids].copy(); start = angle(); turn = math.pi/2
        goal = q.copy(); goal[6] = np.clip(goal[6]+turn, a.ik.limits[6, 0]+.02, a.ik.limits[6, 1]-.02); turned_by = goal[6]-q[6]
        b.act({arm: ('move', dict(joint_rad=goal.tolist(), joint_speed_rad_s=speed, joint_acceleration_rad_s2=[15., 7.5, 10., 12.5, 15., 20., 20.]))})
        b.step(25); followed = abs(angle()-start)
        b.act({arm: ('gripper', dict(width_m=.08, speed_m_s=.1))}); b.act({arm: ('move', dict(delta_m=[0, 0, .08], **GENTLE))})
        held_angle = angle(); b.step(250)
        return dict(name='dial', case=case_id, grasp=grasp['status'], wrist_turn_deg=round(math.degrees(turned_by), 2),
                    dial_turn_deg=round(math.degrees(followed), 2), follow_error_deg=round(math.degrees(abs(followed-abs(turned_by))), 2),
                    drift_after_release_deg=round(math.degrees(abs(angle()-held_angle)), 4), step_ms_mean=round(float(np.mean(b.step_ms)), 2),
                    passed=grasp['status'] == 'completed' and abs(followed-abs(turned_by)) < math.radians(5) and abs(angle()-held_angle) < math.radians(.1))


def timing(case_id):
    with task_dir() as folder:
        b = Bench(case_id, folder); arms = list(b.world.arms)
        b.step(100); idle = float(np.mean(b.step_ms[-100:]))
        for arm in arms:
            a = b.world.arms[arm]; q = b.data.qpos[a.qids].copy(); q[0] += .3
            a.start(arm+'-t', a.validate('move', dict(joint_rad=q.tolist(), joint_speed_rad_s=.5, joint_acceleration_rad_s2=2.), b.cfg, np.full(3, -9.), np.full(3, 9.)), b.data.time)
        b.step(100); moving = float(np.mean(b.step_ms[-100:]))
        return dict(name='timing', case=case_id, arms=len(arms), idle_step_ms=round(idle, 2), moving_step_ms=round(moving, 2),
                    passed=moving < STEP_BUDGET_MS)


def jobs(selected, cases):
    from robofrontier.tasks.families import read
    release = read(ROOT/'benchmark/release.json')
    ids = [c['id'] for f in release['families'].values() for c in f['gpt']]
    if cases: ids = [i for i in ids if i in cases]
    out = []
    if 'rest' in selected: out += [(rest, (i,)) for i in ids]
    if 'carry' in selected:
        for name in CARRY:
            out += [(carry, (name, ('hold', 60.)))]
            out += [(carry, (name, ('joint1', v))) for v in (.5, 1., 2.175)]
            out += [(carry, (name, ('joint7', v))) for v in (.5, 1., 2.61)]
            out += [(carry, (name, ('cartesian', v))) for v in (.3, 1., 2.)]
    if 'place' in selected: out += [(place, ('transport-cube',))]
    if 'push' in selected: out += [(push, ())]
    if 'collide' in selected: out += [(collide, ())]
    if 'dial' in selected: out += [(dial, ('dial-best5-n04-d1', v)) for v in (.3, 1.)]
    if 'relay' in selected: out += [(relay, (f,)) for f in (40., 70.)]
    if 'timing' in selected:
        largest = {}
        for i in ids: largest[i.split('-')[0]] = i
        out += [(timing, (i,)) for i in largest.values()]
    return out


def run(job):
    function, args = job
    start = time.time()
    try: result = function(*args)
    except Exception as error:
        import traceback
        result = dict(name=function.__name__, args=[str(a) for a in args], passed=False, error=f'{type(error).__name__}: {error}',
                      trace=traceback.format_exc()[-1500:])
    result.setdefault('scenario', function.__name__); result['seconds'] = round(time.time()-start, 1)
    return json.loads(json.dumps(result, default=lambda v: v.item() if hasattr(v, 'item') else str(v)))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('scenarios', nargs='*', default=['rest', 'carry', 'place', 'push', 'collide', 'relay', 'dial', 'timing'])
    parser.add_argument('--cases', nargs='*'); parser.add_argument('--workers', type=int, default=os.cpu_count())
    args = parser.parse_args(argv)
    os.environ.setdefault('OMP_NUM_THREADS', '1')
    work = jobs(set(args.scenarios), set(args.cases or []))
    with ProcessPoolExecutor(args.workers) as pool:
        results = []
        for result in pool.map(run, work):
            results.append(result); print(json.dumps(result), flush=True)
    out = ROOT/'runs/engineering/validate-physics'/(time.strftime('%Y%m%d-%H%M%S')+'.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(results=results, passed=all(r['passed'] for r in results)), indent=1)+'\n')
    failed = [r for r in results if not r['passed']]
    print(f'{len(results)-len(failed)} of {len(results)} passed; {out}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
