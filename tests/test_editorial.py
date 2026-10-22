"""Offline invariant tests; all prices and finish names below are synthetic fixtures."""
import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cs2_shorts.editorial import (FORMATS, base_name, build_editorial_copy, eligible_rows,
    load_history, make_plans, select_plan, local_script, write_history)


def fixtures():
    rows, catalog = [], []
    for weapon in ('AK-47', 'AWP', 'M4A1-S', 'USP-S', 'Glock-18', 'Desert Eagle', 'MP9'):
        for i in range(65):
            for wear, price in (('Field-Tested', 1 + i / 20), ('Factory New', 8 + i / 10)):
                name = f'{weapon} | Test Finish {i} ({wear})'
                rows.append({'market_hash_name': name, 'min_price': price, 'quantity': 2 + i})
                catalog.append({'market_hash_name': name, 'image': 'https://example.com/art.png'})
        name = f'{weapon} | Premium (Factory New)'
        rows.append({'market_hash_name': name, 'min_price': 100, 'quantity': 3})
        catalog.append({'market_hash_name': name, 'image': 'https://example.com/art.png'})
    return rows, catalog


class EditorialTests(unittest.TestCase):
    def setUp(self):
        self.raw, self.catalog = fixtures()
        self.rows = eligible_rows(self.raw, self.catalog)

    def test_all_formats_and_budget_integrity(self):
        plans = make_plans(self.rows, [], 'USD', random.Random(1))
        self.assertEqual({p.format for p in plans}, set(FORMATS))
        for p in plans:
            if p.budget:
                self.assertTrue(all(x['price'] < p.budget for x in p.items))
            if p.format == 'loadout':
                self.assertLess(sum(x['price'] for x in p.items), p.budget)
                self.assertEqual(len({x['weapon'] for x in p.items}), 3)
            if p.format == 'wear':
                self.assertEqual(len({base_name(x['name']) for x in p.items}), 1)

    def test_21_videos_rotate_with_no_finish_repeats_in_cooldown(self):
        rng, history, selected = random.Random(9), [], []
        for _ in range(21):
            p = select_plan(make_plans(self.rows, history, 'USD', rng), history, rng)
            names = {base_name(x['name']) for x in p.items}
            recent = {n for h in history[-12:] for n in h['skins']}
            self.assertFalse(names & recent)
            self.assertNotIn(p.fingerprint, {h['fingerprint'] for h in history})
            selected.append(p.format)
            history.append({'format': p.format, 'fingerprint': p.fingerprint, 'skins': list(names)})
        self.assertEqual(len(set(selected[:7])), 7)

    def test_invalid_or_estimated_prices_never_selected(self):
        for bad in ({'min_price': None, 'suggested_price': 2}, {'min_price': float('nan')},
                    {'min_price': float('inf')}, {'min_price': -2}, {'quantity': 0},
                    {'market_hash_name': 'Invented skin'}):
            with self.subTest(bad=bad):
                self.assertEqual(eligible_rows([{**self.raw[0], **bad}], self.catalog), [])

    def test_exhaustion_does_not_repeat(self):
        with self.assertRaises(RuntimeError):
            select_plan([], [], random.Random(1))

    def test_speech_actually_reaches_renderer(self):
        from cs2_shorts.media import _voiceover_lines, make_scenes
        plan = make_plans(self.rows, [], 'USD', random.Random(2))[0]
        copy = build_editorial_copy(plan, None, '2026-10-22T10:00:00Z')
        self.assertEqual(_voiceover_lines(copy, 'USD'), copy.scene_lines)
        self.assertEqual(len(copy.scene_lines), len(plan.items) + 2)
        self.assertTrue(all(x['name'] in copy.description for x in plan.items))
        self.assertNotIn('free skin', ' '.join(copy.scene_lines))
        with patch('cs2_shorts.editorial_visuals.make_editorial_scenes', return_value=['scene']):
            self.assertEqual(make_scenes(copy, 'USD', Path('/tmp')), ['scene'])

    def test_history_persistence_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'history.json'
            self.assertEqual(load_history(path), [])
            history = [{'format': 'duel', 'fingerprint': 'abc', 'skins': ['AK-47 | Slate']}]
            write_history(path, history)
            self.assertEqual(load_history(path), history)
            path.write_text('{broken')
            with self.assertRaises(json.JSONDecodeError):
                load_history(path)

    def test_legacy_voice_unchanged(self):
        from cs2_shorts.scripts import VideoCopy
        from cs2_shorts.media import _voiceover_lines
        item = {'name': 'AK-47 | Slate (Field-Tested)', 'price': 3}
        copy = VideoCopy('title', 'description', [], 'old', 'budget', item, items=[item])
        self.assertTrue(_voiceover_lines(copy, 'USD')[0].startswith('Get a ten dollar'))


if __name__ == '__main__':
    unittest.main()


class HistoryTransportTests(unittest.TestCase):
    def setUp(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location('history_transport',
            Path(__file__).resolve().parents[1] / 'scripts/editorial_history.py')
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_first_save_creates_branch_with_history_atomically(self):
        m = self.module
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'history.json'
            p.write_text('[{"format":"duel","skins":[],"fingerprint":"abc"}]')
            calls = []
            def api(route, method='GET', body=None):
                calls.append((route, method, body))
                return {'sha': 'generated-sha', 'tree': {'sha': 'base-tree-sha'}}
            with patch.object(m, 'PATH', p), patch.object(m, 'get_file', return_value=None), \
                 patch.object(m, 'api', api), patch.object(m.subprocess, 'check_output', return_value='head\n'), \
                 patch('sys.argv', ['history', 'save']):
                m.main()
            self.assertEqual([c[0] for c in calls], ['/git/commits/head', '/git/trees', '/git/commits', '/git/refs'])
            self.assertIn('data/editorial-history.json', calls[1][2]['tree'][0]['path'])

    def test_existing_history_uses_sha_guard(self):
        import base64
        m = self.module
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'history.json'
            p.write_text('[{"new":true}]')
            with patch.object(m, 'PATH', p), patch.object(m, 'get_file', return_value={
                    'sha': 'old-sha', 'content': base64.b64encode(b'[]').decode()}), \
                 patch.object(m, 'api') as api, patch('sys.argv', ['history', 'save']):
                m.main()
                self.assertEqual(api.call_args.args[2]['sha'], 'old-sha')

    def test_restore_does_not_overwrite_on_invalid_remote(self):
        import base64
        m = self.module
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'history.json'
            p.write_text('["keep me"]')
            with patch.object(m, 'PATH', p), patch.object(m, 'get_file', return_value={
                    'content': base64.b64encode(b'{}').decode()}), \
                 patch('sys.argv', ['history', 'restore']), self.assertRaises(ValueError):
                m.main()
            self.assertEqual(p.read_text(), '["keep me"]')


class LocalWriterTests(unittest.TestCase):
    def plans(self):
        raw, catalog = fixtures()
        return make_plans(eligible_rows(raw, catalog), [], 'USD', random.Random(3))

    def test_every_format_has_local_script_and_aligned_beats(self):
        formats = set()
        for plan in self.plans():
            script = local_script(plan, [], random.Random(1))
            self.assertEqual(len(script['beats']), len(plan.items))
            self.assertTrue(script['hook'])
            self.assertTrue(all(script['beats']))
            copy = build_editorial_copy(plan, script, 'TEST TIMESTAMP')
            self.assertEqual(copy.scene_lines[0], script['hook'])
            self.assertEqual(len(copy.scene_lines), len(plan.items) + 2)
            formats.add(plan.format)
        self.assertEqual(formats, set(FORMATS))

    def test_local_hooks_do_not_repeat_while_variants_available(self):
        from cs2_shorts.editorial import HOOKS
        for fmt in FORMATS:
            plan = next(p for p in self.plans() if p.format == fmt)
            history = []
            for i in range(len(HOOKS[fmt])):
                script = local_script(plan, history, random.Random(i))
                self.assertNotIn(script['hook'], {h['hook'] for h in history})
                history.append({'hook': script['hook']})

    def test_duel_price_gap_and_loadout_total_are_computed(self):
        from cs2_shorts.editorial import Plan, money
        items = [{'name': 'AK-47 | Fixture A (Field-Tested)', 'price': 3.25, 'quantity': 10},
                 {'name': 'AK-47 | Fixture B (Field-Tested)', 'price': 7.50, 'quantity': 20}]
        p = Plan('duel', 'Test', items, ['A', 'B'], 'hook', 'outro', 'USD')
        script = local_script(p, [], random.Random(1))
        self.assertIn('$4.25 more', script['beats'][1])
        p.format = 'loadout'
        script = local_script(p, [], random.Random(1))
        self.assertIn('$10.75', script['beats'][1])

    def test_series_has_no_language_model_connection_or_secret_requirement(self):
        root = Path(__file__).resolve().parents[1]
        for file in (root / 'src/cs2_shorts/editorial.py', root / '.github/workflows/cs2-skin-stories.yml'):
            source = file.read_text().lower()
            self.assertNotIn('api.openai.com', source)
            self.assertNotIn('openai_api_key', source)
            self.assertNotIn('creative_script', source)
            self.assertNotIn('gpt-4', source)

    def test_run_can_publish_without_any_language_model_secret(self):
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import Mock
        from cs2_shorts.editorial import run
        raw, catalog = fixtures()
        with tempfile.TemporaryDirectory() as d:
            cfg = SimpleNamespace(currency='USD', data_dir=Path(d) / 'data',
                output_dir=Path(d) / 'output', image_timeout=8, voice='test', upload_enabled=True)
            config = ModuleType('cs2_shorts.config')
            config.settings, config.validate_settings = cfg, Mock()
            provider = ModuleType('cs2_shorts.providers.skinport')
            provider.SkinportProvider = Mock(return_value=SimpleNamespace(_get=lambda endpoint: raw))
            youtube = ModuleType('cs2_shorts.youtube')
            youtube.upload_video = Mock(return_value='test-video-id')
            with patch.dict(sys.modules, {'cs2_shorts.config': config,
                'cs2_shorts.providers.skinport': provider, 'cs2_shorts.youtube': youtube}), \
                patch('cs2_shorts.media._skin_catalog', return_value=catalog), \
                patch('cs2_shorts.media.render_video', return_value=30), \
                patch.dict('os.environ', {}, clear=True):
                output = run()
            youtube.upload_video.assert_called_once()
            history = load_history(cfg.data_dir / 'editorial-history.json')
            self.assertEqual(history[-1]['status'], 'published')
            self.assertEqual(history[-1]['youtube_video_id'], 'test-video-id')
            metadata = json.loads(output.with_suffix('.json').read_text())
            self.assertEqual(metadata['script_source'], 'local format writer with verified market facts')
            self.assertEqual(metadata['status'], 'published')
