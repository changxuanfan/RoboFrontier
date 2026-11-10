"""Test-only scene: one Panda (robot B at y=0) on a 0.4 m table with small cubes.

It carries the release physics (scripts/build_release.py) and steps as a Transport world.

It is the scene the removed three-arm generated task built, reduced to one arm, and
written as a scene folder with an `initial` keyframe so `World` loads it the way it
loads a released scene. Hand, grasp and contact regressions keep their geometry.
"""
import copy
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

import mujoco
import numpy as np

from robofrontier.runtime.pipeline import World
from robofrontier.physics.robot_control import PandaArm
from robofrontier.io import ROOT, vector

TABLE_HEIGHT_M = .4
CUBE_HALF_M = .02
CUBE_MASS_KG = .05
FRICTION = (1., .005, .0001)
ARM = 'B'


def _camera(world, name, position, target, fovy):
    z = np.array(position, dtype=float)-np.array(target)
    z /= np.linalg.norm(z)
    x = np.cross([0, 0, 1], z); x /= np.linalg.norm(x)
    y = np.cross(z, x)
    ET.SubElement(world, 'camera', name=name, pos=vector(position), xyaxes=vector([*x, *y]), fovy=str(fovy))


def scene_xml(cubes, noslip_iterations=10):
    """MJCF for robot B at y=0 and one cube per position, before its keyframe."""
    root = ET.parse(ROOT/'vendor/panda/panda.xml').getroot()
    root.set('model', 'RoboFrontier single-arm test scene')
    root.find('compiler').set('meshdir', 'model-assets')
    root.remove(root.find('keyframe'))
    root.find('option').attrib.update(timestep='.002', gravity='0 0 -9.81', integrator='implicitfast',
                                      solver='Newton', iterations='100', noslip_iterations=str(noslip_iterations))
    visual = ET.SubElement(root, 'visual')
    ET.SubElement(visual, 'global', offwidth='1280', offheight='800')
    world = root.find('worldbody')
    original = copy.deepcopy(world.find('body'))
    world.clear()
    sections = {}
    for tag in ('tendon', 'equality', 'actuator', 'contact'):
        section = root.find(tag)
        sections[tag] = list(copy.deepcopy(section))
        section.clear()
    named = {e.get('name') for e in original.iter() if e.get('name')}
    for children in sections.values():
        named.update(e.get('name') for child in children for e in child.iter() if e.get('name'))

    def renamed(element):
        element = copy.deepcopy(element)
        for e in element.iter():
            for key, value in list(e.attrib.items()):
                if (key == 'name' or key in ('joint', 'joint1', 'joint2', 'tendon', 'body1', 'body2')) and value in named:
                    e.set(key, ARM+'_'+value)
        return element
    body = renamed(original); body.set('pos', vector([0, 0, TABLE_HEIGHT_M]))
    for suffix in ('finger_joint1', 'finger_joint2'):
        joint = body.find(f".//joint[@name='{ARM}_{suffix}']")
        joint.set('solreflimit', '0.004 1')
        joint.set('solimplimit', '0.99 0.999 0.0001 0.5 2')
    hand = body.find(f".//body[@name='{ARM}_hand']")
    ET.SubElement(hand, 'site', name=ARM+'_tcp', pos='0 0 .1029', size='.004', rgba='1 .8 0 1')
    world.append(body)
    for tag, children in sections.items():
        for child in children: root.find(tag).append(renamed(child))
    ET.SubElement(world, 'light', pos='.2 0 3', dir='0 0 -1', diffuse='.85 .85 .85')
    ET.SubElement(world, 'geom', name='floor', type='plane', size='4 4 .1', rgba='.13 .16 .20 1')
    ET.SubElement(world, 'geom', name='table', type='box', pos=vector([.30, 0, TABLE_HEIGHT_M-.025]),
                  size=vector([.52, .47, .025]), rgba='.45 .36 .27 1', friction=vector(FRICTION), condim='4')
    for name, position in cubes.items():
        cube = ET.SubElement(world, 'body', name=name, pos=vector(position))
        ET.SubElement(cube, 'freejoint', name=name+'_free')
        ET.SubElement(cube, 'geom', name=name+'_geom', type='box', size=vector([CUBE_HALF_M]*3), mass=str(CUBE_MASS_KG),
                      friction=vector(FRICTION), condim='4', rgba='.08 .7 .2 1')
    _camera(world, 'B_front', [1.35, 0, 1.3], [.40, 0, .46], 45)
    _camera(world, 'global', [2.3, 0, 2.65], [.25, 0, .5], 51)
    return root


def make_world(directory, cubes=None, harness=None, noslip_iterations=10):
    """A World over the fixture scene in `directory`; `harness` is frozen as its harness.json.

    The arm starts at its home reference and settles for one second, as the generated
    task did, and that settled state becomes the `initial` keyframe."""
    cubes = {'cube': [.42, 0., .42]} if cubes is None else cubes
    directory = Path(directory)
    folder = directory/'private/inputs/scene'
    if folder.exists(): shutil.rmtree(folder)  # A test may build several worlds in one folder.
    folder.mkdir(parents=True)
    (folder/'model-assets').symlink_to(ROOT/'vendor/panda/assets', target_is_directory=True)
    root = scene_xml(cubes, noslip_iterations)
    root.find('compiler').set('meshdir', str(folder/'model-assets'))
    from scripts.build_release import apply_release_physics
    apply_release_physics(root, mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode')))
    model = mujoco.MjModel.from_xml_string(ET.tostring(root, encoding='unicode'))
    data = mujoco.MjData(model)
    PandaArm(model, data, ARM, [.40, 0., .68])
    mujoco.mj_forward(model, data)
    for _ in range(500): mujoco.mj_step(model, data)
    root.find('compiler').set('meshdir', 'model-assets')
    keyframe = ET.SubElement(root, 'keyframe')
    ET.SubElement(keyframe, 'key', name='initial', qpos=vector(data.qpos), ctrl=vector(data.ctrl))
    (folder/'scene.xml').write_text(ET.tostring(root, encoding='unicode'))
    if harness is not None:
        (directory/'private/inputs/harness.json').write_text(json.dumps(harness))
    task = {'kind': 'single_arm_test_scene', 'family': 'transport', 'scene_asset': 'private/inputs/scene/scene.xml', 'arms': {ARM: {}},
            'objects': [{'id': name} for name in cubes]}
    return World(directory, task)
