"""Last-moment changes after claim/upload must block the untouched send receipt."""
import copy
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path

from core.catalog import Catalog, now
from cards import web_card_queue as queue
from core.services import atomic_json
from cards.web_card_inputs import digest
from browser.web_submission_guard import check


class WebSubmissionGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.config = {'catalog_path':str(self.catalog.path), 'studio_library_root':str(self.root/'library')}
        queue.install(self.catalog)

    def request(self, *, rework_kind=None, human_protected=False):
        pid = self.catalog.upsert({'title':'Synthetic', 'doi':'10.9999/last-guard'})
        source = self.root/'original.pdf'; source.write_bytes(b'Original source, version 1')
        self.catalog.update(pid, acquisition='available', asset_path=str(source), asset_hash=digest(source))
        folder = self.root/'web_cards'/pid; folder.mkdir(parents=True, exist_ok=True)
        for name, body in (('source.pdf', 'Sanitized original source'), ('source-context.json', 'Complete original context'),
                           ('visual.pdf', 'All 220dpi original pages'), ('prompt.txt', 'Source-only generic card instructions')):
            (folder/name).write_text(body)
        packet = {'source_original_sha256':digest(source), 'page_count':1,
                  'input_hashes':{n:digest(folder/n) for n in ('source.pdf', 'source-context.json', 'visual.pdf', 'prompt.txt')}}
        atomic_json(folder/'packet.json', packet)
        target = self.root/'library'/pid; target.mkdir(parents=True)
        selection = {}; old = None
        if rework_kind:
            old = target/'card.json'
            atomic_json(old, {'title':'Synthetic', 'key_findings':'Original evidence-bound conclusion',
                              'meta':{'scientific_verified':False}})
            backup = target/'history'/'authorized-rework'; backup.mkdir(parents=True)
            (backup/'card.json').write_bytes(old.read_bytes())
            selection = {'rework':{'kind':rework_kind, 'old_card_path':str(old), 'old_sha256':digest(old),
                                   'backup':str(backup), 'human_protected':human_protected}}
            self.catalog.update(pid, card_path=str(old))
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)',
                       (pid, digest(source), 'Synthetic', json.dumps(selection), 'preparing', now()))
        job = queue.jobs(self.catalog)[0]
        # Model selection and upload can run between these checks. The mutation
        # tests change state during that interval, before send_click_started=True.
        check(self.catalog, self.config, job, folder, packet)
        return job, folder, packet, source, old

    def deny_after_upload(self, job, folder, packet, pattern):
        attempt = {'state':'ready', 'send_click_started':False}
        with self.assertRaisesRegex(ValueError, pattern):
            check(self.catalog, self.config, job, folder, packet)
            attempt.update(state='submission_started', send_click_started=True)
        self.assertEqual(attempt, {'state':'ready', 'send_click_started':False})

    def test_source_review_new_human_decision_during_upload_blocks_send(self):
        job, folder, packet, _, old = self.request(rework_kind='source_review')
        before = old.read_bytes()
        self.catalog.event(job['paper_id'], 'human_decision', {'decision':'keep', 'reason':'User retained this version'})
        self.deny_after_upload(job, folder, packet, '人工决定')
        self.assertEqual(old.read_bytes(), before)

    def test_source_review_decision_field_change_blocks_even_without_event(self):
        job, folder, packet, _, old = self.request(rework_kind='source_review')
        with self.catalog.connect() as db:
            db.execute("UPDATE papers SET decision='keep' WHERE id=?", (job['paper_id'],))
        self.deny_after_upload(job, folder, packet, '人工决定')
        self.assertEqual(digest(old), json.loads(job['selection'])['rework']['old_sha256'])

    def test_source_review_original_card_change_during_upload_blocks_send(self):
        job, folder, packet, _, old = self.request(rework_kind='source_review')
        old.write_text(old.read_text()+' ')
        self.deny_after_upload(job, folder, packet, '旧卡片已变化|原卡版本变化')

    def test_source_review_backup_change_blocks_original_version_authorization(self):
        job, folder, packet, _, old = self.request(rework_kind='source_review')
        record = json.loads(job['selection'])['rework']
        (Path(record['backup'])/'card.json').write_text('A changed backup')
        self.deny_after_upload(job, folder, packet, '备份指纹')

    def test_original_source_file_change_during_upload_blocks_send(self):
        job, folder, packet, source, _ = self.request()
        source.write_bytes(b'Another source or version')
        self.deny_after_upload(job, folder, packet, '原文指纹')

    def test_catalog_source_fingerprint_change_blocks_binding_without_file_change(self):
        job, folder, packet, _, _ = self.request()
        self.catalog.update(job['paper_id'], asset_hash='different-catalog-source-hash')
        self.deny_after_upload(job, folder, packet, '原文指纹|原文绑定')

    def test_each_frozen_input_change_during_upload_blocks_send(self):
        job, folder, packet, _, _ = self.request()
        for name in ('source.pdf', 'source-context.json', 'visual.pdf', 'prompt.txt'):
            with self.subTest(input=name):
                before = (folder/name).read_bytes()
                (folder/name).write_text('Changed '+name)
                self.deny_after_upload(job, folder, packet, '冻结输入')
                (folder/name).write_bytes(before)

    def test_packet_manifest_change_blocks_even_when_all_files_still_match(self):
        job, folder, packet, _, _ = self.request()
        changed = copy.deepcopy(packet); changed['page_count'] = 2
        atomic_json(folder/'packet.json', changed)
        self.deny_after_upload(job, folder, packet, '冻结.*清单|冻结.*材料|packet|材料.*版本')

    def test_claimed_selection_change_blocks_before_click(self):
        job, folder, packet, _, _ = self.request()
        with self.catalog.connect() as db:
            db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                       (json.dumps({'rework':{'correction_id':'another-task'}}), job['paper_id']))
        self.deny_after_upload(job, folder, packet, '任务版本|队列状态')

    def test_claimed_queue_state_or_source_binding_change_blocks_before_click(self):
        job, folder, packet, _, _ = self.request()
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='needs_inspection' WHERE paper_id=?", (job['paper_id'],))
        self.deny_after_upload(job, folder, packet, '队列状态')
        with self.catalog.connect() as db:
            db.execute("UPDATE web_card_jobs SET state='preparing',source_sha256='another' WHERE paper_id=?", (job['paper_id'],))
        self.deny_after_upload(job, folder, packet, '任务版本|队列状态')

    def test_late_identity_version_and_scope_flags_block_send(self):
        job, folder, packet, _, _ = self.request()
        for flag in ('identity_review_required', 'version_review_required', 'out_of_scope'):
            with self.subTest(flag=flag):
                metadata = self.catalog.get(job['paper_id'])['metadata']
                metadata.update({f:False for f in ('identity_review_required', 'version_review_required', 'out_of_scope')})
                metadata[flag] = True
                with self.catalog.connect() as db:
                    db.execute('UPDATE papers SET metadata=? WHERE id=?', (json.dumps(metadata), job['paper_id']))
                self.deny_after_upload(job, folder, packet, '身份、版本或范围')

    def test_new_card_created_during_fresh_generation_upload_blocks_send(self):
        job, folder, packet, _, _ = self.request()
        target = self.root/'library'/job['paper_id']/'card.json'
        target.write_text('A newly saved protected card')
        self.deny_after_upload(job, folder, packet, '已有卡片')
        self.assertEqual(target.read_text(), 'A newly saved protected card')

    def test_explicit_manifest_human_candidate_remains_allowed_and_old_card_untouched(self):
        job, folder, packet, _, old = self.request(rework_kind='authorized_manifest', human_protected=True)
        before = old.read_bytes()
        self.catalog.event(job['paper_id'], 'human_decision', {'decision':'keep'})
        self.catalog.decide(job['paper_id'], 'keep')
        paper = check(self.catalog, self.config, job, folder, packet)
        self.assertEqual(paper['decision'], 'keep')
        self.assertEqual(old.read_bytes(), before)
        record = json.loads(job['selection'])['rework']
        self.assertEqual(digest(Path(record['backup'])/'card.json'), digest(old))

    def test_source_review_human_protected_flag_does_not_bypass_new_human_decision(self):
        job, folder, packet, _, _ = self.request(rework_kind='source_review', human_protected=True)
        self.catalog.event(job['paper_id'], 'human_decision', {'decision':'keep'})
        self.deny_after_upload(job, folder, packet, '人工决定')

    def test_unbound_legacy_review_rework_cannot_fall_back_to_cards(self):
        from correction.card_correction_queue import allows_web_job, web_job_kind
        job, _, _, _, _ = self.request(rework_kind='source_review')
        self.config['web_cards'] = {'enabled':True}
        self.config['card_correction'] = {'enabled':True}
        self.assertEqual(web_job_kind(job), 'correction')
        self.assertFalse(allows_web_job(self.config, job))


if __name__ == '__main__':
    unittest.main()
