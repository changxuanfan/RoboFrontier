"""The built hall: the shell and all 36 desks as one set of still shapes.

`build_hall` writes the folder that runs load (`benchmark/hall/built`, shipped in the asset
archive): `hall.xml`, the texture and mesh files it names, and `hall.json`. Every shape sits
directly in the world, takes no part in collisions and keeps its name, so a run can leave out
the desk it simulates itself (`roboteam.sim.hall.world`).
"""

import hashlib
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

from roboteam.io import ROOT
from roboteam.sim.robot_control import matrix_quat, quat_matrix

BUILT = ROOT / 'benchmark/hall/built'
HALL_GROUP = 4  # geom group of every hall shape; MuJoCo draws groups 0-2 unless told otherwise
# Structures above the desks would shade them and block the top cameras: they are left out.
OVERHEAD = ('roof', 'ventilation', 'conduit', 'lighting', 'tray', 'ceiling', 'crane', 'duct', 'lamp')
OVERHEAD_FROM_M = 4.4
KEY_LIGHT = 'factory_daylight'
KEY_DIRECTION = (0.17, 0.12, -0.978)
SIMPLIFY_CELL_M = 0.01
SIMPLIFY_FROM_FACES = 1000
KEY, FILL = 0.62, 0.10  # key light strength; factor on the ceiling fill lights


def _vec(values):
    return ' '.join(repr(float(x)) for x in np.asarray(values).ravel())


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _materials(root):
    """Floor and bench colours as the hall was designed, which the generated scene file states darker."""
    for material in root.iter('material'):
        name = material.get('name', '')
        if not material.get('rgba'):
            continue
        rgba = np.array([float(x) for x in material.get('rgba').split()])
        if name.startswith('factory_zone_floor'):
            rgba[:3] = 0.27 * rgba[:3] + 0.73 * np.array([0.90, 0.92, 0.94])
        elif name == 'factory_floor':
            rgba[:3] = np.clip(rgba[:3] * 1.22, 0, 1)
        elif name == 'factory_bench_wood':
            rgba[:3] = np.clip(rgba[:3] * np.array([2.2, 2.8, 4.0]), 0, 1)
        material.set('rgba', _vec(rgba))
        material.attrib.pop('reflectance', None)


def _lights(world, lights):
    """One key light that casts the shadows and the weak ceiling fills."""
    for light in lights:
        if light.get('type') == 'image':
            continue
        entry = {k: v for k, v in light.attrib.items() if k in ('name', 'type', 'pos', 'dir', 'diffuse')}
        diffuse = np.array([float(x) for x in light.get('diffuse', '1 1 1').split()])
        if light.get('name') == KEY_LIGHT:
            entry.update(
                dir=_vec(KEY_DIRECTION), diffuse=_vec([KEY, KEY * 0.98, KEY * 0.94]), castshadow='true'
            )
        else:
            entry.update(diffuse=_vec(diffuse * FILL), castshadow='false')
        entry['specular'] = '0 0 0'
        ET.SubElement(world, 'light', **entry)


def _simplified(vertices, faces):
    """A mesh with its vertices merged on a grid of SIMPLIFY_CELL_M, or None when that saves little.

    The arms on the other 35 desks are background: at full detail they are 44 million
    triangles, which an image looking across the hall would spend most of its time on."""
    cells, index = np.unique(
        np.floor(vertices / SIMPLIFY_CELL_M).astype(np.int64), axis=0, return_inverse=True
    )
    index = index.reshape(-1)
    merged = np.zeros((len(cells), 3))
    np.add.at(merged, index, vertices)
    merged /= np.bincount(index)[:, None]
    triangles = index[faces]
    triangles = triangles[
        (triangles[:, 0] != triangles[:, 1])
        & (triangles[:, 1] != triangles[:, 2])
        & (triangles[:, 0] != triangles[:, 2])
    ]
    # The same triangle may now appear more than once; keep one of each, with its winding.
    _, first = np.unique(np.sort(triangles, axis=1), axis=0, return_index=True)
    triangles = triangles[np.sort(first)]
    if len(triangles) > 0.6 * len(faces) or len(triangles) < 4:
        return None
    return merged, triangles


def _simplify_meshes(model, asset, output):
    """Replace every large untextured mesh by a simplified file in the compiled mesh's own frame.

    Returns the names of the replaced meshes: a geom of one is placed by its compiled pose."""
    replaced = set()
    for element in asset.findall('mesh'):
        mesh = model.mesh(element.get('name')).id
        count = int(model.mesh_facenum[mesh])
        if count < SIMPLIFY_FROM_FACES or model.mesh_texcoordnum[mesh]:
            continue
        start, vertices = int(model.mesh_vertadr[mesh]), int(model.mesh_vertnum[mesh])
        faces = model.mesh_face[int(model.mesh_faceadr[mesh]) : int(model.mesh_faceadr[mesh]) + count]
        result = _simplified(model.mesh_vert[start : start + vertices].astype(float), faces)
        if result is None:
            continue
        points, triangles = result
        text = ''.join('v %.6f %.6f %.6f\n' % tuple(p) for p in points) + ''.join(
            'f %d %d %d\n' % tuple(t + 1) for t in triangles
        )
        target = Path('files') / (hashlib.sha256(text.encode()).hexdigest()[:16] + '.obj')
        (output / target).parent.mkdir(parents=True, exist_ok=True)
        (output / target).write_text(text)
        for key in list(element.attrib):
            if key != 'name':
                del element.attrib[key]
        element.set('file', target.as_posix())
        replaced.add(element.get('name'))
    return replaced


def flatten(scene, output):
    """Write `scene` as `output`/hall.xml with every shape in the world body; returns the shape count."""
    scene, output = Path(scene), Path(output)
    model = mujoco.MjModel.from_xml_path(str(scene))
    data = mujoco.MjData(model)
    mujoco.mj_kinematics(model, data)
    root = ET.parse(scene).getroot()
    world = root.find('worldbody')
    lights = [e for e in world if e.tag == 'light']
    for element in list(world):
        world.remove(element)
    # Step options, defaults and view settings belong to the task scene the hall is attached to.
    for tag in ('default', 'option', 'visual', 'statistic'):
        if root.find(tag) is not None:
            root.remove(root.find(tag))
    _materials(root)
    types = {int(v): str(k).split('_')[-1].lower() for k, v in mujoco.mjtGeom.__members__.items()}
    output.mkdir(parents=True, exist_ok=True)
    simplified = _simplify_meshes(model, root.find('asset'), output)
    kept, used_materials, used_meshes = [], set(), set()
    for g in range(model.ngeom):
        name = model.geom(g).name
        owner = name + ' ' + model.body(int(model.geom_bodyid[g])).name
        if '__' not in name and (
            any(word in owner for word in OVERHEAD)
            or (data.geom_xpos[g, 2] > OVERHEAD_FROM_M and 'wall' not in owner and 'column' not in owner)
        ):
            continue
        kind = int(model.geom_type[g])
        rotation = data.geom_xmat[g].reshape(3, 3)
        position = data.geom_xpos[g]
        entry = dict(
            type=types[kind],
            rgba=_vec(model.geom_rgba[g]),
            group=str(HALL_GROUP),
            contype='0',
            conaffinity='0',
            mass='0',
        )
        if name:
            entry['name'] = name
        if kind == mujoco.mjtGeom.mjGEOM_MESH:
            # A compiled mesh is re-centred; the file's own frame is what the scene file places.
            mesh = int(model.geom_dataid[g])
            entry['mesh'] = model.mesh(mesh).name
            if entry['mesh'] not in simplified:
                rotation = rotation @ quat_matrix(model.mesh_quat[mesh]).T
                position = position - rotation @ model.mesh_pos[mesh]
            used_meshes.add(entry['mesh'])
        else:
            entry['size'] = _vec(model.geom_size[g])
        if model.geom_matid[g] >= 0:
            entry['material'] = model.mat(int(model.geom_matid[g])).name
            used_materials.add(entry['material'])
        entry.update(pos=_vec(position), quat=_vec(matrix_quat(rotation)))
        ET.SubElement(world, 'geom', **entry)
        kept.append(g)
    _lights(world, lights)
    # Only the assets the kept shapes use, and only the files those name.
    asset = root.find('asset')
    used_textures = set()
    for element in list(asset):
        if element.tag == 'mesh' and element.get('name') not in used_meshes:
            asset.remove(element)
        elif element.tag == 'material':
            if element.get('name') not in used_materials:
                asset.remove(element)
                continue
            used_textures.update(
                [element.get('texture')]
                + [layer.get('texture') for layer in element.findall('layer') if layer.get('role') == 'rgb']
            )
            for layer in element.findall('layer'):
                if layer.get('role') != 'rgb':  # MuJoCo's own renderer draws the colour layer only
                    element.remove(layer)
    for element in list(asset):
        if element.tag == 'texture' and element.get('name') not in used_textures:
            asset.remove(element)
    files = {}
    for element in asset:
        if element.get('file'):
            if element.get('name') in simplified and element.tag == 'mesh':
                files[element.get('file')] = _sha256(output / element.get('file'))
                continue
            source = scene.parent / element.get('file')
            target = Path('files') / (_sha256(source)[:16] + source.suffix)
            (output / target).parent.mkdir(exist_ok=True)
            if not (output / target).exists():
                shutil.copyfile(source, output / target)
            element.set('file', target.as_posix())
            files[target.as_posix()] = _sha256(output / target)
    ET.indent(root)
    (output / 'hall.xml').write_text(ET.tostring(root, encoding='unicode') + '\n')
    flat = mujoco.MjModel.from_xml_path(str(output / 'hall.xml'))
    flat_data = mujoco.MjData(flat)
    mujoco.mj_kinematics(flat, flat_data)
    if flat.nbody != 1 or flat.ngeom != len(kept):
        raise ValueError('The flat hall lost or gained shapes')
    # A simplified mesh has its own centre, so its geom is compared by where its vertices lie instead.
    exact = np.array(
        [
            not (
                model.geom_type[g] == mujoco.mjtGeom.mjGEOM_MESH
                and model.mesh(int(model.geom_dataid[g])).name in simplified
            )
            for g in kept
        ]
    )
    kept = np.array(kept)
    for name, ours, theirs in (
        ('position', flat_data.geom_xpos[exact], data.geom_xpos[kept[exact]]),
        ('rotation', flat_data.geom_xmat[exact], data.geom_xmat[kept[exact]]),
        ('size', flat.geom_size[exact], model.geom_size[kept[exact]]),
        ('colour', flat.geom_rgba, model.geom_rgba[kept]),
        ('type', flat.geom_type, model.geom_type[kept]),
    ):
        if np.abs(np.asarray(ours, float) - np.asarray(theirs, float)).max() > 1e-9:
            raise ValueError('The flat hall differs from the composed hall in ' + name)
    for ours, theirs in zip(np.flatnonzero(~exact), kept[~exact]):
        centre = [
            d.geom_xpos[g] + d.geom_xmat[g].reshape(3, 3) @ m.geom_aabb[g, :3]
            for m, d, g in ((flat, flat_data, ours), (model, data, theirs))
        ]
        if np.abs(centre[0] - centre[1]).max() > 2 * SIMPLIFY_CELL_M:
            raise ValueError('A simplified mesh moved: ' + flat.geom(ours).name)
    return files


def build_hall(output=BUILT):
    """Generate the shell, place the 36 released desks in it and write the flat hall."""
    from roboteam.sim.hall.build import build_factory
    from roboteam.sim.hall.desks import compose

    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        shell, _ = build_factory(output=scratch / 'shell')
        release = json.loads((ROOT / 'benchmark/release.json').read_text())
        cases = []
        for task_type in release['task_types']:
            cases += json.loads((ROOT / 'benchmark' / task_type / 'catalog.json').read_text())['cases']
        catalog = scratch / 'catalog.json'
        catalog.write_text(json.dumps({'cases': cases}))
        composed = compose(shell, catalog, scratch / 'hall')
        files = flatten(composed, output)
        manifest = json.loads((composed.parent / 'manifest.json').read_text())
    hall = dict(
        schema='roboteam.hall.v1',
        hall_sha256=_sha256(output / 'hall.xml'),
        files=files,
        desks={
            place['case_id']: dict(
                translation_m=place['translation_m'],
                yaw_rad=place['yaw_rad'],
                scene_sha256=manifest['workstation_names'][place['case_id']]['source_scene_sha256'],
            )
            for place in manifest['placements']
        },
    )
    (output / 'hall.json').write_text(json.dumps(hall, indent=2) + '\n')
    return hall
