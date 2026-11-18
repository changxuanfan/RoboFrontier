"""Compose the released workstations into the factory hall, as visual geometry only.

The composed scene has no task joints or contacts.
"""

import hashlib
import json
import math
import re
import shutil
import xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from roboteam.runtime.run.setup import write_json
from roboteam.sim.hall.labels import place_label, region_title
from roboteam.sim.robot_control import matrix_quat, quat_matrix
from roboteam.sim.workstation import Workstation


def colour_compatible_signature(source):
    """Strict scene identity apart from visual RGBA; hash all local assets too."""
    path = Path(source.path)
    tree = ET.parse(path / 'scene.xml')
    for geom in tree.iter('geom'):
        if source.manifest['case']['family'] == 'mosaic' and re.fullmatch(
            r'[A-Z]_stock[0-9]+_geom', geom.get('name', '')
        ):
            geom.attrib.pop('rgba', None)
    h = hashlib.sha256(ET.tostring(tree.getroot(), encoding='utf-8'))
    assets = path / 'assets'
    if assets.exists():
        for item in sorted(assets.rglob('*')):
            if item.is_symlink():
                raise ValueError('Symlinked scene asset not supported')
            if item.is_file():
                h.update(str(item.relative_to(path)).encode())
                h.update(hashlib.sha256(item.read_bytes()).digest())
    return h.hexdigest()


def vec(values):
    return ' '.join(repr(float(x)) for x in np.asarray(values).ravel())


def placements(catalog, regions, root, aisle=1.2, source_overrides=None):
    """Size-aware 3x3 shelves; physical hardware is never scaled."""
    result = []
    for region in regions:
        task_type = region['id']
        entries = []
        gap = float(region.get('workstation_gap_m', aisle))
        for case in catalog['cases']:
            if case['family'] != task_type:
                continue
            source = Workstation((source_overrides or {}).get(case['id'], root / case['directory']))
            m, d = source.model, source.data
            source.frame()
            corners = []
            table_corners = []
            for g in range(m.ngeom):
                name = m.geom(g).name
                if int(m.geom_type[g]) == mujoco.mjtGeom.mjGEOM_PLANE or name.startswith(('sky', 'floor')):
                    continue
                box = m.geom_aabb[g]
                r = d.geom_xmat[g].reshape(3, 3)
                center = d.geom_xpos[g] + r @ box[:3]
                half = abs(r) @ box[3:]
                if name.startswith('table_') and 'leg' not in name:
                    table_corners.extend((center[:2] - half[:2], center[:2] + half[:2]))
                if not (m.geom_contype[g] or m.geom_conaffinity[g]):
                    continue
                corners.extend((center[:2] - half[:2], center[:2] + half[:2]))
            bases = np.asarray(
                [b['position_parent_m'][:2] for b in source.manifest['bodies'] if b['id'].endswith('_link0')]
            )
            low = np.minimum(np.min(corners, axis=0), bases.min(axis=0) - 1.0)
            high = np.maximum(np.max(corners, axis=0), bases.max(axis=0) + 1.0)
            if not table_corners:
                raise ValueError('No tabletop geometry: ' + case['id'])
            table = np.asarray(table_corners)
            entries.append(
                dict(
                    case=case,
                    low=low,
                    high=high,
                    size=high - low,
                    table_low=table.min(axis=0),
                    table_high=table.max(axis=0),
                )
            )
        if not entries:
            continue
        scales = sorted({e['case'].get('dials', e['case']['arms']) for e in entries})

        def cell(row, col):
            # Rows are built from -Y to +Y; the top camera looks with +Y up.
            level, scale = 3 - row, scales[col]
            return next(
                e
                for e in entries
                if e['case']['level'] == level and e['case'].get('dials', e['case']['arms']) == scale
            )

        grid = [[cell(row, col) for col in range(3)] for row in range(3)]
        widths = [max(grid[r][c]['size'][0] for r in range(3)) for c in range(3)]
        heights = [max(grid[r][c]['size'][1] for c in range(3)) for r in range(3)]
        x0, y0, x1, y1 = region['bounds_xy_m']
        total = np.array([sum(widths) + 2 * gap, sum(heights) + 2 * gap])
        origin = (np.array([x0 + x1, y0 + y1]) - total) / 2
        origin[1] += float(region.get('workstation_offset_y_m', 0.0))
        if np.any(origin < np.array([x0, y0]) + 0.6):
            raise ValueError('Region too small: ' + task_type)
        for row in range(3):
            for col in range(3):
                e = grid[row][col]
                center = origin + [
                    sum(widths[:col]) + col * gap + widths[col] / 2,
                    sum(heights[:row]) + row * gap + heights[row] / 2,
                ]
                shift = center - (e['low'] + e['high']) / 2
                case = e['case']
                result.append(
                    dict(
                        case_id=case['id'],
                        task_type=task_type,
                        source_directory=case['directory'],
                        translation_m=[*shift, 0.0],
                        yaw_rad=0.0,
                        scale=1.0,
                        planning_bounds_xy_m=[*(e['low'] + shift), *(e['high'] + shift)],
                        table_bounds_xy_m=[*(e['table_low'] + shift), *(e['table_high'] + shift)],
                        inter_cell_gap_m=gap,
                        planning_scope='Initial physical bounds plus indicative 1m base radius; actual carried-motion swept bounds remain to be checked',
                    )
                )
    return result


class Assets:
    def __init__(self, asset, folder):
        self.asset = asset
        self.folder = folder
        self.signatures = {}
        self.counter = 0

    def import_source(self, source):
        xml = ET.parse(source.path / 'scene.xml').getroot()
        compiler = xml.find('compiler')
        mapping = {}
        for original in sorted(xml.findall('asset/*'), key=lambda e: e.tag == 'material'):
            if original.tag == 'texture' and original.get('type') == 'skybox':
                continue
            e = deepcopy(original)
            old = e.attrib.pop('name', None)
            e.attrib.pop('class', None)
            if e.tag == 'material':
                mid = source.model.mat(old).id
                for key, field in [
                    ('rgba', 'mat_rgba'),
                    ('specular', 'mat_specular'),
                    ('shininess', 'mat_shininess'),
                    ('reflectance', 'mat_reflectance'),
                    ('emission', 'mat_emission'),
                ]:
                    e.set(key, vec(np.atleast_1d(getattr(source.model, field)[mid])))
            for key in ('texture', 'material', 'mesh'):
                if e.get(key) in mapping:
                    e.set(key, mapping[e.get(key)])
            if e.get('file'):
                prefix = (
                    compiler.get('meshdir', '')
                    if e.tag == 'mesh'
                    else compiler.get('texturedir', '')
                    if e.tag == 'texture'
                    else ''
                )
                path = (source.path / prefix / e.get('file')).resolve()
                checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                target = self.folder / 'workstation-assets' / (checksum + path.suffix)
                target.parent.mkdir(exist_ok=True)
                if not target.exists():
                    shutil.copyfile(path, target)
                e.set('file', str(target.relative_to(self.folder)))
            signature = (
                e.tag,
                tuple(sorted(e.attrib.items())),
                ET.tostring(e, encoding='unicode') if len(e) else '',
            )
            if signature not in self.signatures:
                name = f'ws_asset_{self.counter}'
                self.counter += 1
                e.set('name', name)
                self.asset.append(e)
                self.signatures[signature] = name
            if old:
                mapping[old] = self.signatures[signature]
        return mapping


def compose(
    shell,
    catalog_path,
    output,
    table_opening_scale=None,
    source_overrides=None,
    source_root=None,
    placement_overrides=None,
):
    shell = Path(shell).resolve()
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    root_dir = Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[3]
    catalog = json.loads(Path(catalog_path).read_text())
    shell_manifest = json.loads((shell.parent / 'manifest.json').read_text())
    plan = placements(catalog, shell_manifest['regions'], root_dir, source_overrides=source_overrides)
    overrides = placement_overrides or {}
    if set(overrides) - {p['case_id'] for p in plan}:
        raise ValueError('Unknown workstation placement override')
    for place in plan:
        if place['case_id'] not in overrides:
            continue
        values = overrides[place['case_id']]
        if set(values) - {'translation_m', 'yaw_rad'}:
            raise ValueError('Only rigid translation/yaw may change')
        shift = np.asarray(values.get('translation_m', place['translation_m']), float)
        yaw = float(values.get('yaw_rad', place['yaw_rad']))
        if shift.shape != (3,) or not np.isfinite(shift).all() or not np.isfinite(yaw):
            raise ValueError('Invalid rigid placement')
        # Placement bounds describe source XY footprints, never a scale change.
        a, b, c, d = place['planning_bounds_xy_m']
        old = np.asarray(place['translation_m'])
        corners = np.array([[x, y, 0.0] for x in (a, c) for y in (b, d)]) - old
        angle = yaw - place['yaw_rad']
        co, si = math.cos(angle), math.sin(angle)
        moved = corners @ np.array([[co, -si, 0], [si, co, 0], [0, 0, 1.0]]).T + shift
        place.update(
            translation_m=shift.tolist(),
            yaw_rad=yaw,
            planning_bounds_xy_m=[*moved[:, :2].min(axis=0), *moved[:, :2].max(axis=0)],
        )
        a, b, c, d = place['table_bounds_xy_m']
        corners = np.array([[x, y, 0.0] for x in (a, c) for y in (b, d)]) - old
        moved = corners @ np.array([[co, -si, 0], [si, co, 0], [0, 0, 1.0]]).T + shift
        place['table_bounds_xy_m'] = [*moved[:, :2].min(axis=0), *moved[:, :2].max(axis=0)]
    root = ET.parse(shell).getroot()
    shutil.copytree(shell.parent / 'assets', output / 'assets')
    if (shell.parent / 'build-config.json').exists():
        shutil.copyfile(shell.parent / 'build-config.json', output / 'build-config.json')
    option = root.find('option')
    if option is None:
        option = ET.SubElement(root, 'option')
    flag = option.find('flag')
    if flag is None:
        flag = ET.SubElement(option, 'flag')
    flag.set('contact', 'disable')
    assets = Assets(root.find('asset'), output)
    world = root.find('worldbody')
    mapping = {}
    labels = []
    # Include carts, racks and other above-floor shell geometry, not just tables.
    # Roof geometry is hidden for the inspection top view and is excluded here.
    shell_model = mujoco.MjModel.from_xml_path(str(shell))
    shell_data = mujoco.MjData(shell_model)
    mujoco.mj_kinematics(shell_model, shell_data)
    occupied = []
    for gid in range(shell_model.ngeom):
        if shell_model.geom_group[gid] == 1:
            continue
        box = shell_model.geom_aabb[gid]
        rot = shell_data.geom_xmat[gid].reshape(3, 3)
        center = shell_data.geom_xpos[gid] + rot @ box[:3]
        half = abs(rot) @ box[3:]
        if shell_model.geom_type[gid] == mujoco.mjtGeom.mjGEOM_MESH and half[0] > 3 and half[1] > 3:
            # A batched conduit mesh can surround the whole hall while leaving
            # its interior empty. Its aggregate AABB is not solid occupancy.
            mid = int(shell_model.geom_dataid[gid])
            va = shell_model.mesh_vertadr[mid]
            vn = shell_model.mesh_vertnum[mid]
            fa = shell_model.mesh_faceadr[mid]
            fn = shell_model.mesh_facenum[mid]
            vertices = shell_model.mesh_vert[va : va + vn] @ rot.T + shell_data.geom_xpos[gid]
            triangles = vertices[shell_model.mesh_face[fa : fa + fn]]
            for triangle in triangles:
                if triangle[:, 2].max() > 0.035:
                    occupied.append([*triangle[:, :2].min(axis=0), *triangle[:, :2].max(axis=0)])
            continue
        if center[2] + half[2] > 0.035:
            occupied.append([*(center[:2] - half[:2]), *(center[:2] + half[:2])])
    shell_occupied = occupied.copy()
    occupied.extend(p['planning_bounds_xy_m'] for p in plan)
    del shell_model, shell_data

    def floor_label(name, text, position, half):
        image = Image.new('RGB', (1600, 256), (245, 245, 240))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(str(root_dir / 'benchmark/hall/fonts/BarlowCondensed-SemiBold.ttf'), 150)
        draw.text((800, 128), text, font=font, anchor='mm', fill=(0, 0, 0))
        file = output / 'workstation-assets' / (name + '.png')
        file.parent.mkdir(exist_ok=True)
        image.save(file)
        ET.SubElement(root.find('asset'), 'texture', name=name, type='2d', file=str(file.relative_to(output)))
        ET.SubElement(
            root.find('asset'),
            'material',
            name=name,
            texture=name,
            texuniform='false',
            specular='0',
            roughness='.85',
        )
        ET.SubElement(
            world,
            'geom',
            name=name,
            type='box',
            pos=vec(position),
            size=vec([*half, 0.0001]),
            material=name,
            contype='0',
            conaffinity='0',
            mass='0',
        )

    types = {int(v): str(k)[7:].lower() for k, v in mujoco.mjtGeom.__members__.items()}
    # enum names are mjGEOM_BOX etc; conversion strips mjGEOM_.
    for place in plan:
        source = Workstation(
            (source_overrides or {}).get(place['case_id'], root_dir / place['source_directory'])
        )
        source.frame()
        m, d = source.model, source.data
        amap = assets.import_source(source)
        from roboteam.sim.table_presentation import scale_rectangular_opening_for_render

        if place['task_type'] == 'transport':
            item = next(c for c in catalog['cases'] if c['id'] == place['case_id'])
            scale_rectangular_opening_for_render(
                m,
                item.get('table_opening_scale', 1.0) if table_opening_scale is None else table_opening_scale,
            )
            mujoco.mj_kinematics(m, d)
        # Display only: a letter label under a robot base slides out towards the table edge.
        from roboteam.sim.hall.labels import robot_label_moves

        label_moves = robot_label_moves(m, d, avoid_objects=place['task_type'] != 'mosaic')
        t = np.asarray(place['translation_m'])
        yaw = place['yaw_rad']
        c, s = math.cos(yaw), math.sin(yaw)
        rotation = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.0]])
        prefix = place['case_id'] + '__'
        bodymap = {}
        geommap = {}
        animated = set(source.manifest['motion_recording_contract']['dynamic_bodies'])
        for bid in range(m.nbody):
            # Source cameras show groups0/1/2. Collision-only robot meshes in
            # group3 would overlap their visual skins and cause z-fighting.
            ids = [
                g
                for g in range(m.ngeom)
                if int(m.geom_bodyid[g]) == bid
                and int(m.geom_group[g]) <= 2
                and int(m.geom_type[g]) != mujoco.mjtGeom.mjGEOM_PLANE
                and not m.geom(g).name.startswith(('sky', 'floor'))
            ]
            if not ids:
                continue
            name = m.body(bid).name or 'world'
            r = np.eye(3) if not bid else d.xmat[bid].reshape(3, 3)
            p = np.zeros(3) if not bid else d.xpos[bid]
            body = ET.SubElement(
                world,
                'body',
                name=prefix + name,
                pos=vec(rotation @ p + t),
                quat=vec(matrix_quat(rotation @ r)),
            )
            if name in animated:
                body.set('mocap', 'true')
            bodymap[name] = body.get('name')
            for g in ids:
                entry = source.manifest['geometries'][g]
                local_r = quat_matrix(m.geom_quat[g])
                local_p = m.geom_pos[g].copy()
                typ = int(m.geom_type[g])
                if not bid and entry['id'] in label_moves:
                    local_p[:2] = label_moves[entry['id']]['to_xy']
                    local_r = quat_matrix(label_moves[entry['id']]['quat_wxyz'])
                kwargs = dict(
                    name=prefix + entry['id'],
                    type=types[typ],
                    size=vec(m.geom_size[g]),
                    pos=vec(local_p),
                    quat=vec(matrix_quat(local_r)),
                    rgba=vec(m.geom_rgba[g]),
                    contype='0',
                    conaffinity='0',
                    mass='0',
                    group='0',
                )
                if typ == mujoco.mjtGeom.mjGEOM_MESH:
                    mid = int(m.geom_dataid[g])
                    raw_r = local_r @ quat_matrix(m.mesh_quat[mid]).T
                    raw_p = local_p - raw_r @ m.mesh_pos[mid]
                    kwargs.update(mesh=amap[m.mesh(mid).name], pos=vec(raw_p), quat=vec(matrix_quat(raw_r)))
                if m.geom_matid[g] >= 0:
                    kwargs['material'] = amap[m.mat(int(m.geom_matid[g])).name]
                if entry['id'].startswith('table_') and 'leg' not in entry['id']:
                    if root.find("asset/material[@name='factory_bench_wood']") is not None:
                        kwargs['material'] = 'factory_bench_wood'
                ET.SubElement(body, 'geom', **kwargs)
                geommap[entry['id']] = kwargs['name']
        mapping[place['case_id']] = dict(
            body_names=bodymap,
            geom_names=geommap,
            source_scene_sha256=source.manifest['scene_sha256'],
            colour_compatible_sha256=colour_compatible_signature(source),
            robot_labels_moved=label_moves,
        )
    # Area names stay centered on their upper edge. Furniture placement must
    # reserve this space; never shift a title to work around a supply cart.
    for region in shell_manifest['regions']:
        position, half = region_title(region)
        position, box = place_label([position], half, occupied)
        floor_label('ws_region_' + region['id'], region['label'], position, half)
        occupied.append(box)
        labels.append(
            dict(
                id='ws_region_' + region['id'],
                kind='region',
                text=region['label'],
                position_m=position,
                half_size_m=half,
                bounds_xy_m=box,
            )
        )
    for place in plan:
        lowx, lowy, highx, highy = place['table_bounds_xy_m']
        cx = (lowx + highx) / 2
        half = [min(1.4, (highx - lowx) / 2 - 0.10), 0.13]
        candidates = [[cx, lowy - half[1] - gap, 0.004] for gap in (0.20, 0.30, 0.45, 0.60, 1.0)]
        # The planning envelope deliberately extends beyond the tabletop; it
        # must not force a caption far away from its own table.
        blocked = (
            shell_occupied
            + [p['planning_bounds_xy_m'] for p in plan if p is not place]
            + [x['bounds_xy_m'] for x in labels]
        )
        position, box = place_label(candidates, half, blocked)
        name = 'ws_caption_' + place['case_id']
        text = place['case_id'].upper()
        floor_label(name, text, position, half)
        occupied.append(box)
        labels.append(
            dict(id=name, kind='station', text=text, position_m=position, half_size_m=half, bounds_xy_m=box)
        )
    ET.indent(root)
    scene = output / 'scene.xml'
    ET.ElementTree(root).write(scene, encoding='unicode')
    manifest = deepcopy(shell_manifest)
    manifest.update(
        id=shell_manifest['id'] + '-workstations',
        scope=f'{len(plan)} visual workstations; recorded-state playback only; zero task dynamics',
        scene_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),
        placements=plan,
        workstation_names=mapping,
        task_workstations=len(plan),
        source_catalog=str(Path(catalog_path).resolve()),
        table_opening_linear_scale=table_opening_scale,
        source_overrides={k: str(Path(v).resolve()) for k, v in (source_overrides or {}).items()},
    )
    manifest['factory_labels'] = dict(
        clearance_m=0.10,
        scope='Conservative initial above-floor XY footprints and station planning bounds; roof excluded',
        labels=labels,
    )
    manifest['workstation_assets'] = [
        dict(
            path=str(p.relative_to(output)),
            sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            bytes=p.stat().st_size,
        )
        for p in sorted((output / 'workstation-assets').iterdir())
    ]
    write_json(output / 'manifest.json', manifest)
    return scene
