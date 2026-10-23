import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect import canonical, feed_items, page_items, merge, acceptable


class CollectionTests(unittest.TestCase):
    def test_tracking_variants_do_not_duplicate_or_remove_history(self):
        existing = [{'url': 'https://example.com/old/', 'title': 'Old article', 'first_seen_at': '2025-01-01T00:00:00+00:00', 'published_at': None},
                    {'url': 'https://example.com/news?utm_source=x', 'title': 'Earlier title', 'first_seen_at': '2026-01-01T00:00:00+00:00', 'published_at': None}]
        incoming = [{'url': 'https://example.com/news/?fbclid=2', 'title': 'Updated title', 'published_at': '2026-10-20T00:00:00+00:00'}]
        records, added = merge(existing, incoming, '2026-10-23T00:00:00+00:00')
        self.assertEqual(added, 0)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]['first_seen_at'], '2026-01-01T00:00:00+00:00')
        unchanged, added = merge(records, [], '2026-10-24T00:00:00+00:00')
        self.assertEqual(records, unchanged)

    def test_rss_and_atom_preserve_source_dates(self):
        rss = b'<rss><channel><item><title>News</title><link>https://example.com/a</link><description>&lt;b&gt;Description&lt;/b&gt;</description><pubDate>Thu, 22 Oct 2026 12:00:00 GMT</pubDate></item></channel></rss>'
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>News</title><link href="https://example.com/a"/><published>2026-10-22T12:00:00Z</published></entry></feed>'
        for data in (rss, atom):
            item = feed_items(data, 'https://example.com')[0]
            self.assertEqual(item['published_at'], '2026-10-22T12:00:00+00:00')
            self.assertEqual(item['url'], 'https://example.com/a')

    def test_missing_dates_are_not_invented(self):
        data = b'<rss><channel><item><title>Undated news</title><link>https://example.com/a</link></item></channel></rss>'
        self.assertIsNone(feed_items(data, 'https://example.com')[0]['published_at'])

    def test_listing_metadata_date_and_unsafe_links(self):
        data = b'<div><time datetime="2026-10-20"></time><a href="/news/abc"><h3>A substantial announcement title</h3></a></div>'
        items = page_items(data, 'https://example.com', r'/news/[^/]+$')
        self.assertEqual(len(items), 1)
        self.assertTrue(items[0]['published_at'].startswith('2026-10-20'))
        self.assertIsNone(canonical('javascript:alert(1)'))
        self.assertIsNone(canonical('https://user:password@example.com/a'))

    def test_ads_are_filtered(self):
        self.assertFalse(acceptable({'url': 'https://example.com/a', 'title': 'Cupom de desconto para comprar computador'}, {'id': 'tecnoblog'}))


if __name__ == '__main__':
    unittest.main()
