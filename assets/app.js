(function () {
  'use strict';
  var ids = function (id) { return document.getElementById(id); };
  var mode = document.body.dataset.mode || 'home';
  var page = 1, size = mode === 'home' ? 60 : 100, category = 'Todos', onlySaved = false;
  var all = null, allPromise = null, persist = true, timer;
  var cards = Array.from(document.querySelectorAll('#grid .card'));
  function read(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) || fallback; } catch (e) { persist = false; return fallback; } }
  function write(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { persist = false; } }
  var raw = read('pulso-saved-v1', []);
  var saved = Array.isArray(raw) ? raw.filter(function (x) { return typeof x === 'string'; }).map(canonical) : [];
  function canonical(value) { try { var u = new URL(value); u.hash = ''; u.pathname = u.pathname.replace(/\/$/, '') || '/'; Array.from(u.searchParams.keys()).forEach(function (k) { if (/^(utm_|fbclid|gclid|mc_)/i.test(k)) u.searchParams.delete(k); }); return u.href; } catch (e) { return value; } }
  function norm(s) { return s.toLocaleLowerCase('pt-BR').normalize('NFD').replace(/[\u0300-\u036f]/g, ''); }
  function key(card) { return canonical(card.querySelector('h3 a').href); }
  function esc(value) { var d = document.createElement('span'); d.textContent = value || ''; return d.innerHTML; }
  function dateLabel(value) { if (!value) return 'Data não informada pela fonte'; if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value.split('-').reverse().join('/'); var d = new Date(value); return isNaN(d) ? 'Data não informada pela fonte' : d.toLocaleDateString('pt-BR', { timeZone: 'America/Sao_Paulo' }); }
  function makeCard(a) {
    var card = document.createElement('article'); card.className = 'card';
    card.dataset.category = a.category; card.dataset.source = a.source; card.dataset.date = a.published_at || ''; card.dataset.id = a.id; card.dataset.month = (a.published_at || '').slice(0, 7);
    // URLs are independently checked before they become clickable links.
    var u; try { u = new URL(a.url); } catch (e) { return null; } if (!/^https?:$/.test(u.protocol)) return null;
    card.innerHTML = '<div class="cardtop"><span class="source">' + esc(a.source) + '</span><button class="save" aria-pressed="false">♡</button></div><div class="category">' + esc(a.category) + '</div><h3><a target="_blank" rel="noopener noreferrer">' + esc(a.title) + '</a></h3><p>' + esc(a.summary || 'A fonte não forneceu uma descrição. Abra o link para ler a publicação original.') + '</p><span class="source-kind">' + (a.editorial_seed ? 'Resumo editorial' : a.summary ? 'Descrição da fonte' : 'Anúncio na fonte') + '</span><div class="cardbottom"><time>' + dateLabel(a.published_at) + '</time><a target="_blank" rel="noopener noreferrer">Ler na fonte ↗</a></div>';
    card.querySelectorAll('a').forEach(function (link) { link.href = u.href; }); card.querySelector('time').dateTime = a.published_at || ''; return card;
  }
  function draw(data) { var fragment = document.createDocumentFragment(); data.forEach(function (a) { var card = makeCard(a); if (card) fragment.appendChild(card); }); ids('grid').replaceChildren(fragment); cards = Array.from(ids('grid').querySelectorAll('.card')); }
  function syncSaved() {
    ids('savedcount').textContent = saved.length; ids('saved').setAttribute('aria-pressed', String(onlySaved));
    cards.forEach(function (c) { var b = c.querySelector('.save'), active = saved.includes(key(c)); b.setAttribute('aria-pressed', String(active)); b.textContent = active ? '♥' : '♡'; b.setAttribute('aria-label', (active ? 'Remover das salvas: ' : 'Salvar notícia: ') + c.querySelector('h3').textContent); });
  }
  function apply() {
    var q = norm(ids('search').value.trim()), source = ids('source').value, sort = ids('sort').value, month = ids('month') ? ids('month').value : '';
    var found = cards.filter(function (c) { return (category === 'Todos' || c.dataset.category === category) && (!source || c.dataset.source === source) && (!q || norm(c.textContent).includes(q)) && (!month || c.dataset.month === month) && (!onlySaved || saved.includes(key(c))); });
    found.sort(function (a, b) { if (sort === 'source') return a.dataset.source.localeCompare(b.dataset.source, 'pt-BR') || b.dataset.date.localeCompare(a.dataset.date); if (!a.dataset.date || !b.dataset.date) return Number(!!b.dataset.date) - Number(!!a.dataset.date); return sort === 'oldest' ? a.dataset.date.localeCompare(b.dataset.date) : b.dataset.date.localeCompare(a.dataset.date); });
    var pages = Math.max(1, Math.ceil(found.length / size)); page = Math.min(page, pages); var visible = new Set(found.slice((page - 1) * size, page * size));
    cards.forEach(function (c) { c.hidden = !visible.has(c); }); found.forEach(function (c) { ids('grid').appendChild(c); });
    ids('results').textContent = found.length + (found.length === 1 ? ' notícia' : ' notícias') + (onlySaved ? ' salvas' : '');
    ids('empty').hidden = found.length > 0;
    ids('empty').textContent = source && !cards.some(function (c) { return c.dataset.source === source; }) ? 'Nenhuma notícia desta fonte no conjunto atual. Consulte o arquivo e a situação da coleta em Fontes.' : onlySaved ? 'Nenhuma notícia salva neste navegador com estes filtros.' : 'Nenhuma notícia encontrada. Tente outra busca ou limpe os filtros.';
    ids('pager').hidden = pages <= 1; ids('page-label').textContent = page + ' / ' + pages; ids('prev').disabled = page <= 1; ids('next').disabled = page >= pages;
    document.querySelectorAll('[data-filter]').forEach(function (b) { var active = b.dataset.filter === category; b.classList.toggle('active', active); b.setAttribute('aria-pressed', String(active)); });
    syncSaved();
  }
  function loadAll() {
    if (all) return Promise.resolve(all);
    if (allPromise) return allPromise;
    allPromise = fetch('data/articles.json', { cache: 'no-store' }).then(function (r) { if (!r.ok) throw new Error('archive'); return r.json(); }).then(function (data) { if (!Array.isArray(data)) throw new Error('archive'); all = data; return data; }).catch(function (e) { allPromise = null; throw e; }); return allPromise;
  }
  function message(text) { clearTimeout(timer); ids('toast').textContent = text; timer = setTimeout(function () { ids('toast').textContent = ''; }, 5000); }
  function changed() { page = 1; apply(); }
  document.querySelectorAll('[data-filter],[data-nav]').forEach(function (b) { b.addEventListener('click', function () { category = b.dataset.filter || b.dataset.nav; changed(); }); });
  ids('search').addEventListener('input', changed); ['source', 'sort', 'month'].forEach(function (id) { if (ids(id)) ids(id).addEventListener('change', changed); });
  ids('reset').addEventListener('click', function () { category = 'Todos'; onlySaved = false; ids('search').value = ''; ids('source').value = ''; ids('sort').value = 'recent'; if (ids('month')) ids('month').value = ''; if (mode === 'home' && all) draw(all.slice(0, 60)); changed(); });
  ids('saved').addEventListener('click', function () {
    onlySaved = !onlySaved; category = 'Todos'; ids('search').value = ''; ids('source').value = ''; if (ids('month')) ids('month').value = '';
    if (onlySaved) loadAll().then(function (data) { if (onlySaved) { draw(data); changed(); } }).catch(function () { message('O arquivo não carregou. As salvas continuam guardadas; tente novamente.'); });
    else if (all) draw(mode === 'home' ? all.slice(0, 60) : all);
    changed(); ids('noticias').scrollIntoView({ block: 'start' });
  });
  ids('grid').addEventListener('click', function (event) { var b = event.target.closest('.save'); if (!b) return; var c = b.closest('.card'), k = key(c), exists = saved.includes(k); saved = exists ? saved.filter(function (x) { return x !== k; }) : saved.concat(k); write('pulso-saved-v1', saved); apply(); message((exists ? 'Notícia removida das salvas.' : 'Notícia salva neste navegador.') + (!persist ? ' Disponível somente nesta sessão.' : '')); });
  ids('prev').addEventListener('click', function () { page--; apply(); ids('noticias').scrollIntoView({ block: 'start' }); }); ids('next').addEventListener('click', function () { page++; apply(); ids('noticias').scrollIntoView({ block: 'start' }); });
  function theme(dark) { document.body.classList.toggle('dark', dark); ids('theme').setAttribute('aria-pressed', String(dark)); ids('theme').setAttribute('aria-label', dark ? 'Ativar tema claro' : 'Ativar tema escuro'); }
  theme(read('pulso-dark-v1', false) === true); ids('theme').addEventListener('click', function () { var dark = !document.body.classList.contains('dark'); theme(dark); write('pulso-dark-v1', dark); });
  var requested = new URLSearchParams(window.location.search).get('fonte'); if (requested && Array.from(ids('source').options).some(function (o) { return o.value === requested; })) ids('source').value = requested;
  apply();
  if (mode === 'archive') loadAll().then(function (data) { draw(data); changed(); }).catch(function () { message('Exibindo parte do arquivo. Recarregue para consultar todo o histórico.'); });
})();
