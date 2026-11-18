"""Build the factory hall as a portable static background, independent of task workstations."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from scipy.spatial import ConvexHull

from roboteam.io import ROOT

DEFAULT_CONFIG = ROOT / 'benchmark/hall/layout.json'
LAYERS = {'structure': 0, 'roof': 1, 'north': 2, 'south': 3, 'west': 4, 'east': 5}


def _vec(x):
    return ' '.join(f'{float(v):.8g}' for v in x)


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _font(size):
    path = ROOT / 'benchmark/hall/fonts/BarlowCondensed-SemiBold.ttf'
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def _texture_assets(folder, seed, painted_roof=False):
    """Deterministic, tileable authored finishes; no image API or external service."""
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    size = 1024
    noise = np.zeros((size, size), dtype=np.float32)
    for n, weight in [(8, 2.6), (32, 1.5), (128, 0.8), (1024, 0.55)]:
        a = rng.random((n, n), dtype=np.float32)
        a = np.asarray(Image.fromarray(a).resize((size, size), Image.Resampling.BICUBIC))
        noise += (a - 0.5) * weight
    # Periodic high-frequency texture, with restrained coarse mottling.
    y, x = np.mgrid[:size, :size]
    field = noise + 0.7 * np.sin(2 * np.pi * x / size) * np.sin(4 * np.pi * y / size)
    gray = np.clip(150 + 4.5 * field, 132, 167).astype(np.uint8)
    color = np.stack([gray, np.clip(gray.astype(int) + 1, 0, 255), gray], axis=-1).astype(np.uint8)
    Image.fromarray(color).save(folder / 'concrete-color.png')
    rough = np.clip(158 + field * 8, 132, 188).astype(np.uint8)
    Image.fromarray(np.repeat(rough[..., None], 3, axis=2)).save(folder / 'concrete-roughness.png')
    grain = np.sin(y * 0.16 + np.sin(x * 0.008) * 2.5 + noise * 1.2) * 0.025 + noise * 0.018
    wood = np.clip(0.90 + grain, 0.76, 0.98)
    Image.fromarray(np.uint8(np.repeat(wood[..., None], 3, axis=2) * 255)).save(folder / 'bench-grain.png')
    # A tiny normal variation; the 4m tile represents fine grain, not deep bumps.
    smooth = np.asarray(Image.fromarray(gray).filter(ImageFilter.GaussianBlur(1.1))).astype(float)
    dy, dx = np.gradient(smooth)
    normal = np.stack([-dx * 0.7, -dy * 0.7, np.full_like(dx, 127)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    Image.fromarray(np.uint8(np.clip((normal * 0.5 + 0.5) * 255, 0, 255))).save(
        folder / 'concrete-normal.png'
    )
    # Wall paint with quiet roller variation, suitable for reuse across many bays.
    paint = np.clip(184 + field * 1.7, 176, 194).astype(np.uint8)
    Image.fromarray(
        np.stack([paint, paint, np.clip(paint.astype(int) - 3, 0, 255)], -1).astype(np.uint8)
    ).save(folder / 'wall-paint.png')
    # Ribs are texture detail; roof thickness and framing remain real geometry.
    rib = np.clip(
        (208 if painted_roof else 96)
        + (5 if painted_roof else 9) * np.cos(x / size * 2 * np.pi * 24)
        + noise * 0.5,
        75,
        225 if painted_roof else 110,
    ).astype(np.uint8)
    Image.fromarray(np.stack([rib, rib, np.clip(rib.astype(int) + 2, 0, 255)], -1).astype(np.uint8)).save(
        folder / 'roof-ribs.png'
    )
    stripe = Image.new('RGB', (256, 512), (236, 169, 37))
    draw = ImageDraw.Draw(stripe)
    for offset in range(-512, 768, 120):
        draw.polygon(
            [(0, offset), (256, offset + 160), (256, offset + 215), (0, offset + 55)], fill=(30, 34, 35)
        )
    stripe.save(folder / 'hazard-stripe.png')
    # Filterable shutter grooves: sub-pixel black 3D slats broke into dots in
    # distant views. A mipmapped finish preserves the broad panel silhouette.
    yy = np.arange(2048)[:, None]
    phase = (yy / 2048 * 4.76 / 0.13) % 1
    crease = np.exp(-(((phase - 0.5) / 0.045) ** 2))
    highlight = np.exp(-(((phase - 0.42) / 0.08) ** 2))
    shutter = np.repeat(np.clip(174 - 29 * crease + 6 * highlight, 0, 255), 1024, axis=1)
    Image.fromarray(np.uint8(np.repeat(shutter[..., None], 3, axis=2))).save(folder / 'shutter-ribs.png')
    source = folder.parent / 'source/polyhaven'
    for stem in ['concrete-color', 'concrete-roughness', 'concrete-normal']:
        cached = source / (stem + '.jpg')
        if cached.exists():
            pixels = np.asarray(Image.open(cached).convert('RGB')).astype(float)
            if stem == 'concrete-color':
                pixels = pixels * 0.50 + pixels.mean(axis=(0, 1), keepdims=True) * 0.50
            elif stem == 'concrete-normal':
                pixels = pixels * 0.16 + np.array([128, 128, 255]) * 0.84
            Image.fromarray(np.uint8(np.clip(pixels, 0, 255))).save(folder / (stem + '.png'))
    # Repeated maintenance graphics are shared flat textures, not hundreds of tiny meshes.
    for name in ['process', 'safety', 'tools']:
        image = Image.new('RGB', (1024, 512), (221, 224, 218) if name != 'tools' else (79, 91, 96))
        draw = ImageDraw.Draw(image)
        if name == 'tools':
            for xx in range(16, 1024, 22):
                for yy in range(16, 512, 22):
                    draw.ellipse((xx - 2, yy - 2, xx + 2, yy + 2), fill=(43, 53, 58))
            draw.rectangle((0, 0, 1024, 62), fill=(33, 54, 69))
            draw.text((26, 10), 'MAINTENANCE  /  TOOL CONTROL', font=_font(38), fill=(233, 236, 230))
            for i, xx in enumerate(range(75, 980, 110)):
                top = 105 + (i % 3) * 20
                bottom = 300 + (i % 2) * 70
                draw.line((xx, top + 25, xx, bottom), fill=(173, 181, 180), width=16)
                draw.arc((xx - 23, top, xx + 23, top + 46), 0, 295, fill=(204, 210, 207), width=13)
                draw.rounded_rectangle((xx - 13, bottom - 70, xx + 13, bottom + 10), 7, fill=(22, 42, 56))
                draw.text((xx - 27, 438), f'{i + 1:02}', font=_font(24), fill=(200, 208, 204))
        else:
            draw.rectangle((0, 0, 1024, 76), fill=(24, 63, 86) if name == 'process' else (206, 149, 42))
            draw.text(
                (28, 13),
                'OPERATIONS / DAILY STATUS' if name == 'process' else 'SAFETY / AUTHORIZED PERSONNEL',
                font=_font(42),
                fill=(239, 241, 234) if name == 'process' else (31, 35, 36),
            )
            if name == 'process':
                for xx in [30, 345, 660, 995]:
                    draw.line((xx, 115, xx, 470), fill=(156, 169, 172), width=2)
                for yy in [155, 210, 265, 320, 375, 430, 470]:
                    draw.line((30, yy, 995, yy), fill=(156, 169, 172), width=2)
                for i, text in enumerate(['PLAN', 'IN PROGRESS', 'VERIFIED']):
                    draw.text((50 + i * 315, 106), text, font=_font(31), fill=(43, 62, 69))
                for col, rows in [(0, [0, 2, 3]), (1, [1, 2]), (2, [0, 1, 3, 4])]:
                    for row in rows:
                        x = 52 + col * 315
                        y = 170 + row * 55
                        draw.rectangle(
                            (x, y, x + 220, y + 27),
                            fill=[(111, 143, 160), (201, 171, 93), (131, 158, 133)][col],
                        )
                        draw.line((x + 12, y + 9, x + 160, y + 9), fill=(67, 84, 87), width=2)
            else:
                for xx, symbol, title in [
                    (174, '!', 'KEEP AISLES CLEAR'),
                    (512, 'I', 'PPE REQUIRED'),
                    (850, '+', 'FIRST AID'),
                ]:
                    draw.ellipse(
                        (xx - 66, 130, xx + 66, 262), fill=(29, 79, 108) if symbol != '!' else (216, 164, 55)
                    )
                    draw.text(
                        (xx, 194),
                        symbol,
                        font=_font(96),
                        anchor='mm',
                        fill=(239, 240, 232) if symbol != '!' else (40, 43, 40),
                    )
                    draw.text((xx, 310), title, font=_font(27), anchor='mm', fill=(36, 48, 52))
                    for yy in [356, 378, 400]:
                        draw.line((xx - 98, yy, xx + 98, yy), fill=(117, 132, 135), width=3)
        image.save(folder / ('panel_' + name + '.png'))
    return sorted(folder.glob('*.png'))


def _rx(angle):
    return np.array(
        [[1, 0, 0], [0, math.cos(angle), -math.sin(angle)], [0, math.sin(angle), math.cos(angle)]]
    )


def _rz(angle):
    return np.array(
        [[math.cos(angle), -math.sin(angle), 0], [math.sin(angle), math.cos(angle), 0], [0, 0, 1]]
    )


def _floor_finish(folder, config):
    """A restrained whole-floor finish at the existing 2K texture budget.

    Keep fine sourced grain, but put maintenance patches and broad roughness
    variation in building coordinates so they do not repeat every few metres.
    This is appearance only; the floor geometry and collision policy are unchanged.
    """
    size = 2048
    rng = np.random.default_rng(config['seed'] + 303)

    def repeat_source(name):
        tile = (
            Image.open(folder / (name + '.png')).convert('RGB').resize((256, 256), Image.Resampling.LANCZOS)
        )
        return np.tile(np.asarray(tile, dtype=float), (8, 8, 1))

    color = repeat_source('concrete-color')
    gray = color.mean(2)
    small = Image.fromarray(rng.random((24, 24), dtype=np.float32))
    macro = np.asarray(small.resize((size, size), Image.Resampling.BICUBIC)) - 0.5
    finish = 128 + (gray - gray.mean()) * 0.45 + macro * 8
    rough = 150 + (repeat_source('concrete-roughness').mean(2) - 132) * 0.35 + macro * 12
    # Soft-edged, slightly different maintenance patches; no repeating dirt tiles.
    W, D = config['building']['width_m'], config['building']['depth_m']
    for x, y, w, h, tone in [
        (-0.23 * W, -0.24 * D, 2.0, 1.5, 3),
        (0.31 * W, 0.20 * D, 2.4, 1.8, -3),
        (-0.37 * W, 0.32 * D, 1.8, 1.2, -2),
    ]:
        mask = Image.new('L', (size, size))
        draw = ImageDraw.Draw(mask)
        draw.rectangle(
            (
                (x - w / 2 + W / 2) / W * size,
                (y - h / 2 + D / 2) / D * size,
                (x + w / 2 + W / 2) / W * size,
                (y + h / 2 + D / 2) / D * size,
            ),
            fill=255,
        )
        alpha = np.asarray(mask.filter(ImageFilter.GaussianBlur(2)), dtype=float) / 255
        finish += alpha * tone
        rough += alpha * 7
    # A few quiet scuffs in the perimeter service strips, not in task slots.
    scuffs = Image.new('L', (size, size))
    draw = ImageDraw.Draw(scuffs)
    for side in [-1, 1]:
        for y in [-0.34 * D, -0.08 * D, 0.21 * D, 0.36 * D]:
            x = side * (W / 2 - 1.8)
            px = (x + W / 2) / W * size
            py = (y + D / 2) / D * size
            draw.arc((px - 12, py - 7, px + 12, py + 7), 20, 140, fill=100, width=1)
    wear = np.asarray(scuffs.filter(ImageFilter.GaussianBlur(0.65)), dtype=float) / 255
    finish -= wear * 8
    rough += wear * 9
    Image.fromarray(np.uint8(np.clip(np.repeat(finish[..., None], 3, axis=2), 0, 255))).save(
        folder / 'concrete-color.png'
    )
    Image.fromarray(np.uint8(np.clip(np.repeat(rough[..., None], 3, axis=2), 0, 255))).save(
        folder / 'concrete-roughness.png'
    )
    normal = repeat_source('concrete-normal') * 0.35 + np.array([128, 128, 255]) * 0.65
    Image.fromarray(np.uint8(np.clip(normal, 0, 255))).save(folder / 'concrete-normal.png')


class _Builder:
    def __init__(self, config, assets, output):
        self.cfg, self.assets_path, self.output = config, assets, output
        b = config['building']
        self.width, self.depth, self.height = b['width_m'], b['depth_m'], b['eave_height_m']
        self.root = ET.Element('mujoco', model=config['id'])
        ET.SubElement(self.root, 'compiler', angle='radian', autolimits='true', inertiafromgeom='false')
        ET.SubElement(self.root, 'option', timestep='.002', gravity='0 0 -9.81')
        self.asset = ET.SubElement(self.root, 'asset')
        self.world = ET.SubElement(self.root, 'worldbody')
        self.defaults = ET.SubElement(self.root, 'default')
        background_class = ET.SubElement(self.defaults, 'default', {'class': 'factory_visual'})
        ET.SubElement(background_class, 'geom', contype='0', conaffinity='0', density='0')
        v = ET.SubElement(self.root, 'visual')
        ET.SubElement(v, 'global', offwidth='1920', offheight='1920')
        ET.SubElement(
            v,
            'quality',
            shadowsize=str(config['lighting']['shadow_map_size']),
            offsamples='4',
            numslices='16',
            numstacks='8',
        )
        ET.SubElement(v, 'headlight', ambient='.23 .23 .23', diffuse='.42 .42 .42', specular='.12 .12 .12')
        ET.SubElement(v, 'map', znear='.005', zfar='5', shadowclip='2', shadowscale='1')
        ET.SubElement(
            self.root, 'statistic', center='0 0 2.5', extent=str(max(self.width, self.depth) * 0.55)
        )
        self.meshes, self.mesh_triangles, self.serial = {}, 0, 0
        self.objects, self.cameras = [], []
        self.props = []
        self.batching = {}
        self._materials()

    def _materials(self):
        colors = {
            'floor': ((0.72, 0.73, 0.72, 1), 0.0, 0.50),
            'wall': ((0.78, 0.78, 0.75, 1), 0.0, 0.87),
            'band': ((0.28, 0.32, 0.34, 1), 0.12, 0.62),
            'concrete': ((0.55, 0.56, 0.54, 1), 0.0, 0.84),
            'steel': ((0.09, 0.105, 0.12, 1), 0.18, 0.58),
            'steel_light': ((0.55, 0.58, 0.59, 1), 0.85, 0.36),
            'roof': ((0.61, 0.63, 0.64, 1), 0.65, 0.62),
            'yellow': ((0.95, 0.58, 0.065, 1), 0.0, 0.68),
            'black': ((0.045, 0.052, 0.058, 1), 0.1, 0.6),
            'cabinet': ((0.67, 0.69, 0.68, 1), 0.03, 0.52),
            'cabinet_dark': ((0.29, 0.33, 0.34, 1), 0.03, 0.55),
            'blue': ((0.035, 0.19, 0.39, 1), 0.0, 0.60),
            'bin_inside': ((0.025, 0.07, 0.135, 1), 0.0, 0.78),
            'label': ((0.88, 0.87, 0.8, 1), 0.0, 0.8),
            'cardboard': ((0.47, 0.33, 0.19, 1), 0.0, 0.92),
            'tape': ((0.57, 0.44, 0.27, 1), 0.0, 0.5),
            'red': ((0.65, 0.035, 0.018, 1), 0.12, 0.34),
            'green': ((0.04, 0.20, 0.075, 1), 0.0, 0.87),
            'leaf_light': ((0.1, 0.29, 0.12, 1), 0.0, 0.78),
            'pot': ((0.21, 0.23, 0.22, 1), 0.1, 0.8),
            'glass': ((0.56, 0.66, 0.71, 0.23), 0.05, 0.45),
            'lamp': ((1, 0.98, 0.91, 1), 0.0, 0.2),
            'bench_wood': ((0.55, 0.37, 0.22, 1), 0.0, 0.48),
            'exit': ((0.02, 0.42, 0.16, 1), 0.0, 0.65),
        }
        colors['asphalt'] = ((0.19, 0.21, 0.22, 1), 0.0, 0.91)
        for name, rgba in self.cfg['appearance'].get('material_colors', {}).items():
            old = colors[name]
            colors[name] = (tuple(rgba), old[1], old[2])
        for name, roughness in self.cfg['appearance'].get('material_roughness', {}).items():
            old = colors[name]
            colors[name] = (old[0], old[1], roughness)
        for name, metallic in self.cfg['appearance'].get('material_metallic', {}).items():
            old = colors[name]
            colors[name] = (old[0], metallic, old[2])
        for name, (rgba, metal, rough) in colors.items():
            spec = {
                'name': 'factory_' + name,
                'rgba': _vec(rgba),
                'metallic': str(metal),
                'roughness': str(rough),
                'specular': '.25',
                'shininess': '.25',
            }
            if name == 'lamp':
                spec['emission'] = '1'
            if name == 'exit':
                spec['emission'] = '.2'
            material = ET.SubElement(self.asset, 'material', **spec)
            if name == 'bench_wood':
                ET.SubElement(
                    self.asset,
                    'texture',
                    name='factory_bench_grain',
                    type='2d',
                    file='assets/textures/bench-grain.png',
                )
                material.set('texture', 'factory_bench_grain')
                material.set('texuniform', 'true')
                material.set('texrepeat', '2 2')
            if name == 'floor':
                if self.cfg['appearance'].get('whole_floor_finish', False):
                    material.set('texuniform', 'false')
                    material.set('texrepeat', '1 1')
                else:
                    material.set('texuniform', 'true')
                    material.set('texrepeat', _vec([1 / self.cfg['appearance']['floor_tile_m']] * 2))
                for filename, role in [
                    ('concrete-color.png', 'rgb'),
                    ('concrete-roughness.png', 'roughness'),
                    ('concrete-normal.png', 'normal'),
                ]:
                    texture = 'factory_' + Path(filename).stem.replace('-', '_')
                    ET.SubElement(
                        self.asset, 'texture', name=texture, type='2d', file='assets/textures/' + filename
                    )
                    ET.SubElement(material, 'layer', texture=texture, role=role)
            elif name in ('wall', 'roof'):
                filename = 'wall-paint.png' if name == 'wall' else 'roof-ribs.png'
                texture = 'factory_' + name + '_surface'
                ET.SubElement(
                    self.asset, 'texture', name=texture, type='2d', file='assets/textures/' + filename
                )
                material.set('texture', texture)
                material.set('texuniform', 'true')
                material.set('texrepeat', '.3 .3' if name == 'wall' else '1 1')
        for region in self.cfg['regions']:
            if 'floor_rgba' not in region:
                continue
            import copy

            floor = copy.deepcopy(self.asset.find("material[@name='factory_floor']"))
            for layer in floor.findall('layer'):
                if layer.get('role') in ('rgb', 'rgba'):
                    floor.remove(layer)
            floor.set('name', 'factory_zone_floor_' + region['id'])
            floor.set('rgba', _vec(region['floor_rgba']))
            self.asset.append(floor)
            for kind, rgba in [('accent', region['accent_rgba']), ('cabinet', region['accent_rgba'])]:
                ET.SubElement(
                    self.asset,
                    'material',
                    name='factory_zone_' + kind + '_' + region['id'],
                    rgba=_vec(rgba),
                    roughness='.65',
                    metallic='.05',
                    specular='.25',
                )
        ET.SubElement(
            self.asset,
            'texture',
            name='factory_sky',
            type='skybox',
            builtin='gradient',
            rgb1='.65 .70 .75',
            rgb2='.8 .82 .83',
            width='512',
            height='3072',
        )
        ET.SubElement(
            self.asset, 'texture', name='factory_hazard', type='2d', file='assets/textures/hazard-stripe.png'
        )
        ET.SubElement(
            self.asset,
            'material',
            name='factory_hazard_material',
            texture='factory_hazard',
            texuniform='false',
            roughness='.65',
        )
        ET.SubElement(
            self.asset,
            'texture',
            name='factory_shutter_ribs',
            type='2d',
            file='assets/textures/shutter-ribs.png',
        )
        ET.SubElement(
            self.asset,
            'material',
            name='factory_shutter',
            texture='factory_shutter_ribs',
            texuniform='false',
            rgba='.75 .79 .8 1',
            metallic='.62',
            roughness='.43',
        )
        ET.SubElement(
            self.asset,
            'mesh',
            name='factory_shutter_face',
            inertia='shell',
            vertex='-2.5 -2.38 0 2.5 -2.38 0 2.5 2.38 0 -2.5 2.38 0',
            face='0 1 2 0 2 3',
            texcoord='0 1 1 1 1 0 0 0',
        )
        self.mesh_triangles += 2

    def body(self, name, pos=(0, 0, 0), yaw=0, group='structure', category='architecture'):
        body = ET.SubElement(
            self.world,
            'body',
            name='factory_' + name,
            childclass='factory_visual',
            pos=_vec(pos),
            quat=_vec([math.cos(yaw / 2), 0, 0, math.sin(yaw / 2)]),
        )
        self.objects.append(
            dict(id='factory_' + name, category=category, translation_m=list(pos), yaw_rad=yaw, layer=group)
        )
        return body

    def _name(self):
        self.serial += 1
        return 'factory_geom_' + str(self.serial)

    def _bevel_mesh(self, half, bevel):
        half = np.array(half, float)
        bevel = min(bevel, float(half.min()) * 0.45)
        key = tuple(np.round([*half, bevel], 6))
        if key in self.meshes:
            return self.meshes[key]
        vertices = []
        for sx in [-1, 1]:
            for sy in [-1, 1]:
                for sz in [-1, 1]:
                    signs = np.array([sx, sy, sz])
                    for axis in range(3):
                        p = half - bevel
                        p = p.copy()
                        p[axis] = half[axis]
                        vertices.append(p * signs)
        vertices = np.unique(vertices, axis=0)
        hull = ConvexHull(vertices)
        faces = []
        for tri, equation in zip(hull.simplices, hull.equations):
            tri = tri.copy()
            a, b, c = vertices[tri]
            if np.dot(np.cross(b - a, c - a), equation[:3]) < 0:
                tri[[1, 2]] = tri[[2, 1]]
            faces.append(tri)
        name = 'factory_bevel_' + str(len(self.meshes))
        file = self.assets_path / 'meshes' / f'{name}.obj'
        file.parent.mkdir(exist_ok=True)
        file.write_text(
            '\n'.join(
                ['v ' + _vec(v) for v in vertices]
                + ['f ' + ' '.join(str(int(x) + 1) for x in tri) for tri in faces]
            )
            + '\n'
        )
        ET.SubElement(self.asset, 'mesh', name=name, file='assets/meshes/' + file.name)
        self.meshes[key] = name
        self.mesh_triangles += len(faces)
        return name

    def box(self, parent, pos, half, material, group='structure', bevel=0, rotation=None):
        if material == 'cabinet':
            for region in self.cfg['regions']:
                if region.get('accent_rgba') and region['id'] + '-' in parent.get('name', ''):
                    material = 'zone_cabinet_' + region['id']
                    break
        attrs = dict(
            name=self._name(), pos=_vec(pos), material='factory_' + material, group=str(LAYERS[group])
        )
        if rotation is not None:
            attrs['xyaxes'] = _vec([*rotation[:, 0], *rotation[:, 1]])
        if bevel > 0:
            attrs.update(type='mesh', mesh=self._bevel_mesh(half, bevel))
        else:
            attrs.update(type='box', size=_vec(half))
        return ET.SubElement(parent, 'geom', **attrs)

    def cylinder(self, parent, pos, radius, halfheight, material, group='structure', rotation=None):
        attrs = dict(
            name=self._name(),
            type='cylinder',
            pos=_vec(pos),
            size=_vec([radius, halfheight]),
            material='factory_' + material,
            group=str(LAYERS[group]),
        )
        if rotation is not None:
            attrs['xyaxes'] = _vec([*rotation[:, 0], *rotation[:, 1]])
        return ET.SubElement(parent, 'geom', **attrs)

    def line(self, parent, a, b, radius, material, group='structure'):
        return ET.SubElement(
            parent,
            'geom',
            name=self._name(),
            type='capsule',
            fromto=_vec([*a, *b]),
            size=str(radius),
            material='factory_' + material,
            group=str(LAYERS[group]),
        )

    def sign(
        self,
        parent,
        name,
        text,
        pos,
        size,
        yaw=0,
        group='structure',
        bg=(188, 188, 181),
        fg=(28, 32, 33),
        painted=False,
    ):
        pixels_w = min(1024, max(128, int(size[0] * 320)))
        pixels_h = min(512, max(64, int(size[1] * 320)))
        image = Image.new('RGBA' if painted else 'RGB', (pixels_w, pixels_h), (0, 0, 0, 0) if painted else bg)
        draw = ImageDraw.Draw(image)
        font = _font(int(pixels_h * 0.70))
        bounds = draw.textbbox((0, 0), text, font=font)
        scale = min(1, pixels_w * 0.92 / max(1, bounds[2] - bounds[0]))
        font = _font(max(12, int(pixels_h * 0.70 * scale)))
        draw.text(
            (pixels_w / 2, pixels_h / 2), text, font=font, anchor='mm', fill=(*fg, 255) if painted else fg
        )
        file = self.assets_path / 'textures' / ('sign_' + name + '.png')
        image.save(file)
        tex = 'factory_sign_' + name
        texture = ET.SubElement(
            self.asset, 'texture', name=tex, type='2d', file='assets/textures/' + file.name
        )
        if painted:
            texture.set('nchannel', '4')
        ET.SubElement(
            self.asset,
            'material',
            name=tex,
            texture=tex,
            texuniform='false',
            roughness='.85',
            rgba='1 1 1 .999' if painted else '1 1 1 1',
        )
        # Plane local XY, outward normal +Z, rotated into an upright sign.
        w, h = size
        mesh = tex + '_quad'
        ET.SubElement(
            self.asset,
            'mesh',
            name=mesh,
            inertia='shell',
            vertex=_vec([-w / 2, -h / 2, 0, w / 2, -h / 2, 0, w / 2, h / 2, 0, -w / 2, h / 2, 0]),
            face='0 1 2 0 2 3',
            texcoord='0 1 1 1 1 0 0 0',
        )
        rot = _rz(yaw) @ _rx(math.pi / 2)
        ET.SubElement(
            parent,
            'geom',
            name=self._name(),
            type='mesh',
            mesh=mesh,
            pos=_vec(pos),
            xyaxes=_vec([*rot[:, 0], *rot[:, 1]]),
            material=tex,
            group=str(LAYERS[group]),
        )
        self.mesh_triangles += 2

    def panel(self, parent, name, pos, size, group='structure', yaw=0):
        """Reuse a pre-authored panel texture across many real mounted boards."""
        tex = 'factory_panel_' + name
        if self.asset.find(f"material[@name='{tex}']") is None:
            ET.SubElement(
                self.asset, 'texture', name=tex, type='2d', file='assets/textures/panel_' + name + '.png'
            )
            ET.SubElement(self.asset, 'material', name=tex, texture=tex, texuniform='false', roughness='.8')
        mesh = tex + '_quad_' + hashlib.sha256(_vec(size).encode()).hexdigest()[:10]
        if self.asset.find(f"mesh[@name='{mesh}']") is None:
            w, h = size
            ET.SubElement(
                self.asset,
                'mesh',
                name=mesh,
                inertia='shell',
                vertex=_vec([-w / 2, -h / 2, 0, w / 2, -h / 2, 0, w / 2, h / 2, 0, -w / 2, h / 2, 0]),
                face='0 1 2 0 2 3',
                texcoord='0 1 1 1 1 0 0 0',
            )
            self.mesh_triangles += 2
        rot = _rz(yaw) @ _rx(math.pi / 2)
        ET.SubElement(
            parent,
            'geom',
            name=self._name(),
            type='mesh',
            mesh=mesh,
            pos=_vec(pos),
            xyaxes=_vec([*rot[:, 0], *rot[:, 1]]),
            material=tex,
            group=str(LAYERS[group]),
        )

    def static_batches(self):
        """Combine opaque plain-colour boxes per semantic body/material/layer.

        No cross-body transforms, textured surfaces, transparency or cylinders
        are merged. Source bounds remain independently computable for auditing.
        These visual-only meshes are never suitable as a physical collision hull.
        """
        material_ok = {
            m.get('name')
            for m in self.asset.findall('material')
            if not m.get('texture')
            and not m.findall('layer')
            and float(m.get('rgba', '1 1 1 1').split()[3]) == 1
        }
        sources = {}
        for m in self.asset.findall('mesh'):
            if m.get('file'):
                vertices = []
                faces = []
                for row in (
                    (self.assets_path / Path(m.get('file')).relative_to('assets')).read_text().splitlines()
                ):
                    a = row.split()
                    if a and a[0] == 'v':
                        vertices.append([float(v) for v in a[1:4]])
                    elif a and a[0] == 'f':
                        faces.append([int(v.split('/')[0]) - 1 for v in a[1:4]])
                sources[m.get('name')] = (np.asarray(vertices), np.asarray(faces))
        signs = np.array(
            [
                [-1, -1, -1],
                [1, -1, -1],
                [1, 1, -1],
                [-1, 1, -1],
                [-1, -1, 1],
                [1, -1, 1],
                [1, 1, 1],
                [-1, 1, 1],
            ],
            float,
        )
        cube_faces = np.array(
            [
                [0, 2, 1],
                [0, 3, 2],
                [4, 5, 6],
                [4, 6, 7],
                [0, 1, 5],
                [0, 5, 4],
                [1, 2, 6],
                [1, 6, 5],
                [2, 3, 7],
                [2, 7, 6],
                [3, 0, 4],
                [3, 4, 7],
            ]
        )
        before = len(list(self.world.iter('geom')))
        batches = 0
        merged = 0
        for body in self.world.findall('body'):
            groups = {}
            for geom in body.findall('geom'):
                if geom.get('material') not in material_ok:
                    continue
                if geom.get('type') == 'box' or geom.get('mesh') in sources:
                    groups.setdefault((geom.get('material'), geom.get('group')), []).append(geom)
            for (mat, group), geoms in groups.items():
                if len(geoms) < 3:
                    continue
                verts = []
                faces = []
                offset = 0
                for geom in geoms:
                    if geom.get('type') == 'box':
                        v = signs * np.fromstring(geom.get('size'), sep=' ')
                        f = cube_faces
                    else:
                        v, f = sources[geom.get('mesh')]
                    if geom.get('xyaxes'):
                        axes = np.fromstring(geom.get('xyaxes'), sep=' ').reshape(2, 3)
                        rot = np.column_stack([*axes, np.cross(*axes)])
                        v = v @ rot.T
                    v = v + np.fromstring(geom.get('pos', '0 0 0'), sep=' ')
                    verts.extend(v)
                    faces.extend(f + offset)
                    offset += len(v)
                    body.remove(geom)
                name = body.get('name') + '_' + mat.removeprefix('factory_') + '_g' + group + '_batch'
                file = self.assets_path / 'meshes' / (name + '.obj')
                file.write_text(
                    '\n'.join(
                        ['v ' + _vec(v) for v in verts]
                        + ['f ' + ' '.join(str(int(i) + 1) for i in tri) for tri in faces]
                    )
                    + '\n'
                )
                ET.SubElement(self.asset, 'mesh', name=name, file='assets/meshes/' + file.name)
                ET.SubElement(body, 'geom', name=name, type='mesh', mesh=name, material=mat, group=group)
                self.mesh_triangles += len(faces)
                batches += 1
                merged += len(geoms)
        used = {g.get('mesh') for g in self.world.iter('geom') if g.get('mesh')}
        for mesh in list(self.asset.findall('mesh')):
            if mesh.get('name') not in used:
                self.asset.remove(mesh)
        self.mesh_triangles = 0
        for mesh in self.asset.findall('mesh'):
            if mesh.get('name') in sources:
                self.mesh_triangles += len(sources[mesh.get('name')][1])
            elif mesh.get('face'):
                self.mesh_triangles += len(mesh.get('face').split()) // 3
            else:
                file = self.assets_path / Path(mesh.get('file')).relative_to('assets')
                self.mesh_triangles += sum(row.startswith('f ') for row in file.read_text().splitlines())
        self.batching = dict(
            source_geoms=before,
            render_geoms=len(list(self.world.iter('geom'))),
            batches=batches,
            merged_source_geoms=merged,
            scope='Opaque static boxes/chamfers; within body, material and visibility layer only',
        )

    def wall_geometry(self):
        W, D, H = self.width, self.depth, self.height
        for side, y, yaw, layer in [('north', D / 2, 0, 'north'), ('south', -D / 2, math.pi, 'south')]:
            body = self.body(side + '_wall', [0, y, 0], yaw, layer)
            # A roller door is a physically present visual insert in a real opening.
            for x, half in [(-(W + 5.2) / 4, (W - 5.2) / 4), ((W + 5.2) / 4, (W - 5.2) / 4)]:
                self.box(body, [x, 0, H / 2], [half, 0.09, H / 2], 'wall', layer)
                self.box(body, [x, -0.105, 0.72], [half, 0.025, 0.72], 'band', layer)
            self.box(body, [0, 0, (H + 4.8) / 2], [2.6, 0.09, (H - 4.8) / 2], 'wall', layer)
            door = self.body(side + '_door', [0, y, 0], yaw, layer)
            self.box(door, [0, -0.055, 2.38], [2.5, 0.06, 2.38], 'steel_light', layer)
            rot = _rx(math.pi / 2)
            ET.SubElement(
                door,
                'geom',
                name=self._name(),
                type='mesh',
                mesh='factory_shutter_face',
                pos='0 -.124 2.38',
                xyaxes=_vec([*rot[:, 0], *rot[:, 1]]),
                material='factory_shutter',
                group=str(LAYERS[layer]),
            )
            for x in [-2.61, 2.61]:
                self.box(door, [x, -0.08, 2.47], [0.09, 0.12, 2.47], 'steel', layer)
            self.box(door, [0, -0.08, 4.92], [2.7, 0.14, 0.12], 'steel', layer)
            for x in [-1.5, 0, 1.5]:
                self.box(door, [x, -0.13, 2.8], [0.43, 0.018, 0.19], 'black', layer, bevel=0.025)
                self.box(door, [x, -0.153, 2.8], [0.39, 0.008, 0.15], 'glass', layer)
            self.sign(
                door,
                side + '_exit',
                'EXIT',
                [3.5, -0.17, 2.75],
                [0.65, 0.20],
                group=layer,
                bg=(14, 104, 50),
                fg=(235, 240, 230),
            )
            self.box(door, [3.5, -0.14, 1.25], [0.12, 0.07, 0.18], 'cabinet_dark', layer, bevel=0.012)
            self.cylinder(door, [3.5, -0.23, 1.35], 0.035, 0.02, 'green', layer, rotation=_rx(math.pi / 2))
            self.sign(
                body,
                side + '_left',
                'TRANSPORT' if side == 'north' else 'DIAL',
                [-W * 0.27, -0.12, 4.6],
                [5.3, 0.72],
                group=layer,
                painted=True,
            )
            self.sign(
                body,
                side + '_right',
                'MOSAIC' if side == 'north' else 'RELAY',
                [W * 0.27, -0.12, 4.6],
                [5.3, 0.72],
                group=layer,
                painted=True,
            )
            # Region and operational signs remain; the former brand wall is clear.
        # Side walls are assembled around glazed openings instead of textured solid boxes.
        for side, x, yaw, layer in [
            ('east', W / 2, -math.pi / 2, 'east'),
            ('west', -W / 2, math.pi / 2, 'west'),
        ]:
            body = self.body(side + '_wall', [x, 0, 0], yaw, layer)
            self.box(body, [0, 0, 0.65], [D / 2, 0.09, 0.65], 'wall', layer)
            self.box(body, [0, -0.105, 0.65], [D / 2, 0.018, 0.65], 'band', layer)
            self.box(body, [0, 0, 6.0], [D / 2, 0.09, 1.2], 'wall', layer)
            n = round(D / 6)
            step = D / n
            for i in range(n):
                cx = -D / 2 + (i + 0.5) * step
                window_w = step - 0.5
                for xx in [cx - step / 2, cx + step / 2]:
                    self.box(body, [xx, 0, 3.05], [0.25, 0.09, 1.75], 'wall', layer)
                self.box(body, [cx, 0.005, 3.05], [window_w / 2, 0.018, 1.73], 'glass', layer)
                for xx in [cx - window_w / 2, cx, cx + window_w / 2]:
                    self.box(body, [xx, -0.055, 3.05], [0.035, 0.035, 1.77], 'steel_light', layer)
                for zz in [1.3, 3.05, 4.8]:
                    self.box(
                        body, [cx, -0.055, zz], [window_w / 2 + 0.03, 0.035, 0.035], 'steel_light', layer
                    )
                self.box(body, [cx, -0.12, 1.28], [window_w / 2 + 0.05, 0.13, 0.035], 'steel_light', layer)

    def shell(self):
        W, D, H = self.width, self.depth, self.height
        floor = self.body('floor')
        if any('floor_rgba' in r for r in self.cfg['regions']):
            # Flush, non-overlapping epoxy bays: no coplanar coloured overlays.
            xs = sorted({-W / 2, W / 2, *[r['bounds_xy_m'][i] for r in self.cfg['regions'] for i in (0, 2)]})
            ys = sorted({-D / 2, D / 2, *[r['bounds_xy_m'][i] for r in self.cfg['regions'] for i in (1, 3)]})
            for a, c in zip(xs, xs[1:]):
                for b, d in zip(ys, ys[1:]):
                    x, y = (a + c) / 2, (b + d) / 2
                    region = next(
                        (
                            r
                            for r in self.cfg['regions']
                            if r['bounds_xy_m'][0] < x < r['bounds_xy_m'][2]
                            and r['bounds_xy_m'][1] < y < r['bounds_xy_m'][3]
                        ),
                        None,
                    )
                    material = 'zone_floor_' + region['id'] if region and 'floor_rgba' in region else 'floor'
                    self.box(floor, [x, y, -0.07], [(c - a) / 2, (d - b) / 2, 0.07], material)
        else:
            self.box(floor, [0, 0, -0.07], [W / 2, D / 2, 0.07], 'floor')
        # Thin inset seams and sparse patches; no workstation-sized grid.
        spacing = self.cfg['appearance']['floor_joint_spacing_m']
        for x in np.arange(-W / 2 + spacing, W / 2, spacing):
            self.box(floor, [x, 0, 0.0008], [0.004, D / 2, 0.0008], 'band')
        for y in np.arange(-D / 2 + spacing, D / 2, spacing):
            self.box(floor, [0, y, 0.0008], [W / 2, 0.004, 0.0008], 'band')
        self.wall_geometry()
        # Real perimeter steel columns, flanges and protective feet.
        for side, x in [('west', -W / 2 + 0.25), ('east', W / 2 - 0.25)]:
            n = round(D / 6)
            for i, y in enumerate(np.linspace(-D / 2 + 0.2, D / 2 - 0.2, n + 1)):
                b = self.body(f'{side}_column_{i}', [x, y, 0], category='structure')
                self.box(b, [0, 0, H / 2], [0.075, 0.14, H / 2], 'steel')
                for xx in [-0.12, 0.12]:
                    self.box(b, [xx, 0, H / 2], [0.025, 0.18, H / 2], 'steel')
                self.box(b, [0, 0, 0.035], [0.25, 0.25, 0.035], 'steel_light', bevel=0.015)
                self.box(b, [0, 0, 0.5], [0.18, 0.2, 0.45], 'yellow', bevel=0.025)
                for z in [0.3, 0.65]:
                    self.box(b, [0, -0.205, z], [0.18, 0.012, 0.045], 'black')
        roof = self.body('roof', group='roof')
        rise = self.cfg['building']['roof_rise_m']
        slope = math.atan2(rise, W / 2)
        for side in [-1, 1]:
            r = np.array(
                [
                    [math.cos(slope), 0, side * math.sin(slope)],
                    [0, 1, 0],
                    [-side * math.sin(slope), 0, math.cos(slope)],
                ]
            )
            self.box(
                roof,
                [side * W / 4, 0, H + rise / 2],
                [math.hypot(W / 2, rise) / 2, D / 2 + 0.15, 0.055],
                'roof',
                'roof',
                rotation=r,
            )
        for y in np.linspace(-D / 2 + 0.25, D / 2 - 0.25, round(D / 6) + 1):
            self.line(roof, [-W / 2, y, H], [0, y, H + rise], 0.07, 'steel', 'roof')
            self.line(roof, [0, y, H + rise], [W / 2, y, H], 0.07, 'steel', 'roof')
            for z in [H - 0.28, H - 0.48]:
                self.box(roof, [0, y, z], [W / 2, 0.11, 0.025], 'steel', 'roof')
            self.box(roof, [0, y, H - 0.38], [W / 2, 0.025, 0.1], 'steel', 'roof')
            nodes = np.linspace(-W / 2, W / 2, 13)
            for j, (a, b) in enumerate(zip(nodes, nodes[1:])):
                topx = b if j % 2 == 0 else a
                bottomx = a if j % 2 == 0 else b
                self.line(
                    roof,
                    [bottomx, y, H - 0.38],
                    [topx, y, H + rise * (1 - abs(topx) / (W / 2))],
                    0.027,
                    'steel',
                    'roof',
                )
        for x in np.arange(-W / 2 + 2, W / 2, 3.5):
            z = H + rise * (1 - abs(x) / (W / 2)) - 0.09
            self.box(roof, [x, 0, z], [0.045, D / 2, 0.065], 'steel_light', 'roof')

    def infrastructure(self):
        W, D, H = self.width, self.depth, self.height
        b = self.body('lighting_and_trays', group='roof', category='infrastructure')
        for x in np.linspace(-W / 2 + 5, W / 2 - 5, 7):
            for y in np.linspace(-D / 2 + 4, D / 2 - 4, 6):
                z = H - 0.95
                self.box(b, [x, y, z], [1.15, 0.13, 0.055], 'steel_light', 'roof', bevel=0.015)
                self.box(b, [x, y, z - 0.06], [1.08, 0.10, 0.008], 'lamp', 'roof')
                for dx in [-0.8, 0.8]:
                    self.line(b, [x + dx, y, z + 0.05], [x + dx, y, H + 0.05], 0.006, 'steel', 'roof')
        for x in [-W / 2 + 1.2, W / 2 - 1.2, -3.2, 3.2]:
            z = H - 0.65
            for dx in [-0.18, 0.18]:
                self.box(b, [x + dx, 0, z], [0.025, D / 2 - 0.4, 0.055], 'steel_light', 'roof')
            for y in np.arange(-D / 2 + 0.5, D / 2, 0.6):
                self.box(b, [x, y, z - 0.045], [0.18, 0.025, 0.015], 'steel_light', 'roof')
            for k in range(3):
                self.line(
                    b,
                    [x - 0.1 + k * 0.08, -D / 2 + 0.5, z + 0.015],
                    [x - 0.1 + k * 0.08, D / 2 - 0.5, z + 0.015],
                    0.012,
                    'black' if k != 1 else 'yellow',
                    'roof',
                )
        # Pipe headers run along the actual perimeter, with bends and descent supports.
        for side in [-1, 1]:
            x = side * (W / 2 - 0.32)
            for zz, mat in [(H - 1.05, 'steel_light'), (H - 1.32, 'black')]:
                self.line(b, [x, -D / 2 + 0.4, zz], [x, D / 2 - 0.4, zz], 0.035, mat, 'roof')
            for y in np.arange(-D / 2 + 2, D / 2, 6):
                self.line(b, [x, y, H - 1.45], [x, y, H - 0.3], 0.009, 'steel', 'roof')

    def paint(self):
        b = self.body('area_markings', category='markings')
        half = self.cfg['appearance']['region_line_width_m'] / 2
        for region in self.cfg['regions']:
            x0, y0, x1, y1 = region['bounds_xy_m']
            material = 'zone_accent_' + region['id'] if region.get('accent_rgba') else 'yellow'
            for y in [y0, y1]:
                self.box(b, [(x0 + x1) / 2, y, 0.002], [abs(x1 - x0) / 2, half, 0.001], material)
            for x in [x0, x1]:
                self.box(b, [x, (y0 + y1) / 2, 0.002], [half, abs(y1 - y0) / 2, 0.001], material)
        # Main circulation marks only: no task-table rectangles.
        for x in [-0.85, 0.85]:
            for y in np.arange(-self.depth / 2 + 2, self.depth / 2 - 2, 3.5):
                self.box(b, [x, y, 0.002], [half, 0.55, 0.001], 'yellow')

    def cabinet(self, name, pos, yaw=0, kind='electrical'):
        b = self.body(name, pos, yaw, category='perimeter_equipment')
        w, d, h = (1.1, 0.55, 2.0) if kind == 'electrical' else (0.92, 0.50, 0.95)
        self.box(b, [0, 0, h / 2], [w / 2, d / 2, h / 2 - 0.035], 'cabinet', bevel=0.025)
        self.box(b, [0, 0, 0.05], [w / 2 - 0.045, d / 2 - 0.025, 0.05], 'black')
        if kind == 'electrical':
            for xx in [-w / 4, w / 4]:
                self.box(
                    b,
                    [xx, -d / 2 - 0.008, h / 2],
                    [w / 4 - 0.012, 0.014, h / 2 - 0.08],
                    'cabinet',
                    bevel=0.008,
                )
                self.box(b, [xx + 0.15, -d / 2 - 0.032, 1.03], [0.012, 0.018, 0.09], 'black', bevel=0.006)
            self.box(b, [0, -d / 2 - 0.035, 1.62], [0.13, 0.017, 0.09], 'cabinet_dark', bevel=0.008)
            self.box(b, [0, -d / 2 - 0.055, 1.62], [0.1, 0.004, 0.06], 'blue')
            for j in range(6):
                self.box(b, [0.33, -d / 2 - 0.026, 0.22 + j * 0.027], [0.14, 0.006, 0.004], 'black')
            self.sign(
                b, name + '_label', 'RF / POWER', [0, -d / 2 - 0.029, 1.87], [0.38, 0.065], bg=(160, 168, 168)
            )
        else:
            for j in range(5):
                z = 0.18 + j * 0.14
                self.box(b, [0, -d / 2 - 0.015, z], [w / 2 - 0.035, 0.018, 0.06], 'cabinet_dark', bevel=0.007)
                self.box(b, [0, -d / 2 - 0.04, z + 0.025], [w * 0.33, 0.015, 0.009], 'steel_light')
        R = _rz(yaw)
        half = np.abs(R[:2, :2]) @ np.array([w / 2, d / 2])
        self.props.append(
            dict(
                id='factory_' + name,
                bounds_xy_m=[pos[0] - half[0], pos[1] - half[1], pos[0] + half[0], pos[1] + half[1]],
            )
        )

    def bin(self, parent, pos, w=0.32, d=0.35, h=0.22):
        x, y, z = pos
        self.box(parent, [x, y, z + 0.012], [w / 2, d / 2, 0.012], 'blue', bevel=0.008)
        for xx in [-w / 2 + 0.012, w / 2 - 0.012]:
            self.box(parent, [x + xx, y, z + h / 2], [0.012, d / 2, h / 2], 'blue', bevel=0.006)
        self.box(parent, [x, y + d / 2 - 0.012, z + h / 2], [w / 2, 0.012, h / 2], 'blue')
        self.box(parent, [x, y - d / 2 + 0.012, z + h * 0.28], [w / 2, 0.012, h * 0.28], 'blue', bevel=0.006)
        self.box(parent, [x, y - d / 2 - 0.002, z + 0.035], [w * 0.2, 0.003, 0.018], 'label')

    def rack(self, name, pos, yaw=0):
        b = self.body(name, pos, yaw, category='perimeter_equipment')
        w, d, h = 2.0, 0.65, 2.25
        for x in [-w / 2, w / 2]:
            for y in [-d / 2, d / 2]:
                self.box(b, [x, y, h / 2], [0.025, 0.025, h / 2], 'steel_light')
                self.box(b, [x, y, 0.015], [0.055, 0.055, 0.015], 'steel')
        for z in [0.17, 0.7, 1.23, 1.76]:
            self.box(b, [0, 0, z], [w / 2, d / 2, 0.025], 'steel')
            for i, x in enumerate([-0.72, -0.25, 0.25, 0.72]):
                if i == 0 and z < 0.3:
                    self.box(b, [x, 0, z + 0.2], [0.20, 0.24, 0.18], 'cardboard', bevel=0.008)
                    self.box(b, [x, 0, z + 0.385], [0.025, 0.24, 0.003], 'tape')
                else:
                    self.bin(b, [x, -0.03, z + 0.03], w=0.38, d=0.47, h=0.27)
        for xx in [-w / 2, w / 2]:
            self.box(b, [xx, 0, 2.23], [0.025, d / 2, 0.025], 'steel_light')
        for x in [-0.45, 0.40]:
            self.box(b, [x, 0.04, 2.0], [0.26, 0.22, 0.20], 'cardboard', bevel=0.008)
            self.box(b, [x, 0.04, 2.204], [0.025, 0.22, 0.003], 'tape')
        self.line(b, [-w / 2, d / 2, 0.15], [w / 2, d / 2, h], 0.012, 'steel')
        self.line(b, [w / 2, d / 2, 0.15], [-w / 2, d / 2, h], 0.012, 'steel')
        R = _rz(yaw)
        half = np.abs(R[:2, :2]) @ np.array([w / 2 + 0.06, d / 2 + 0.06])
        self.props.append(
            dict(
                id='factory_' + name,
                bounds_xy_m=[pos[0] - half[0], pos[1] - half[1], pos[0] + half[0], pos[1] + half[1]],
            )
        )

    def plant(self, name, pos):
        b = self.body(name, pos, category='perimeter_equipment')
        self.cylinder(b, [0, 0, 0.22], 0.22, 0.22, 'pot')
        for k in range(10):
            a = k * 2.399
            tip = np.array([0.36 * math.cos(a), 0.36 * math.sin(a), 1.05 + 0.35 * math.sin(k * 1.1)])
            self.line(b, [0, 0, 0.4], tip, 0.008, 'green')
            for q in [0.5, 0.75, 1.0]:
                p = tip * q
                direction = np.array([math.cos(a), math.sin(a), 0.3])
                end = p + direction * 0.20
                self.line(b, p, end, 0.035, 'leaf_light' if k % 3 == 0 else 'green')
        self.props.append(
            dict(id='factory_' + name, bounds_xy_m=[pos[0] - 0.6, pos[1] - 0.6, pos[0] + 0.6, pos[1] + 0.6])
        )

    def extinguisher(self, name, pos, yaw):
        b = self.body(name, pos, yaw, category='perimeter_equipment')
        self.box(b, [0, 0.03, 0.50], [0.16, 0.035, 0.38], 'red', bevel=0.015)
        self.cylinder(b, [0, -0.10, 0.46], 0.075, 0.23, 'red')
        self.box(b, [0, -0.10, 0.72], [0.055, 0.04, 0.025], 'black', bevel=0.01)
        self.line(b, [0.07, -0.1, 0.72], [0.12, -0.1, 0.35], 0.012, 'black')
        self.box(b, [0, -0.178, 0.47], [0.043, 0.004, 0.08], 'label')

    def equipment(self):
        W, D = self.width, self.depth
        if not self.cfg['appearance']['include_perimeter_storage']:
            return
        for side in [-1, 1]:
            # Front of local furniture is -Y. Rotate to face the room from each side.
            yaw = -side * math.pi / 2
            x = side * (W / 2 - 0.58)
            for i, y in enumerate(np.linspace(-D / 2 + 3.5, D / 2 - 3.5, 6)):
                if i % 3 == 0:
                    self.cabinet(f'side_{side}_electrical_{i}', [x, y, 0], yaw)
                    self.extinguisher(f'side_{side}_fire_{i}', [side * (W / 2 - 0.25), y + 1.1, 0], yaw)
                elif i % 3 == 1:
                    self.rack(f'side_{side}_rack_{i}', [x, y, 0], yaw)
                else:
                    self.cabinet(f'side_{side}_drawer_{i}', [x, y, 0], yaw, 'drawer')
            if self.cfg['appearance']['include_plants']:
                for y in [-D / 2 + 1.3, D / 2 - 1.3]:
                    self.plant(f'plant_{side}_{int(y)}', [side * (W / 2 - 0.7), y, 0])
        for side in [-1, 1]:
            y = side * (D / 2 - 0.6)
            yaw = 0 if side == 1 else math.pi
            for i, x in enumerate([-17, -13, -8, 8, 13, 17]):
                if abs(x) > W / 2 - 2:
                    continue
                if i % 2:
                    self.cabinet(f'end_{side}_cabinet_{i}', [x, y, 0], yaw)
                else:
                    self.rack(f'end_{side}_rack_{i}', [x, y, 0], yaw)
            for x in [-4.3, 4.3]:
                self.extinguisher(f'end_{side}_fire_{x}', [x, side * (D / 2 - 0.18), 0], yaw)
        # Conduit drops join the perimeter headers to selected cabinets.
        b = self.body('electrical_conduits', category='infrastructure')
        for side in [-1, 1]:
            for y in [-D / 2 + 3.5, D / 2 - 3.5]:
                x = side * (W / 2 - 0.2)
                self.line(b, [x, y, 2.0], [x, y, self.height - 1.05], 0.018, 'steel_light')
                for z in [2.3, 3.6, 4.9]:
                    self.box(b, [x, y, z], [0.04, 0.035, 0.015], 'steel')

    def cart(self, name, pos, yaw=0):
        b = self.body(name, pos, yaw, category='perimeter_equipment')
        for z in [0.25, 0.85]:
            self.box(b, [0, 0, z], [0.58, 0.33, 0.025], 'steel_light', bevel=0.015)
            for y in [-0.32, 0.32]:
                self.box(b, [0, y, z + 0.045], [0.58, 0.016, 0.045], 'cabinet_dark')
        for x in [-0.54, 0.54]:
            for y in [-0.28, 0.28]:
                self.box(b, [x, y, 0.54], [0.018, 0.018, 0.43], 'steel_light')
                self.cylinder(b, [x, y, 0.10], 0.09, 0.025, 'black', rotation=_rx(math.pi / 2))
        for z in [0.28, 0.88]:
            for x in [-0.28, 0.25]:
                self.bin(b, [x, -0.02, z], w=0.42, d=0.48, h=0.22)
        self.line(b, [0.6, -0.3, 0.85], [0.6, -0.3, 1.08], 0.018, 'steel_light')
        self.line(b, [0.6, 0.3, 0.85], [0.6, 0.3, 1.08], 0.018, 'steel_light')
        self.line(b, [0.6, -0.3, 1.08], [0.6, 0.3, 1.08], 0.018, 'steel_light')

    def tool_station(self, name, pos, yaw=0):
        """A compact maintenance drawer unit and real framed shadow board."""
        self.cabinet(name + '_base', pos, yaw, 'drawer')
        b = self.body(name + '_board', pos, yaw, category='perimeter_equipment')
        for x in [-0.46, 0.46]:
            self.box(b, [x, 0.18, 1.42], [0.025, 0.025, 0.5], 'steel_light')
        self.box(b, [0, 0.18, 1.58], [0.55, 0.035, 0.43], 'steel_light', bevel=0.015)
        self.panel(b, 'tools', [0, 0.141, 1.58], [1.05, 0.79])
        # A few tangible handles stand proud of the cheap printed silhouette detail.
        for x in [-0.32, -0.16, 0.02, 0.20]:
            self.box(b, [x, 0.105, 1.50], [0.017, 0.018, 0.10], 'blue', bevel=0.008)
            self.line(b, [x, 0.105, 1.60], [x, 0.105, 1.72], 0.009, 'steel_light')

    def hose_reel(self, name, pos, yaw=0):
        b = self.body(name, pos, yaw, category='perimeter_equipment')
        self.box(b, [0, 0.08, 0.62], [0.04, 0.06, 0.56], 'steel_light')
        self.box(b, [0, 0.06, 0.035], [0.22, 0.21, 0.035], 'steel_light', bevel=0.015)
        for y in [-0.04, -0.16]:
            self.cylinder(b, [0, y, 1.08], 0.21, 0.018, 'blue', rotation=_rx(math.pi / 2))
        self.cylinder(b, [0, -0.10, 1.08], 0.17, 0.055, 'black', rotation=_rx(math.pi / 2))
        self.cylinder(b, [0, -0.185, 1.08], 0.045, 0.018, 'steel_light', rotation=_rx(math.pi / 2))
        for a, c in [
            ([0.16, -0.1, 1.02], [0.24, -0.1, 0.65]),
            ([0.24, -0.1, 0.65], [0.18, -0.1, 0.30]),
            ([0.18, -0.1, 0.30], [-0.08, -0.1, 0.22]),
        ]:
            self.line(b, a, c, 0.014, 'black')

    def detail_equipment(self):
        W, D, H = self.width, self.depth, self.height
        # Fill perimeter gaps only: leave the future task regions and aisle untouched.
        for side in [-1, 1]:
            yaw = -side * math.pi / 2
            x = side * (W / 2 - 0.70)
            for i, y in enumerate([-14, -7, 0, 7, 14]):
                if i in [0, 4]:
                    self.rack(f'detail_{side}_rack_{i}', [x, y, 0], yaw)
                elif i in [1, 3]:
                    self.tool_station(f'detail_{side}_tools_{i}', [x, y, 0], yaw)
                else:
                    self.cart(f'detail_{side}_cart', [x, y, 0], yaw)
            for i, y in enumerate([-5.4, 5.4]):
                self.hose_reel(f'detail_{side}_reel_{i}', [side * (W / 2 - 0.48), y, 0], yaw)
            # Structural IDs and real conduit junctions, not floating billboard labels.
            for i, y in enumerate(np.linspace(-D / 2 + 0.2, D / 2 - 0.2, round(D / 6) + 1)):
                b = self.body(
                    f'column_plate_{side}_{i}', [side * (W / 2 - 0.09), y, 0], yaw, category='infrastructure'
                )
                self.sign(
                    b,
                    f'bay_{side}_{i}',
                    f'{"A" if side < 0 else "B"}{i + 1:02}',
                    [0, -0.34, 3.25],
                    [0.46, 0.54],
                )
                self.box(b, [0, -0.23, 1.9], [0.14, 0.08, 0.18], 'cabinet', bevel=0.012)
                self.line(b, [0, -0.23, 2.08], [0, -0.23, H - 1.2], 0.018, 'steel_light')
                self.panel(b, 'safety', [0, -0.318, 1.9], [0.23, 0.30])
        for side in [-1, 1]:
            y = side * (D / 2 - 0.72)
            yaw = 0 if side == 1 else math.pi
            for x in [-20.5, 20.5]:
                self.rack(f'detail_end_{side}_rack_{x}', [x, y, 0], yaw)
            for x in [-10.5, 10.5]:
                self.tool_station(f'detail_end_{side}_tools_{x}', [x, y, 0], yaw)
            for x in [-5.5, 5.5]:
                self.cart(f'detail_end_{side}_cart_{x}', [x, y, 0], yaw)
            b = self.body(
                f'end_wall_detail_{side}',
                [0, side * D / 2, 0],
                yaw,
                'north' if side == 1 else 'south',
                category='infrastructure',
            )
            layer = 'north' if side == 1 else 'south'
            for x in [-18, -12, -6, 6, 12, 18]:
                self.box(b, [x, -0.10, 3.7], [0.007, 0.005, 3.45], 'cabinet_dark', layer)
            for x, kind in [(-13, 'process'), (13, 'safety')]:
                self.box(b, [x, -0.14, 3.05], [1.4, 0.045, 0.66], 'steel_light', layer, bevel=0.02)
                self.panel(b, kind, [x, -0.189, 3.05], [2.72, 1.24], layer)
            for x in [-7.0, 7.0]:
                self.box(b, [x, -0.18, 2.6], [0.22, 0.08, 0.3], 'cabinet', layer, bevel=0.015)
                for dx in [-0.09, 0.09]:
                    self.line(b, [x + dx, -0.17, 2.9], [x + dx, -0.17, H - 1.1], 0.017, 'steel_light', layer)
                self.panel(b, 'safety', [x, -0.267, 2.6], [0.34, 0.45], layer)
        # Ventilation above the windows; joints, outlets and hangers give functional scale.
        b = self.body('ventilation', group='roof', category='infrastructure')
        for side in [-1, 1]:
            x = side * (W / 2 - 1.0)
            z = H - 1.6
            self.box(b, [x, 0, z], [0.28, D / 2 - 0.6, 0.24], 'steel_light', 'roof', bevel=0.025)
            for y in np.arange(-D / 2 + 1.5, D / 2 - 1, 3):
                self.box(b, [x, y, z], [0.30, 0.025, 0.26], 'cabinet_dark', 'roof')
                self.line(b, [x - 0.32, y, z - 0.27], [x - 0.32, y, H - 0.1], 0.009, 'steel', 'roof')
                self.line(b, [x + 0.32, y, z - 0.27], [x + 0.32, y, H - 0.1], 0.009, 'steel', 'roof')
            for y in np.arange(-D / 2 + 4, D / 2 - 2, 6):
                self.box(b, [x - side * 0.29, y, z], [0.012, 0.42, 0.15], 'black', 'roof')
                for dy in np.linspace(-0.38, 0.38, 12):
                    self.box(b, [x - side * 0.31, y + dy, z], [0.018, 0.012, 0.135], 'steel_light', 'roof')
        # Cross-hall utility lines with sparse clips; no additional real lights/shadow maps.
        for y in [-D / 2 + 1.5, D / 2 - 1.5]:
            self.line(
                b, [-W / 2 + 0.5, y, H - 1.15], [W / 2 - 0.5, y, H - 1.15], 0.035, 'steel_light', 'roof'
            )
            self.line(b, [-W / 2 + 0.5, y, H - 1.38], [W / 2 - 0.5, y, H - 1.38], 0.023, 'red', 'roof')
            for x in np.arange(-W / 2 + 2, W / 2, 4):
                self.line(b, [x, y, H - 1.46], [x, y, H - 0.15], 0.008, 'steel', 'roof')

    def workstation_dressing(self):
        """Hall-only furniture fitted to real solid tabletop footprints."""
        self.workstation_props = []
        settings = self.cfg.get('workstation_dressing', {})
        if not settings.get('enabled'):
            return
        import mujoco

        from roboteam.sim.hall.desks import placements
        from roboteam.sim.workstation import Workstation

        catalog_path = ROOT / settings['catalog']
        catalog = json.loads(catalog_path.read_text())
        if 'task_types' in catalog:
            # The release itself: one workstation per released case.
            def facts(task_type, case_id):
                listed = json.loads((ROOT / 'benchmark' / task_type / 'catalog.json').read_text())['cases']
                return next(
                    {k: c[k] for k in ('level', 'arms', 'dials') if k in c}
                    for c in listed
                    if c['id'] == case_id
                )

            catalog = {
                'cases': [
                    {
                        'task_type': task_type,
                        'id': row['id'],
                        'directory': row['directory'],
                        **facts(task_type, row['id']),
                    }
                    for task_type, entry in catalog['task_types'].items()
                    for row in entry['policy']
                ]
            }
        self.dressing_catalog_sha256 = _hash(catalog_path)
        plan = placements(catalog, self.cfg['regions'], ROOT)
        self.dressing_plan = plan
        for place in plan:
            source = Workstation(ROOT / place['source_directory'])
            source.frame()
            m, d = source.model, source.data
            task = json.loads((source.path / 'task.json').read_text())
            height = task['table_height_m']
            if height < 0.70:
                continue
            table_ids = [
                i
                for i in range(m.ngeom)
                if m.geom(i).name.startswith('table_') and 'leg' not in m.geom(i).name
            ]
            original = m.geom_group.copy()
            m.geom_group[:] = 5
            m.geom_group[table_ids] = 0
            mask = np.array([1, 0, 0, 0, 0, 0], np.uint8)

            def solid(x, y):
                hit = mujoco.mj_ray(
                    m, d, np.array([x, y, height + 0.05]), np.array([0.0, 0.0, -1.0]), mask, True, -1, None
                )
                return 0 <= hit < 0.09

            legs = np.array(
                [d.geom_xpos[i, :2] for i in range(m.ngeom) if m.geom(i).name.startswith('table_leg_')]
            )
            env = json.loads((source.path / 'environment.json').read_text())
            chosen = []
            for table in env['tables']:
                cx, cy, _ = table['center_m']
                hx, hy, _ = table['half_size_m']
                for x in np.arange(cx - hx + 0.65, cx + hx - 0.60, 1.35):
                    for y in np.arange(cy - hy + 0.50, cy + hy - 0.45, 1.15):
                        if len(chosen) >= min(6, max(2, task['scale']['arms'] // 2)):
                            break
                        if any(np.linalg.norm(np.array([x, y]) - q) < 1.15 for q in chosen):
                            continue
                        if len(legs) and np.min(np.linalg.norm(legs - np.array([x, y]), axis=1)) < 0.70:
                            continue
                        if not all(solid(x + dx, y + dy) for dx in (-0.46, 0.46) for dy in (-0.28, 0.28)):
                            continue
                        chosen.append(np.array([x, y]))
            m.geom_group[:] = original
            for index, p in enumerate(chosen):
                position = [p[0] + place['translation_m'][0], p[1] + place['translation_m'][1], 0.0]
                name = 'underbench_' + place['case_id'] + '_' + str(index)
                b = self.body(name, position, category='workstation_storage')
                # Furniture has real thickness, feet, pulls, seams and ventilation.
                variant = index % 4
                if variant in (0, 1):
                    self.box(b, [0, 0, 0.34], [0.43, 0.25, 0.29], 'cabinet', bevel=0.014)
                    for x in (-0.37, 0.37):
                        for y in (-0.19, 0.19):
                            self.cylinder(b, [x, y, 0.035], 0.025, 0.035, 'black')
                    if variant == 0:
                        for j, z in enumerate((0.18, 0.36, 0.54)):
                            self.box(
                                b,
                                [0, -0.257, z],
                                [0.41, 0.009, 0.078],
                                'cabinet_dark' if j == 0 else 'cabinet',
                                bevel=0.006,
                            )
                            self.line(
                                b, [-0.13, -0.279, z + 0.025], [0.13, -0.279, z + 0.025], 0.009, 'steel'
                            )
                    else:
                        # Electrical enclosure: one access door, hinges and filter.
                        self.box(b, [0, -0.260, 0.34], [0.405, 0.014, 0.265], 'cabinet', bevel=0.007)
                        self.line(b, [0.29, -0.286, 0.30], [0.29, -0.286, 0.42], 0.011, 'steel')
                        for z in (0.17, 0.51):
                            self.box(b, [-0.38, -0.28, z], [0.018, 0.012, 0.035], 'steel_light')
                        for z in np.arange(0.17, 0.36, 0.035):
                            self.box(b, [-0.15, -0.279, z], [0.13, 0.003, 0.004], 'black')
                    for z in np.arange(0.16, 0.52, 0.055):
                        self.box(b, [0.433, 0.03, z], [0.0015, 0.15, 0.005], 'black')
                else:
                    for z in (0.08, 0.37, 0.65):
                        self.box(b, [0, 0, z], [0.45, 0.27, 0.018], 'steel_light', bevel=0.006)
                    for x in (-0.43, 0.43):
                        for y in (-0.25, 0.25):
                            self.box(b, [x, y, 0.34], [0.018, 0.018, 0.32], 'steel')
                    for x in (-0.22, 0.22):
                        self.bin(b, [x, -0.01, 0.11], w=0.34, d=0.43, h=0.20)
                    if variant == 2:
                        self.box(b, [0.04, 0.03, 0.51], [0.31, 0.20, 0.10], 'cardboard', bevel=0.008)
                        self.box(b, [0.04, 0.03, 0.612], [0.025, 0.20, 0.001], 'tape')
                    else:
                        for j, z in enumerate((0.44, 0.52, 0.60)):
                            self.box(b, [0, 0, z], [0.37, 0.22, 0.032], 'steel', bevel=0.004)
                            self.box(b, [0.21, -0.225, z], [0.085, 0.004, 0.012], 'label')
                            self.cylinder(
                                b, [-0.31, -0.228, z], 0.005, 0.003, 'green', rotation=_rx(math.pi / 2)
                            )
                if self.cfg['appearance'].get('fine_service_detail', False):
                    self.box(b, [-0.28, -0.265, 0.59], [0.10, 0.003, 0.024], 'label')
                    for k in range(5):
                        self.box(b, [-0.35 + k * 0.035, -0.269, 0.59], [0.009, 0.001, 0.010], 'cabinet_dark')
                    self.cylinder(b, [0.34, -0.267, 0.61], 0.009, 0.004, 'green', rotation=_rx(math.pi / 2))
                    # A service loop lies within the verified solid tabletop.
                    points = [
                        [0.28 + 0.09 * math.cos(t), -0.274, 0.34 + 0.09 * math.sin(t)]
                        for t in np.linspace(0, 2 * math.pi, 17)
                    ]
                    for a, z in zip(points, points[1:]):
                        self.line(b, a, z, 0.006, 'black')
                self.workstation_props.append(
                    dict(
                        id=name,
                        case_id=place['case_id'],
                        position_m=position,
                        footprint_half_m=[0.46, 0.28],
                        top_m=0.67,
                        physical=False,
                        placement='Below verified solid tabletop; not a swept-motion certificate',
                    )
                )
        # Region-corner staging islands stay outside all planned robot/load bays.
        for region in self.cfg['regions']:
            x0, y0, x1, y1 = region['bounds_xy_m']
            occupied = [p['planning_bounds_xy_m'] for p in plan if p['task_type'] == region['id']]
            for index, (x, y) in enumerate(((x0 + 0.7, y0 + 0.65), (x1 - 0.7, y1 - 0.65))):
                if any(
                    x + 0.45 > a and x - 0.45 < c and y + 0.38 > b and y - 0.38 < d for a, b, c, d in occupied
                ):
                    continue
                name = 'staging_' + region['id'] + '_' + str(index)
                b = self.body(name, [x, y, 0], category='floor_storage')
                for yy in (-0.27, 0, 0.27):
                    self.box(b, [0, yy, 0.055], [0.42, 0.045, 0.045], 'cardboard', bevel=0.008)
                for xx in (-0.34, -0.17, 0, 0.17, 0.34):
                    self.box(b, [xx, 0, 0.115], [0.045, 0.33, 0.016], 'cardboard', bevel=0.003)
                for j, (xx, yy, hh) in enumerate(
                    ((-0.20, -0.12, 0.20), (0.20, 0.08, 0.26), (-0.12, 0.10, 0.18))
                ):
                    zz = 0.13 + hh / 2 + (0 if j < 2 else 0.23)
                    self.box(b, [xx, yy, zz], [0.17, 0.14, hh / 2], 'cardboard', bevel=0.006)
                    self.box(b, [xx, yy, zz + hh / 2 + 0.001], [0.025, 0.14, 0.001], 'tape')
                self.workstation_props.append(
                    dict(
                        id=name,
                        position_m=[x, y, 0],
                        footprint_half_m=[0.45, 0.38],
                        top_m=0.57,
                        physical=False,
                        placement='Region corner outside initial planning envelopes',
                    )
                )
                if self.cfg['appearance'].get('fine_service_detail', False):
                    overhead = self.body(
                        'pendant_' + region['id'] + '_' + str(index),
                        [x, y, 0],
                        group='roof',
                        category='infrastructure',
                    )
                    self.line(overhead, [0, 0, self.height - 0.7], [0, 0, 3.55], 0.009, 'black', 'roof')
                    self.cylinder(overhead, [0, 0, 3.43], 0.09, 0.12, 'yellow', 'roof')
                    self.line(overhead, [0, 0, 3.31], [0, 0, 3.13], 0.018, 'black', 'roof')

    def service_equipment(self):
        """Functional service connections and varied equipment in reserved space."""
        if not self.cfg['appearance'].get('service_equipment', False):
            return
        for index, prop in enumerate(getattr(self, 'workstation_props', [])):
            if not prop['id'].startswith('underbench_'):
                continue
            b = self.body('service_' + prop['id'], prop['position_m'], category='workstation_services')
            # All fittings remain below the verified solid tabletop footprint.
            self.box(b, [0, 0.22, 0.69], [0.40, 0.035, 0.025], 'steel_light', bevel=0.004)
            self.box(b, [0.30, -0.269, 0.49], [0.075, 0.012, 0.09], 'cabinet_dark', bevel=0.005)
            for x in (0.265, 0.305, 0.345):
                self.cylinder(
                    b,
                    [x, -0.289, 0.51],
                    0.009,
                    0.008,
                    'yellow' if x == 0.305 else 'black',
                    rotation=_rx(math.pi / 2),
                )
            for k in range(3):
                x = -0.32 + k * 0.065
                points = [[x, 0.24, 0.68], [x, 0.24, 0.47], [x + 0.035, 0.24, 0.22], [x + 0.10, 0.22, 0.12]]
                for a, z in zip(points, points[1:]):
                    self.line(b, a, z, 0.007, 'black')
            if index % 2 == 0:
                self.box(b, [-0.28, 0.02, 0.075], [0.09, 0.15, 0.035], 'blue', bevel=0.01)
                self.line(b, [-0.28, 0.16, 0.11], [-0.28, 0.22, 0.60], 0.012, 'black')
        # Plant equipment occupies the existing perimeter service strip.
        for side in (-1, 1):
            candidates = np.arange(-self.depth / 2 + 2.5, self.depth / 2 - 2.0, 2.8)
            chosen = []
            for y in candidates:
                x = side * (self.width / 2 - 0.65)
                if any(
                    x + 0.42 > a and x - 0.42 < c and y + 1.2 > b and y - 1.2 < d
                    for a, b, c, d in [p['bounds_xy_m'] for p in self.props]
                ):
                    continue
                if any(abs(y - old) < 2.8 for old in chosen):
                    continue
                chosen.append(float(y))
                if len(chosen) == 4:
                    break
            for i, y in enumerate(chosen):
                x = side * (self.width / 2 - 0.65)
                b = self.body(
                    'plant_' + str(side) + '_' + str(i),
                    [x, y, 0],
                    yaw=-side * math.pi / 2,
                    category='wall_services',
                )
                if i % 2 == 0:
                    self.cylinder(b, [0, 0, 0.48], 0.25, 0.46, 'blue', rotation=_rx(math.pi / 2))
                    for xx in (-0.18, 0.18):
                        self.box(b, [xx, 0, 0.13], [0.035, 0.28, 0.13], 'steel')
                    self.box(b, [0, 0, 0.83], [0.15, 0.20, 0.11], 'steel', bevel=0.025)
                    for xx in (-0.10, 0, 0.10):
                        self.line(b, [xx, -0.20, 0.84], [xx, 0.20, 0.84], 0.015, 'steel_light')
                    self.line(b, [0.22, 0, 0.50], [0.34, 0, 1.05], 0.018, 'steel_light')
                else:
                    self.box(b, [0, 0, 0.62], [0.31, 0.27, 0.58], 'cabinet', bevel=0.015)
                    self.box(b, [0, -0.28, 0.76], [0.25, 0.012, 0.35], 'cabinet_dark', bevel=0.007)
                    for zz in (0.46, 0.53, 0.60, 0.67):
                        self.box(b, [0, -0.296, zz], [0.20, 0.004, 0.009], 'black')
                    self.box(b, [0, -0.30, 1.02], [0.15, 0.006, 0.07], 'label', bevel=0.004)
                    for xx in (-0.13, 0.13):
                        self.line(b, [xx, 0.25, 1.18], [xx, 0.25, 2.35], 0.022, 'steel_light')
                # Adjacent reusable tote stacks and grounded protective posts.
                for j in range(3):
                    self.bin(b, [0.75, 0.0, 0.10 + j * 0.20], w=0.48, d=0.40, h=0.18)
                for xx in (-0.55, 1.05):
                    self.cylinder(b, [xx, 0.30, 0.30], 0.055, 0.30, 'yellow')
                    self.box(b, [xx, 0.30, 0.025], [0.11, 0.11, 0.025], 'steel', bevel=0.006)

        for region in self.cfg['regions']:
            x0, y0, x1, y1 = region['bounds_xy_m']
            occupied = [
                p['planning_bounds_xy_m']
                for p in getattr(self, 'dressing_plan', [])
                if p['task_type'] == region['id']
            ]
            from roboteam.sim.hall.labels import bounds, overlaps, region_title

            title, half = region_title(region)
            occupied.append(bounds(title, half))
            for i, (x, y) in enumerate(
                (
                    (x0 + 0.8, (y0 + y1) / 2),
                    (x1 - 0.8, (y0 + y1) / 2),
                    ((x0 + x1) / 2, y0 + 0.8),
                    ((x0 + x1) / 2, y1 - 0.8),
                )
            ):
                for dx in (0, -5.2, 5.2, -6.5, 6.5):
                    px = x + dx
                    if not x0 + 0.7 < px < x1 - 0.7:
                        continue
                    box = bounds([px, y], [0.7, 0.5])
                    if any(overlaps(box, other, 0.10) for other in occupied):
                        continue
                    if any(overlaps(box, p['bounds_xy_m'], 0.10) for p in self.props):
                        continue
                    self.cart('supply_' + region['id'] + '_' + str(i), [px, y, 0], yaw=(i % 2) * math.pi / 2)
                    occupied.append(box)
                    break

        if self.cfg['appearance'].get('fine_service_detail', False):
            self.service_islands()
            self.facility_connections()

    def facility_connections(self):
        """Flush aisle access covers and coherent wall utilities, outside cells."""
        for i, (x, y) in enumerate(((0, -12), (0, 12), (-12, 0), (12, 0))):
            b = self.body('floor_access_' + str(i), [x, y, 0], category='floor_services')
            self.box(b, [0, 0, 0.003], [0.30, 0.24, 0.003], 'steel')
            self.box(b, [0, 0, 0.007], [0.277, 0.217, 0.001], 'cabinet_dark')
            for xx in (-0.24, 0.24):
                for yy in (-0.18, 0.18):
                    self.cylinder(b, [xx, yy, 0.009], 0.009, 0.001, 'steel_light')
        for side in (-1, 1):
            b = self.body(
                'utility_backbone_' + str(side),
                [side * (self.width / 2 - 0.18), 0, 0],
                category='wall_services',
            )
            for z in (5.22, 5.38):
                self.line(b, [0, -self.depth / 2 + 1, z], [0, self.depth / 2 - 1, z], 0.025, 'steel_light')
            for i, y in enumerate((-18.0, -6.0, 6.0, 18.0)):
                self.line(b, [0, y, 5.38], [0, y, 1.8], 0.018, 'steel_light')
                self.box(b, [-side * 0.07, y, 1.55], [0.07, 0.22, 0.25], 'cabinet', bevel=0.012)
                self.box(b, [-side * 0.146, y, 1.56], [0.006, 0.16, 0.18], 'cabinet_dark')
                for yy in (y - 0.08, y + 0.08):
                    self.cylinder(
                        b,
                        [-side * 0.16, yy, 1.57],
                        0.025,
                        0.009,
                        'black',
                        rotation=_rz(math.pi / 2) @ _rx(math.pi / 2),
                    )

    def exterior_yard(self):
        """Small actual 3D service yard for cutaways; no task geometry lives here."""
        if not self.cfg['appearance'].get('exterior_yard', False):
            return
        W, D = self.width, self.depth
        b = self.body('exterior_yard', category='exterior')
        # Ring only: no duplicate coplanar surface below the indoor floor.
        for side in (-1, 1):
            self.box(b, [side * (W / 2 + 5), 0, -0.10], [5, D / 2 + 10, 0.05], 'asphalt')
            self.box(b, [0, side * (D / 2 + 5), -0.10], [W / 2, 5, 0.05], 'asphalt')
            self.box(b, [side * (W / 2 + 0.65), 0, -0.045], [0.55, D / 2, 0.025], 'concrete')
            self.box(b, [0, side * (D / 2 + 0.65), -0.045], [W / 2, 0.55, 0.025], 'concrete')
            for y in (-18, -6, 6, 18):
                self.box(b, [side * (W / 2 + 5), y, -0.046], [0.055, 1.8, 0.004], 'yellow')
            for x in (-12, 12):
                for dx in (-0.55, 0.55):
                    self.cylinder(b, [x + dx, side * (D / 2 + 1.3), 0.37], 0.07, 0.42, 'yellow')
            for y in (-D / 2 - 6, D / 2 + 6):
                for x in (-W / 2 - 5, W / 2 + 5):
                    self.box(b, [x, y, 0.20], [0.70, 0.70, 0.25], 'concrete', bevel=0.05)
                    for j in range(5):
                        self.cylinder(b, [x - 0.5 + j * 0.25, y, 0.48], 0.20, 0.04, 'green')

    def service_islands(self):
        """Small rolling inspection/rack stations in checked gaps between cells."""
        for region in self.cfg['regions']:
            planned = [
                p['planning_bounds_xy_m'] for p in self.dressing_plan if p['task_type'] == region['id']
            ]
            xs = sorted({round((a + c) / 2, 4) for a, b, c, d in planned})
            ys = sorted({round((b + d) / 2, 4) for a, b, c, d in planned})
            candidates = [((a + c) / 2, (b + d) / 2) for a, c in zip(xs, xs[1:]) for b, d in zip(ys, ys[1:])]
            added = 0
            for x, y in candidates:
                if added >= 3:
                    break
                if any(
                    x + 0.95 > a and x - 0.95 < c and y + 0.85 > b and y - 0.85 < d for a, b, c, d in planned
                ):
                    continue
                if any(
                    np.linalg.norm(np.array(o['translation_m'][:2]) - [x, y]) < 2.0
                    for o in self.objects
                    if o['category'] in ('floor_storage', 'perimeter_equipment')
                ):
                    continue
                name = 'inspection_' + region['id'] + '_' + str(added)
                b = self.body(name, [x, y, 0], category='floor_storage')
                added += 1
                for z in (0.17, 0.80):
                    self.box(b, [0, 0, z], [0.50, 0.30, 0.025], 'steel_light', bevel=0.008)
                for xx in (-0.46, 0.46):
                    for yy in (-0.26, 0.26):
                        self.box(b, [xx, yy, 0.47], [0.018, 0.018, 0.30], 'steel')
                        self.cylinder(b, [xx, yy, 0.08], 0.065, 0.025, 'black', rotation=_rx(math.pi / 2))
                self.box(b, [-0.18, 0, 0.46], [0.23, 0.24, 0.25], 'cabinet', bevel=0.012)
                for z in np.arange(0.30, 0.60, 0.05):
                    self.box(b, [-0.18, -0.244, z], [0.17, 0.003, 0.007], 'black')
                self.bin(b, [0.28, 0, 0.20], w=0.30, d=0.43, h=0.22)
                for xx in (-0.25, 0.20):
                    self.bin(b, [xx, 0, 0.83], w=0.34, d=0.43, h=0.14)
                self.box(b, [0.12, 0.18, 1.08], [0.018, 0.018, 0.26], 'steel')
                self.box(b, [0.12, 0.17, 1.32], [0.23, 0.032, 0.15], 'black', bevel=0.012)
                self.box(b, [0.12, 0.134, 1.32], [0.205, 0.004, 0.123], 'blue')
                for xx in (-0.02, 0.06, 0.14):
                    self.box(b, [xx, 0.128, 1.30], [0.022, 0.002, 0.007], 'label')
                self.workstation_props.append(
                    dict(
                        id=name,
                        position_m=[x, y, 0],
                        footprint_half_m=[0.53, 0.33],
                        top_m=1.48,
                        physical=False,
                        placement='Planning bounds plus .4m clearance; separated from other floor equipment',
                    )
                )

    def lights(self):
        cfg = self.cfg['lighting']
        ET.SubElement(
            self.world,
            'light',
            name='factory_environment',
            type='image',
            texture='factory_sky',
            intensity=str(cfg['environment_intensity']),
        )
        ET.SubElement(
            self.world,
            'light',
            name='factory_daylight',
            type='directional',
            pos='-18 -10 16',
            dir='.6 .32 -1',
            intensity=str(cfg['sun_intensity']),
            diffuse='1 .95 .86',
            castshadow='true',
        )
        positions = cfg.get(
            'fill_positions_m',
            [
                [-12, -10, self.height - 0.8],
                [12, -10, self.height - 0.8],
                [-12, 10, self.height - 0.8],
                [12, 10, self.height - 0.8],
            ],
        )
        for i, pos in enumerate(positions):
            ET.SubElement(
                self.world,
                'light',
                name=f'factory_ceiling_fill_{i}',
                type='point',
                pos=_vec(pos),
                intensity=str(cfg['ceiling_cluster_intensity']),
                diffuse='.94 .97 1',
                bulbradius='.8',
                castshadow='false',
            )

    def camera(
        self, name, position, target, fovy=55, hidden=(), orthographic=False, height=None, camera_hidden=()
    ):
        z = np.asarray(position, float) - target
        z /= np.linalg.norm(z)
        x = np.cross([0, 0, 1], z)
        if np.linalg.norm(x) < 1e-8:
            x = np.array([1.0, 0, 0])
        x /= np.linalg.norm(x)
        y = np.cross(z, x)
        attrs = dict(
            name='factory_camera_' + name,
            pos=_vec(position),
            xyaxes=_vec([*x, *y]),
            fovy=str(height if orthographic else fovy),
        )
        if orthographic:
            attrs['projection'] = 'orthographic'
        ET.SubElement(self.world, 'camera', **attrs)
        self.cameras.append(
            dict(
                id=name,
                model_camera=attrs['name'],
                position_m=list(position),
                target_m=list(target),
                vertical_fov_deg=None if orthographic else fovy,
                projection='orthographic' if orthographic else 'perspective',
                orthographic_height_m=height if orthographic else None,
                hidden_layers=list(hidden),
                camera_hidden_layers=list(camera_hidden),
            )
        )

    def views(self):
        W, D, H = self.width, self.depth, self.height
        self.camera('interior_south', [0, -D / 2 + 1.5, 2.2], [0, D / 4, 2.7], 68)
        self.camera('interior_north', [0, D / 2 - 1.5, 2.2], [0, -D / 4, 2.7], 68)
        if self.cfg['appearance'].get('daylight_study', False):
            self.camera('interior_diagonal', [-W / 2 + 3.5, -D / 2 + 3, 4.8], [3, 3, -0.3], 52)
            self.camera('workstation_detail', [-19.0, -19.0, 2.6], [-15.0, -14.0, 0.8], 48)
        else:
            self.camera('interior_diagonal', [-W / 2 + 2, -D / 2 + 2, 3.6], [W / 5, D / 5, 2.4], 62)
        self.camera('interior_east', [W / 2 - 1.5, -4, 2.0], [-W / 3, 4, 2.6], 65)
        self.camera(
            'detail_storage', [-W / 2 + 5, -D / 2 + 7.5, 1.65], [-W / 2 + 0.6, -D / 2 + 10.5, 1.2], 52
        )
        self.camera('detail_brand', [0, D / 2 - 7, 5.4], [0, D / 2, 5.9], 65)
        self.camera('detail_ceiling', [0, -5, 2.0], [4, 7, H - 0.8], 62)
        self.camera('top', [0, 0, H + 25], [0, 0, 0], camera_hidden=['roof'], orthographic=True, height=D + 2)
        self.camera(
            'aerial', [0, -50, 42], [0, 1, 0], camera_hidden=['roof', 'south'], orthographic=True, height=36
        )
        self.camera('aerial_exterior', [0, -34, 37], [0, 0, 0], 55, hidden=['roof'])
        for name, p, h in [
            ('from_south', [0, -D * 1.25, D * 0.80], ['roof', 'south']),
            ('from_north', [0, D * 1.25, D * 0.80], ['roof', 'north']),
            ('from_east', [W * 1.25, 0, W * 0.80], ['roof', 'east']),
            ('from_west', [-W * 1.25, 0, W * 0.80], ['roof', 'west']),
        ]:
            self.camera(name, p, [0, 0, 1.3], 43, hidden=h)
        self.camera('interactive', [0, -D / 2 + 1.5, 2.2], [0, D / 4, 2.7], 68)

    def finish(self):
        self.shell()
        self.infrastructure()
        self.paint()
        self.equipment()
        if self.cfg['appearance'].get('perimeter_detail', False):
            self.detail_equipment()
        self.workstation_dressing()
        self.service_equipment()
        self.exterior_yard()
        self.lights()
        self.views()
        if self.cfg['appearance'].get('batch_static_geometry', False):
            self.static_batches()
        path = self.output / 'scene.xml'
        ET.indent(self.root)
        ET.ElementTree(self.root).write(path, encoding='unicode')
        used_mesh_files = {Path(m.get('file')).name for m in self.asset.findall('mesh') if m.get('file')}
        for file in (self.assets_path / 'meshes').glob('factory_*.obj'):
            if file.name not in used_mesh_files:
                file.unlink()
        asset_files = []
        for file in sorted(self.assets_path.rglob('*')):
            if file.is_file() and file.name != 'asset-manifest.json':
                asset_files.append(
                    dict(
                        path=str(file.relative_to(self.assets_path)),
                        sha256=_hash(file),
                        bytes=file.stat().st_size,
                    )
                )
        manifest = dict(
            schema_version=1,
            id=self.cfg['id'],
            units='metres',
            frame='+X east, +Y north, +Z up',
            scope='Static visual factory; no task workstations or motion playback',
            dimensions_m=[self.width, self.depth, self.height],
            layers=LAYERS,
            regions=self.cfg['regions'],
            objects=self.objects,
            perimeter_props=self.props,
            cameras=self.cameras,
            assets=asset_files,
            mesh_definition_triangles=self.mesh_triangles,
            source='Project-authored geometry and procedural finishes; Poly Haven CC0 concrete maps; OFL Barlow Condensed font',
            scene_sha256=_hash(path),
            physics=dict(
                dynamic_joints=0,
                actuators=0,
                collision_filter='All display geoms use contype=0, conaffinity=0; ground for future physics must be integrated explicitly.',
            ),
        )
        manifest['static_batching'] = self.batching
        manifest['workstation_dressing'] = getattr(self, 'workstation_props', [])
        if hasattr(self, 'dressing_catalog_sha256'):
            manifest['dressing_catalog_sha256'] = self.dressing_catalog_sha256
        manifest['composition_contract'] = {
            'default_class': 'factory_visual',
            'source_sections': ['asset', 'worldbody', 'named default factory_visual'],
            'preserve_target_sections': [
                'compiler',
                'option',
                'actuator',
                'equality',
                'tendon',
                'task cameras',
            ],
            'frame_transform': 'Rigid translation and yaw of the factory relative to the canonical task, or of a recorded workstation in a presentation; no scale change.',
            'warning': 'This standalone shell is not a task replacement. Do not copy its global compiler/options over a running task.',
        }
        (self.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        return path, manifest


def build_factory(config_path=DEFAULT_CONFIG, output=None, workstation_catalog=None):
    """Return a generated scene and manifest; no task imports or simulation steps."""
    config_path = Path(config_path).resolve()
    config = json.loads(config_path.read_text())
    if workstation_catalog is not None:
        workstation_catalog = Path(workstation_catalog).resolve()
        if not workstation_catalog.is_file():
            raise ValueError('Missing explicit workstation catalog')
        config.setdefault('workstation_dressing', {})['catalog'] = str(workstation_catalog)
    output = Path(output or ROOT / 'outputs/factory-hall/scene').resolve()
    output.mkdir(parents=True, exist_ok=True)
    b = config['building']
    W, D = b['width_m'], b['depth_m']
    if min(W, D, b['eave_height_m']) <= 0:
        raise ValueError('Building dimensions must be positive')
    for r in config['regions']:
        x0, y0, x1, y1 = r['bounds_xy_m']
        if not (-W / 2 < x0 < x1 < W / 2 and -D / 2 < y0 < y1 < D / 2):
            raise ValueError('Region outside building: ' + r['id'])
    assets = output / 'assets'
    shutil.copytree(
        ROOT / 'benchmark/hall', assets, dirs_exist_ok=True, ignore=shutil.ignore_patterns('built')
    )
    (assets / 'meshes').mkdir(parents=True, exist_ok=True)
    (assets / 'textures').mkdir(exist_ok=True)
    _texture_assets(assets / 'textures', config['seed'], config['appearance'].get('painted_roof', False))
    if config['appearance'].get('whole_floor_finish', False):
        _floor_finish(assets / 'textures', config)
    scene, manifest = _Builder(config, assets, output).finish()
    # Local, relative assets make the resulting scene directory portable.
    (assets / 'asset-manifest.json').write_text(
        json.dumps(
            {
                'generated_by': 'roboteam.sim.hall.build',
                'seed': config['seed'],
                'third_party': [
                    {
                        'id': 'Barlow Condensed',
                        'source': 'https://github.com/google/fonts/tree/main/ofl/barlowcondensed',
                        'license': 'SIL Open Font License 1.1',
                        'license_file': 'fonts/OFL.txt',
                    },
                    {
                        'id': 'concrete_floor_02',
                        'source': 'https://polyhaven.com/a/concrete_floor_02',
                        'license': 'CC0 1.0',
                        'metadata': 'source/polyhaven/source.json',
                    },
                ],
                'assets': manifest['assets'],
            },
            indent=2,
        )
        + '\n'
    )
    (output / 'build-config.json').write_text(json.dumps(config, indent=2) + '\n')
    return scene, manifest
