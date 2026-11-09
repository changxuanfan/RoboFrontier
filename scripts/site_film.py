"""Cut the RoboFrontier film and its short teaser from the raw Robo World render, with motion
graphics drawn in the project page's style: white signage plates like the labels on the
Robo World floor, the four family colors, Space Grotesk and JetBrains Mono.

short: a white title card on which the map of Robo World draws itself, a zoom into the
       Transport zone, one moment from each of the four zones, the hall orbit rising to
       the overhead view, and an end card. It starts and ends on white, so it loops.
film:  the same opening, then the full zone tours of the raw render with an animated card
       for each family and a plate for each task, and the end card.

banner: the finished title card as the README banner. web: the page's hero loop and the
       README teaser, cut from the short master.

The raw render is the film without titles or subtitles (factory-promo-r14.mp4). Run from
the repository root; short and film write near-lossless masters to encode for the web:

    .venv/bin/python -m scripts.site_film short RAW_RENDER SHORT.mp4
    .venv/bin/python -m scripts.site_film film RAW_RENDER FILM.mp4
    .venv/bin/python -m scripts.site_film web SHORT.mp4 site/assets/video/hero.mp4 docs/media/readme/teaser.webp
    .venv/bin/python -m scripts.site_film banner - docs/media/readme/banner.png
"""
import argparse
import json
import math
from pathlib import Path
import re
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS = ROOT / 'assets/robo_factory/fonts'
TASKS = ROOT / 'site/data/tasks.json'
TITLES = ROOT / 'assets/robo_factory/film-titles.srt'
SUBTITLES = ROOT / 'assets/robo_factory/film-subtitles.srt'
W, H, FPS = 1920, 1080, 30
WHITE, INK, INK2, DIM, LINE, HALL = (255, 255, 255), (21, 24, 28), (59, 65, 72), (105, 113, 124), (211, 214, 219), (244, 245, 246)
COLORS = {'transport': (59, 127, 196), 'mosaic': (63, 148, 64), 'relay': (214, 91, 60), 'dial': (185, 138, 18)}
ORDER = ['transport', 'mosaic', 'relay', 'dial']
NAMES = {'transport': 'Transport', 'mosaic': 'Mosaic', 'relay': 'Relay', 'dial': 'Dial'}
# One moment per zone: the moving side view of its largest Level 3 task. The raw tours repeat
# one camera pattern per zone, offset by 47.43 s (Relay, Transport, Mosaic, Dial).
ZONE_SHOT = {'relay': (44.9, 'relay-a16-d3'), 'transport': (92.33, 'transport-a12-d3'),
             'mosaic': (139.76, 'mosaic-a08-12x24-d3'), 'dial': (187.19, 'dial-best5-n08-d3')}
OPENING_RAW_END = 11.6  # the orbit has risen to the square overhead view of the hall
FFMPEG = 'ffmpeg'


# ---------- drawing helpers ----------
_fonts = {}


def font(kind, size):
    key = (kind, size)
    if key not in _fonts:
        _fonts[key] = ImageFont.truetype(str(FONTS / ('SpaceGrotesk-Bold.ttf' if kind == 'display' else 'JetBrainsMono-Medium.ttf')), size)
    return _fonts[key]


def ease_out(x):
    x = min(1, max(0, x)); return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = min(1, max(0, x)); return 4 * x ** 3 if x < .5 else 1 - (-2 * x + 2) ** 3 / 2


def mix(a, b, k):
    return tuple(round(a[i] + (b[i] - a[i]) * k) for i in range(3))


def tracked(draw, xy, text, fnt, fill, tracking=0.0):
    """Letter-spaced text (PIL has no tracking); returns the width drawn."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += fnt.getlength(ch) + tracking
    return x - xy[0] - tracking


def tracked_width(text, fnt, tracking):
    return sum(fnt.getlength(c) for c in text) + tracking * (len(text) - 1)


def mark(draw, x, y, cell, gap, active=None):
    """The 2 x 2 family mark; `active` dims the other three."""
    for i, key in enumerate(['transport', 'mosaic', 'relay', 'dial']):
        cx, cy = x + (i % 2) * (cell + gap), y + (i // 2) * (cell + gap)
        color = COLORS[key] if active in (None, key) else LINE
        draw.rounded_rectangle([cx, cy, cx + cell, cy + cell], radius=max(1, cell // 5), fill=color)


def plate(lines, width=None, pad=(26, 20), accent=None):
    """A white signage plate with a soft shadow. `lines` are (kind, size, text, fill, tracking).
    Returns an RGBA image and the offset of the plate inside it (for the shadow)."""
    sizes = []
    for kind, size, text, _, tr in lines:
        f = font(kind, size)
        w = tracked_width(text, f, tr) if kind == 'mono' else f.getlength(text)
        asc, desc = f.getmetrics(); sizes.append((w, asc + desc))
    pw = width or int(max(w for w, _ in sizes) + 2 * pad[0] + (34 if accent else 0))
    ph = int(sum(h for _, h in sizes) + 10 * (len(lines) - 1) + 2 * pad[1])
    m = 30
    img = Image.new('RGBA', (pw + 2 * m, ph + 2 * m), (0, 0, 0, 0))
    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([m, m + 6, m + pw, m + ph + 6], radius=10, fill=(16, 20, 28, 60))
    img = Image.alpha_composite(img, shadow.filter(ImageFilter.GaussianBlur(12)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([m, m, m + pw, m + ph], radius=10, fill=WHITE + (255,), outline=LINE + (255,), width=1)
    x0, y = m + pad[0], m + pad[1]
    if accent:
        d.rounded_rectangle([x0, y + 4, x0 + 16, y + 20], radius=3, fill=accent + (255,)); x0 += 30
    for (kind, size, text, fill, tr), (_, hgt) in zip(lines, sizes):
        f = font(kind, size)
        if kind == 'mono':
            tracked(d, (x0, y), text, f, fill + (255,), tr)
        else:
            d.text((x0, y), text, font=f, fill=fill + (255,))
        y += hgt + 10; x0 = m + pad[0] + (30 if accent else 0)
    return img, m


def place(frame, layer, x, y, alpha=1.0):
    """Composite an RGBA layer onto an RGB PIL frame at (x, y) with extra opacity."""
    if alpha <= 0:
        return
    if alpha < 1:
        a = layer.getchannel('A').point(lambda v: int(v * alpha)); layer = layer.copy(); layer.putalpha(a)
    frame.paste(layer, (int(round(x)), int(round(y))), layer)


def cover(img, w, h):
    """Scale an image to cover w x h, center-cropped."""
    s = max(w / img.width, h / img.height)
    r = img.resize((max(1, round(img.width * s)), max(1, round(img.height * s))), Image.BILINEAR)
    x, y = (r.width - w) // 2, (r.height - h) // 2
    return r.crop((x, y, x + w, y + h))


def push(img, k, amount=0.06):
    """Slow push-in: scale about the center by 1 + amount * k."""
    s = 1 + amount * k
    cw, ch = W / s, H / s
    x, y = (W - cw) / 2, (H - ch) / 2
    return img.resize((W, H), Image.BILINEAR, box=(x, y, x + cw, y + ch))


# ---------- the map of Robo World (same layout as the project page) ----------
def map_layout(tasks):
    """Zones and tables in map units: 2 x 2 zones of 3 x 3 tables, columns by team size,
    rows by level, a table widening with its arms."""
    ZW, ZH, GAP, P = 300, 214, 18, 10
    pos = {'transport': (0, 0), 'mosaic': (1, 0), 'relay': (0, 1), 'dial': (1, 1)}
    zones, desks = {}, []
    scale_of = lambda i: re.sub(r'-d\d$', '', i)
    number = lambda i: int((re.search(r'-[an](\d+)', i) or [0, 0])[1])
    for key in ORDER:
        zx, zy = pos[key]; x0, y0 = P + zx * (ZW + GAP), P + zy * (ZH + GAP)
        zones[key] = (x0, y0, ZW, ZH)
        rows = [t for t in tasks if t['family'] == key]
        scales = sorted({scale_of(t['id']) for t in rows}, key=number)
        rh = (ZH - 44) / 3
        for t in rows:
            col, row = scales.index(scale_of(t['id'])), t['level'] - 1
            w, h = 30 + t['arms'] * 2.6, 22 + t['arms'] * .9
            cx, cy = x0 + ZW / 6 * (2 * col + 1), y0 + 38 + rh * (row + .5)
            desks.append({'family': key, 'arms': t['arms'], 'rect': (cx - w / 2, cy - h / 2, w, h), 'order': col + 3 * row})
    return zones, desks, (2 * ZW + GAP + 2 * P, 2 * ZH + GAP + 2 * P)


def perimeter(x, y, w, h, n):
    total, pts = 2 * (w + h), []
    for k in range(n):
        d = (k + .5) * total / n
        if d < w: pts.append((x + d, y)); continue
        d -= w
        if d < h: pts.append((x + w, y + d)); continue
        d -= h
        if d < w: pts.append((x + w - d, y + h)); continue
        d -= w; pts.append((x, y + h - d))
    return pts


class Opening:
    """The white title card: the wordmark and claim on the left, the map drawing itself on
    the right; then the Transport zone of the map grows into the Transport footage."""
    SS = 2  # supersampling for crisp vector shapes

    def __init__(self, tasks):
        self.zones, self.desks, (self.mw, self.mh) = map_layout(tasks)
        self.scale = 800 / self.mw
        self.ox, self.oy = W - 120 - self.mw * self.scale, (H - self.mh * self.scale) / 2 + 20

    def to_px(self, x, y):
        return self.ox + x * self.scale, self.oy + y * self.scale

    def zone_rect(self, key):
        x, y, w, h = self.zones[key]; (a, b), (c, d) = self.to_px(x, y), self.to_px(x + w, y + h)
        return a, b, c, d

    def card(self, t):
        """The title card at time t (s): everything eases in by t = 2.2."""
        S = self.SS
        img = Image.new('RGB', (W * S, H * S), WHITE)
        d = ImageDraw.Draw(img)
        P = lambda x, y: (self.ox * S + x * self.scale * S, self.oy * S + y * self.scale * S)
        # hall floor
        k = ease_out(t / .5)
        if k > 0:
            (a, b), (c, e) = P(0, 0), P(self.mw, self.mh)
            d.rounded_rectangle([a, b, c, e], radius=12 * S, fill=mix(WHITE, HALL, k), outline=mix(WHITE, LINE, k), width=S)
        # aisles
        if t > .35:
            k = ease_out((t - .35) / .5)
            cx, cy = self.mw / 2, self.mh / 2
            col = mix(HALL, COLORS['dial'], .8)
            for (x1, y1, x2, y2) in ((cx, 5, cx, 5 + (self.mh - 10) * k), (5, cy, 5 + (self.mw - 10) * k, cy)):
                (p, q), (r, s) = P(x1, y1), P(x2, y2)
                length, dash = math.hypot(r - p, s - q), 14 * S
                for j in range(int(length // (dash + 12 * S)) + 1):
                    f0, f1 = j * (dash + 12 * S) / max(length, 1), min(1, (j * (dash + 12 * S) + dash) / max(length, 1))
                    if f0 >= 1: break
                    d.line([p + (r - p) * f0, q + (s - q) * f0, p + (r - p) * f1, q + (s - q) * f1], fill=col, width=2 * S)
        # zones, staggered
        for i, key in enumerate(ORDER):
            k = ease_out((t - .15 - i * .12) / .45)
            if k <= 0: continue
            x, y, w, h = self.zones[key]
            (a, b), (c, e) = P(x, y), P(x + w, y + h)
            d.rounded_rectangle([a, b, c, e], radius=8 * S, fill=mix(WHITE, mix(WHITE, COLORS[key], .15), k))
            # floor sign
            name = NAMES[key].upper(); f = font('mono', round(9 * self.scale * S))
            tw = tracked_width(name, f, 2 * S)
            sx, sy = (a + c) / 2, b + 10 * self.scale * S
            d.rounded_rectangle([sx - tw / 2 - 12 * S, sy, sx + tw / 2 + 12 * S, sy + 17 * self.scale * S], radius=3 * S,
                                fill=WHITE, outline=mix(WHITE, LINE, k), width=S)
            tracked(d, (sx - tw / 2, sy + 2.5 * self.scale * S), name, f, mix(WHITE, INK, k), 2 * S)
        # tables pop in, then their arms light up in a wave
        for desk in self.desks:
            zi = ORDER.index(desk['family'])
            start = .55 + zi * .12 + desk['order'] * .05
            k = ease_out((t - start) / .35)
            if k <= 0: continue
            x, y, w, h = desk['rect']; c = COLORS[desk['family']]
            cx, cy = x + w / 2, y + h / 2; s2 = .7 + .3 * k
            x, y, w, h = cx - w * s2 / 2, cy - h * s2 / 2, w * s2, h * s2
            (a, b), (c2, e) = P(x, y), P(x + w, y + h)
            d.rounded_rectangle([a, b, c2, e], radius=3 * S, fill=WHITE, outline=mix(WHITE, c, k), width=2 * S)
            lit = ease_out((t - 1.35 - zi * .1 - desk['order'] * .03) / .3)
            for px, py in perimeter(x, y, w, h, desk['arms']):
                (u, v) = P(px, py); r = 2.3 * self.scale * S
                d.ellipse([u - r, v - r, u + r, v + r], fill=mix(mix(WHITE, INK2, k), c, lit))
        img = img.resize((W, H), Image.LANCZOS)
        d = ImageDraw.Draw(img)
        # left column text
        x = 150
        k = ease_out((t - .2) / .6)
        if k > 0:
            layer = Image.new('RGBA', (900, 520), (0, 0, 0, 0)); g = ImageDraw.Draw(layer)
            mark(g, 2, 8, 15, 4)
            tracked(g, (52, 8), 'MULTI-ROBOT BENCHMARK · MULTIMODAL AGENTS', font('mono', 22), DIM + (255,), 2.2)
            g.text((0, 62), 'RoboFrontier', font=font('display', 112), fill=INK + (255,))
            place(img, layer, x, 300 + 30 * (1 - k), k)
        k = ease_out((t - .55) / .6)
        if k > 0:
            layer = Image.new('RGBA', (900, 200), (0, 0, 0, 0)); g = ImageDraw.Draw(layer)
            g.text((0, 0), 'Can multimodal agents', font=font('display', 50), fill=INK2 + (255,))
            g.text((0, 60), 'run a robot world?', font=font('display', 50), fill=INK2 + (255,))
            place(img, layer, x, 520 + 24 * (1 - k), k)
        k = ease_out((t - .95) / .6)
        if k > 0:
            layer = Image.new('RGBA', (900, 60), (0, 0, 0, 0)); g = ImageDraw.Draw(layer)
            tracked(g, (0, 0), '36 TASKS · 4 FAMILIES · UP TO 16 ARMS', font('mono', 24), DIM + (255,), 2.4)
            place(img, layer, x, 680 + 18 * (1 - k), k)
        return img


# ---------- raw video I/O ----------
def read(raw, start, frames):
    """Yield `frames` RGB frames of the raw render from `start` seconds."""
    proc = subprocess.Popen([FFMPEG, '-v', 'error', '-ss', f'{start:.3f}', '-i', str(raw), '-frames:v', str(frames),
                             '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], stdout=subprocess.PIPE)
    size = W * H * 3
    last = None
    for _ in range(frames):
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        last = Image.frombuffer('RGB', (W, H), buf, 'raw', 'RGB', 0, 1).copy()
        yield last
    proc.stdout.close(); proc.wait()


class Writer:
    def __init__(self, path):
        self.proc = subprocess.Popen([FFMPEG, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS),
                                      '-i', '-', '-c:v', 'libx264', '-preset', 'medium', '-crf', '14', '-pix_fmt', 'yuv420p',
                                      '-movflags', '+faststart', str(path)], stdin=subprocess.PIPE)
        self.n = 0

    def put(self, img):
        self.proc.stdin.write(img.tobytes()); self.n += 1

    def close(self):
        self.proc.stdin.close(); self.proc.wait()
        if self.proc.returncode:
            raise SystemExit('ffmpeg failed')


# ---------- overlays on footage ----------
def task_plate(family, task_id, detail, big=False, label=None):
    c = COLORS[family]
    if big:
        lines = [('mono', 22, label or NAMES[family].upper(), c, 3.0), ('display', 58, task_id, INK, 0), ('mono', 22, detail.upper(), DIM, 1.6)]
    else:
        lines = [('mono', 20, NAMES[family].upper(), c, 3.0), ('display', 44, task_id, INK, 0), ('mono', 20, detail.upper(), DIM, 1.6)]
    return plate(lines, accent=c)


def family_card(number, family, title, body, spec):
    c = COLORS[family]
    return plate([('mono', 22, f'{number:02d} · {NAMES[family].upper()}', c, 3.0), ('display', 64, title, INK, 0),
                  ('display', 34, body, INK2, 0), ('mono', 22, spec.upper(), DIM, 1.8)], pad=(34, 28), accent=c)


def animate_in(frame, layer_m, x, y, i, n, enter=12, leave=8, dx=-36):
    """Slide a plate in from the left, hold, and fade it out over its last frames."""
    layer, m = layer_m
    k_in, k_out = ease_out(i / enter), 1 - ease_out((i - (n - leave)) / leave) if i > n - leave else 1
    place(frame, layer, x - m + dx * (1 - k_in), y - m, min(k_in, k_out))


def progress(frame, family, k):
    layer = Image.new('RGBA', (60, 60), (0, 0, 0, 0)); mark(ImageDraw.Draw(layer), 0, 0, 20, 6, active=family)
    place(frame, layer, W - 72 - 46, 66, k)


def end_card(frame, k):
    """A white veil and the closing card; k eases 0 -> 1."""
    veil = Image.new('RGBA', (W, H), WHITE + (int(200 * k),)); frame.paste(veil, (0, 0), veil)
    layer = Image.new('RGBA', (1200, 420), (0, 0, 0, 0)); g = ImageDraw.Draw(layer)
    f = font('display', 128); tw = f.getlength('RoboFrontier')
    mark(g, (1200 - tw) / 2 - 78, 52, 24, 6)
    g.text(((1200 - tw) / 2, 18), 'RoboFrontier', font=f, fill=INK + (255,))
    for y, text, size, fill, tr in ((190, '36 TASKS · 4 FAMILIES · UP TO 16 ARMS', 26, INK2, 2.6),
                                    (250, 'changxuanfan.github.io/RoboFrontier', 28, COLORS['transport'], .4),
                                    (320, 'ORACLE REFERENCE RUNS IN ROBO WORLD · NOT MODEL RESULTS', 18, DIM, 1.8)):
        fm = font('mono', size); tracked(g, ((1200 - tracked_width(text, fm, tr)) / 2, y), text, fm, fill + (255,), tr)
    place(frame, layer, (W - 1200) / 2, (H - 420) / 2 + 26 * (1 - k), ease_out(k))


def fade_white(frame, k):
    if k <= 0: return frame
    return Image.blend(frame, Image.new('RGB', (W, H), WHITE), min(1, k))


def parse_srt(path):
    out = []
    for block in Path(path).read_text().strip().split('\n\n'):
        lines = block.strip().splitlines()
        a, b = lines[1].split(' --> ')
        sec = lambda s: (lambda h, m, rest: int(h) * 3600 + int(m) * 60 + float(rest.replace(',', '.')))(*s.split(':'))
        out.append((sec(a), sec(b), lines[2:]))
    return out


# ---------- the cut ----------
def build(kind, raw, out):
    tasks = json.loads(TASKS.read_text())['tasks']
    by_id = {t['id']: t for t in tasks}
    opening = Opening(tasks)
    writer = Writer(out)
    TITLE, ZOOM, SHOT, WIPE = int(3.0 * FPS), int(.7 * FPS), int(1.6 * FPS), 10
    # 1. title card
    for i in range(TITLE):
        writer.put(opening.card(i / FPS))
    last_card = opening.card(TITLE / FPS)
    # 2. zone shots: the Transport zone of the map grows into its footage, then wipes
    shots = {}
    for key in ORDER:
        start, _ = ZONE_SHOT[key]
        n = SHOT + (ZOOM if key == 'transport' else 0)
        shots[key] = list(read(raw, start, n))
    a, b, c, e = opening.zone_rect('transport')
    tz = shots['transport']
    for i in range(ZOOM):
        k = ease_in_out(i / (ZOOM - 1))
        x0, y0, x1, y1 = a * (1 - k), b * (1 - k), c + (W - c) * k, e + (H - e) * k
        frame = Image.blend(last_card, Image.new('RGB', (W, H), WHITE), k)
        tile = cover(push(tz[i], 0), max(1, int(x1 - x0)), max(1, int(y1 - y0)))
        maskimg = Image.new('L', tile.size, 0)
        ImageDraw.Draw(maskimg).rounded_rectangle([0, 0, tile.width - 1, tile.height - 1], radius=int(12 * (1 - k)), fill=255)
        frame.paste(tile, (int(x0), int(y0)), maskimg)
        writer.put(frame)
    for zi, key in enumerate(ORDER):
        frames = shots[key][ZOOM:] if key == 'transport' else shots[key]
        _, task_id = ZONE_SHOT[key]; t = by_id[task_id]
        unit = 'dials' if key == 'dial' else None
        detail = f"Level {t['level']} · {t['arms']} arms" + (f" · {t['workload']} dials" if unit else '')
        layer = task_plate(key, NAMES[key], f'{task_id} · {detail}', big=True, label=f'ZONE {zi + 1:02d} / 04')
        # the last zone wipes in ink into the hall orbit
        nxt_color = COLORS[ORDER[zi + 1]] if zi + 1 < len(ORDER) else INK
        for i, f in enumerate(frames):
            img = push(f, i / SHOT)
            animate_in(img, layer, 72, H - 72 - (layer[0].height - 2 * layer[1]), i, len(frames), leave=6)
            progress(img, key, ease_out(i / 8))
            if i >= len(frames) - WIPE // 2:
                img = _wipe_out(img, i - (len(frames) - WIPE // 2), WIPE, nxt_color)
            if zi > 0 and i < WIPE // 2:
                img = _wipe_in(img, i + WIPE // 2, WIPE, COLORS[key])
            writer.put(img)
    # 3. the hall orbit (and, for the film, the full tours) from raw 0
    end_raw = OPENING_RAW_END if kind == 'short' else None
    titles = parse_srt(TITLES)[1:5]
    subs = parse_srt(SUBTITLES)
    world = plate([('mono', 20, 'ROBO WORLD', INK, 3.0), ('display', 44, 'One hall, 36 tasks', INK, 0),
                   ('mono', 20, 'Four zones · nine tasks each · simulated Franka arms'.upper(), DIM, 1.6)], accent=COLORS['transport'])
    cards = []
    for n, (a0, a1, lines) in enumerate(titles, start=1):
        fam = lines[0].lower()
        cards.append((a0, a1, family_card(n, fam, lines[0], ' '.join(lines[1:-1]), lines[-1])))
    plates = []
    for a0, a1, lines in subs:
        tid, *rest = [p.strip() for p in lines[0].split('·')]
        plates.append((a0, a1, task_plate(by_id[tid]['family'], tid, ' · '.join(rest))))
    total = int((OPENING_RAW_END if kind == 'short' else 210.5) * FPS)
    last = None
    for i, f in enumerate(read(raw, 0, total)):
        t = i / FPS; img = f.copy()
        if i < WIPE // 2:
            img = _wipe_in(img, i + WIPE // 2, WIPE, INK)
        if .5 <= t < 4.5:
            animate_in(img, world, 72, H - 72 - (world[0].height - 2 * world[1]), int((t - .5) * FPS), int(4 * FPS))
        if kind == 'film':
            for a0, a1, layer in cards:
                if a0 <= t < a1:
                    animate_in(img, layer, 72, 72, int((t - a0) * FPS), int((a1 - a0) * FPS), enter=16, leave=10)
            for a0, a1, layer in plates:
                if a0 <= t < a1:
                    animate_in(img, layer, 72, H - 72 - (layer[0].height - 2 * layer[1]), int((t - a0) * FPS), int((a1 - a0) * FPS))
            if t >= 203.5:
                end_card(img, ease_out((t - 203.5) / 1.2))
                img = fade_white(img, (t - 209.8) / .7)
        writer.put(img); last = f
    if kind == 'short':
        hold = int(2.8 * FPS)
        for i in range(hold):
            img = last.copy(); t = i / FPS
            end_card(img, ease_out(t / 1.0))
            writer.put(fade_white(img, (t - 2.2) / .6))
    writer.close()
    return writer.n


def _wipe_out(img, j, n, color):
    """First half of a wipe: a band in `color` covers the frame from the left."""
    e = ease_in_out(j / (n / 2 - 1) if n > 2 else 1)
    d = ImageDraw.Draw(img); d.rectangle([0, 0, W * e, H], fill=color); d.rectangle([max(0, W * e - 10), 0, W * e, H], fill=WHITE)
    return img


def _wipe_in(img, j, n, color):
    """Second half: the band retracts to the right, revealing the new shot."""
    e = ease_in_out((j - n / 2) / (n / 2 - 1) if n > 2 else 1)
    d = ImageDraw.Draw(img); d.rectangle([W * e, 0, W, H], fill=color); d.rectangle([W * e, 0, min(W, W * e + 10), H], fill=WHITE)
    return img


def web(short, hero, teaser):
    """From the short master: the project page's hero loop (the four zones and the hall orbit,
    without title and end cards; 720p H.264) and the README teaser (the four zones as an
    animated WebP, which GitHub autoplays)."""
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', '3.7', '-to', '21.6', '-i', str(short), '-an', '-vf', 'scale=1280:720:flags=lanczos',
                    '-c:v', 'libx264', '-preset', 'slow', '-crf', '25', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(hero)], check=True)
    subprocess.run([FFMPEG, '-v', 'error', '-y', '-ss', '3.7', '-to', '11.8', '-i', str(short), '-an', '-vf', 'fps=15,scale=960:-2:flags=lanczos',
                    '-c:v', 'libwebp_anim', '-lossless', '0', '-q:v', '62', '-compression_level', '6', '-loop', '0', str(teaser)], check=True)


def banner(out, width=1600):
    """The README banner: the finished title card, cropped to a wide band."""
    card = Opening(json.loads(TASKS.read_text())['tasks']).card(3.0)
    top, bottom = 200, 930
    band = card.crop((60, top, W - 40, bottom))
    band.resize((width, round(width * band.height / band.width)), Image.LANCZOS).save(out, optimize=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('kind', choices=['short', 'film', 'banner', 'web'])
    parser.add_argument('raw', help='raw render; for web, the short master; unused by banner')
    parser.add_argument('out', nargs='+', help='output; for web, the hero MP4 and the teaser WebP')
    parser.add_argument('--still', type=float, help='write only the frame of the title card at this time, as PNG')
    args = parser.parse_args(argv)
    args.out = args.out if args.kind == 'web' else args.out[0]
    if args.still is not None:
        Opening(json.loads(TASKS.read_text())['tasks']).card(args.still).save(args.out); return
    if args.kind == 'banner':
        banner(args.out); return
    if args.kind == 'web':
        web(args.raw, *args.out); return
    print(build(args.kind, args.raw, args.out), 'frames')


if __name__ == '__main__':
    main()
