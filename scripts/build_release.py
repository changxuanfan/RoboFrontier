"""Write the benchmark release: one conversion of the released scenes to their final form.

The release is frozen after this runs; nothing at run time rebuilds or patches it.
Each step changes the files under benchmark/<family>/<case>/ in place and is safe to
run again on its own output.

    python -m scripts.build_release physics   # contact and solver settings into every scene.xml
    python -m scripts.build_release check     # the scenes already carry them

See docs/physics.md for the values and where they come from.
"""
import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT/'benchmark'
FAMILIES = ('transport', 'mosaic', 'relay', 'dial')

# Solver options every scene carries (docs/physics.md). The rest of <option> stays as built:
# implicitfast, 2 ms steps, Newton with 100 iterations.
OPTION = {'cone': 'elliptic', 'impratio': '1', 'noslip_iterations': '10', 'noslip_tolerance': '1e-9'}
# One contact stiffness for every collision geom: the stiffest that is stable at 2 ms steps
# (time constant 2 x timestep, critical damping). Rigid parts then sink in by micrometres.
SOLREF = '0.004 1'
SOLIMP = '0.95 0.99 0.001 0.5 2'
# Sliding friction: rubber finger pads 0.8, every other surface 0.4. Torsional and rolling
# friction stay at their small values; round loose parts roll a little and stop.
FINGER_FRICTION = (.8, .005, .0001)
SURFACE_FRICTION = (.4, .005, .0001)
DIAL_MODULE_ROLLING = .03       # a module disk leans on its rim and needs this to stop
ROUND_ROLLING_PER_RADIUS = .1   # loose cylinders and spheres

# The hand's tendon actuator passes half its force to each finger; a grasp may press each
# finger with up to 140 N (physics/franka_limits.py), so the actuator reaches 280 N.
HAND_ACTUATOR = re.compile(r'[A-Z]_actuator8')
HAND_FORCE_RANGE = '-280 280'
MODULE = re.compile(r'_module_(disk|stem)$')
ROBOT_JOINT = re.compile(r'[A-Z]_(joint[1-7]|finger_joint[12])')


def cases():
    return [path.parent for family in FAMILIES for path in sorted((BENCHMARK/family).glob('*/scene.xml'))]


def compile_scene(folder, xml=None):
    """The scene as MuJoCo compiles it, with asset paths resolved against its folder."""
    root = ET.fromstring(xml) if xml is not None else ET.parse(folder/'scene.xml').getroot()
    compiler = root.find('compiler')
    compiler.set('meshdir', str((folder/compiler.get('meshdir', '')).resolve()))
    for texture in root.findall('asset/texture'):
        if texture.get('file'): texture.set('file', str(folder/texture.get('file')))
    return mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))


def geom_elements(root):
    """XML <geom> elements in compiled geom order: world geoms, then each body's own
    geoms with bodies in depth-first order, which is how MuJoCo numbers them."""
    world = root.find('worldbody')
    ordered = list(world.findall('geom'))
    def visit(body):
        ordered.extend(body.findall('geom'))
        for child in body.findall('body'): visit(child)
    for body in world.findall('body'): visit(body)
    return ordered


def contact_parameters(model):
    """Per collision geom: (friction, condim, priority), from what the geom is and where."""
    robot = set()  # bodies a robot joint moves, and the mounts that carry them
    for j in range(model.njnt):
        if ROBOT_JOINT.fullmatch(model.joint(j).name or ''):
            b = int(model.jnt_bodyid[j])
            while b: robot.add(b); b = int(model.body_parentid[b])
    free = {int(model.jnt_bodyid[j]) for j in range(model.njnt) if int(model.jnt_type[j]) == int(mujoco.mjtJoint.mjJNT_FREE)}
    round_types = (int(mujoco.mjtGeom.mjGEOM_CYLINDER), int(mujoco.mjtGeom.mjGEOM_SPHERE))
    result = {}
    for g in range(model.ngeom):
        if not model.geom_contype[g] | model.geom_conaffinity[g]: continue
        body = int(model.geom_bodyid[g]); static = True; on_robot = False
        b = body
        while b:
            if b in robot: on_robot = True
            if model.body_jntnum[b]: static = False
            b = int(model.body_parentid[b])
        condim = int(model.geom_condim[g]); friction = SURFACE_FRICTION; priority = 0
        if on_robot and 'finger' in (model.body(body).name or ''):
            friction, condim, priority = FINGER_FRICTION, 4, 1
        elif on_robot:
            pass
        elif MODULE.search(model.geom(g).name or ''):
            friction, condim = (*SURFACE_FRICTION[:2], DIAL_MODULE_ROLLING), 6
        elif static:
            condim = max(condim, 4)
        elif body in free and int(model.geom_type[g]) in round_types:
            friction, condim = (*SURFACE_FRICTION[:2], ROUND_ROLLING_PER_RADIUS*float(model.geom_size[g, 0])), 6
        else:
            condim = 4
        result[g] = (friction, condim, priority)
    return result


def number(value):
    return repr(float(value))  # shortest text that reads back as the same double


def apply_release_physics(root, model, label='scene'):
    """Write the release solver options, contact parameters and hand force range into an
    MJCF tree; `model` is that tree compiled."""
    elements = geom_elements(root)
    if len(elements) != model.ngeom:
        raise ValueError(f'{label}: {len(elements)} <geom> elements for {model.ngeom} compiled geoms')
    for g, element in enumerate(elements):
        if element.get('name', '') != (model.geom(g).name or ''):
            raise ValueError(f'{label}: geom {g} order differs from the XML')
    option = root.find('option')
    for key, value in OPTION.items(): option.set(key, value)
    for g, (friction, condim, priority) in contact_parameters(model).items():
        element = elements[g]
        element.set('friction', ' '.join(number(v) for v in friction))
        element.set('condim', str(condim))
        element.set('solref', SOLREF); element.set('solimp', SOLIMP)
        if priority: element.set('priority', str(priority))
        elif 'priority' in element.attrib: del element.attrib['priority']
    for actuator in root.find('actuator'):
        if HAND_ACTUATOR.fullmatch(actuator.get('name', '')): actuator.set('forcerange', HAND_FORCE_RANGE)
    return root


def bake_physics(folder):
    """scene.xml with the release's solver options and contact parameters written in."""
    root = ET.fromstring((folder/'scene.xml').read_text())
    apply_release_physics(root, compile_scene(folder), folder.name)
    ET.indent(root, '  ')
    return ET.tostring(root, encoding='unicode')+'\n'


def expected_contacts(model):
    """The release contact values applied to a compiled model in memory."""
    params = contact_parameters(model)
    friction = model.geom_friction.copy(); condim = model.geom_condim.copy(); priority = model.geom_priority.copy()
    solref = model.geom_solref.copy(); solimp = model.geom_solimp.copy()
    for g, (f, c, p) in params.items():
        friction[g] = f; condim[g] = c; priority[g] = p
        solref[g] = [float(v) for v in SOLREF.split()]; solimp[g] = [float(v) for v in SOLIMP.split()]
    return dict(geom_friction=friction, geom_condim=condim, geom_priority=priority, geom_solref=solref, geom_solimp=solimp)


def check_physics(folder):
    """Problems with a scene's baked physics; empty when it carries the release values."""
    model = compile_scene(folder)
    problems = []
    if model.opt.cone != mujoco.mjtCone.mjCONE_ELLIPTIC: problems.append('cone')
    if model.opt.impratio != 1. or model.opt.noslip_iterations != 10 or model.opt.noslip_tolerance != 1e-9:
        problems.append('solver options')
    hands = [a for a in range(model.nu) if HAND_ACTUATOR.fullmatch(model.actuator(a).name or '')]
    if not hands or any(list(model.actuator_forcerange[a]) != [-280., 280.] for a in hands): problems.append('hand actuator force')
    for name, values in expected_contacts(model).items():
        if not np.array_equal(getattr(model, name), values): problems.append(name)
    return problems


def write_if_changed(path, text):
    if path.read_text() != text: path.write_text(text); return True
    return False


def file_sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def replace_hashes(folder, replaced):
    """Rewrite the case files that record a changed file's hash, until none is stale
    (a rewritten task.json changes its own hash in turn)."""
    files = sorted(folder.glob('*.json'))
    replaced = dict(replaced)
    while replaced:
        changes = {}
        for path in files:
            text = path.read_text(); new = text
            for old, value in replaced.items(): new = new.replace(old, value)
            if new != text:
                before = file_sha256(path); path.write_text(new); changes[before] = file_sha256(path)
        replaced = changes


def index_release():
    """Record each released case's current file hashes in its release.json policy entry."""
    path = BENCHMARK/'release.json'
    release = json.loads(path.read_text())
    for family in release['families'].values():
        for case in family['gpt']:
            folder = ROOT/case['directory']
            case['source_files'] = {name: file_sha256(folder/name) for name in case['source_files']}
            projection = case.get('public_projection')
            if projection: projection['sha256'] = file_sha256(ROOT/projection['path'])
    path.write_text(json.dumps(release, indent=2, ensure_ascii=False)+'\n')


def physics(args):
    changed = 0
    for folder in cases():
        before = file_sha256(folder/'scene.xml')
        if write_if_changed(folder/'scene.xml', bake_physics(folder)):
            changed += 1
            replace_hashes(folder, {before: file_sha256(folder/'scene.xml')})
        problems = check_physics(folder)
        if problems: raise SystemExit(f'{folder.name}: {problems}')
    index_release()
    pin_asset_release()
    print(f'{changed} of {len(cases())} scenes rewritten')


def pin_asset_release():
    """The scene assets (meshes, label images) are unchanged, so the pinned asset archive
    still serves this release; record which release it now serves."""
    path = ROOT/'configs/policy-assets.json'
    config = json.loads(path.read_text()); config['release_sha256'] = file_sha256(BENCHMARK/'release.json')
    path.write_text(json.dumps(config, indent=2)+'\n')


def check(args):
    bad = {folder.name: p for folder in cases() if (p := check_physics(folder))}
    print(json.dumps(bad or 'all scenes carry the release physics', indent=1))
    return 1 if bad else 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='step', required=True)
    sub.add_parser('physics').set_defaults(run=physics)
    sub.add_parser('check').set_defaults(run=check)
    args = parser.parse_args(argv)
    return args.run(args) or 0


if __name__ == '__main__':
    sys.exit(main())
