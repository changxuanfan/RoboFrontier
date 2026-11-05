// RoboFrontier project page. Everything shown comes from data/*.json; missing data is shown
// as pending, never as a placeholder number.
(() => {
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const h = (tag, attrs = {}, ...kids) => {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    // ARIA states are the strings "true"/"false"; other boolean attributes are present or absent.
    const aria = k.startsWith('aria-');
    if (v == null || (v === false && !aria)) continue;
    if (k === 'class') el.className = v; else if (k === 'style') el.style.cssText = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v); else el.setAttribute(k, aria ? String(v) : v === true ? '' : v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};
const svg = (tag, attrs = {}, ...kids) => {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  for (const kid of kids.flat()) if (kid != null) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
};
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const canHover = matchMedia('(hover: hover)').matches;
const FAMILY_ORDER = ['transport', 'mosaic', 'relay', 'dial'];
const SHOWCASE = {transport: 'transport-a12-d3', mosaic: 'mosaic-a08-12x24-d3', relay: 'relay-a16-d3', dial: 'dial-best5-n08-d3'};
// Theme tokens (site.css), so every chart follows the light or dark theme.
const MODEL_COLORS = Array.from({length: 8}, (_, i) => `var(--m${i + 1})`);

const state = {tasks: null, media: null, results: null, source: 'oracle', family: 'all', view: 'front', explainFamily: 'transport'};

async function load(path) {
  try { const r = await fetch(path, {cache: 'no-cache'}); return r.ok ? r.json() : null; } catch { return null; }
}

// ---------- chrome: top bar, theme, reveal, counters ----------
// Light by default; the Theme button switches to dark and the choice is remembered per browser.
function theme() {
  const root = document.documentElement, button = $('#theme');
  const show = () => { const dark = root.dataset.theme === 'dark';
    button.setAttribute('aria-pressed', dark); button.setAttribute('aria-label', dark ? 'Switch to light theme' : 'Switch to dark theme'); };
  button.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark'; show();
    try { localStorage.setItem('rf-theme', root.dataset.theme); } catch { /* storage may be blocked */ }
  });
  show();
}
function chrome() {
  const rail = $('#rail');
  const links = $$('.rail nav a');
  const onScroll = () => rail.classList.toggle('solid', scrollY > 8);
  addEventListener('scroll', onScroll, {passive: true}); onScroll();
  const chapters = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) links.forEach(a => a.classList.toggle('on', a.dataset.chapter === e.target.id));
  }), {rootMargin: '-45% 0px -50% 0px'});
  $$('section.chapter[id]').forEach(s => chapters.observe(s));
  theme();
  const reveal = new IntersectionObserver(entries => entries.forEach(e => {
    if (e.isIntersecting) { e.target.classList.add('in'); reveal.unobserve(e.target); }
  }), {threshold: .12});
  $$('.reveal').forEach(el => reveal.observe(el));
  const counters = new IntersectionObserver(entries => entries.forEach(e => {
    if (!e.isIntersecting) return; counters.unobserve(e.target);
    const end = +e.target.dataset.count; if (reduced) return;
    const t0 = performance.now();
    const step = t => { const k = Math.min(1, (t - t0) / 1100); e.target.textContent = Math.round(end * (1 - (1 - k) ** 3)); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }), {threshold: .6});
  $$('[data-count]').forEach(el => counters.observe(el));
  const hero = $('#hero-video');
  new IntersectionObserver(([e]) => e.isIntersecting ? hero.play().catch(() => {}) : hero.pause()).observe(hero);
  if (reduced) hero.pause();
  $$('[data-copy]').forEach(b => b.addEventListener('click', async () => {
    await navigator.clipboard.writeText($('#' + b.dataset.copy).textContent); b.textContent = 'Copied'; setTimeout(() => b.textContent = 'Copy', 1600);
  }));
}

// ---------- media helpers ----------
const mediaSet = key => state.media?.sets.find(s => s.key === key);
function clip(key, id, view) {
  const set = mediaSet(key); const rec = set?.tasks[id]?.[view];
  return rec ? {video: set.base + rec.video, poster: set.base + rec.poster, duration: rec.duration_s, size: rec.size} : null;
}
const task = id => state.tasks.tasks.find(t => t.id === id);
const famColor = f => `var(--${f})`;

// A frame with a poster that plays its clip on hover (or when in view on touch screens).
const viewPlayer = canHover ? null : new IntersectionObserver(entries => entries.forEach(e => {
  const v = $('video', e.target); if (!v) return;
  if (e.isIntersecting && e.intersectionRatio > .6) start(e.target, v); else stop(e.target, v);
}), {threshold: [0, .6, 1]});
function start(host, v) { if (reduced) return; if (!v.src) v.src = v.dataset.src; v.play().then(() => host.classList.add('playing')).catch(() => {}); }
function stop(host, v) { v.pause(); host.classList.remove('playing'); }
function frame(c, hud) {
  const f = h('div', {class: 'frame'});
  if (c) { f.append(h('img', {src: c.poster, alt: '', loading: 'lazy', decoding: 'async'}), h('video', {'data-src': c.video, muted: true, loop: true, playsinline: true, preload: 'none'})); $('video', f).muted = true; }
  if (hud) f.append(h('span', {class: 'hud'}, hud));
  return f;
}
function hoverPlay(host) {
  const v = $('video', host); if (!v) return host;
  if (canHover) { host.addEventListener('mouseenter', () => start(host, v)); host.addEventListener('mouseleave', () => stop(host, v));
    host.addEventListener('focus', () => start(host, v)); host.addEventListener('blur', () => stop(host, v)); }
  else viewPlayer.observe(host);
  return host;
}

// ---------- hero map ----------
// A schematic of the Robo World hall: the four zones in their floor colors, nine tables each.
// Columns are team sizes and rows are levels; a table widens with its team, one dot per arm.
const ZONES = {transport: [0, 0], mosaic: [1, 0], relay: [0, 1], dial: [1, 1]};
const scaleOf = id => id.replace(/-d\d$/, '');
const scaleNumber = id => +(id.match(/-[an](\d+)/) || [0, 0])[1];
function perimeter(x, y, w, hgt, n) {
  const total = 2 * (w + hgt), pts = [];
  for (let k = 0; k < n; k++) {
    let d = (k + .5) * total / n;
    if (d < w) { pts.push([x + d, y]); continue; } d -= w;
    if (d < hgt) { pts.push([x + w, y + d]); continue; } d -= hgt;
    if (d < w) { pts.push([x + w - d, y + hgt]); continue; } d -= w;
    pts.push([x, y + hgt - d]);
  }
  return pts;
}
function plan() {
  const box = $('#plan'), cap = $('#plan-caption'), idle = cap.textContent;
  const ZW = 300, ZH = 214, GAP = 18, P = 10, W = 2 * ZW + GAP + 2 * P, H = 2 * ZH + GAP + 2 * P;
  const map = svg('svg', {viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': 'Robo World: four zones, nine tasks each'});
  // The hall floor and its two aisles, dashed down the middle as on the rendered floor.
  map.append(svg('rect', {class: 'hall', x: .5, y: .5, width: W - 1, height: H - 1, rx: 6}),
    svg('path', {class: 'aisle', d: `M${W / 2} ${P / 2}V${H - P / 2}M${P / 2} ${H / 2}H${W - P / 2}`}));
  for (const key of FAMILY_ORDER) {
    const [zx, zy] = ZONES[key], x0 = P + zx * (ZW + GAP), y0 = P + zy * (ZH + GAP), fam = state.tasks.families[key];
    const zone = svg('g', {class: 'zone', style: `--fc:var(--${key})`});
    const name = fam.name.toUpperCase(), sign = name.length * 7.4 + 22;
    zone.append(svg('rect', {class: 'floor', x: x0, y: y0, width: ZW, height: ZH, rx: 4, style: `fill:color-mix(in srgb,var(--${key}) 15%,var(--card))`}),
      svg('rect', {class: 'sign', x: x0 + ZW / 2 - sign / 2, y: y0 + 10, width: sign, height: 17, rx: 2}),
      svg('text', {x: x0 + ZW / 2, y: y0 + 21.5}, name));
    const rows = state.tasks.tasks.filter(t => t.family === key);
    const scales = [...new Set(rows.map(t => scaleOf(t.id)))].sort((a, b) => scaleNumber(a) - scaleNumber(b));
    const ids = rows.map(t => t.id), rh = (ZH - 44) / 3;
    for (const t of rows) {
      const col = scales.indexOf(scaleOf(t.id)), row = t.level - 1;
      const w = 30 + t.arms * 2.6, hgt = 22 + t.arms * .9;
      const cx = x0 + ZW / 6 * (2 * col + 1), cy = y0 + 38 + rh * (row + .5);
      const label = `${t.id} · ${fam.name}, Level ${t.level} (${t.level_note}) · ${t.arms} arms · ${t.workload} ${t.unit}`;
      const desk = svg('g', {class: 'desk', tabindex: 0, role: 'button', 'aria-label': `${label}. Play its Oracle run.`},
        svg('rect', {x: cx - w / 2, y: cy - hgt / 2, width: w, height: hgt, rx: 2.5}),
        ...perimeter(cx - w / 2, cy - hgt / 2, w, hgt, t.arms).map(([px, py]) => svg('circle', {cx: px, cy: py, r: 2.1})));
      const show = () => { cap.textContent = `${label}. Select to play its Oracle run.`; };
      const hide = () => { cap.textContent = idle; };
      const play = () => openPlayer('oracle', t.id, ids);
      desk.addEventListener('mouseenter', show); desk.addEventListener('focus', show);
      desk.addEventListener('mouseleave', hide); desk.addEventListener('blur', hide);
      desk.addEventListener('click', play);
      desk.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); play(); } });
      zone.append(desk);
    }
    map.append(zone);
  }
  box.append(map);
  if (reduced) return;
  let visible = false;
  new IntersectionObserver(([e]) => { visible = e.isIntersecting; }).observe(box);
  const desks = $$('.desk', map);
  setInterval(() => {
    if (!visible || map.matches(':hover')) return;
    const d = desks[Math.floor(Math.random() * desks.length)];
    d.classList.add('on'); setTimeout(() => d.classList.remove('on'), 1100);
  }, 700);
}

// ---------- benchmark ----------
function families() {
  const box = $('#families'), fams = state.tasks.families;
  for (const key of FAMILY_ORDER) {
    const f = fams[key], all = state.tasks.tasks.filter(t => t.family === key);
    const arms = [...new Set(all.map(t => t.arms))].sort((a, b) => a - b);
    const work = [...new Set(all.map(t => t.workload))].sort((a, b) => a - b);
    const id = SHOWCASE[key], t = task(id);
    const card = h('button', {class: 'fam', type: 'button', style: `--c:${famColor(key)}`, 'aria-label': `${f.name}: play ${id}`,
      onclick: () => openPlayer('oracle', id, all.map(x => x.id))},
      h('div', {class: 'bar'}),
      frame(clip('oracle', id, 'front'), `ORACLE${t.oracle?.kind === 'assisted' ? ' (ASSISTED)' : ''} · ${t.arms} ARMS · L${t.level}`),
      h('div', {class: 'meta'}, h('h3', {}, f.name, h('small', {}, `${arms[0]}–${arms.at(-1)} arms`)),
        h('p', {}, `${f.verb}. ${work[0]}–${work.at(-1)} ${f.unit} per task.`)));
    box.append(hoverPlay(card));
  }
}

// ---------- explainer: what changes across a family's nine tasks ----------
// Initial-state renders from the task atlas (site/assets/atlas), one camera per family.
const ATLAS_VIEW = {transport: 'global', mosaic: 'top', relay: 'global', dial: 'global'};
const atlasImage = id => `assets/atlas/${id}-${ATLAS_VIEW[familyOf(id)]}.jpg`;
const range = xs => { const v = [...new Set(xs)].sort((a, b) => a - b); return v.length > 1 ? `${v[0]}–${v.at(-1)}` : `${v[0]}`; };
function explainer() {
  const tabs = $('#explain-tabs');
  for (const key of FAMILY_ORDER) tabs.append(h('button', {type: 'button', role: 'tab', 'aria-selected': key === state.explainFamily, style: `--c:${famColor(key)}`,
    onclick: e => { state.explainFamily = key; $$('button', tabs).forEach(b => b.setAttribute('aria-selected', b === e.currentTarget)); drawExplainer(); }},
    h('i'), state.tasks.families[key].name));
  drawExplainer();
}
function drawExplainer() {
  const key = state.explainFamily, fam = state.tasks.families[key];
  const rows = state.tasks.tasks.filter(t => t.family === key);
  const scales = [...new Set(rows.map(t => scaleOf(t.id)))].sort((a, b) => scaleNumber(a) - scaleNumber(b));
  const side = $('#explain-side'), grid = $('#explain-grid');
  side.style.setProperty('--c', famColor(key)); grid.style.setProperty('--c', famColor(key));
  const teams = scales.map(sc => { const col = rows.filter(r => scaleOf(r.id) === sc), t = col[0];
    // Dial columns are dial counts; their arm count doubles from Level 2.
    return key === 'dial' ? {head: `${t.workload} dials`, sub: `${range(col.map(r => r.arms))} arms`} : {head: `${t.arms} arms`, sub: `${t.workload} ${t.unit}`}; });
  side.replaceChildren(
    h('h4', {}, fam.name), h('p', {class: 'verb'}, `${fam.verb}.`),
    h('ul', {class: 'chips'}, h('li', {}, `${range(rows.map(t => t.arms))} arms`), h('li', {}, `${range(rows.map(t => t.workload))} ${fam.unit}`), h('li', {}, '3 levels')),
    h('p', {class: 'side-label'}, 'Levels change the job'),
    h('ol', {class: 'levels'}, fam.levels.map((note, i) => h('li', {}, h('b', {}, `L${i + 1}`), note))),
    h('p', {class: 'side-label'}, 'Team sizes change the scale'),
    h('ol', {class: 'levels teams'}, teams.map((tm, i) => h('li', {}, h('b', {}, ['S', 'M', 'L'][i]), `${tm.head} · ${tm.sub}`))));
  grid.replaceChildren(h('div', {class: 'corner'}),
    ...teams.map(tm => h('div', {class: 'col-head'}, h('b', {}, tm.head), tm.sub)));
  for (const level of [1, 2, 3]) {
    grid.append(h('div', {class: 'row-head'}, h('b', {}, `L${level}`), h('span', {}, fam.levels[level - 1])));
    for (const sc of scales) {
      const t = rows.find(r => scaleOf(r.id) === sc && r.level === level), c = clip('oracle', t.id, 'front');
      const cell = h('button', {class: 'shot', type: 'button', 'aria-label': `${t.id}: initial state. Play its Oracle run.`,
        onclick: () => openPlayer('oracle', t.id, rows.map(r => r.id))},
        frame(c ? {...c, poster: atlasImage(t.id)} : {poster: atlasImage(t.id), video: null}), h('span', {class: 'shot-id'}, t.id));
      grid.append(c ? hoverPlay(cell) : cell);
    }
  }
  grid.classList.remove('swap'); void grid.offsetWidth; grid.classList.add('swap');
}

function protocolArms() {
  const g = $('#p-arms'); if (!g) return;
  const xs = Array.from({length: 6}, (_, i) => 160 + i * 56);
  const circles = xs.map((x, i) => { const c = svg('circle', {cx: x, cy: 316, r: 9}); g.append(c, svg('text', {x, y: 344, class: 't-dim'}, 'ABCDEF'[i])); return c; });
  const owner = [0, 0, 1, 1, 1, 2];
  if (reduced) return;
  let k = 0;
  setInterval(() => { k = (k + 1) % 8; circles.forEach((c, i) => c.classList.toggle('busy', k >= 1 + owner[i] && k < 6)); }, 900);
}

// ---------- watch ----------
// Model video sets planned for the wall. A planned set shows "soon" until media.json lists it;
// the wall opens on the first published set and falls back to Oracle.
const PLANNED_SOURCES = [{key: 'gpt-6.1', label: 'GPT-6.1'}];
function sources() {
  const list = PLANNED_SOURCES.map(p => ({...p, pending: !mediaSet(p.key)}));
  for (const s of state.media?.sets || []) if (!['oracle', 'film'].includes(s.key) && !list.some(x => x.key === s.key)) list.push({key: s.key, label: s.label || s.key});
  for (const m of models()) if (!list.some(x => x.key === m.key)) list.push({key: m.key, label: m.label, pending: !mediaSet(m.key)});
  list.push({key: 'oracle', label: 'Oracle'});
  return list;
}
function wallControls() {
  const tabs = $('#source-tabs');
  state.source = sources().find(x => !x.pending)?.key || 'oracle';
  for (const s of sources()) tabs.append(h('button', {type: 'button', role: 'tab', 'aria-selected': s.key === state.source, title: s.pending ? 'Videos are rendering' : null,
    onclick: e => { state.source = s.key; $$('button', tabs).forEach(b => b.setAttribute('aria-selected', b === e.currentTarget)); drawWall(); }},
    s.label, s.pending ? h('small', {}, '· soon') : null));
  const fam = $('#wall-family');
  for (const key of ['all', ...FAMILY_ORDER]) fam.append(h('button', {type: 'button', role: 'tab', 'aria-selected': key === state.family,
    style: key === 'all' ? null : `--c:${famColor(key)}`,
    onclick: e => { state.family = key; $$('button', fam).forEach(b => b.setAttribute('aria-selected', b === e.currentTarget)); drawWall(); }},
    key === 'all' ? null : h('i'), key === 'all' ? 'All' : state.tasks.families[key].name));
  $$('#wall-view button').forEach(b => b.addEventListener('click', () => {
    state.view = b.dataset.view; $$('#wall-view button').forEach(x => x.setAttribute('aria-selected', x === b)); drawWall(); }));
  drawWall();
}
function drawWall() {
  const box = $('#wall'); box.replaceChildren();
  const list = state.tasks.tasks.filter(t => state.family === 'all' || t.family === state.family);
  const ids = list.map(t => t.id);
  let shown = 0;
  for (const t of list) {
    const c = clip(state.source, t.id, state.view);
    const tile = h('button', {class: 'tile' + (c ? '' : ' empty'), type: 'button', style: `--c:${famColor(t.family)}`, disabled: !c,
      'aria-label': c ? `Play ${t.id}` : `${t.id}: not rendered yet`, onclick: () => openPlayer(state.source, t.id, ids)},
      c ? frame(c) : h('div', {class: 'frame'}, h('span', {}, 'Rendering')),
      h('div', {class: 'tile-meta'}, h('span', {class: 'chip'}, h('i'), h('b', {}, t.id)), c ? fmtDuration(c.duration) : `L${t.level}`));
    if (c) { shown++; hoverPlay(tile); }
    box.append(tile);
  }
  if (!shown) box.append(h('p', {class: 'wall-note'}, 'These runs are still being rendered in Robo World. They will appear here when published.'));
}
const ORACLE_KIND = {program: 'Reference program', assisted: 'Operator-assisted reference program',
  reviewed: 'Historical run; completion confirmed by review, not by the current scorer'};
function oracleNote(o) {
  if (!o) return '';
  const revision = o.revision === 'historical' ? '' : `, recorded on revision ${o.revision}`;
  return `${ORACLE_KIND[o.kind]}${revision}. Idle time removed, ${o.speedup}× speed.`;
}
const fmtDuration = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

// ---------- player ----------
const player = {key: null, id: null, list: [], view: 'front'};
function openPlayer(key, id, list) {
  Object.assign(player, {key, id, list: list || [id], view: state.view});
  showPlayer(); const d = $('#player'); if (!d.open) d.showModal();
}
function showPlayer() {
  const t = task(player.id), c = clip(player.key, player.id, player.view) || clip(player.key, player.id, 'front');
  const fam = state.tasks.families[t.family];
  $('#player-kicker').textContent = `${sources().find(s => s.key === player.key)?.label || player.key} · ${fam.name} · Level ${t.level}`;
  $('#player-title').textContent = t.id;
  $('#player-facts').textContent = `${t.arms} arms · ${t.workload} ${t.unit} · ${t.level_note}.` +
    (player.key === 'oracle' ? ' ' + oracleNote(t.oracle) : '') + (c ? ` ${fmtDuration(c.duration)} as edited.` : '');
  const v = $('#player-video'); v.hidden = !c;
  if (c) { v.poster = c.poster; v.src = c.video; v.play().catch(() => {}); }
  else { v.removeAttribute('src'); $('#player-facts').textContent += ' This video is not published yet.'; }
  $$('#player-view button').forEach(b => b.setAttribute('aria-selected', b.dataset.view === player.view));
  const i = player.list.indexOf(player.id);
  $('#player-prev').disabled = i <= 0; $('#player-next').disabled = i >= player.list.length - 1;
}
function playerControls() {
  const d = $('#player'), v = $('#player-video');
  const step = k => { const i = player.list.indexOf(player.id) + k; if (i >= 0 && i < player.list.length && clip(player.key, player.list[i], 'front')) { player.id = player.list[i]; showPlayer(); } };
  $('#player-prev').onclick = () => step(-1); $('#player-next').onclick = () => step(1);
  $('#player-close').onclick = () => d.close();
  $$('#player-view button').forEach(b => b.onclick = () => { const t = v.currentTime / (v.duration || 1); player.view = b.dataset.view; showPlayer();
    v.addEventListener('loadedmetadata', () => { v.currentTime = t * v.duration; }, {once: true}); });
  // A close event can arrive after the player was reopened; only release a closed player's video.
  d.addEventListener('close', () => { if (d.open) return; v.pause(); v.removeAttribute('src'); v.load(); });
  d.addEventListener('click', e => { if (e.target === d) d.close(); });
  d.addEventListener('keydown', e => { if (e.key === 'ArrowRight') step(1); if (e.key === 'ArrowLeft') step(-1); });
  $$('[data-film]').forEach(b => b.addEventListener('click', () => {
    const film = state.media?.film; if (!film) return;
    $('#player-kicker').textContent = 'RoboFrontier · film'; $('#player-title').textContent = 'Robo World: four families, 36 tasks';
    $('#player-facts').textContent = film.note || ''; $('#player-view').hidden = true; $('#player-prev').hidden = $('#player-next').hidden = true;
    v.poster = film.poster || ''; v.src = film.video; d.showModal(); v.play().catch(() => {});
    d.addEventListener('close', () => { $('#player-view').hidden = false; $('#player-prev').hidden = $('#player-next').hidden = false; }, {once: true});
  }));
}

// ---------- results ----------
const METRICS = [
  {key: 'completion', label: 'Completion rate', fmt: pct, better: 'high', of: rs => mean(rs.map(r => +!!r.success))},
  {key: 'progress', label: 'Mean progress', fmt: pct, better: 'high', of: rs => mean(rs.map(r => r.progress))},
  {key: 'failures', label: 'Failed actions / run', fmt: num, better: 'low', of: rs => mean(rs.map(r => r.failed_actions))},
  {key: 'failure_rate', label: 'Failure rate', fmt: pct, better: 'low', of: rs => ratio(rs, 'failed_actions', 'actions')},
  {key: 'retries', label: 'Retries / run', fmt: num, better: 'low', of: rs => mean(rs.map(r => r.retries))},
  {key: 'retry_rate', label: 'Retry rate', fmt: pct, better: 'low', of: rs => ratio(rs, 'retries', 'actions')},
  {key: 'time', label: 'Time to finish', fmt: hours, better: 'low', of: rs => mean(rs.filter(r => r.success).map(r => r.wall_s))},
  {key: 'tokens_in', label: 'Input tokens / run', fmt: big, better: 'low', of: rs => mean(rs.map(r => r.tokens_in))},
  {key: 'tokens_out', label: 'Output tokens / run', fmt: big, better: 'low', of: rs => mean(rs.map(r => r.tokens_out))},
  {key: 'collisions', label: 'Arm collisions / run', fmt: num, better: 'low', of: rs => mean(rs.map(r => r.collisions))},
  {key: 'parallel', label: 'Parallel efficiency', fmt: pct, better: 'high', of: rs => mean(rs.map(r => r.parallel_efficiency))},
  {key: 'messages', label: 'Messages / run', fmt: num, better: 'low', of: rs => mean(rs.map(r => r.messages))},
];
function mean(xs) { xs = xs.filter(x => Number.isFinite(x)); return xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : null; }
function ratio(rs, a, b) { const n = rs.reduce((s, r) => s + (r[a] || 0), 0), d = rs.reduce((s, r) => s + (r[b] || 0), 0); return d ? n / d : null; }
function pct(x) { return x == null ? '—' : `${(x * 100).toFixed(x < .1 ? 1 : 0)}%`; }
function num(x) { return x == null ? '—' : x >= 100 ? Math.round(x).toLocaleString() : x.toFixed(1); }
function big(x) { return x == null ? '—' : x >= 1e6 ? `${(x / 1e6).toFixed(1)}M` : x >= 1e3 ? `${(x / 1e3).toFixed(0)}k` : String(Math.round(x)); }
function hours(x) { return x == null ? '—' : `${(x / 3600).toFixed(1)} h`; }
const familyOf = id => id.split('-')[0];
function runs(filter = {}) {
  return (state.results?.runs || []).map(r => ({family: familyOf(r.case), level: +r.case.slice(-1), ...r}))
    .filter(r => Object.entries(filter).every(([k, v]) => r[k] === v));
}
// The benchmark setting: adaptive, with the shared skill file. Comparison runs feed only the analysis.
const bench = (filter = {}) => runs({topology: 'adaptive', ...filter}).filter(r => r.skills !== false);
function models() {
  const seen = new Map();
  for (const r of bench()) if (!seen.has(r.model)) seen.set(r.model, {key: r.model, label: r.model_label || r.model});
  return [...seen.values()].map((m, i) => ({...m, color: MODEL_COLORS[i % MODEL_COLORS.length]}));
}

function pendingPanel(title, text, metrics) {
  return h('div', {class: 'pending'}, h('h4', {}, title), h('p', {}, text),
    metrics ? h('ul', {class: 'metric-list'}, metrics.map(m => h('li', {}, m))) : null);
}
// An empty chart frame for a study whose runs are not in data/results.json yet: axes, axis
// titles and the series it will compare, never placeholder values.
function skeleton({kind = 'bars', x, y, series = [], metrics = []}) {
  const W = 640, H = 230, L = 46, B = 30, T = 12, s = svg('svg', {viewBox: `0 0 ${W} ${H}`, 'aria-hidden': 'true'});
  for (let k = 0; k <= 4; k++) { const yy = T + (H - T - B) * k / 4; s.append(svg('line', {x1: L, x2: W - 8, y1: yy, y2: yy, class: 'grid'})); }
  if (kind === 'lines') for (let hr = 0; hr <= 24; hr += 6) s.append(svg('text', {x: L + (W - L - 8) * hr / 24, y: H - 8, 'text-anchor': hr === 24 ? 'end' : 'middle'}, `${hr}h`));
  s.append(svg('line', {x1: L, x2: L, y1: T, y2: H - B, class: 'axis'}), svg('line', {x1: L, x2: W - 8, y1: H - B, y2: H - B, class: 'axis'}),
    svg('text', {x: 12, y: (H - B + T) / 2, transform: `rotate(-90 12 ${(H - B + T) / 2})`, 'text-anchor': 'middle'}, y || ''),
    svg('text', {x: (W + L) / 2, y: H - 8 - (kind === 'lines' ? 14 : 0), 'text-anchor': 'middle'}, kind === 'lines' ? '' : x || ''));
  return h('div', {class: 'chart skeleton'},
    h('div', {class: 'chart-head'}, h('span', {class: 'legend'}, series.map(se => h('span', {style: `--c:${se.color}`}, h('i'), se.label))),
      h('span', {class: 'status'}, h('i'), 'Runs in progress')),
    h('div', {class: 'frame-wrap'}, s, h('p', {}, kind === 'lines' && x ? `${x}. ` : '', 'Fills in from data/results.json when the runs behind it are complete.')),
    metrics.length ? h('ul', {class: 'metric-list'}, metrics.map(m => h('li', {}, m))) : null);
}

// The board leads with failures: completion saturates for strong models.
const BOARD = ['failures', 'failure_rate', 'retries', 'retry_rate', 'completion', 'progress', 'time', 'tokens_in', 'tokens_out', 'collisions', 'parallel', 'messages'];
function results() {
  const box = $('#results-body'), ms = models();
  if (!ms.length) {
    box.append(skeleton({kind: 'bars', x: 'Failed actions per run', y: 'Model', metrics: BOARD.map(k => METRICS.find(m => m.key === k).label)}));
    timeCharts(ms); return;
  }
  const order = BOARD.map(k => METRICS.find(m => m.key === k));
  let metric = order[0];
  const chips = h('div', {class: 'segmented', role: 'tablist', 'aria-label': 'Metric'});
  const chart = h('div', {class: 'chart'});
  const draw = () => { chart.replaceChildren(rankChart(ms, metric)); };
  for (const m of order) chips.append(h('button', {type: 'button', role: 'tab', 'aria-selected': m === metric,
    onclick: e => { metric = m; $$('button', chips).forEach(b => b.setAttribute('aria-selected', b === e.currentTarget)); draw(); }}, m.label));
  draw();
  box.append(h('div', {class: 'board'}, chips, chart, heatmap(ms), table(ms)));
  timeCharts(ms);
}
// Completion and tokens against hours since START, one line per model.
function timeCharts(ms) {
  const curve = (key, rs, step = 1800) => {
    const end = Math.max(...rs.flatMap(r => (r[key] || []).map(p => p[0])), 0);
    const at = (c, t) => { let v = 0; for (const [ct, cv] of c) { if (ct > t) break; v = cv; } return v; };
    const pts = []; for (let t = 0; t <= end; t += step) pts.push([t, mean(rs.map(r => at(r[key] || [], t)))]); return pts;
  };
  const done = ms.filter(m => bench({model: m.key}).some(r => r.completion_curve?.length));
  $('#time-chart').append(done.length
    ? h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('span', {class: 'legend'}, done.map(m => h('span', {style: `--c:${m.color}`}, h('i'), m.label)))),
      lineChart(done.map(m => ({color: m.color, points: curve('completion_curve', bench({model: m.key}))}))))
    : skeleton({kind: 'lines', x: 'Hours since START', y: 'Tasks complete'}));
  const spent = ms.filter(m => bench({model: m.key}).some(r => r.token_curve?.length));
  if (!spent.length) { $('#token-chart').append(skeleton({kind: 'lines', x: 'Hours since START', y: 'Tokens'})); return; }
  const series = spent.map(m => ({color: m.color, points: curve('token_curve', bench({model: m.key}))}));
  const top = Math.max(...series.flatMap(se => se.points.map(p => p[1])), 1);
  $('#token-chart').append(h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('span', {class: 'legend'}, spent.map(m => h('span', {style: `--c:${m.color}`}, h('i'), m.label)))),
    lineChart(series, {yMax: top, fmt: big})));
}

function rankChart(ms, metric) {
  const rows = ms.map(m => ({m, v: metric.of(bench({model: m.key}))})).filter(r => r.v != null)
    .sort((a, b) => metric.better === 'high' ? b.v - a.v : a.v - b.v);
  const max = Math.max(...rows.map(r => r.v), 1e-9), W = 1240, row = 40, left = 200;
  const s = svg('svg', {viewBox: `0 0 ${W} ${rows.length * row + 10}`, role: 'img', 'aria-label': metric.label});
  rows.forEach((r, i) => {
    const y = i * row + 6, w = (W - left - 90) * r.v / max;
    s.append(svg('text', {x: 0, y: y + 21, class: 'label'}, r.m.label),
      svg('rect', {x: left, y: y + 6, height: 22, rx: 3, width: reduced ? w : 0, style: `fill:${r.m.color}`, class: 'bar-rect', 'data-w': w}),
      svg('text', {x: left + w + 10, y: y + 22}, metric.fmt(r.v)));
  });
  requestAnimationFrame(() => requestAnimationFrame(() => $$('rect[data-w]', s).forEach(rect => rect.setAttribute('width', rect.dataset.w))));
  return h('div', {}, h('div', {class: 'chart-head'}, h('h4', {}, metric.label), h('span', {class: 'legend'}, metric.better === 'high' ? 'higher is better' : 'lower is better')), s);
}

function heatmap(ms) {
  const cols = FAMILY_ORDER.flatMap(f => [1, 2, 3].map(l => ({f, l}))), cw = 58, ch = 34, left = 180, top = 44;
  const s = svg('svg', {viewBox: `0 0 ${left + cols.length * cw} ${top + ms.length * ch}`, role: 'img', 'aria-label': 'Completion by family and level'});
  cols.forEach((c, j) => s.append(svg('text', {x: left + j * cw + cw / 2, y: top - 10, 'text-anchor': 'middle'}, `${c.f[0].toUpperCase()}${c.l}`)));
  ms.forEach((m, i) => {
    s.append(svg('text', {x: 0, y: top + i * ch + 22, class: 'label'}, m.label));
    cols.forEach((c, j) => {
      const v = mean(bench({model: m.key, family: c.f, level: c.l}).map(r => +!!r.success));
      s.append(svg('rect', {x: left + j * cw + 2, y: top + i * ch + 2, width: cw - 4, height: ch - 4,
        rx: 4, style: `fill:${v == null ? 'var(--card2)' : `color-mix(in oklab, var(--${c.f}) ${Math.round(15 + 85 * v)}%, var(--card))`}`}),
        svg('text', {x: left + j * cw + cw / 2, y: top + i * ch + 22, 'text-anchor': 'middle', class: 'label'}, v == null ? '·' : pct(v)));
    });
  });
  return h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('h4', {}, 'Completion by family and level'),
    h('span', {class: 'legend'}, FAMILY_ORDER.map(f => h('span', {style: `--c:${famColor(f)}`}, h('i'), state.tasks.families[f].name)))), s);
}

function table(ms) {
  let sortKey = 'completion', dir = -1;
  const wrap = h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('h4', {}, 'All metrics')));
  const holder = h('div', {class: 'table-wrap'}); wrap.append(holder);
  const draw = () => {
    const rows = ms.map(m => ({m, vals: Object.fromEntries(METRICS.map(x => [x.key, x.of(bench({model: m.key}))]))}))
      .sort((a, b) => ((a.vals[sortKey] ?? -Infinity) - (b.vals[sortKey] ?? -Infinity)) * dir);
    holder.replaceChildren(h('table', {class: 'data'},
      h('thead', {}, h('tr', {}, h('th', {}, 'Model'), METRICS.map(x => h('th', {'aria-sort': x.key === sortKey ? (dir < 0 ? 'descending' : 'ascending') : null,
        onclick: () => { dir = x.key === sortKey ? -dir : -1; sortKey = x.key; draw(); }}, x.label)))),
      h('tbody', {}, rows.map(r => h('tr', {}, h('td', {}, r.m.label), METRICS.map(x => h('td', {}, x.fmt(r.vals[x.key]))))))));
  };
  draw(); return wrap;
}

// ---------- analysis ----------
const TOPOLOGIES = [
  {key: 'single', label: 'Single', text: 'One agent drives every arm.'},
  {key: 'controller-worker', label: 'Controller–Worker', text: 'A permanent worker per arm.'},
  {key: 'worker-worker', label: 'Worker–Worker', text: 'Peers coordinate directly.'},
  {key: 'adaptive', label: 'Adaptive', text: 'Delegates on demand.'},
];
function topoGlyph(key) {
  const s = svg('svg', {viewBox: '0 0 200 110', 'aria-hidden': 'true'});
  const node = (x, y, lead) => svg('circle', {cx: x, cy: y, r: lead ? 10 : 7, class: lead ? 'lead' : null});
  const line = (a, b, msg) => svg('line', {x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: msg ? 'msg' : null});
  const arms = [[30, 88], [75, 88], [125, 88], [170, 88]];
  if (key === 'single') s.append(...arms.map(a => line([100, 24], a)), node(100, 24, true), ...arms.map(a => node(...a)));
  if (key === 'controller-worker') { const w = [[30, 60], [75, 60], [125, 60], [170, 60]];
    s.append(...w.map(p => line([100, 18], p, true)), ...w.map((p, i) => line(p, arms[i])), node(100, 18, true), ...w.map(p => node(...p)), ...arms.map(a => svg('rect', {x: a[0] - 4, y: a[1] - 4, width: 8, height: 8, class: 'arm'}))); }
  if (key === 'worker-worker') { const w = [[30, 40], [75, 70], [125, 40], [170, 70]];
    s.append(line(w[0], w[1], true), line(w[1], w[2], true), line(w[2], w[3], true), line(w[0], w[2], true), line(w[1], w[3], true), ...w.map(p => node(...p))); }
  if (key === 'adaptive') { const d = [[55, 72], [145, 72]];
    s.append(...d.map(p => line([100, 20], p, true)), node(100, 20, true), ...d.map(p => node(...p)), line(d[0], arms[0]), line(d[0], arms[1]), line(d[1], arms[3]),
      ...arms.map(a => svg('rect', {x: a[0] - 4, y: a[1] - 4, width: 8, height: 8, class: 'arm'}))); }
  return s;
}
function analysis() {
  const box = $('#topologies');
  for (const t of TOPOLOGIES) box.append(h('div', {class: 'topo' + (t.key === 'adaptive' ? ' best' : '')},
    h('h4', {}, t.label, t.key === 'adaptive' ? h('span', {class: 'badge'}, 'BENCHMARK') : null), h('p', {}, t.text), topoGlyph(t.key)));
  communication(); skills(); cameras();
}

function groupedBars(groups, series, metrics) {
  // groups: [{label, values:{seriesKey: number|null}}] per metric; normalized per metric.
  const W = 1240, rowH = 30 * series.length + 26, left = 200;
  const s = svg('svg', {viewBox: `0 0 ${W} ${metrics.length * rowH}`, role: 'img'});
  metrics.forEach((m, i) => {
    const vals = series.map(se => m.of(se.runs)), max = Math.max(...vals.filter(v => v != null), 1e-9), y0 = i * rowH;
    s.append(svg('text', {x: 0, y: y0 + 18, class: 'label'}, m.label));
    series.forEach((se, j) => { const v = vals[j], w = v == null ? 0 : (W - left - 90) * v / max, y = y0 + 4 + j * 30;
      s.append(svg('rect', {x: left, y, width: reduced ? w : 0, 'data-w': w, height: 20, rx: 3, style: `fill:${se.color}`, class: 'bar-rect'}),
        svg('text', {x: left + w + 8, y: y + 15}, v == null ? 'pending' : m.fmt(v))); });
  });
  requestAnimationFrame(() => requestAnimationFrame(() => $$('rect[data-w]', s).forEach(r => r.setAttribute('width', r.dataset.w))));
  return s;
}

function communication() {
  const box = $('#communication-chart');
  const gpt = runs().filter(r => /gpt/i.test(r.model));
  const series = TOPOLOGIES.map((t, i) => ({key: t.key, label: t.label, color: ['var(--dim)', 'var(--transport)', 'var(--relay)', 'var(--accent)'][i], runs: gpt.filter(r => r.topology === t.key)}));
  if (series.filter(s => s.runs.length).length < 2) {
    box.append(skeleton({x: 'Per organization', y: 'Value', series,
      metrics: ['Completion', 'Failed actions', 'Time to finish', 'Tokens', 'Parallel efficiency', 'Arm collisions', 'Messages', 'Delegations']}));
    return;
  }
  const pick = ['completion', 'time', 'tokens_in', 'parallel', 'collisions', 'messages'].map(k => METRICS.find(m => m.key === k));
  box.append(h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('h4', {}, 'Same model, four organizations'),
    h('span', {class: 'legend'}, series.map(s => h('span', {style: `--c:${s.color}`}, h('i'), s.label)))), groupedBars(null, series, pick)));
}

function lineChart(series, {yMax = 1, fmt = pct} = {}) {
  const W = 1240, H = 380, L = 56, B = 30, T = 10;
  const maxX = Math.max(...series.flatMap(s => s.points.map(p => p[0])), 1);
  const sx = v => L + (W - L - 10) * v / maxX, sy = v => T + (H - T - B) * (1 - v / yMax);
  const s = svg('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img'});
  for (const k of [0, .25, .5, .75, 1]) s.append(svg('line', {x1: L, x2: W - 10, y1: sy(k * yMax), y2: sy(k * yMax), class: 'grid'}), svg('text', {x: 0, y: sy(k * yMax) + 4}, fmt(k * yMax)));
  for (let hr = 0; hr <= maxX / 3600; hr += 6) s.append(svg('text', {x: sx(hr * 3600), y: H - 8, 'text-anchor': 'middle'}, `${hr}h`));
  for (const se of series) {
    const d = se.points.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
    const path = svg('path', {d, fill: 'none', style: `stroke:${se.color}`, 'stroke-width': 2.5});
    s.append(path);
    if (!reduced) requestAnimationFrame(() => { const len = path.getTotalLength(); path.style.strokeDasharray = len; path.style.strokeDashoffset = len;
      path.getBoundingClientRect(); path.style.transition = 'stroke-dashoffset 1.6s cubic-bezier(.2,.8,.2,1)'; path.style.strokeDashoffset = 0; });
  }
  return s;
}
function meanCurve(rs, step = 1800) {
  const end = Math.max(...rs.flatMap(r => (r.progress_curve || []).map(p => p[0])), 0);
  const at = (curve, t) => { let v = 0; for (const [ct, cv] of curve) { if (ct > t) break; v = cv; } return v; };
  const pts = []; for (let t = 0; t <= end; t += step) pts.push([t, mean(rs.map(r => at(r.progress_curve || [], t)))]);
  return pts;
}
function skills() {
  const box = $('#skills-chart'), all = runs({topology: 'adaptive'}).filter(r => r.progress_curve?.length);
  const withS = all.filter(r => r.skills === true), without = all.filter(r => r.skills === false);
  if (!withS.length || !without.length) {
    box.append(skeleton({kind: 'lines', x: 'Hours since START', y: 'Mean progress',
      series: [{label: 'With skills', color: 'var(--accent)'}, {label: 'Without skills', color: 'var(--dim)'}],
      metrics: ['Progress over time', 'Late-run repeated failures', 'Time to finish', 'Skill file growth']})); return;
  }
  const series = [{label: 'With skills', color: 'var(--accent)', points: meanCurve(withS)}, {label: 'Without skills', color: 'var(--dim)', points: meanCurve(without)}];
  box.append(h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('h4', {}, 'Mean task progress over time'),
    h('span', {class: 'legend'}, series.map(s => h('span', {style: `--c:${s.color}`}, h('i'), s.label)))), lineChart(series)));
}
// Camera access: each role reads only its own arms' cameras (ego) or every camera (all).
function cameras() {
  const box = $('#camera-chart'), rs = runs({topology: 'adaptive'});
  const series = [{key: 'ego', label: 'Own cameras', color: 'var(--relay)'}, {key: 'all', label: 'Every camera', color: 'var(--transport)'}]
    .map(se => ({...se, runs: rs.filter(r => r.camera_access === se.key)}));
  if (series.some(se => !se.runs.length)) {
    box.append(skeleton({x: 'Per camera setting', y: 'Value', series, metrics: ['Completion', 'Failed actions', 'Camera reads', 'Time to finish', 'Tokens']})); return;
  }
  const pick = ['completion', 'failures', 'time', 'tokens_in'].map(k => METRICS.find(m => m.key === k));
  box.append(h('div', {class: 'chart'}, h('div', {class: 'chart-head'}, h('span', {class: 'legend'}, series.map(se => h('span', {style: `--c:${se.color}`}, h('i'), se.label)))),
    groupedBars(null, series, pick)));
}

// ---------- start ----------
async function main() {
  chrome();
  const fixture = new URLSearchParams(location.search).get('fixture');
  [state.tasks, state.media, state.results] = await Promise.all([load('data/tasks.json'), load('data/media.json'),
    load(fixture ? `_dev/${fixture.replace(/[^\w.-]/g, '')}` : 'data/results.json')]);
  if (!state.tasks) { $('#families').append(pendingPanel('Data unavailable', 'data/tasks.json could not be loaded.')); return; }
  plan(); families(); explainer(); protocolArms(); wallControls(); playerControls(); results(); analysis();
  deepLink(); addEventListener('hashchange', deepLink);
}

// README links: #film opens the film; #task=<id>[&view=side][&source=<set>] opens one run.
function deepLink() {
  const hash = location.hash.slice(1);
  if (hash === 'film') { $('[data-film]')?.click(); return; }
  const p = new URLSearchParams(hash), id = p.get('task');
  if (!id || !task(id)) return;
  const source = mediaSet(p.get('source')) ? p.get('source') : 'oracle';
  state.view = p.get('view') === 'side' ? 'side' : 'front';
  $('#watch').scrollIntoView();
  openPlayer(source, id, state.tasks.tasks.filter(t => t.family === task(id).family).map(t => t.id));
}
main();
})();
