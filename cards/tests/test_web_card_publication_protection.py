"""A saved source-review response cannot overwrite changed user/source state."""
import os
import hashlib
import json
import shutil
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from unittest.mock import patch

from core.catalog import Catalog, now
from cards import web_card_queue as queue
from cards.paper_quality import RUBRIC
from core.services import atomic_json
from cards.web_card_inputs import digest, prepare
from cards.web_card_service import publish_saved


QUOTE = 'A synthetic observation was measured under explicit source conditions.'


class PublicationProtection(unittest.TestCase):
    def setUp(self):
        import pymupdf
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        bundle_environment=patch.dict(os.environ,{'CODEX_CHAT_ZIP_DIR':str(self.root/'zips')})
        bundle_environment.start();self.addCleanup(bundle_environment.stop)
        self.catalog = Catalog(self.root/'catalog.sqlite3')
        self.pid = self.catalog.upsert({'title':'Synthetic source review', 'doi':'10.9999/publication'})
        queue.install(self.catalog)
        self.source = self.root/'original.pdf'
        with pymupdf.open() as doc:
            doc.new_page().insert_text((30,60), QUOTE, fontsize=10); doc.save(self.source)
        self.catalog.update(self.pid, acquisition='available', asset_path=str(self.source), asset_hash=digest(self.source))
        self.folder = self.root/'web_cards'/self.pid
        self.packet = prepare(self.source, self.folder, self.pid, 'Synthetic source review', digest(self.source))
        self.target = self.root/'library'/self.pid; self.target.mkdir(parents=True)
        self.old = self.target/'card.json'; atomic_json(self.old, {'old_science':'Retain this exact evidence-bound card'})
        shutil.copy2(self.folder/'source.pdf', self.target/'source.pdf')
        shutil.copytree(self.folder/'pages', self.target/'pages')
        backup = self.target/'history'/'authorized-review'; backup.mkdir(parents=True)
        shutil.copy2(self.old, backup/'card.json')
        self.catalog.update(self.pid, card_path=str(self.old))
        self.record = {'kind':'source_review', 'review_id':'original-review', 'correction_id':'independent-correction',
                       'old_card_path':str(self.old), 'old_sha256':digest(self.old), 'backup':str(backup), 'human_protected':False}
        with self.catalog.connect() as db:
            db.execute('INSERT INTO web_card_jobs(paper_id,source_sha256,title,selection,state,updated) VALUES(?,?,?,?,?,?)',
                       (self.pid, digest(self.source), 'Synthetic source review', json.dumps({'rework':self.record}), 'collecting', now()))
        self.job = queue.jobs(self.catalog)[0]
        evaluation = {k:{'score':None, 'reason':'信息不足', 'source_pages':[]} for k in ('overall_quality','direction_novelty')}
        evaluation['overall_quality']['dimensions'] = {k:{'score':None, 'reason':'信息不足', 'source_pages':[]} for k in RUBRIC}
        card = {'title':'Synthetic source review', 'info':{k:'原文未提供，无法确认' for k in ('标题','作者','期刊','年份','DOI','研究对象','主要方法','关键词')}, 'one_line_summary':'A synthetic source-only contribution.',
                'key_findings':'A synthetic observation under the original stated conditions.', 'intro_summary':'A source-bound question.',
                'conclusion_summary':'A source-bound conclusion.', 'warnings':[], 'equations':[], 'tables':[],
                'figures':[{'number':'1','caption':'Synthetic observation','figure_info':'Source conditions','label':'Fig. 1', 'source_page':1, 'evidence_id':'P001', 'one_line':'Observed response.',
                            'summary':'The source states this condition.', 'detail':'A source-bound description.',
                            'result':'The observation under these conditions.', 'evidence_quote':QUOTE}],
                'paper_evaluation':evaluation}
        self.raw = json.dumps(card)
        self.provider = self.folder/'chatgpt'; self.provider.mkdir()
        (self.provider/'response-raw.txt').write_text(self.raw)
        self.attempt = {'state':'response_saved', 'settings':{'model':'synthetic'}, 'conversation_url':'https://chatgpt.com/c/synthetic',
                        'raw_sha256':hashlib.sha256(self.raw.encode()).hexdigest(), 'inputs':self.packet['input_hashes']}
        atomic_json(self.provider/'attempt.json', self.attempt)
        self.config = {'catalog_path':str(self.catalog.path), 'studio_library_root':str(self.root/'library')}
        self.before = {'card':self.old.read_bytes(), 'source':(self.target/'source.pdf').read_bytes(),
                       'image':digest(self.target/'pages'/'P001.png'), 'raw':digest(self.provider/'response-raw.txt')}

    def blocked(self, expected_reason):
        publish_saved(self.config, self.job, self.raw, self.attempt, 'chatgpt')
        self.assertEqual(self.old.read_bytes(), self.before['card'])
        self.assertEqual((self.target/'source.pdf').read_bytes(), self.before['source'])
        self.assertEqual(digest(self.target/'pages'/'P001.png'), self.before['image'])
        self.assertEqual(digest(self.provider/'response-raw.txt'), self.before['raw'])
        self.assertEqual(self.catalog.get(self.pid)['card_path'], str(self.old))
        candidate = self.folder/'gpt-rework-candidate'/'card.json'
        self.assertTrue(candidate.is_file())
        data = json.loads(candidate.read_text())
        self.assertFalse(data['meta']['scientific_verified']); self.assertFalse(data['meta']['production_contract_complete'])
        self.assertEqual(data['meta']['publication_protection']['state'], 'needs_inspection')
        self.assertIn(expected_reason, data['meta']['publication_protection']['reason'])
        self.assertTrue(Path(data['figures'][0]['image_path']).is_file())
        self.assertTrue(candidate.with_name('source.pdf').is_file())
        self.assertEqual(queue.jobs(self.catalog)[0]['state'], 'needs_inspection')

    def test_original_pdf_changed_while_generating_retains_complete_candidate(self):
        self.source.write_bytes(b'A different original version while the model was generating')
        self.blocked('实时原文指纹变化')

    def test_missing_attachment_stops_publication_and_preserves_existing_card(self):
        before=self.old.read_bytes()
        value=json.loads(self.raw);value['warnings']=['未收到可读取的 visual.pdf 附件。']
        publish_saved(self.config,self.job,json.dumps(value),self.attempt,'chatgpt')
        self.assertEqual(self.old.read_bytes(),before)
        self.assertEqual(queue.jobs(self.catalog)[0]['state'],'needs_inspection')

    def test_catalog_source_hash_changed_while_generating_blocks_publication(self):
        self.catalog.update(self.pid, asset_hash='another-original-version')
        self.blocked('目录或冻结原文指纹变化')

    def test_identity_version_or_scope_became_unconfirmed_blocks_publication(self):
        self.catalog.upsert({'title':'Synthetic source review', 'doi':'10.9999/publication', 'version_review_required':True})
        self.blocked('身份、版本或范围需确认')

    def test_human_decision_during_generation_retains_original_and_full_candidate(self):
        self.catalog.decide(self.pid, 'keep')
        self.blocked('人工决定')

    def test_decision_field_without_event_is_also_protected(self):
        with self.catalog.connect() as db:
            db.execute("UPDATE papers SET decision='deep_read' WHERE id=?", (self.pid,))
        self.blocked('人工决定')

    def test_original_card_edited_while_generating_retains_user_edit(self):
        self.old.write_text('The user edited the original card while generation was active')
        self.before['card'] = self.old.read_bytes()
        self.blocked('旧卡片授权需核对')

    def test_queue_selection_changed_while_generating_blocks_stale_publication(self):
        with self.catalog.connect() as db:
            db.execute('UPDATE web_card_jobs SET selection=? WHERE paper_id=?',
                       (json.dumps({'rework':{**self.record, 'correction_id':'a-different-correction'}}), self.pid))
        self.blocked('修正任务或原文绑定变化')

    def test_source_review_unchanged_binding_publishes_without_scientific_acceptance(self):
        publish_saved(self.config, self.job, self.raw, self.attempt, 'chatgpt')
        published=Path(self.catalog.get(self.pid)['card_path'])
        self.assertNotEqual(published,self.old)
        self.assertEqual(self.old.read_bytes(),self.before['card'])
        card = json.loads(published.read_text())
        self.assertEqual(queue.jobs(self.catalog)[0]['state'], 'completed')
        self.assertEqual(card['meta']['selection']['rework']['correction_id'], 'independent-correction')
        self.assertFalse(card['meta']['scientific_verified']); self.assertFalse(card['meta']['production_contract_complete'])
        self.assertEqual((Path(self.record['backup'])/'card.json').read_bytes(), self.before['card'])


if __name__ == '__main__':
    unittest.main()
