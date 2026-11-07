"""Reserve real floor space for factory wayfinding, outside equipment footprints."""
import math
import re

import mujoco
import numpy as np


def bounds(center, half):
    x,y=center[:2];w,h=half
    return [x-w,y-h,x+w,y+h]


def overlaps(a,b,margin=0.):
    return a[0]<b[2]+margin and a[2]>b[0]-margin and a[1]<b[3]+margin and a[3]>b[1]-margin


def region_title(region):
    x0,y0,x1,y1=region['bounds_xy_m']
    return [(x0+x1)/2,y1-.6,.004],[3.6,.5]


def place_label(candidates,half,occupied,margin=.10):
    for position in candidates:
        box=bounds(position,half)
        if not any(overlaps(box,other,margin)for other in occupied):
            return list(position),box
    raise ValueError('No clear floor space for label; adjust layout instead of hiding text under furniture')


# A robot's letter is printed on the tabletop next to its base and partly reaches
# under it. The display (never the source scene) places every letter label, upright
# for the front camera, with its near edge on the robot's whole outline
# seen from above, arm included, so a top view shows it: along its own direction
# from the base, away from the arm; where that spot leaves the table (a robot at
# the table edge) or, where objects matter, lies under them (a Dial module), on the
# base's right or left side instead, else in front of it; failing all, the least
# covered of them. Mosaic stock may cover a label: its cubes surround every base. Footprints use each
# geometry's projected outline at the current pose.
ROBOT_LABEL = re.compile(r'([A-Z]{1,2})_label')
ROBOT_LINK = re.compile(r'([A-Z]{1,2})_link\d+')  # robot geometry is often unnamed; its body is not
ITEM_PRINT = re.compile(r'[A-Z]{1,2}_item\d+_print\d+')
LABEL_GAP_M = 0.
LABEL_SIDES_DEG = (0, -90, 90, 180)
OBJECT_COVER = .10  # largest share of a label that objects may cover
STANDING_M = .05  # robot geometry whose bottom is this close to the tabletop is its base


def _outline(model, data, gid):
    """XY points of a geometry's outline seen from above, in world coordinates."""
    kind = model.geom_type[gid]; size = model.geom_size[gid]
    if kind == mujoco.mjtGeom.mjGEOM_MESH:
        mid = model.geom_dataid[gid]
        local = model.mesh_vert[model.mesh_vertadr[mid]:model.mesh_vertadr[mid]+model.mesh_vertnum[mid]]
    elif kind == mujoco.mjtGeom.mjGEOM_BOX:
        local = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)])*size
    else:
        angles = np.linspace(0, 2*math.pi, 24, endpoint=False)
        ring = np.column_stack((np.cos(angles), np.sin(angles)))
        if kind in (mujoco.mjtGeom.mjGEOM_CYLINDER, mujoco.mjtGeom.mjGEOM_CAPSULE):
            radius, half = size[0], size[1]+(size[0] if kind == mujoco.mjtGeom.mjGEOM_CAPSULE else 0)
            local = np.vstack([np.column_stack((ring*radius, np.full(24, z))) for z in (-half, 0, half)])
        else:  # sphere and ellipsoid
            radii = size if kind == mujoco.mjtGeom.mjGEOM_ELLIPSOID else np.repeat(size[0], 3)
            local = np.vstack([np.column_stack((ring*math.cos(t)*radii[:2], np.full(24, math.sin(t)*radii[2])))
                               for t in np.linspace(-math.pi/2, math.pi/2, 7)])
    world = local@data.geom_xmat[gid].reshape(3, 3).T+data.geom_xpos[gid]
    return world


def _hull(points):
    points = sorted(set(map(tuple, np.round(points, 5))))
    if len(points) < 3:
        return points
    def half(sequence):
        out = []
        for p in sequence:
            while len(out) >= 2 and (out[-1][0]-out[-2][0])*(p[1]-out[-2][1])-(out[-1][1]-out[-2][1])*(p[0]-out[-2][0]) <= 0:
                out.pop()
            out.append(p)
        return out
    lower, upper = half(points), half(reversed(points))
    return lower[:-1]+upper[:-1]


def _inside(hull, points):
    """Points inside a counter-clockwise convex outline."""
    edges = np.roll(hull, -1, axis=0)-hull
    offsets = points[:, None, :]-hull[None, :, :]
    return np.all(edges[None, :, 0]*offsets[..., 1]-edges[None, :, 1]*offsets[..., 0] >= 0, axis=1)


def robot_label_moves(model, data, avoid_objects=True):
    """New source-frame XY for every robot letter label, LABEL_GAP_M outside its base.

    Returns {geom name: dict(robot, from_xy, to_xy, distance_from_base_m, side_deg,
    on_table)}; on_table is False only if no side keeps the label on the table."""
    names = [model.geom(g).name for g in range(model.ngeom)]
    labels = [g for g, n in enumerate(names) if model.geom_bodyid[g] == 0 and ROBOT_LABEL.fullmatch(n)]
    tables = [g for g, n in enumerate(names) if n.startswith('table_') and 'leg' not in n]
    if not labels or not tables:
        return {}
    top = max(_outline(model, data, g)[:, 2].max() for g in tables)
    # Tabletop pieces as outlines: a ring of segments or a frame round an opening has holes.
    surfaces = [np.asarray(_hull(_outline(model, data, g)[:, :2])) for g in tables
                if _outline(model, data, g)[:, 2].max() > top-.005]
    objects = []
    for g in range(model.ngeom):
        if (g in labels or g in tables or ROBOT_LINK.fullmatch(model.body(model.geom_bodyid[g]).name)
                or model.geom_group[g] > 2 or model.geom_type[g] == mujoco.mjtGeom.mjGEOM_PLANE
                or names[g].startswith(('floor', 'sky'))):
            continue
        points = _outline(model, data, g)
        if points[:, 2].max() >= top-.03 and points[:, 2].min() <= top+STANDING_M:
            hull = _hull(points[:, :2])
            if len(hull) >= 3:
                objects.append(np.asarray(hull))
    samples = np.array([[x, y] for x in np.linspace(-.9, .9, 10) for y in np.linspace(-.9, .9, 10)])
    outlines = {}
    for g in range(model.ngeom):
        match = ROBOT_LINK.fullmatch(model.body(model.geom_bodyid[g]).name)
        if match and model.geom_group[g] <= 2:
            outlines.setdefault(match.group(1), []).append(_outline(model, data, g)[:, :2])
    # Letters read upright in the front view: a label's local +y is the letter's top,
    # so it points along the front camera's horizontal viewing direction.
    front = None
    cam = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, 'global')
    if cam >= 0 and model.cam_bodyid[cam] == 0:
        # A world-fixed camera: its model orientation is its pose, whatever data holds.
        matrix = np.zeros(9); mujoco.mju_quat2Mat(matrix, model.cam_quat[cam])
        view = -matrix.reshape(3, 3)[:, 2]
        front = math.atan2(view[1], view[0])-math.pi/2
    moves = {}
    for g in labels:
        robot = ROBOT_LABEL.fullmatch(names[g]).group(1)
        base = data.xpos[model.body(robot+'_link0').id][:2]
        current = data.geom_xpos[g][:2].copy()
        away = current-base; away /= max(np.linalg.norm(away), 1e-9)
        footprint = np.vstack(outlines[robot])
        rotation = data.geom_xmat[g].reshape(3, 3)[:2, :2]
        if front is not None:
            rotation = np.array([[math.cos(front), -math.sin(front)], [math.sin(front), math.cos(front)]])
        corners = np.array([[x, y] for x in (-1, 1) for y in (-1, 1)])*model.geom_size[g][:2]@rotation.T
        points = samples*model.geom_size[g][:2]@rotation.T
        options = []
        for side in LABEL_SIDES_DEG:
            c, s = math.cos(math.radians(side)), math.sin(math.radians(side))
            direction = np.array([c*away[0]-s*away[1], s*away[0]+c*away[1]])
            reach = float(((footprint-base)@direction).max())
            centre = base+direction*(reach+LABEL_GAP_M+float((corners@direction).max()))
            edge = np.vstack((corners, points))+centre
            on_table = np.zeros(len(edge), dtype=bool)
            for surface in surfaces:
                on_table |= _inside(surface, edge)
            if not on_table.all():
                continue
            inside = np.zeros(len(points), dtype=bool)
            for outline in objects:
                inside |= _inside(outline, points+centre)
            options.append((float(inside.mean()), side, centre))
            if not avoid_objects or options[-1][0] <= OBJECT_COVER:
                break
        if not options:
            raise ValueError('No side of the base keeps robot label '+names[g]+' on the table')
        cover, side, centre = options[-1] if not avoid_objects or options[-1][0] <= OBJECT_COVER else min(options, key=lambda o: o[0])
        yaw = math.atan2(rotation[1, 0], rotation[0, 0])
        moves[names[g]] = dict(robot=robot, from_xy=current.tolist(), to_xy=centre.tolist(), side_deg=side,
                               quat_wxyz=[math.cos(yaw/2), 0., 0., math.sin(yaw/2)],
                               object_cover=cover, distance_from_base_m=float(np.linalg.norm(centre-base)))
    return moves


def item_print_turns(model):
    """Display quaternions for block letters printed upside down on their side faces.

    The source scene prints a block's +y face with the letter's top pointing at the
    plug blades. Only videos read the result; runs keep the frozen scene."""
    turns = {}
    half_turn = np.array([0., 0., 0., 1.])
    for gid in range(model.ngeom):
        name = model.geom(gid).name
        if not ITEM_PRINT.fullmatch(name):
            continue
        matrix = np.zeros(9)
        mujoco.mju_quat2Mat(matrix, model.geom_quat[gid])
        matrix = matrix.reshape(3, 3)
        if abs(matrix[2, 2]) < .5 and matrix[2, 1] < -.5:
            turned = np.zeros(4)
            mujoco.mju_mulQuat(turned, model.geom_quat[gid], half_turn)
            turns[name] = turned.tolist()
    return turns


def apply_display_labels(model, data, avoid_objects=True):
    """Place letter labels and block letters as every video shows them."""
    moves = robot_label_moves(model, data, avoid_objects=avoid_objects)
    for name, move in moves.items():
        gid = model.geom(name).id
        model.geom_pos[gid][:2] = move['to_xy']
        model.geom_quat[gid] = move['quat_wxyz']
    turns = item_print_turns(model)
    for name, quaternion in turns.items():
        model.geom_quat[model.geom(name).id] = quaternion
    mujoco.mj_kinematics(model, data)
    return moves, turns


def place_robot_labels(model, data, task):
    """Put a run's letter labels where its videos show them, before the run starts.

    Labels are visual geometry on the world body, so no contact or dynamics changes.
    Spots come from the scene's initial keyframe, so every segment and every video of
    the run agrees."""
    scratch = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, scratch, model.key('initial').id)
    mujoco.mj_kinematics(model, scratch)
    moves = robot_label_moves(model, scratch, avoid_objects=task.get('family') != 'mosaic')
    for name, move in moves.items():
        gid = model.geom(name).id
        model.geom_pos[gid][:2] = move['to_xy']
        model.geom_quat[gid] = move['quat_wxyz']
    mujoco.mj_kinematics(model, data)
    return moves
