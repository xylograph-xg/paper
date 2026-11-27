"""Independent native-panel contracts: no fake activity or write-on-read."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from desktop_widget.api import page_grid, control, snapshot


class PanelBoundaries(unittest.TestCase):
    def test_formula_window_separates_visual_warning_from_activity_and_expires(self):
        from desktop_widget.formula_window import window_cells
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'shared-gpt-window.json').write_text(json.dumps(dict(window_id=17,slots=[dict(slot_id='03',target_id='t')])))
            page = dict(checked_at=95,inspection_complete=True,streaming=True,image_health=dict(image_notice=True))
            (root/'window-observation.json').write_text(json.dumps(dict(pid=7,window_id=17,pages={'t':page})))
            status = dict(pid=7)
            cells = window_cells(root,root,status,True,100)
            self.assertEqual(len(cells),20)
            self.assertEqual(cells[2]['state'],'生成中')
            self.assertTrue(cells[2]['imageWarning'])
            self.assertEqual(cells[0]['state'],'未登记')
            for now,pid in ((160,7),(100,8)):
                stale = window_cells(root,root,dict(pid=pid),True,now)[2]
                self.assertEqual(stale['state'],'待观测')
                self.assertFalse(stale['imageWarning'])

    def test_reserved_slots_without_observation_never_become_generating(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'config').mkdir()
            (root/'data').mkdir()
            config = {'catalog_path': str(root/'data/catalog.sqlite3'), 'web_cards': {
                'enabled': True, 'shared_window': {'enabled': True, 'slot_count': 20}}}
            registry = {'schema_version': 1, 'window_id': 77,
                        'endpoint': 'http://127.0.0.1:9222', 'slots': [
                            {'slot_id': f'{i+1:02d}', 'target_id': f't{i:02d}'} for i in range(20)]}
            (root/'config/first_round.json').write_text(json.dumps(config))
            (root/'data/shared-gpt-window.json').write_text(json.dumps(registry))
            (root/'data/gpt-window-pool.json').write_text(json.dumps({'windows': {
                f't{i:02d}': {'state': 'busy'} for i in range(20)}}))
            before = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            value = page_grid.page_grid(root, at=100, owner_live=False)
            self.assertEqual((value['columns'], value['rows']), (20, 5))
            self.assertEqual(len(value['cells']), 100)
            self.assertEqual(value['currentStatusCounts']['running'], 0)
            self.assertEqual(value['backlog']['queuedTasks'], 0)
            self.assertFalse(value['backlog']['inventoryConfirmed'])
            after = {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}
            self.assertEqual(after, before)

    def test_pause_rejects_outside_group_and_mismatched_catalog_without_control_write(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(control, 'set_user_pause') as writer:
            root = Path(folder)
            with patch.object(control, 'ROOT', root):
                outside = root/'config.json'
                outside.write_text('{}')
                with self.assertRaises(ValueError):
                    control.pause(outside)
                group = root/'data/model_comparisons/20261006_same_prompt/demo/config.json'
                group.parent.mkdir(parents=True)
                group.write_text(json.dumps({'catalog_path': str(root/'foreign.sqlite3')}))
                with self.assertRaises(ValueError):
                    control.pause(group)
                writer.assert_not_called()

    def test_status_database_query_never_creates_missing_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder)/'missing.sqlite3'
            self.assertEqual(snapshot.db_rows(catalog, 'SELECT 1'), [])
            self.assertFalse(catalog.exists())
