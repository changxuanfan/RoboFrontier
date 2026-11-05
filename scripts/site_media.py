"""Encode task videos for the project page and README, with posters and a verified manifest.

encode:  each source MP4 becomes a 720p H.264 file (CRF 28, preset slow, faststart, no
         audio) and a 1280-px JPEG poster. The manifest records size, duration and SHA-256
         of every output and the SHA-256 of its source. Existing verified outputs are kept.
montage: one 1920 x 1080 video per family, a 3 x 3 grid of its nine tasks (rows are
         difficulty levels, columns scales), each tile sped up to a common length.
explainer: the README benchmark figure: per family, its largest team at Levels 1-3 from the
         task atlas, with what each level changes.
stills:  README images: montage posters with a play badge and a 400-px thumbnail of every
         task. The README banner and teaser come from scripts/site_film.py.

Sources is a JSON file: {"set": "oracle", "tasks": {"<case>": {"front": path, "side": path}}}.
Run from the repository root:

    .venv/bin/python -m scripts.site_media encode SOURCES OUT
    .venv/bin/python -m scripts.site_media montage OUT/manifest.json FAMILY OUT_MP4
    .venv/bin/python -m scripts.site_media stills OUT/manifest.json MONTAGE_DIR docs/media/readme
    .venv/bin/python -m scripts.site_media explainer docs/task-atlas/images docs/media/readme/benchmark.jpg
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

FFMPEG = os.environ.get('FFMPEG', 'ffmpeg')
FFPROBE = os.environ.get('FFPROBE', 'ffprobe')
POSTER_AT = 0.6  # Later in a run the scene shows real progress.


def sha256(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def probe(path):
    out = subprocess.run([FFPROBE, '-v', 'error', '-select_streams', 'v:0', '-count_packets',
                          '-show_entries', 'stream=width,height,nb_read_packets:format=duration',
                          '-of', 'json', str(path)], check=True, capture_output=True, text=True).stdout
    data = json.loads(out)
    stream = data['streams'][0]
    return {'width': stream['width'], 'height': stream['height'], 'frames': int(stream['nb_read_packets']),
            'duration_s': round(float(data['format']['duration']), 3)}


def encode_one(source, video, poster, height=720, crf=28):
    source_info = probe(source)
    tmp = video.with_name(video.stem + '.part.mp4')
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-i', str(source), '-an', '-vf', f'scale=-2:{height}',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', str(crf), '-pix_fmt', 'yuv420p',
                    '-movflags', '+faststart', str(tmp)], check=True)
    info = probe(tmp)
    # A dropped or truncated encode must not replace a good file.
    if info['height'] != height or abs(info['duration_s'] - source_info['duration_s']) > 0.2:
        raise ValueError(f'Encode of {source} does not match its source: {info} vs {source_info}')
    tmp.replace(video)
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', str(round(info['duration_s'] * POSTER_AT, 2)), '-i', str(video),
                    '-frames:v', '1', '-vf', 'scale=1280:-2', '-q:v', '4', str(poster)], check=True)
    return info


def encode(sources, out, workers=2):
    spec = json.loads(Path(sources).read_text())
    out = Path(out); out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / 'manifest.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {
        'schema': 'robofrontier.site-media.v1', 'set': spec['set'], 'tasks': {}}
    jobs = []
    for case, views in sorted(spec['tasks'].items()):
        for view, source in sorted(views.items()):
            source = Path(source)
            video, poster = out / f'{case}-{view}.mp4', out / f'{case}-{view}.jpg'
            known = manifest['tasks'].get(case, {}).get(view)
            if (known and video.exists() and poster.exists() and known['sha256'] == sha256(video)
                    and known['source_sha256'] == sha256(source)):
                continue
            jobs.append((case, view, source, video, poster))

    def run(job):
        case, view, source, video, poster = job
        info = encode_one(source, video, poster)
        return case, view, {'video': video.name, 'poster': poster.name, 'size': video.stat().st_size,
                            'sha256': sha256(video), 'source_sha256': sha256(source), **info}

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for case, view, record in pool.map(run, jobs):
            manifest['tasks'].setdefault(case, {})[view] = record
            tmp = manifest_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(manifest, indent=1, sort_keys=True) + '\n'); tmp.replace(manifest_path)
            print(case, view, record['size'], record['duration_s'], flush=True)
    return manifest


def montage(manifest_path, family, output, length_s=60, view='front'):
    """A 3 x 3 grid of one family: rows are levels 1-3, columns increasing scale."""
    manifest_path = Path(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    cases = sorted(c for c in manifest['tasks'] if c.startswith(family + '-'))
    if len(cases) != 9:
        raise ValueError(f'{family} has {len(cases)} encoded tasks, expected 9')
    scale = lambda c: int(re.search(r'-[an](\d+)', c).group(1))  # arms, or dials for Dial
    columns = sorted({scale(c) for c in cases})
    grid = [[next(c for c in cases if scale(c) == col and c.endswith(f'-d{level}')) for col in columns] for level in (1, 2, 3)]
    inputs, filters = [], []
    for i, case in enumerate(c for row in grid for c in row):
        record = manifest['tasks'][case][view]
        inputs += ['-i', str(manifest_path.parent / record['video'])]
        speed = record['duration_s'] / length_s
        # Each tile runs its whole recording in the common length; short ones hold their last frame.
        filters.append(f'[{i}:v]setpts=PTS/{max(speed, 1):.4f},scale=640:360,tpad=stop_mode=clone:stop_duration={length_s},'
                       f'trim=duration={length_s},setsar=1[v{i}]')
    layout = '|'.join(f'{x * 640}_{y * 360}' for y in range(3) for x in range(3))
    graph = ';'.join(filters) + ';' + ''.join(f'[v{i}]' for i in range(9)) + f'xstack=inputs=9:layout={layout}[out]'
    subprocess.run([FFMPEG, '-v', 'error', '-y', *inputs, '-filter_complex', graph, '-map', '[out]', '-an', '-r', '30',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', '26', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
                    str(output)], check=True)
    return {'output': str(output), 'grid': grid, **probe(output)}


def grab(video, at_s, path, width):
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', str(at_s), '-i', str(video), '-frames:v', '1',
                    '-vf', f'scale={width}:-2', '-q:v', '3', str(path)], check=True)


def play_badge(path, size=0.16):
    """Mark a still as a video: a lime disc with a dark play triangle, no text."""
    from PIL import Image, ImageDraw
    image = Image.open(path).convert('RGB')
    w, h = image.size; r = int(min(w, h) * size / 2); cx, cy = w // 2, h // 2
    layer = Image.new('RGBA', image.size, (0, 0, 0, 0)); draw = ImageDraw.Draw(layer)
    draw.ellipse([cx - r - 6, cy - r - 6, cx + r + 6, cy + r + 6], fill=(6, 8, 11, 110))
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(212, 255, 58, 240))
    t = r * 0.45
    draw.polygon([(cx - t * 0.7, cy - t), (cx - t * 0.7, cy + t), (cx + t * 1.05, cy)], fill=(6, 8, 11, 255))
    Image.alpha_composite(image.convert('RGBA'), layer).convert('RGB').save(path, quality=86, optimize=True)


def explainer(atlas, out, width=1800):
    """The README benchmark figure: one row per family, its largest team at Levels 1-3, each
    the task's real initial state from the task atlas, with what the level changes."""
    from PIL import Image, ImageDraw, ImageFont
    fonts = Path(__file__).resolve().parents[1] / 'assets/robo_factory/fonts'
    display = lambda n: ImageFont.truetype(str(fonts / 'SpaceGrotesk-Bold.ttf'), n)
    mono = lambda n: ImageFont.truetype(str(fonts / 'JetBrainsMono-Medium.ttf'), n)
    data = json.loads((Path(__file__).resolve().parents[1] / 'site/data/tasks.json').read_text())
    colors = {'transport': (59, 127, 196), 'mosaic': (63, 148, 64), 'relay': (214, 91, 60), 'dial': (185, 138, 18)}
    view = {'transport': 'global', 'mosaic': 'top', 'relay': 'global', 'dial': 'global'}
    ink, ink2, dim, line = (21, 24, 28), (59, 65, 72), (105, 113, 124), (211, 214, 219)
    side, gap, pad = 330, 22, 36
    cw = (width - 2 * pad - side - 2 * gap) // 3; ch = round(cw * 5 / 8); row = ch + 104
    head = 64
    img = Image.new('RGB', (width, pad + head + 4 * row + 3 * gap + pad), (255, 255, 255))
    d = ImageDraw.Draw(img)
    for i, label in enumerate(['LEVEL 1', 'LEVEL 2', 'LEVEL 3']):
        x = pad + side + i * (cw + gap)
        d.text((x, pad + 10), label, font=mono(22), fill=dim)
    d.text((pad, pad + 10), 'LARGEST TEAM PER FAMILY', font=mono(22), fill=dim)
    for r, key in enumerate(['transport', 'mosaic', 'relay', 'dial']):
        fam, y = data['families'][key], pad + head + r * (row + gap)
        tasks = [t for t in data['tasks'] if t['family'] == key]
        top = max(tasks, key=lambda t: (t['workload'], t['arms']))
        scale = re.sub(r'-d\d$', '', top['id'])
        d.rounded_rectangle([pad, y, width - pad, y + row - 1], radius=12, outline=line, width=2,
                            fill=tuple(round(255 + (c - 255) * .06) for c in colors[key]))
        d.rounded_rectangle([pad + 24, y + 30, pad + 44, y + 50], radius=4, fill=colors[key])
        d.text((pad + 58, y + 20), fam['name'], font=display(44), fill=ink)
        words, lines, cur = fam['verb'].split(), [], ''
        for w in words:
            if display(24).getlength(f'{cur} {w}'.strip()) > side - 60: lines.append(cur); cur = w
            else: cur = f'{cur} {w}'.strip()
        lines.append(cur)
        for k, text in enumerate(lines):
            d.text((pad + 24, y + 92 + k * 32), text, font=display(24), fill=ink2)
        arms = sorted({t['arms'] for t in tasks}); work = sorted({t['workload'] for t in tasks})
        d.text((pad + 24, y + row - 76), f'{arms[0]}-{arms[-1]} ARMS', font=mono(20), fill=dim)
        d.text((pad + 24, y + row - 46), f"{work[0]}-{work[-1]} {fam['unit'].upper()}", font=mono(20), fill=dim)
        for level in (1, 2, 3):
            t = next(t for t in tasks if t['id'] == f'{scale}-d{level}')
            x = pad + side + (level - 1) * (cw + gap)
            shot = Image.open(Path(atlas) / f"{t['id']}-{view[key]}.jpg").convert('RGB').resize((cw, ch), Image.LANCZOS)
            mask = Image.new('L', (cw, ch), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, cw - 1, ch - 1], radius=10, fill=255)
            img.paste(shot, (x, y + 16), mask)
            d.text((x + 2, y + 16 + ch + 12), f'L{level}', font=mono(22), fill=colors[key])
            note, out_lines, cur = t['level_note'].split(), [], ''
            for w in note:
                if display(23).getlength(f'{cur} {w}'.strip()) > cw - 52: out_lines.append(cur); cur = w
                else: cur = f'{cur} {w}'.strip()
            out_lines.append(cur)
            for k, text in enumerate(out_lines[:2]):
                d.text((x + 46, y + 16 + ch + 10 + k * 30), text, font=display(23), fill=ink)
    img.save(out, quality=86, optimize=True, progressive=True)
    return out


def stills(manifest_path, montages, out):
    """README images: montage posters (with play badges), 36 task thumbnails."""
    from PIL import Image
    manifest_path, out = Path(manifest_path), Path(out)
    (out / 'tasks').mkdir(parents=True, exist_ok=True)
    for montage in sorted(Path(montages).glob('montage-*.mp4')):
        poster = out / (montage.stem + '.jpg'); grab(montage, 45, poster, 1600); play_badge(poster, 0.12)
    manifest = json.loads(manifest_path.read_text())
    for case, views in manifest['tasks'].items():
        thumb = out / 'tasks' / f'{case}.jpg'
        Image.open(manifest_path.parent / views['front']['poster']).convert('RGB').resize((400, 225)).save(thumb, quality=78, optimize=True)
    return sorted(str(p.relative_to(out)) for p in out.rglob('*') if p.suffix in ('.jpg', '.webp'))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    e = sub.add_parser('encode'); e.add_argument('sources'); e.add_argument('out'); e.add_argument('--workers', type=int, default=2)
    m = sub.add_parser('montage'); m.add_argument('manifest'); m.add_argument('family'); m.add_argument('output')
    m.add_argument('--length-s', type=float, default=60); m.add_argument('--view', default='front')
    s = sub.add_parser('stills'); s.add_argument('manifest'); s.add_argument('montages'); s.add_argument('out')
    x = sub.add_parser('explainer'); x.add_argument('atlas'); x.add_argument('out')
    args = parser.parse_args(argv)
    if args.command == 'encode':
        encode(args.sources, args.out, args.workers)
    elif args.command == 'explainer':
        print(explainer(args.atlas, args.out))
    elif args.command == 'stills':
        print('\n'.join(stills(args.manifest, args.montages, args.out)))
    else:
        print(json.dumps(montage(args.manifest, args.family, args.output, args.length_s, args.view), indent=1))


if __name__ == '__main__':
    main()
