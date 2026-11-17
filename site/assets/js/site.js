// RoboTeam project page. Everything shown comes from data/*.json; missing data is shown
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
// The video sets on the wall, in this order: the six models of the paper, then the Oracle.
// A set shows "soon" until data/media.json lists it. `about` says how the set was run.
const SOURCES = [
  {key: 'gpt-6.1-sol', label: 'gpt-6.1-sol', about: 'gpt-6.1-sol in Codex with the adaptive system.'},
  {key: 'opus-5.5', label: 'opus-5.5', about: 'opus-5.5 in Claude Code with the adaptive system.'},
  {key: 'kimi-k3.1-pro', label: 'kimi-k3.1-pro', about: 'kimi-k3.1-pro in Codex with the adaptive system.'},
  {key: 'qwen3.8-flash', label: 'qwen3.8-flash', about: 'qwen3.8-flash in Codex with the adaptive system.'},
  {key: 'deepseek-v4.1-flash', label: 'deepseek-v4.1-flash', about: 'deepseek-v4.1-flash in Codex with the adaptive system.'},
  {key: 'glm-5.3-flash', label: 'glm-5.3-flash', about: 'glm-5.3-flash in Codex with the adaptive system.'},
  {key: 'oracle', label: 'Oracle', about: 'The Oracle: gpt-6.1-sol in Codex as a single agent, given the ground-truth position of every object instead of camera images. Some recordings were operator-assisted or made on earlier scene revisions; each video says which.'},
];
// Results are published apart from the code, in the data repository.
const RESULTS_URL = 'https://changxuanfan.github.io/RoboTeam-data/results.json';

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
    try { localStorage.setItem('roboteam-theme', root.dataset.theme); } catch { /* storage may be blocked */ }
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

const familyOf = id => id.split('-')[0];
const scaleOf = id => id.replace(/-d\d$/, '');
const scaleNumber = id => +(id.match(/-[an](\d+)/) || [0, 0])[1];
// The first published set that has this task, models before the Oracle.
const bestSet = id => SOURCES.find(s => clip(s.key, id, 'front'))?.key;
const outcome = (key, id) => state.results?.outcomes?.[key]?.[id];
const hours = x => x == null ? '—' : `${x < 10 ? x.toFixed(1) : Math.round(x)} h`;
function pendingPanel(title, text) { return h('div', {class: 'pending'}, h('h4', {}, title), h('p', {}, text)); }

// ---------- hero: one live run of each task type ----------
function stage() {
  const box = $('#stage');
  for (const key of FAMILY_ORDER) {
    const id = SHOWCASE[key], t = task(id), set = bestSet(id), c = set && clip(set, id, 'front');
    const all = state.tasks.tasks.filter(x => x.family === key).map(x => x.id);
    const tile = h('button', {class: 'stage-tile', type: 'button', style: `--c:${famColor(key)}`, disabled: !c,
      'aria-label': `${state.tasks.families[key].name}: ${t.arms} arms. Open the run.`, onclick: () => openPlayer(set, id, all)},
      c ? h('video', {src: c.video, poster: c.poster, muted: true, loop: true, playsinline: true, autoplay: !reduced, preload: 'metadata'}) : h('div', {class: 'stage-empty'}),
      h('span', {class: 'stage-label'}, h('b', {}, state.tasks.families[key].name), `${t.arms} arms`));
    const v = $('video', tile); if (v) v.muted = true;
    box.append(tile);
  }
  const videos = $$('video', box);
  new IntersectionObserver(([e]) => videos.forEach(v => e.isIntersecting && !reduced ? v.play().catch(() => {}) : v.pause())).observe(box);
}

// ---------- watch ----------
const sourceOf = key => SOURCES.find(s => s.key === key);
function wallControls() {
  const tabs = $('#source-tabs');
  state.source = SOURCES.find(s => mediaSet(s.key))?.key || 'oracle';
  for (const s of SOURCES) { const pending = !mediaSet(s.key);
    tabs.append(h('button', {type: 'button', role: 'tab', 'aria-selected': s.key === state.source, title: pending ? 'Videos are being prepared' : null,
      onclick: e => { state.source = s.key; $$('button', tabs).forEach(b => b.setAttribute('aria-selected', b === e.currentTarget)); drawWall(); }},
      s.label, pending ? h('small', {}, '· soon') : null)); }
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
  const done = list.filter(t => outcome(state.source, t.id)?.completed).length, scored = list.filter(t => outcome(state.source, t.id)).length;
  $('#wall-about').textContent = sourceOf(state.source).about + (scored ? ` Completed ${done} of ${scored} shown.` : '');
  let shown = 0;
  for (const t of list) {
    const c = clip(state.source, t.id, state.view), o = outcome(state.source, t.id);
    const tile = h('button', {class: 'tile' + (c ? '' : ' empty'), type: 'button', style: `--c:${famColor(t.family)}`, disabled: !c,
      'aria-label': c ? `Play ${t.id}` : `${t.id}: video not published yet`, onclick: () => openPlayer(state.source, t.id, ids)},
      c ? frame(c, o ? (o.completed ? `Completed · ${hours(o.hours)}` : 'Not completed') : null) : h('div', {class: 'frame'}, h('span', {}, 'Soon')),
      h('div', {class: 'tile-meta'}, h('span', {class: 'chip'}, h('i'), h('b', {}, t.id)), `${t.arms} arms · L${t.level}`));
    if (o) tile.classList.add(o.completed ? 'done' : 'missed');
    if (c) { shown++; hoverPlay(tile); }
    box.append(tile);
  }
  if (!shown) box.append(h('p', {class: 'wall-note'}, `The ${sourceOf(state.source).label} videos are being prepared. They will appear here when published.`));
}
const ORACLE_KIND = {program: 'Recorded from its program', assisted: 'Operator-assisted recording',
  reviewed: 'Earlier recording; completion confirmed by review, not by the current evaluator'};
function oracleNote(o) {
  if (!o) return '';
  const revision = o.revision === 'historical' ? '' : `, on scene revision ${o.revision}`;
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
  const t = task(player.id), c = clip(player.key, player.id, player.view) || clip(player.key, player.id, 'front'), o = outcome(player.key, player.id);
  const fam = state.tasks.families[t.family];
  $('#player-kicker').textContent = `${sourceOf(player.key)?.label || player.key} · ${fam.name} · Level ${t.level}`;
  $('#player-title').textContent = t.id;
  $('#player-facts').textContent = `${t.arms} arms · ${t.workload} ${t.unit} · ${t.level_note}.` +
    (player.key === 'oracle' ? ' ' + oracleNote(t.oracle) : '') + (o ? (o.completed ? ` Completed in ${hours(o.hours)}.` : ' Not completed.') : '') + (c ? ` ${fmtDuration(c.duration)} as edited.` : '');
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
      const t = rows.find(r => scaleOf(r.id) === sc && r.level === level), set = bestSet(t.id), c = set && clip(set, t.id, 'front');
      const cell = h('button', {class: 'shot', type: 'button', 'aria-label': `${t.id} at its start. Open a run.`,
        onclick: () => openPlayer(set, t.id, rows.map(r => r.id))},
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

function topoGlyph(key) {
  const s = svg('svg', {viewBox: '0 0 200 110', 'aria-hidden': 'true'});
  const node = (x, y, lead) => svg('circle', {cx: x, cy: y, r: lead ? 10 : 7, class: lead ? 'lead' : null});
  const line = (a, b, msg) => svg('line', {x1: a[0], y1: a[1], x2: b[0], y2: b[1], class: msg ? 'msg' : null});
  const arms = [[30, 88], [75, 88], [125, 88], [170, 88]];
  if (key === 'single-agent') s.append(...arms.map(a => line([100, 24], a)), node(100, 24, true), ...arms.map(a => node(...a)));
  if (key === 'hierarchical') { const w = [[30, 60], [75, 60], [125, 60], [170, 60]];
    s.append(...w.map(p => line([100, 18], p, true)), ...w.map((p, i) => line(p, arms[i])), node(100, 18, true), ...w.map(p => node(...p)), ...arms.map(a => svg('rect', {x: a[0] - 4, y: a[1] - 4, width: 8, height: 8, class: 'arm'}))); }
  if (key === 'decentralized') { const w = [[30, 40], [75, 70], [125, 40], [170, 70]];
    s.append(line(w[0], w[1], true), line(w[1], w[2], true), line(w[2], w[3], true), line(w[0], w[2], true), line(w[1], w[3], true), ...w.map(p => node(...p))); }
  if (key === 'adaptive') { const d = [[55, 72], [145, 72]];
    s.append(...d.map(p => line([100, 20], p, true)), node(100, 20, true), ...d.map(p => node(...p)), line(d[0], arms[0]), line(d[0], arms[1]), line(d[1], arms[3]),
      ...arms.map(a => svg('rect', {x: a[0] - 4, y: a[1] - 4, width: 8, height: 8, class: 'arm'}))); }
  return s;
}
// ---------- how it works ----------
const SYSTEMS = [
  {key: 'adaptive', label: 'Adaptive', text: 'One controller forks delegates and hands them arms.'},
  {key: 'single-agent', label: 'Single-agent', text: 'One agent controls every arm.'},
  {key: 'hierarchical', label: 'Hierarchical', text: 'One worker per arm under a controller.'},
  {key: 'decentralized', label: 'Decentralized', text: 'One worker per arm, no controller.'},
];
function systems() {
  const box = $('#topologies');
  for (const t of SYSTEMS) box.append(h('div', {class: 'topo' + (t.key === 'adaptive' ? ' best' : '')}, h('h4', {}, t.label), h('p', {}, t.text), topoGlyph(t.key)));
}

// ---------- results ----------
// data: {conditions: [{key, label, group, completed, within: {3, 6, 12, 24}, median_hours,
//        median_input_tokens_m, atomic_failure}], outcomes: {<set>: {<task>: {completed, hours}}}}
const WITHIN = ['3', '6', '12', '24'];
function results() {
  const data = state.results, findings = $('#findings'), board = $('#board');
  if (!data?.conditions?.length) {
    board.append(pendingPanel('Results are being published', 'The numbers of all 14 conditions will appear here: tasks completed, time, input tokens and how often steps fail.'));
    return;
  }
  const total = state.tasks.tasks.length, get = key => data.conditions.find(c => c.key === key);
  const best = get('adaptive'), low = get('low-resolution'), robot = get('robot-tool-only'), oracle = get('oracle');
  const card = (figure, title, text) => h('article', {class: 'finding'}, h('strong', {}, figure), h('h3', {}, title), h('p', {}, text));
  if (best) findings.append(
    card(`${best.completed}/${total}`, 'The best model completes most tasks',
      `A typical task takes ${hours(best.median_hours)} and ${Math.round(best.median_input_tokens_m)} million input tokens.`),
    card(`${Math.round(best.atomic_failure * 100)}%`, 'of its steps fail at least once',
      'Agents may retry, so a task that ends correctly can still contain many failures.'));
  if (oracle && low && robot) findings.append(
    card(`${oracle.completed} → ${low.completed}`, 'What limits the agents is seeing',
      `With ground-truth positions every task is completed. With low-resolution images ${low.completed} are, and without code tools ${robot.completed}.`));
  const groups = [...new Set(data.conditions.map(c => c.group))];
  for (const g of groups) {
    board.append(h('h4', {class: 'board-group'}, g));
    for (const c of data.conditions.filter(x => x.group === g)) {
      let before = 0;
      const bar = h('div', {class: 'bar-track', role: 'img', 'aria-label': `${c.label}: ${c.completed} of ${total} tasks completed`},
        WITHIN.map((k, i) => { const n = (c.within?.[k] ?? c.completed) - before; before += n;
          return n > 0 ? h('i', {style: `width:${n / total * 100}%;opacity:${1 - i * .22}`, title: `${before} within ${k} h`}) : null; }));
      board.append(h('div', {class: 'board-row' + (c.key === 'adaptive' ? ' ref' : '')}, h('span', {class: 'board-label'}, c.label), bar, h('b', {}, c.completed)));
    }
  }
  board.append(h('p', {class: 'board-key'}, 'Tasks completed of ', String(total), '. Darker means completed sooner: within 3, 6, 12 and 24 hours.'));
}

// ---------- start ----------
async function main() {
  chrome();
  const fixture = new URLSearchParams(location.search).get('fixture');
  [state.tasks, state.media, state.results] = await Promise.all([load('data/tasks.json'), load('data/media.json'),
    load(fixture ? `_dev/${fixture.replace(/[^\w.-]/g, '')}` : RESULTS_URL)]);
  if (!state.tasks) { $('#wall').append(pendingPanel('Data unavailable', 'data/tasks.json could not be loaded.')); return; }
  stage(); wallControls(); explainer(); systems(); protocolArms(); playerControls(); results();
  deepLink(); addEventListener('hashchange', deepLink);
}

// Links: #task=<id>[&view=side][&source=<set>] opens one run.
function deepLink() {
  const p = new URLSearchParams(location.hash.slice(1)), id = p.get('task');
  if (!id || !task(id)) return;
  const source = mediaSet(p.get('source')) ? p.get('source') : bestSet(id) || 'oracle';
  state.view = p.get('view') === 'side' ? 'side' : 'front';
  $('#watch').scrollIntoView();
  openPlayer(source, id, state.tasks.tasks.filter(t => t.family === task(id).family).map(t => t.id));
}
main();
})();
