#!/usr/bin/env python3
"""Build static news pages. No browser-side news API is required."""
from collections import Counter
from datetime import datetime
from html import escape
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo
from collect import ROOT, merge, dump


def label_date(value, full=False):
    if not value:
        return 'Data não informada pela fonte'
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return datetime.strptime(value, '%Y-%m-%d').strftime('%d/%m/%Y')
    d = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(ZoneInfo('America/Sao_Paulo'))
    return d.strftime('%d/%m/%Y às %H:%M' if full else '%d/%m/%Y')


def card(a):
    e = lambda x: escape(str(x or ''), quote=True)
    date = label_date(a.get('published_at'))
    date_attr = a.get('published_at') or ''
    note = 'Resumo editorial' if a.get('editorial_seed') else 'Descrição da fonte' if a.get('summary') else 'Anúncio na fonte'
    summary = a.get('summary') or 'A fonte não forneceu uma descrição. Abra o link para ler a publicação original.'
    return f'''<article class="card" data-category="{e(a['category'])}" data-source="{e(a['source'])}" data-date="{e(date_attr)}" data-id="{e(a['id'])}" data-month="{e(date_attr[:7])}">
<div class="cardtop"><span class="source">{e(a['source'])}</span><button class="save" aria-label="Salvar notícia: {e(a['title'])}" aria-pressed="false">♡</button></div>
<div class="category">{e(a['category'])}</div><h3><a href="{e(a['url'])}" target="_blank" rel="noopener noreferrer">{e(a['title'])}</a></h3><p>{e(summary)}</p>
<span class="source-kind">{note}</span><div class="cardbottom"><time datetime="{e(date_attr)}">{date}</time><a href="{e(a['url'])}" target="_blank" rel="noopener noreferrer">Ler na fonte ↗</a></div></article>'''


def main():
    config = json.loads((ROOT / 'sources.json').read_text())
    status = json.loads((ROOT / 'data/status.json').read_text())
    articles = json.loads((ROOT / 'data/articles.json').read_text())
    seed = json.loads((ROOT / 'data/seed.json').read_text())
    articles, _ = merge(seed, articles, status['last_attempt_at'])
    allowed = {s['id'] for s in config['sources'] if s['approved']}
    articles = [a for a in articles if a['source_id'] in allowed]
    dump(ROOT / 'data/articles.json', articles)
    status['total_articles'] = len(articles)
    dump(ROOT / 'data/status.json', status)
    sources = config['sources']
    groups = list(dict.fromkeys(s['group'] for s in sources))
    counts = Counter(a['source_id'] for a in articles)
    home = (ROOT / 'templates/home.html').read_text()
    styles = re.search(r'<style>([\s\S]*?)</style>', home)[1]
    styles += '''.source-kind{font-size:11px;color:var(--muted)}.collection-banner{margin:0 0 22px;padding:13px 17px;border:1px solid var(--line);border-radius:9px;background:var(--paper);font-size:12px;color:var(--muted)}.collection-banner a{text-decoration:underline}.pager{display:flex;align-items:center;gap:15px;justify-content:center;margin:24px 0}.pager button[disabled]{opacity:.4;cursor:default}.archive-link{display:block;text-align:center;margin-top:24px;padding:15px;border:1px solid var(--line);border-radius:9px;font-weight:650;background:var(--paper)}.filterrow select{max-width:300px}.source-state{display:block;font-size:12px;margin:12px 0;color:var(--muted)}.last-update{font-size:12px;color:var(--muted)}@media(max-width:640px){.filterrow select{max-width:240px}}'''
    home = re.sub(r'<style>[\s\S]*?</style>', '<style>' + styles + '</style>', home, count=1)
    home = re.sub(r'<script>[\s\S]*?</script>', '<script src="assets/app.js" defer></script>', home)
    home = home.replace('href="./" aria-label="PULSO início"', 'href="./" aria-label="PULSO início"')
    home = re.sub(r'<span class="edition">[\s\S]*?</span>', '<span class="edition">Atualização automática · a cada 3 horas</span>', home)
    home = re.sub(r'SELEÇÃO PULSO / 23 OUT 2026', 'NOTÍCIAS EM ATUALIZAÇÃO', home)
    home = re.sub(r'<div class="editiontag"><span>●</span> Edição de 23/10/2026</div>', '<div class="editiontag"><span>●</span> Coleta automática ativa</div>', home)
    home = home.replace('<a href="fontes.html">Fontes (33)</a>', '<a href="arquivo.html">Arquivo</a><a href="fontes.html">Fontes (33)</a>')
    options = '<option value="">Todas as fontes aprovadas</option>'
    for g in groups:
        options += '<optgroup label="' + escape(g, quote=True) + '">'
        for s in sources:
            if s['group'] == g:
                options += '<option value="' + escape(s['name'], quote=True) + '">' + escape(s['name']) + ' · ' + str(counts[s['id']]) + ' no arquivo</option>'
        options += '</optgroup>'
    home = re.sub(r'<select id="source">[\s\S]*?</select>', '<select id="source">' + options + '</select>', home)
    months = sorted({a['published_at'][:7] for a in articles if a.get('published_at')}, reverse=True)
    month_select = '<label>Mês <select id="month"><option value="">Todos os meses</option>' + ''.join('<option value="' + m + '">' + m[5:] + '/' + m[:4] + '</option>' for m in months) + '</select></label>'
    updated = label_date(status.get('last_success_at'), True)
    checked = label_date(status.get('last_attempt_at'), True)
    health = f"{status['successful_sources']}/{len(sources)} fontes com retorno na última tentativa"
    banner = f'<div class="collection-banner"><strong>Última coleta com retorno: {updated} (Brasília).</strong> {health}. Histórico preservado. <a href="fontes.html">Ver situação das fontes →</a></div>'
    home = home.replace('<section id="noticias"', banner + '<section id="noticias"')
    home = home.replace('<noscript><p>As notícias e os links estão disponíveis abaixo. Ative JavaScript para usar os filtros e salvar notícias.</p></noscript>', '<noscript><p>As notícias e os links estão disponíveis abaixo. Ative JavaScript para usar filtros e salvas. <a href="arquivo.html">Ver arquivo de notícias</a>.</p></noscript>')
    home = re.sub(r'<div class="note">[\s\S]*?</div></main>', '<div class="note"><p><strong>Sobre o PULSO.</strong> Coleta das fontes aprovadas a cada três horas, sujeita à disponibilidade de cada site e ao agendamento do GitHub. Descrições extraídas das fontes, sem resumo ou tradução por IA. Publicações sem data são identificadas. As notícias antigas continuam no <a href="arquivo.html">arquivo</a>. Notícias salvas ficam neste navegador.</p><a href="fontes.html">Fontes e estado da coleta →</a></div></main>', home)
    # Always refresh the hero and radar alongside the cards.
    dated = [a for a in articles if a.get('published_at')]
    highlights = (dated or articles)[:3]
    if highlights:
        a = highlights[0]
        feature = f'<article class="feature"><div class="eyebrow">EM DESTAQUE · {escape(a["category"])}</div><h2>{escape(a["title"])}</h2><p>{escape(a.get("summary") or "Confira a publicação original na fonte.")}</p><a class="read" href="{escape(a["url"], quote=True)}" target="_blank" rel="noopener noreferrer">Ler na fonte ↗</a><small>{escape(a["source"])} · {label_date(a.get("published_at"))}</small></article>'
        home = re.sub(r'<article class="feature">[\s\S]*?</article>', lambda _: feature, home)
        radar = ''.join(f'<div class="briefitem"><span>{i:02}</span><div><small>{escape(a["category"])}</small><h3><a href="{escape(a["url"], quote=True)}" target="_blank" rel="noopener noreferrer">{escape(a["title"])} ↗</a></h3></div></div>' for i, a in enumerate(highlights[1:], 1))
        radar += '<div class="briefitem"><span>→</span><div><small>Arquivo PULSO</small><h3><a href="arquivo.html">Todas as notícias, incluindo as edições anteriores</a></h3></div></div>'
        home = re.sub(r'<aside class="brief">[\s\S]*?</aside>', lambda _: '<aside class="brief"><div class="briefhead"><h2>Em poucos minutos</h2><span>NO RADAR</span></div>' + radar + '</aside>', home)
    old_grid_start = home.index('<div class="grid" id="grid">')
    old_grid_end = home.index('<div class="empty" id="empty"', old_grid_start)
    home = home[:old_grid_start] + '<div class="grid" id="grid">{{CARDS}}</div><div class="pager" id="pager" hidden><button class="tool" id="prev">← Anterior</button><span id="page-label"></span><button class="tool" id="next">Próxima →</button></div><a class="archive-link" href="arquivo.html">Ver todas as notícias no arquivo →</a>' + home[old_grid_end:]
    home = re.sub(r'<span id="results"[^>]*>[^<]*</span>', '<span id="results" role="status" aria-live="polite">{{COUNT}} notícias</span>', home)
    out = ROOT / '_site'
    out.mkdir(exist_ok=True)

    def page(path, records, mode, number=1, pages=1):
        value = home.replace('{{CARDS}}', '\n'.join(card(a) for a in records)).replace('{{COUNT}}', str(len(records)))
        value = value.replace('<body>', '<body data-mode="' + mode + '">', 1)
        if mode == 'archive':
            value = re.sub(r'<section class="hero"[\s\S]*?</section>', '', value, count=1)
            value = value.replace('O que merece sua atenção.', 'Arquivo de notícias.').replace('Seu radar de notícias', 'Histórico do PULSO')
            value = value.replace('NOTÍCIAS EM ATUALIZAÇÃO', 'HISTÓRICO PRESERVADO')
            value = value.replace('<title>PULSO — Tecnologia, contexto e o que vem a seguir</title>', '<title>Arquivo de notícias — PULSO</title>')
            value = value.replace('<button class="tool" id="reset">Limpar</button>', month_select + '<button class="tool" id="reset">Limpar</button>')
            nav = '<noscript><p>' + ' '.join('<a href="arquivo' + ('' if n == 1 else '-' + str(n)) + '.html">Página ' + str(n) + '</a>' for n in range(1, pages + 1)) + '</p></noscript>'
            value = value.replace('<div class="filterbox">', nav + '<div class="filterbox">', 1)
            value = value.replace('<a class="archive-link" href="arquivo.html">Ver todas as notícias no arquivo →</a>', '')
        value = value.replace('<script src="assets/app.js" defer>', '<script src="assets/app.js" defer>')
        (out / path).write_text(value, encoding='utf-8')

    page('index.html', articles[:config['homepage_limit']], 'home')
    chunk = 100
    total_pages = max(1, (len(articles) + chunk - 1) // chunk)
    for i in range(total_pages):
        page('arquivo' + ('' if i == 0 else '-' + str(i + 1)) + '.html', articles[i*chunk:(i+1)*chunk], 'archive', i+1, total_pages)

    source_page = (ROOT / 'templates/sources.html').read_text()
    source_page = source_page.replace('A edição atual reúne seis notícias de Anthropic, GitHub e Mozilla. As demais fontes estão cadastradas para as próximas atualizações. A coleta automática ainda não está ativa.', f'A coleta automática consulta estas fontes a cada três horas. Última tentativa: {checked} (Brasília). {health}. O arquivo reúne {len(articles)} notícias. Falhas de acesso não apagam as notícias já coletadas.')
    source_page = source_page.replace('Os links “Ver nesta edição” mostram somente as notícias já publicadas.', 'Os links “Ver notícias” abrem o arquivo com filtro por fonte. As descrições são as fornecidas pelos veículos.')
    source_page = source_page.replace('Ver nesta edição →', 'Ver notícias →').replace('href="./?fonte=', 'href="arquivo.html?fonte=')
    for s in sources:
        state = status['sources'].get(s['id'], {})
        message = ('Com retorno na última coleta' if state.get('state') == 'ok' else 'Indisponível na última tentativa; nova tentativa programada')
        status_text = f'<span class="source-state">{message} · {counts[s["id"]]} notícias no arquivo</span>'
        pattern = r'(<h3><a href="' + re.escape(escape(s['url'], quote=True)) + r'"[^>]*>[^<]*</a></h3><p>[\s\S]*?</p>)'
        source_page = re.sub(pattern, lambda m: m[1] + status_text, source_page, count=1)
    source_page = source_page.replace('</style>', '.source-state{display:block;font-size:12px;margin:12px 0;color:var(--muted)}</style>', 1)
    source_page = source_page.replace('<a class="tool" href="./">← Notícias</a>', '<a class="tool" href="arquivo.html">Arquivo</a><a class="tool" href="./">← Notícias</a>')
    (out / 'fontes.html').write_text(source_page, encoding='utf-8')
    shutil.copytree(ROOT / 'assets', out / 'assets', dirs_exist_ok=True)
    shutil.copytree(ROOT / 'data', out / 'data', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'sources.json', out / 'sources.json')
    (out / '.nojekyll').write_text('')
    # Root copies preserve the familiar main/root source and downloadable HTML.
    for f in out.glob('*.html'):
        shutil.copy2(f, ROOT / f.name)
    print(f'Geradas homepage (60 recentes), arquivo ({len(articles)} registros) e fontes ({len(sources)}).')


if __name__ == '__main__':
    main()
