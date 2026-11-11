import tempfile
from datetime import date
from pathlib import Path
import unittest
from xml.etree import ElementTree as ET

from scripts.render_profile import (
    normalize_pinned, compute_stats, ascii_portrait,
    render_all, build_readme, truncate,
)


class RenderProfileTests(unittest.TestCase):
    def test_pinned_repositories_keep_graphql_order_and_descriptions(self):
        nodes = [
            {"name": "repo-b", "description": "API de pagamentos", "url": "https://github.com/CBS041/repo-b", "isPrivate": False, "primaryLanguage": {"name": "TypeScript"}},
            {"name": "repo-a", "description": "Sistema de chamados", "url": "https://github.com/CBS041/repo-a", "isPrivate": False, "primaryLanguage": {"name": "Python"}},
            {"name": "repo-privado", "description": "Não revelar", "url": "https://github.com/CBS041/repo-privado", "isPrivate": True, "primaryLanguage": None},
            {"name": "repo-c", "description": None, "url": "https://github.com/CBS041/repo-c", "isPrivate": False, "primaryLanguage": None},
        ]
        pins = normalize_pinned(nodes)
        self.assertEqual([r['name'] for r in pins], ['repo-b', 'repo-a', 'repo-c'])
        self.assertEqual(pins[0]['description'], 'API de pagamentos')
        self.assertEqual(pins[-1]['description'], 'Confira o código e a documentação do projeto.')

    def test_streak_allows_today_without_contributions(self):
        days = [
            {"date": "2026-11-07", "count": 3},
            {"date": "2026-11-08", "count": 1},
            {"date": "2026-11-09", "count": 2},
            {"date": "2026-11-10", "count": 0},
        ]
        stats = compute_stats(days, date(2026, 11, 10))
        self.assertEqual(stats['streak'], 3)
        self.assertEqual(stats['active_days'], 3)
        self.assertEqual(stats['busiest'], ('2026-11-07', 3))

    def test_monthly_totals_distributes_each_day_correctly(self):
        days = [
            {"date": "2026-10-31", "count": 2},
            {"date": "2026-11-01", "count": 4},
            {"date": "2026-11-10", "count": 1},
        ]
        stats = compute_stats(days, date(2026, 11, 10))
        self.assertEqual(stats['months'][-2]['total'], 2)
        self.assertEqual(stats['months'][-1]['total'], 5)

    def test_ascII_fallback_and_truncation(self):
        self.assertGreaterEqual(len(ascii_portrait(None).splitlines()), 10)
        self.assertTrue(truncate('uma palavra muito longa aqui', 14).endswith('…'))

    def test_svg_rendering_and_readme_use_live_pins(self):
        sample = {
            'schema_version': 1,
            'user': 'CBS041',
            'pinned': [
                {"name": "repo-b", "description": "API de pagamentos", "url": "https://github.com/CBS041/repo-b", "language": "TypeScript"},
                {"name": "repo-a", "description": "Sistema de chamados", "url": "https://github.com/CBS041/repo-a", "language": "Python"},
            ],
            'days': [
                {"date": "2026-11-08", "count": 3},
                {"date": "2026-11-09", "count": 2},
            ],
            'generated_at': '2026-11-10T09:00:00Z'
        }
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder)
            for static in [False, True]:
                files = render_all(sample, out / ('static' if static else 'animated'),
                                   static=static, today=date(2026, 11, 10), fonts='')
                self.assertEqual(len(files), 8)  # hero, 3 links, 2 stats, 2 repos
                for file in files:
                    markup = file.read_text(encoding='utf-8')
                    ET.fromstring(markup)
                    self.assertIn('prefers-reduced-motion', markup)
                    if static:
                        self.assertNotIn('<animate ', markup)
                self.assertIn('API de pagamentos', (out / ('static' if static else 'animated') / 'repo-01.svg').read_text())
            readme = build_readme(sample)
            self.assertLess(readme.index('repo-b'), readme.index('repo-a'))
            self.assertIn('width="32.5%"', readme)
            self.assertIn('cards/static/hero.svg', readme)
            self.assertIn('https://github.com/CBS041/repo-b', readme)


if __name__ == '__main__':
    unittest.main()
