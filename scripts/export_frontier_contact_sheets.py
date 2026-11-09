"""Export current initial scenes only: 72 renders and four readable contact sheets.

No stepping, policy, Oracle or mutation of source scenes. Presentation cameras
retain their named orientation, with framing fitted to the complete apparatus.
"""
import hashlib
import html
import itertools
import json
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from robofrontier.suite.scenes import ROOT, catalog, case_directory


OUT = ROOT / 'docs/generated/frontier-suite/contact-sheets-20261024'
WIDTH, HEIGHT = 1920, 1200
INK = '#182631'
PAPER = '#f1f5f7'
LABELS = {
    'transport': ('Transport', ['Cube placement', 'Fixed two-slot insertion', 'Spring-board insertion']),
    'relay': ('Relay', ['Beam', 'Beam + short-ring weight', 'Beam + cable weight']),
    'mosaic': ('Rocket Mosaic', ['Recessed pockets', 'Table grid', 'Unmarked tabletop']),
    'dial': ('Spring dial codebreaker', ['Fixed tabletop gear', 'Floating gear', 'Floating crank']),
}


def font(size):
    return ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Unicode.ttf', size)


def fit_camera(model, data, view):
    """Fit actual geometry AABB corners, rather than cropping extended elbows."""
    corners = []
    signs = np.array(list(itertools.product((-1, 1), repeat=3)))
    for i in range(model.ngeom):
        name = model.geom(i).name or ''
        if model.geom_type[i] == mujoco.mjtGeom.mjGEOM_PLANE or name in ('floor', 'ground'):
            continue
        center, half = model.geom_aabb[i, :3], model.geom_aabb[i, 3:]
        if not np.isfinite(half).all() or max(half) > 20:
            continue
        local = center + signs * half
        corners.append(local @ data.geom_xmat[i].reshape(3, 3).T + data.geom_xpos[i])
    points = np.concatenate(corners)
    cid = model.camera(view).id
    if model.cam_bodyid[cid] != 0:
        raise ValueError('Presentation fit requires a world-fixed camera')
    original = model.cam_pos[cid].copy()
    rotation = data.cam_xmat[cid].reshape(3, 3)
    relative = (points - original) @ rotation
    shift = (relative[:, :2].min(0) + relative[:, :2].max(0)) / 2
    relative[:, :2] -= shift
    tan_y = np.tan(np.deg2rad(model.cam_fovy[cid]) / 2) * .91
    tan_x = tan_y * WIDTH / HEIGHT
    extra = max(np.max(abs(relative[:, 0]) / tan_x + relative[:, 2]),
                np.max(abs(relative[:, 1]) / tan_y + relative[:, 2]), 0)
    model.cam_pos[cid] = original + rotation @ np.array([*shift, extra])
    mujoco.mj_forward(model, data)
    return dict(source_camera=view, orientation_unchanged=True,
                original_position_m=original.tolist(), presentation_position_m=model.cam_pos[cid].tolist(),
                fovy_deg=float(model.cam_fovy[cid]))


def render_case(case):
    folder = case_directory(case)
    xml = folder / 'scene.xml'
    model = mujoco.MjModel.from_xml_path(str(xml))
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, model.key('initial').id)
    mujoco.mj_forward(model, data)
    qpos = data.qpos.copy()
    model.vis.global_.offwidth = WIDTH
    model.vis.global_.offheight = HEIGHT
    target = OUT / 'individual' / case['id']
    target.mkdir(parents=True, exist_ok=True)
    cameras = {}
    with mujoco.Renderer(model, width=WIDTH, height=HEIGHT) as renderer:
        for view in ('top', 'global'):
            cameras[view] = fit_camera(model, data, view)
            renderer.update_scene(data, camera=view)
            Image.fromarray(renderer.render()).save(target / (view + '.png'))
    if not (data.time == 0 and np.array_equal(data.qpos, qpos)):
        raise ValueError('Static export moved physics')
    print(case['id'], flush=True)
    return dict(case_id=case['id'], directory=str(folder.relative_to(ROOT)),
                scene_revision=case.get('scene_revision', 1),
                scene_sha256=hashlib.sha256(xml.read_bytes()).hexdigest(),
                arms=case['arms'], dials=case.get('dials'), columns=case.get('columns'),
                views={v: str((target / (v + '.png')).relative_to(OUT)) for v in cameras},
                cameras=cameras)


def description(case):
    text = f"{case['arms']} arms"
    if case['family'] == 'mosaic':
        text += f" · 7×{case['columns']}"
    elif case['family'] == 'dial':
        text += f" · {case['dials']} dials"
    elif case['family'] == 'relay':
        text += f" · {case['arms']//2} groups"
    return text


def compose(family, cases, views):
    title, levels = LABELS[family]
    scales = sorted(set(c.get('dials', c['arms']) for c in cases))
    margin, gap, header, caption, view_label = 40, 28, 190, 108, 42
    cell_w = WIDTH + 32
    cell_h = caption + len(views) * (HEIGHT + view_label + 12) + 20
    size = (margin*2 + cell_w*3 + gap*2, header + cell_h*3 + gap*2 + 80)
    sheet = Image.new('RGB', size, PAPER)
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 30), title + ' · Nine scenes', fill=INK, font=font(66))
    draw.text((margin, 112), 'Rows: D1 → D3    Columns: increasing scale    |    Initial state, static render', fill=INK, font=font(34))
    for row in range(3):
        for col, scale in enumerate(scales):
            case = next(c for c in cases if c['level'] == row+1 and c.get('dials', c['arms']) == scale)
            x, y = margin + col*(cell_w+gap), header + row*(cell_h+gap)
            draw.rounded_rectangle((x, y, x+cell_w, y+cell_h), radius=16, fill='white')
            draw.text((x+16, y+8), f"D{row+1} {levels[row]}  |  {description(case)}", font=font(34), fill=INK)
            draw.text((x+16, y+59), case['id']+f" · v{case.get('scene_revision',1)}", font=font(27), fill='#4b6170')
            yy = y + caption
            for view in views:
                label = 'TOP · Top' if view == 'top' else 'FRONT · Front'
                draw.text((x+16, yy), label, fill=INK, font=font(28))
                with Image.open(OUT/'individual'/case['id']/(view+'.png')) as image:
                    sheet.paste(image, (x+16, yy+view_label))
                yy += HEIGHT + view_label + 12
    draw.text((margin, size[1]-55), 'RoboFrontier · 36 scenes / 72 views · No physics or policy execution; camera padding does not alter the world.', fill=INK, font=font(28))
    suffix = 'top-front' if len(views) == 2 else views[0]
    name = family + '-' + suffix
    sheet.save(OUT/(name+'.png'), optimize=True)
    sheet.save(OUT/(name+'.jpg'), quality=95, subsampling=0)
    thumb = sheet.copy()
    thumb.thumbnail((1500, 2100))
    thumb.save(OUT/(name+'-preview.jpg'), quality=92)
    print(name, size, flush=True)
    return dict(file=name+'.png', jpeg=name+'.jpg', preview=name+'-preview.jpg', width=size[0], height=size[1])


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    cases = catalog()['cases']
    manifest = dict(kind='Current-scene initial-keyframe presentation export',
                    physical_steps=0, render_resolution=[WIDTH, HEIGHT], cases=[], sheets={})
    for case in cases:
        manifest['cases'].append(render_case(case))
    for family in LABELS:
        group = [c for c in cases if c['family'] == family]
        manifest['sheets'][family] = [compose(family, group, v) for v in (('top','global'), ('top',), ('global',))]
    (OUT/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    sections = []
    for family, (title, _) in LABELS.items():
        plates = manifest['sheets'][family]
        links = ' · '.join(f'<a href="{p["file"]}">{label} Original PNG</a>' for p,label in zip(plates,('Top + front','Top only','Front only')))
        cards = []
        for c in [c for c in cases if c['family'] == family]:
            prefix = f'individual/{c["id"]}/'
            cards.append(f'<article><b>{html.escape(c["id"])} — {description(c)}</b><div class="pair">'+''.join(f'<a href="{prefix}{v}.png"><span>{label}</span><img loading="lazy" src="{prefix}{v}.png"></a>' for v,label in [('top','Top'),('global','Front')])+'</div></article>')
        sections.append(f'<section id="{family}"><h2>{title}</h2><p>{links}</p><a href="{plates[0]["file"]}"><img class="plate" src="{plates[0]["preview"]}"></a><details><summary>Expand 18 individual high-resolution images for nine scenes</summary>{"".join(cards)}</details></section>')
    (OUT/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>RoboFrontier · 36-scene atlas</title><style>body{font-family:system-ui;background:#f1f5f7;color:#182631;margin:32px auto;max-width:1500px;padding:0 24px}h1{font-size:36px}a{color:#175d94}nav{position:sticky;top:0;background:#f1f5f7;padding:16px 0}nav a{margin-right:24px}.plate{max-width:100%;max-height:1100px;object-fit:contain;object-position:left}section{margin:40px 0}article{background:white;padding:20px;margin:20px 0;border-radius:12px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.pair img{width:100%}.pair span{display:block}summary{cursor:pointer;font-size:20px;padding:16px}</style><h1>RoboFrontier · 36 scenes / 72 views</h1><p>Initial scene states. Open full-size lossless images or expand individual views. Each original is 1920×1200. Camera padding changes no physics and resumes no experiment.</p><nav>'+''.join(f'<a href="#{f}">{t[0]}</a>' for f,t in LABELS.items())+'</nav>'+''.join(sections))
    print(OUT/'index.html', flush=True)


if __name__ == '__main__':
    main()
