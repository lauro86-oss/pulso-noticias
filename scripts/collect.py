#!/usr/bin/env python3
"""Collect approved public feeds; merge records without deleting history."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
import hashlib
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import socket
import urllib.error
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UTC = timezone.utc
USER_AGENT = 'PULSO-News/1.0 (+https://github.com/lauro86-oss/pulso-noticias)'
MAX_BYTES = 15_000_000


def now():
    return datetime.now(UTC).isoformat(timespec='seconds')


def canonical(url):
    p = urlsplit(html.unescape(url.strip()))
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password:
        return None
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if not k.lower().startswith(('utm_', 'fbclid', 'gclid', 'mc_'))]
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/') or '/', urlencode(query), ''))


def clean(value):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', value or ''))).strip()


def excerpt(value, limit=220):
    value = clean(value)
    return value if len(value) <= limit else value[:limit].rsplit(' ', 1)[0] + '…'


def date_value(value):
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            datetime.strptime(value, '%Y-%m-%d')
            return value if value <= datetime.now(UTC).date().isoformat() else None
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        try:
            dt = parsedate_to_datetime(value)
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    if dt > datetime.now(UTC) + timedelta(days=1):
        return None
    return dt.astimezone(UTC).isoformat(timespec='seconds')


def local_name(tag):
    return tag.rsplit('}', 1)[-1]


def child_text(node, names):
    for name in names:
        for child in node:
            if local_name(child.tag) == name:
                return ''.join(child.itertext())
    return ''


def feed_items(data, base):
    root = ET.fromstring(data)
    if local_name(root.tag) not in ('rss', 'feed', 'RDF'):
        raise ValueError('A resposta não é RSS/Atom')
    items = []
    for entry in root.iter():
        if local_name(entry.tag) not in ('item', 'entry'):
            continue
        url = child_text(entry, ['link'])
        for link in entry:
            if local_name(link.tag) == 'link' and link.get('href') and link.get('rel', 'alternate') == 'alternate':
                url = link.get('href')
                break
        if not url:
            url = child_text(entry, ['guid', 'id'])
        if not url:
            continue
        items.append({'url': urljoin(base, url), 'title': clean(child_text(entry, ['title'])),
                      'summary': excerpt(child_text(entry, ['description', 'summary', 'encoded', 'content'])),
                      'published_at': date_value(child_text(entry, ['pubDate', 'published', 'date', 'updated']))})
    return items


class Node:
    def __init__(self, tag='', attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or []), parent, []

    def text(self):
        return ''.join(c if isinstance(c, str) else c.text() for c in self.children)

    def nodes(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.nodes(tag)


class Document(HTMLParser):
    def __init__(self, value):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.current = self.root
        self.feed(value)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'):
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, attrs, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def page_items(data, base, pattern):
    doc = Document(data.decode('utf-8', errors='replace'))
    results = []

    def walk_json(value):
        if isinstance(value, list):
            for item in value:
                walk_json(item)
        elif isinstance(value, dict):
            types = value.get('@type', [])
            if isinstance(types, str):
                types = [types]
            if set(types) & {'NewsArticle', 'BlogPosting', 'Article'}:
                url = value.get('url') or value.get('mainEntityOfPage')
                if isinstance(url, dict):
                    url = url.get('@id')
                if isinstance(url, str) and value.get('headline'):
                    results.append({'url': urljoin(base, url), 'title': clean(value['headline']),
                                    'summary': excerpt(value.get('description', '')),
                                    'published_at': date_value(value.get('datePublished'))})
            for v in value.values():
                if isinstance(v, (dict, list)):
                    walk_json(v)

    for node in doc.root.nodes('script'):
        if node.attrs.get('type') == 'application/ld+json':
            try:
                walk_json(json.loads(node.text()))
            except (ValueError, TypeError):
                pass
    if not pattern:
        return results
    for link in doc.root.nodes('a'):
        url = urljoin(base, link.attrs.get('href', ''))
        if urlsplit(url).hostname != urlsplit(base).hostname or not re.search(pattern, urlsplit(url).path):
            continue
        title_nodes = [n for n in link.nodes() if n.tag in ('h1', 'h2', 'h3', 'h4')]
        title = clean(title_nodes[0].text() if title_nodes else link.text())
        if not (25 <= len(title) <= 230):
            continue
        if title.lower() in ('read more', 'learn more'):
            continue
        # A listing link without publication metadata remains explicitly undated.
        published = None
        container = link
        for _ in range(3):
            times = list(container.nodes('time'))
            if times:
                published = date_value(times[0].attrs.get('datetime', ''))
                if published:
                    break
            nearby = clean(container.text())
            dates = re.findall(r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}', nearby)
            if len(dates) == 1 and len(nearby) < 1500:
                for fmt in ('%b %d, %Y', '%B %d, %Y', '%b %d %Y', '%B %d %Y'):
                    try:
                        published = date_value(datetime.strptime(dates[0], fmt).date().isoformat())
                        break
                    except ValueError:
                        pass
                if published:
                    break
            if not container.parent:
                break
            container = container.parent
        results.append({'url': url, 'title': title, 'summary': '', 'published_at': published})
    return results


def request(url):
    req = Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/rss+xml, application/atom+xml, application/xml, text/html;q=0.9, */*;q=0.1'})
    with urlopen(req, timeout=18) as res:
        data = res.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError('Resposta excedeu o limite de tamanho')
        return data, res.geturl(), res.headers.get('Content-Type', '')


def category(item, source):
    text = (item['title'] + ' ' + item.get('summary', '')).lower()
    if source['group'] == 'Segurança digital' or re.search(r'\b(security|segurança|vulnerab\w*|malware|ransomware|phishing|breach)\b', text):
        return 'Segurança'
    if source['id'] == 'github':
        return 'GitHub'
    if source['group'] == 'IA e modelos' or re.search(r'\b(ai|ia|llm|agent\w*|inteligência artificial|claude|gemini|chatgpt)\b', text):
        if re.search(r'\b(model\w*|launch\w*|introduc\w*|lança\w*|release\w*)\b', text):
            return 'Lançamentos de modelos'
        return 'Inteligência artificial'
    return 'Softwares'


def acceptable(item, source):
    if not item.get('title') or len(item['title']) < 12 or not canonical(item['url']):
        return False
    text = item['title'].lower()
    if source.get('required_keyword') and source['required_keyword'] not in (text + ' ' + item.get('summary', '').lower()):
        return False
    if re.search(r'(R\$|US\$|sem juros|cashback|menor pre[çc]o|despenca|por apenas)', text):
        return False
    if re.search(r'\b(cupom|cupons|promoção|promoções|oferta|ofertas|desconto|descontos|deals|giveaway|sponsored|patrocinado|horóscopo|loteria|futebol)\b', text):
        return False
    if source['id'] in {'canaltech', 'tecmundo', 'olhar-digital', 'ars-technica', 'the-verge', 'techcrunch', 'mit-tech-review'}:
        return bool(re.search(r'\b(ia|ai|inteligência|artificial|agent\w*|modelo\w*|model\w*|software\w*|app\w*|windows|linux|android|ios|apple|google|microsoft|meta|github|openai|anthropic|claude|gemini|chatgpt|qwen|mistral|nvidia|program\w*|código|code|segurança|security|privacidade|privacy|dados|data|digital|internet|cloud|nuvem|browser|navegador|firefox|chrome|vulnerab\w*|malware|ransomware|hack\w*|phishing|python|javascript|open.source|rob[oó]t\w*)\b', text))
    return True


def collect_source(source):
    errors = []
    urls = list(source.get('feeds', []))
    for url in urls:
        try:
            data, final, _ = request(url)
            items = feed_items(data, final)
            if items:
                return source, items, {'state': 'ok', 'method': 'feed', 'endpoint': final, 'error': None}
            errors.append('Feed sem itens: ' + url)
        except Exception as error:
            errors.append(type(error).__name__ + ': ' + str(error)[:140])
    try:
        data, final, _ = request(source['url'])
        doc = Document(data.decode('utf-8', errors='replace'))
        discovered = []
        for n in doc.root.nodes('link'):
            if 'alternate' in n.attrs.get('rel', '') and any(t in n.attrs.get('type', '') for t in ('rss', 'atom')):
                candidate = urljoin(final, n.attrs.get('href', ''))
                if candidate not in urls and candidate not in discovered:
                    discovered.append(candidate)
        for endpoint in discovered[:2]:
            try:
                feed, actual, _ = request(endpoint)
                items = feed_items(feed, actual)
                if items:
                    return source, items, {'state': 'ok', 'method': 'feed', 'endpoint': actual, 'error': None}
            except Exception as error:
                errors.append(type(error).__name__ + ': ' + str(error)[:140])
        items = page_items(data, final, source.get('article_path_pattern'))
        if items:
            return source, items, {'state': 'ok', 'method': 'page', 'endpoint': final, 'error': None}
        errors.append('Página pública sem notícias extraíveis')
    except Exception as error:
        errors.append(type(error).__name__ + ': ' + str(error)[:140])
    for page in source.get('alternate_pages', []):
        try:
            data, final, _ = request(page)
            items = page_items(data, final, source.get('article_path_pattern'))
            if items:
                return source, items, {'state': 'ok', 'method': 'page', 'endpoint': final, 'error': None}
        except Exception as error:
            errors.append(type(error).__name__ + ': ' + str(error)[:140])
    return source, [], {'state': 'unavailable', 'method': None, 'endpoint': None, 'error': '; '.join(errors[-2:])}


def merge(existing, incoming, timestamp):
    records = {}
    for item in existing:
        key = canonical(item['url'])
        if key:
            records[key] = dict(item, url=key)
    added = 0
    for item in incoming:
        key = canonical(item['url'])
        if not key:
            continue
        if key in records:
            old = records[key]
            # Keep the first-seen timestamp and editorial seed summaries.
            for field in ('title', 'published_at'):
                if item.get(field):
                    old[field] = item[field]
            if not old.get('editorial_seed') and item.get('summary'):
                old['summary'] = item['summary']
        else:
            records[key] = dict(item, url=key, id=hashlib.sha256(key.encode()).hexdigest()[:20], first_seen_at=timestamp)
            added += 1
    return sorted(records.values(), key=lambda x: (x.get('published_at') or '', x['first_seen_at'], x['url']), reverse=True), added


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def run():
    timestamp = now()
    config = json.loads((ROOT / 'sources.json').read_text())
    if not config.get('automatic_collection_enabled'):
        raise SystemExit('Coleta desativada na configuração')
    sources = [s for s in config['sources'] if s.get('approved')]
    allowed = {s['id'] for s in sources}
    history_path = ROOT / 'data/articles.json'
    existing = json.loads(history_path.read_text()) if history_path.exists() else []
    seed_path = ROOT / 'data/seed.json'
    if seed_path.exists():
        existing = json.loads(seed_path.read_text()) + existing
    existing = [item for item in existing if item['source_id'] in allowed]
    previous_path = ROOT / 'data/status.json'
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    incoming, states = [], {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        tasks = [pool.submit(collect_source, s) for s in sources]
        for task in as_completed(tasks):
            source, items, state = task.result()
            good = []
            seen = set()
            for item in items[:100]:
                key = canonical(item['url'])
                if key not in seen and acceptable(item, source) and not any(urlsplit(key or '').hostname == e['scope'].split('/')[0] or (urlsplit(key or '').hostname or '').endswith('.' + e['scope'].split('/')[0]) for e in config.get('excluded_sources', [])):
                    seen.add(key)
                    item.update(source_id=source['id'], source=source['name'], category=category(item, source))
                    good.append(item)
                if len(good) >= 40:
                    break
            incoming.extend(good)
            state.update(name=source['name'], checked_at=timestamp, received=len(items), accepted=len(good),
                         last_success_at=timestamp if state['state'] == 'ok' else previous.get('sources', {}).get(source['id'], {}).get('last_success_at'))
            states[source['id']] = state
            print(source['name'] + ': ' + state['state'] + ', ' + str(len(good)) + ' itens aceitos', flush=True)
    records, added = merge(existing, incoming, timestamp)
    successful = sum(s['state'] == 'ok' for s in states.values())
    last_success = timestamp if successful else previous.get('last_success_at')
    status = {'last_attempt_at': timestamp, 'last_success_at': last_success,
              'schedule': config['schedule'], 'approved_sources': len(sources), 'successful_sources': successful,
              'unavailable_sources': len(sources) - successful, 'new_articles': added,
              'total_articles': len(records), 'sources': dict(sorted(states.items()))}
    dump(history_path, records)
    dump(previous_path, status)
    summary = '\n'.join(['## Coleta PULSO', f'- Fontes consultadas: {len(sources)}',
                         f'- Fontes com retorno: {successful}', f'- Notícias novas: {added}',
                         f'- Notícias no arquivo: {len(records)}',
                         '- Fontes indisponíveis: ' + ', '.join(s['name'] for s in states.values() if s['state'] != 'ok')])
    print(summary)
    import os
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as output:
            output.write(summary + '\n')
    return successful


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
