"""Build and show only the current Relay revision; no policy or Oracle."""
import argparse
import hashlib
import html
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from robofrontier.suite.v2 import ROOT, CATALOG, cases, directory, build
from robofrontier.run_setup import write_json

REV = max(c['scene_revision'] for c in cases() if c['family']=='relay')
OUT = ROOT/f'docs/generated/frontier-v2/relay-r{REV}'
LABELS = ['L1 · Straight beam', 'L2 · Curved beam + weight', 'L3 · Elastic elbow + short pendulum']


def sheet(data, view):
    width, height = 1920, 1200
    card_w, card_h = width+24, height+90
    image = Image.new('RGB', (3*card_w+80, 3*card_h+190), '#eef2f4')
    draw = ImageDraw.Draw(image)
    font = lambda size: ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf', size)
    draw.text((28, 24), f'RELAY R{REV} | '+('TOP' if view=='top' else 'FRONT'), font=font(48), fill='#173044')
    draw.text((28, 92), 'Rows: L1 / L2 / L3    Columns: 8 / 12 / 16 arms    Static previews only', font=font(28), fill='#456071')
    for c in data:
        col = [8, 12, 16].index(c['arms']); row = c['level']-1
        x = 24+col*(card_w+12); y = 170+row*(card_h+6)
        draw.rounded_rectangle((x, y, x+card_w, y+card_h), radius=12, fill='white')
        draw.text((x+12, y+9), f"{c['arms']} arms / {c['arms']//4} beams | {LABELS[row]}", font=font(28), fill='#173044')
        draw.text((x+12, y+46), c['id'], font=font(21), fill='#526b7b')
        with Image.open(directory(c)/f'preview-{view}.png') as source:
            image.paste(source, (x+12, y+84))
    image.save(OUT/f'relay-{view}-all.png')
    image.thumbnail((2400, 1900))
    image.save(OUT/f'relay-{view}-overview.jpg', quality=95, subsampling=0)


def main(replace=False):
    OUT.mkdir(parents=True, exist_ok=True)
    data = [c for c in cases() if c['family']=='relay']
    old_files = [p for c in data for revision in range(10,REV) for p in directory(dict(c, scene_revision=revision)).rglob('*') if p.is_file()]
    before = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in old_files}
    write_json(OUT/'source-preserved-hashes.json', before)
    for c in data:
        if c['scene_revision']==REV:
            build(c, replace_draft=replace, render=True)
        else:
            if not ((directory(c)/'preview-top.png').exists() and (directory(c)/'preview-global.png').exists()):
                raise ValueError("Check failed: (directory(c)/'preview-top.png').exists() and (directory(c)/'preview-global.png').exists()")
        print('STATIC READY', c['id'], flush=True)
    changed = [p for p, checksum in before.items() if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=checksum]
    if not (not changed):
        raise ValueError(changed)
    write_json(OUT/'catalog.json', dict(revision=REV, family='relay', case_count=9, cases=data,
        source_revision=10, old_source_files_checked=len(before), old_source_changes=changed,
        physics_steps=0, oracle_run=False, policy_run=False))
    # Replace only Relay references; other families' actual saved entries stay intact.
    catalog = json.loads(CATALOG.read_text())
    updates = {c['id']:c for c in data}
    catalog['cases'] = [updates.get(c['id'], c) for c in catalog['cases']]
    write_json(CATALOG, catalog)
    for view in ('top', 'global'):
        sheet(data, view)
    cards = []
    for c in sorted(data, key=lambda c:(c['level'], c['arms'])):
        target = OUT/c['id']; target.mkdir(exist_ok=True)
        for view in ('top', 'global'):
            source = directory(c)/f'preview-{view}.png'
            # Gallery copies are presentation artifacts; environment assets remain independent.
            import shutil
            shutil.copyfile(source, target/f'{view}.png')
        cards.append(f'<article><h2>{c["arms"]} arms · L{c["level"]} · {c["arms"]//4} beams</h2><p>{html.escape(c["id"])} · r{c['scene_revision']}</p><div class="views">'+''.join(
            f'<a href="{c["id"]}/{view}.png"><strong>{label}</strong><img src="{c["id"]}/{view}.png" loading="lazy"></a>'
            for view,label in [('top','TOP'),('global','FRONT')])+'</div></article>')
    (OUT/'index.html').write_text(('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Relay r11 · Nine environments</title><style>body{font:17px system-ui;background:#eef2f4;color:#173044;max-width:1650px;margin:30px auto;padding:0 22px}p{line-height:1.7}a{color:#185e8c}article{background:white;margin:22px 0;padding:20px;border-radius:12px}.views{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%}strong{display:block;padding:10px 0}.overview{max-width:1500px}@media(max-width:700px){.views{grid-template-columns:1fr}}</style><h1>Relay r11 · Nine environments</h1><p>8/12/16 arms x L1/L2/L3. START and GOAL are 0.80x1.36 m narrow outlines. The 12/16-arm zones return to the curved table ends, without side extensions; 8-arm zones are at the straight table ends. L2/L3 assembly openings face local route progress. Twelve arms form a 90-degree arc: seven outer (A-G), five inner (H-L); inner tabletop opening diameter 3.20 m, inner robot arrangement diameter 4.32 m, radial row spacing 1.30 m. Handover teams are not prescribed. The 8/16-arm scenes retain r13. Arrows are longer/thicker, with 7/9/11 in the 8/12/16-arm scenes. Older versions remain; beams remain scattered.</p><p>Environment updates, static geometry checks and actual static MuJoCo renders only. No Oracle, GPT or physics stepping; relay planning and handover acceptance are unchanged.</p><p><a href="relay-top-all.png">Nine-case top overview</a> · <a href="relay-global-all.png">Nine-case front overview</a> · <a href="catalog.json">Revision and check inventory</a></p><a href="relay-top-all.png"><img class="overview" src="relay-top-overview.jpg"></a>'''+''.join(cards)+'</html>').replace('Relay r11 · Nine environments',f'Relay r{REV} · Nine environments'))
    print(OUT/'index.html', flush=True)


if __name__=='__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--replace-draft', action='store_true')
    main(parser.parse_args().replace_draft)
