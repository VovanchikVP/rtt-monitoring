const POLL_MS = 3000;
let pollTimer = null;
let selectedTour = null;
// карточки турниров из последнего ответа /tours: нужны заголовку состава,
// в /tours/{id}/players названия турнира нет
const toursById = new Map();
// раскрытые игроки: id → { points, matches }, где каждая половина —
// { loading } | { data } | { error }. Слева от графика идут последние матчи.
// Каждый игрок открывается и закрывается сам по себе, их может быть сколько угодно
const opened = new Map();
// состав выбранного турнира из последнего ответа; null — ещё грузится.
// Нужен, чтобы при перерисовке списка турниров собрать строку состава заново
let roster = [];
// столько колонок в таблице турниров — на всю ширину растягивается состав
const TOUR_COLUMNS = 6;

const $ = (id) => document.getElementById(id);
// состав открыт не больше чем у одного турнира, поэтому ищем по всему документу
const inRoster = (selector) => document.querySelector(`tr[data-roster] ${selector}`);
const fmtDate = (d) => d ? d.split('-').reverse().join('.') : null;

function tourDates(t) {
  const from = fmtDate(t.begin_date), to = fmtDate(t.end_date);
  if (from && to) return `${from} — ${to}`;
  return from || to || '';
}

// турнир считается незаполненным, пока фоновая задача не подтянула карточку
const isPending = (t) => t.name === null;

// свёрнутую секцию раскрываем один раз на выбор турнира, иначе перерисовка
// по таймеру не давала бы свернуть её обратно
let revealedTour = null;

// завершённые приходят страницами: сервер отдаёт партию и общее их число
const DONE_LIMIT = 10;
let doneOffset = 0;
let doneTotal = 0;

function renderTours(current, finished) {
  // строки создаются заново, поэтому фокус запоминаем и возвращаем — иначе
  // после первого же нажатия Enter клавиатурная навигация обрывается
  const focused = document.activeElement?.closest?.('tr[data-tour]')?.dataset.tour ?? null;

  fillTours($('tours'), current);
  fillTours($('tours-done'), finished);

  const total = current.length + doneTotal;
  $('tours-empty').hidden = total > 0;
  $('tours').hidden = current.length === 0;
  $('tours-current-empty').hidden = total === 0 || current.length > 0;

  const box = $('tours-done-box');
  box.hidden = doneTotal === 0;
  $('tours-done-summary').textContent =
    `Завершённые турниры — ${doneTotal} ${tourWord(doneTotal)}`;
  renderPager();

  // выбранный турнир мог оказаться в свёрнутой части
  if (selectedTour !== revealedTour) {
    revealedTour = selectedTour;
    if (finished.some((t) => t.id === selectedTour)) box.open = true;
  }

  if (focused !== null) {
    document.querySelector(`tr[data-tour="${focused}"]`)?.focus();
  }
}

function renderPager() {
  // кнопки не пересоздаются, а только меняют состояние: иначе фокус
  // слетал бы с них при каждой перерисовке по таймеру
  const pages = Math.max(1, Math.ceil(doneTotal / DONE_LIMIT));
  $('tours-done-pager').hidden = pages < 2;
  $('done-page').textContent = `${Math.floor(doneOffset / DONE_LIMIT) + 1} из ${pages}`;
  $('done-prev').disabled = doneOffset === 0;
  $('done-next').disabled = doneOffset + DONE_LIMIT >= doneTotal;
}

async function turnDonePage(step) {
  const pressed = step > 0 ? $('done-next') : $('done-prev');
  const wasFocused = document.activeElement === pressed;

  doneOffset = Math.max(0, doneOffset + step * DONE_LIMIT);
  await loadTours();

  // дошли до края — кнопка погасла, уводим фокус на соседнюю
  if (wasFocused && pressed.disabled) (step > 0 ? $('done-prev') : $('done-next')).focus();
}

$('done-prev').addEventListener('click', () => turnDonePage(-1));
$('done-next').addEventListener('click', () => turnDonePage(1));

function fillTours(table, tours) {
  const tbody = table.querySelector('tbody');
  tbody.innerHTML = '';
  for (const t of tours) {
    tbody.appendChild(tourRow(t));
    // состав вставляется следующей строкой, прямо под своим турниром
    if (t.id === selectedTour) tbody.appendChild(rosterRow(t));
  }
}

function rosterRow(tour) {
  const tr = document.createElement('tr');
  tr.className = 'roster-row';
  tr.dataset.roster = tour.id;

  const td = document.createElement('td');
  td.colSpan = TOUR_COLUMNS;
  td.appendChild($('roster-template').content.cloneNode(true));
  tr.appendChild(td);

  fillRoster(td.querySelector('.roster'), tour);
  return tr;
}

function fillRoster(block, tour) {
  // пока карточка турнира не заполнена, названия ещё нет — показываем id
  block.querySelector('.roster-title').textContent = tour?.name
    ? `Участники — ${tour.name}`
    : `Участники турнира ${tour?.id ?? selectedTour}`;
  block.querySelector('.roster-status').textContent = rosterStatus();
  renderPlayers(block.querySelector('tbody'));
}

function rosterStatus() {
  if (roster === null) return 'загружаем…';
  return roster.length ? `${roster.length} чел.` : 'состав ещё не загружен';
}

// состав перерисовывается на месте: ходить за списком турниров незачем
function renderRoster() {
  const block = inRoster('.roster');
  if (block) fillRoster(block, toursById.get(selectedTour) ?? { id: selectedTour });
}

function tourRow(t) {
  const tr = document.createElement('tr');
  tr.className = t.id === selectedTour ? 'clickable selected' : 'clickable';
  tr.dataset.tour = t.id;
  tr.tabIndex = 0;
  tr.title = t.id === selectedTour ? 'Скрыть участников' : 'Показать участников';
  tr.setAttribute('aria-expanded', t.id === selectedTour ? 'true' : 'false');

  const name = isPending(t)
    ? '<span class="pending">заполняется…</span>'
    : escape(t.name);

  tr.innerHTML = `
    <td class="num">${t.id}</td>
    <td>${name}</td>
    <td>${escape(t.location) || ''}</td>
    <td>${tourDates(t)}</td>
    <td class="num">${t.players_count}</td>
    <td class="num">
      <button class="icon danger" data-delete="${t.id}"
              title="Удалить турнир" aria-label="Удалить турнир ${t.id}">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor"
             stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M4 7h16M10 4h4M9 7v12M15 7v12M6 7l1 13h10l1-13"/>
        </svg>
      </button>
    </td>`;
  return tr;
}

function tourWord(n) {
  const t = n % 10, h = n % 100;
  if (t === 1 && h !== 11) return 'турнир';
  if (t >= 2 && t <= 4 && (h < 12 || h > 14)) return 'турнира';
  return 'турниров';
}

function escape(s) {
  if (s === null || s === undefined) return '';
  return String(s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function loadTours() {
  // два списка: отслеживаемые целиком и страница завершённых
  const [current, finished] = await Promise.all([
    get('/tours'),
    get(`/tours/finished?limit=${DONE_LIMIT}&offset=${doneOffset}`),
  ]);

  // турниры могли удалить, и страницы с таким смещением больше нет
  const lastOffset = Math.max(0, Math.ceil(finished.total / DONE_LIMIT) - 1) * DONE_LIMIT;
  if (doneOffset > lastOffset) {
    doneOffset = lastOffset;
    return loadTours();          // смещение уже верное, второй раз не повторится
  }

  doneTotal = finished.total;
  toursById.clear();
  for (const t of [...current, ...finished.items]) toursById.set(t.id, t);
  renderTours(current, finished.items);

  // опрос нужен, только пока есть незаполненные турниры
  const pending = [...current, ...finished.items].filter(isPending).length;
  if (pending > 0) {
    $('tours-status').innerHTML =
      `<span class="dot"></span>ждём данные по ${pending} ${plural(pending)}`;
    schedulePoll();
  } else {
    stopPoll();
    $('tours-status').textContent = '';
  }
}

async function get(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`GET ${url} → ${resp.status}`);
  return resp.json();
}

function plural(n) {
  const t = n % 10, h = n % 100;
  if (t === 1 && h !== 11) return 'турниру';
  return 'турнирам';
}

function schedulePoll() {
  if (pollTimer !== null) return;         // опрос уже запущен
  pollTimer = setTimeout(async () => {
    pollTimer = null;
    try {
      await loadTours();
      if (selectedTour !== null) await loadPlayers(selectedTour);
    } catch (e) {
      $('tours-status').textContent = 'нет связи с сервером, пробуем ещё раз';
      schedulePoll();
    }
  }, POLL_MS);
}

function stopPoll() {
  if (pollTimer !== null) {
    clearTimeout(pollTimer);
    pollTimer = null;
  }
}

// строка состава появляется сразу по клику, не дожидаясь ответа сервера
function openRoster(tourId) {
  closePlayers();
  selectedTour = tourId;
  roster = null;
  location.hash = `tour=${tourId}`;   // состав можно открыть по прямой ссылке

  const row = document.querySelector(`tr[data-tour="${tourId}"]`);
  if (row) row.after(rosterRow(toursById.get(tourId) ?? { id: tourId }));
  updateTourRow(tourId);
}

async function loadPlayers(tourId) {
  const resp = await fetch(`/tours/${tourId}/players`);
  if (resp.status === 404) { closePlayers(); return; }
  if (!resp.ok) throw new Error(`GET players → ${resp.status}`);
  const players = await resp.json();

  // пока ходили за составом, могли выбрать другой турнир
  if (tourId !== selectedTour) return;
  roster = players;
  renderRoster();
}

function renderPlayers(tbody) {
  const players = roster ?? [];
  // строки создаются заново, поэтому фокус запоминаем и возвращаем
  const focused = document.activeElement?.closest?.('tr[data-player]')?.dataset.player ?? null;
  tbody.innerHTML = '';

  // строка могла остаться раскрытой у игрока, которого больше нет в составе
  const present = new Set(players.map((p) => String(p.id)));
  for (const id of opened.keys()) {
    if (!present.has(id)) opened.delete(id);
  }

  for (const p of players) {
    const id = String(p.id);
    const open = opened.has(id);

    const tr = document.createElement('tr');
    tr.className = open ? 'clickable selected' : 'clickable';
    tr.dataset.player = id;
    tr.tabIndex = 0;
    tr.title = open ? CLOSE_HINT : OPEN_HINT;
    tr.setAttribute('aria-expanded', open ? 'true' : 'false');
    tr.innerHTML = `
      <td class="num">${p.number}</td>
      <td>${escape(p.name)}</td>
      <td class="num">${p.age ?? '—'}</td>
      <td>${escape(p.city)}</td>
      <td class="num">${p.points}</td>`;
    tbody.appendChild(tr);

    // матчи и график вставляются следующей строкой, прямо под своим игроком
    if (open) tbody.appendChild(detailsRow(id, tr));
  }

  if (focused !== null) tbody.querySelector(`tr[data-player="${focused}"]`)?.focus();
}

const OPEN_HINT = 'Показать матчи и график рейтинга';
const CLOSE_HINT = 'Скрыть матчи и график рейтинга';

async function togglePlayer(playerId) {
  const id = String(playerId);
  if (opened.has(id)) {
    opened.delete(id);
    updatePlayerRow(id);
    inRoster(`tr[data-details="${id}"]`)?.remove();
    return;
  }

  opened.set(id, { points: { loading: true }, matches: { loading: true } });
  updatePlayerRow(id);
  const row = inRoster(`tr[data-player="${id}"]`);
  if (row) row.after(detailsRow(id, row));

  // матчи и очки грузятся независимо: сбой одного не прячет другое
  await Promise.all([
    loadPart(id, 'points', `/players/${id}/points`),
    loadPart(id, 'matches', `/players/${id}/matches`),
  ]);
}

async function loadPart(id, part, url) {
  let state;
  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`GET ${url} → ${resp.status}`);
    state = { data: await resp.json() };
  } catch (e) {
    state = { error: true };
  }

  // пока ходили за данными, состав мог перерисоваться или строка — закрыться
  const current = opened.get(id);
  if (!current) return;
  opened.set(id, { ...current, [part]: state });
  renderDetails(id);
}

function updatePlayerRow(id) {
  const row = inRoster(`tr[data-player="${id}"]`);
  if (!row) return;
  const open = opened.has(id);
  row.classList.toggle('selected', open);
  row.title = open ? CLOSE_HINT : OPEN_HINT;
  row.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function detailsRow(id, playerRow) {
  const tr = document.createElement('tr');
  tr.className = 'details-row';
  tr.dataset.details = id;

  const td = document.createElement('td');
  td.colSpan = 5;
  // слева матчи, справа график; ширину колонок задаёт CSS
  const box = document.createElement('div');
  box.className = 'details';
  box.innerHTML = '<div class="matches"></div><div class="chart"></div>';
  td.appendChild(box);
  tr.appendChild(td);

  // отрисовка после вставки в DOM: до неё ширина блока неизвестна
  queueMicrotask(() => renderDetails(id));
  return tr;
}

function renderDetails(id) {
  const state = opened.get(id);
  const playerRow = inRoster(`tr[data-player="${id}"]`);
  const box = inRoster(`tr[data-details="${id}"] .details`);
  if (!state || !playerRow || !box) return;

  const list = box.querySelector('.matches');
  renderMatches(list, state.matches);

  // график не ниже двух строк состава (getBoundingClientRect, а не
  // offsetHeight: тот округляет до целых пикселей)
  const chart = box.querySelector('.chart');
  const min = playerRow.getBoundingClientRect().height * 2;
  // на узком экране колонки встают друг под друга — тянуть график
  // до высоты списка матчей там незачем
  chart.style.height = `${sideBySide(list, chart) ? Math.max(min, height(list)) : min}px`;
  drawChart(state.points, chart);
}

// блоки стоят рядом, пока flex не перенёс график на вторую строку
const sideBySide = (list, chart) =>
  Math.abs(list.getBoundingClientRect().top - chart.getBoundingClientRect().top) < 1;

const height = (node) => node.getBoundingClientRect().height;

function renderMatches(list, state) {
  if (state.loading) return note(list, 'загружаем матчи…');
  if (state.error) return note(list, 'не удалось загрузить матчи');
  if (!state.data.length) return note(list, 'матчей пока нет');

  list.innerHTML = '';
  for (const match of state.data) list.appendChild(matchCard(match));
}

function matchCard(match) {
  const div = document.createElement('div');
  div.className = 'match';
  // победа известна не всегда: матч может быть не доигран
  const outcome = match.won === null ? '' : match.won ? ' win' : ' loss';
  div.innerHTML = `
    <div class="match-top">
      <span class="match-date">${fmtDate(match.date) || 'без даты'}</span>
      <span class="match-sets${outcome}">${escape(match.sets) || '—'}</span>
    </div>
    <div class="match-rival">${escape(match.opponent) || '—'}</div>
    <div class="match-games">${escape(match.games) || '—'}</div>`;
  return div;
}

function drawChart(state, box) {
  if (state.loading) return note(box, 'загружаем график…');
  if (state.error) return note(box, 'не удалось загрузить рейтинг');
  if (!state.data.length) return note(box, 'рейтинг ещё не собран');

  box.innerHTML = '';
  box.appendChild(buildChart(state.data, box.clientWidth, box.clientHeight));
}

function note(box, text) {
  box.innerHTML = '';
  const div = document.createElement('div');
  div.className = 'note';
  div.textContent = text;
  box.appendChild(div);
}

const SVG_NS = 'http://www.w3.org/2000/svg';

function svgNode(tag, attrs) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) node.setAttribute(name, value);
  return node;
}

function buildChart(points, width, height) {
  // слева — место под подписи очков, снизу — под даты
  const pad = { top: 10, right: 10, bottom: 16, left: 38 };
  const svg = svgNode('svg', { width, height, role: 'img' });
  svg.appendChild(svgNode('title', {})).textContent = 'Изменение рейтинга';

  const values = points.map((p) => p.points);
  let min = Math.min(...values);
  let max = Math.max(...values);
  // рейтинг не менялся — линия пойдёт по середине, а не по краю
  const flat = min === max;
  if (flat) { min -= 1; max += 1; }

  const left = pad.left, right = width - pad.right;
  const top = pad.top, bottom = height - pad.bottom;
  const x = (i) => (points.length === 1
    ? (left + right) / 2
    : left + (i * (right - left)) / (points.length - 1));
  const y = (value) => bottom - ((value - min) * (bottom - top)) / (max - min);

  // у неизменного рейтинга подпись одна: 479 и 481 вместо 480 только путали бы
  for (const value of flat ? [values[0]] : [max, min]) {
    const anchor = y(value);
    svg.appendChild(svgNode('line', { class: 'grid', x1: left, x2: right, y1: anchor, y2: anchor }));
    const label = svgNode('text', { class: 'label', x: left - 6, y: anchor + 3, 'text-anchor': 'end' });
    label.textContent = value;
    svg.appendChild(label);
  }

  if (points.length > 1) {
    svg.appendChild(svgNode('polyline', {
      class: 'line',
      points: points.map((p, i) => `${x(i)},${y(p.points)}`).join(' '),
    }));
  }

  points.forEach((p, i) => {
    const dot = svgNode('circle', { class: 'dot', cx: x(i), cy: y(p.points), r: 3 });
    dot.appendChild(svgNode('title', {})).textContent = `${fmtDate(p.date)} — ${p.points}`;
    svg.appendChild(dot);
  });

  // подписи дат только по краям: между ними они сливаются
  const edges = points.length > 1 ? [[0, 'start'], [points.length - 1, 'end']] : [[0, 'middle']];
  for (const [index, anchor] of edges) {
    const label = svgNode('text', {
      class: 'label', x: x(index), y: height - 4, 'text-anchor': anchor,
    });
    label.textContent = fmtMonth(points[index].date);
    svg.appendChild(label);
  }

  return svg;
}

function fmtMonth(value) {
  const [year, month] = value.split('-');
  return `${month}.${year}`;
}

function closePlayers() {
  const previous = selectedTour;
  selectedTour = null;
  roster = [];
  opened.clear();
  document.querySelector('tr[data-roster]')?.remove();
  if (previous !== null) updateTourRow(previous);
  if (location.hash) history.replaceState(null, '', location.pathname);
}

function updateTourRow(tourId) {
  const row = document.querySelector(`tr[data-tour="${tourId}"]`);
  if (!row) return;
  const open = tourId === selectedTour;
  row.classList.toggle('selected', open);
  row.title = open ? 'Скрыть участников' : 'Показать участников';
  row.setAttribute('aria-expanded', open ? 'true' : 'false');
}

function tourFromHash() {
  const m = location.hash.match(/^#tour=(\d+)$/);
  return m ? Number(m[1]) : null;
}

$('add-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const msg = $('add-msg');
  const id = Number($('tour-id').value.trim());
  if (!Number.isInteger(id) || id <= 0) {
    msg.className = 'msg error';
    msg.textContent = 'ID турнира — целое положительное число';
    return;
  }

  msg.className = 'msg ok';
  msg.textContent = 'отправляем…';
  try {
    const resp = await fetch('/tours', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id }),
    });
    if (resp.status === 201) {
      msg.className = 'msg ok';
      msg.textContent = `Турнир ${id} добавлен, данные подтянутся сами`;
      $('tour-id').value = '';
      await loadTours();
    } else {
      const body = await resp.json().catch(() => ({}));
      msg.className = 'msg error';
      msg.textContent = detail(body) || `Ошибка ${resp.status}`;
    }
  } catch (e) {
    msg.className = 'msg error';
    msg.textContent = 'Не удалось отправить запрос';
  }
});

function detail(body) {
  if (typeof body.detail === 'string') return body.detail;
  if (Array.isArray(body.detail)) return body.detail[0]?.msg;
  return null;
}

async function toggleTour(tourId) {
  if (tourId === selectedTour) {
    closePlayers();
    return;
  }
  openRoster(tourId);          // строка появляется сразу, с «загружаем…»
  await loadPlayers(tourId);
}

document.addEventListener('click', async (e) => {
  // клик может прийтись на иконку внутри кнопки, поэтому ищем саму кнопку
  const button = e.target.closest?.('button');
  const delId = button?.dataset.delete;

  // кнопки внутри строки работают сами по себе и состав не открывают
  const row = e.target.closest?.('tr[data-tour]');
  if (row && !button) {
    await toggleTour(Number(row.dataset.tour));
  }

  const playerRow = e.target.closest?.('tr[data-player]');
  if (playerRow && !button) {
    await togglePlayer(playerRow.dataset.player);
  }

  if (delId) {
    if (!confirm(`Удалить турнир ${delId}?`)) return;
    const resp = await fetch(`/tours/${delId}`, { method: 'DELETE' });
    if (resp.ok && Number(delId) === selectedTour) closePlayers();
    await loadTours();
  }
});

document.addEventListener('keydown', async (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const row = e.target.closest?.('tr[data-tour], tr[data-player]');
  if (!row) return;
  e.preventDefault();          // пробел иначе прокручивает страницу
  if (row.dataset.tour !== undefined) await toggleTour(Number(row.dataset.tour));
  else await togglePlayer(row.dataset.player);
});

// ширина графика привязана к ширине таблицы, а высота — к соседним блокам
let resizeTimer = null;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    for (const id of opened.keys()) renderDetails(id);
  }, 150);
});

// при уходе со вкладки опрос не нужен
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stopPoll();
  else loadTours().catch(() => {});
});

(async () => {
  try {
    await loadTours();
    const fromHash = tourFromHash();
    if (fromHash !== null) {
      // перерисовка достанет турнир из свёрнутой части и вернёт строку состава
      openRoster(fromHash);
      await loadTours();
      await loadPlayers(fromHash);
    }
  } catch (e) {
    $('tours-status').textContent = 'нет связи с сервером';
    schedulePoll();
  }
})();
