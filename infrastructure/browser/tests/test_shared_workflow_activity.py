"""Measured streaming is independent of reserved capacity and stale workers."""
import asyncio
import hashlib
import json
import tempfile
import unittest
from core.api import paths__WorkspacePath as Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from browser.shared_workflow_activity import project, observed
from browser.web_page_observer import PageObserver


class ActivityProjection(unittest.TestCase):
    def test_connected_owner_without_any_inspected_pages_has_no_measurement(self):
        report={'activity_schema_version':1,'updated':99,'page_count':0,'pages':[]}
        self.assertEqual(observed(report,at=100),(None,None))

    def test_measured_streaming_only_and_no_double_count(self):
        rows=[{'target_id':'card','kind':'cards','checked_at':99,'activity_verified':True,'streaming':True},
              {'target_id':'card','kind':'cards','checked_at':99,'activity_verified':True,'streaming':True},
              {'target_id':'review','kind':'review','checked_at':99,'activity_verified':True,'streaming':False},
              {'target_id':'unknown','kind':'correction','checked_at':99,'streaming':True}]
        self.assertEqual(observed({'activity_schema_version':1,'updated':99,'pages':rows},at=100)[0],{'cards':1,'review':0,'correction':0})

    def test_fresh_same_owner_observer_keeps_measurement_during_long_upload(self):
        service={'pid':5,'state':'running','updated':1}
        report={'owner_pid':5,'activity_schema_version':1,'updated':99,'pages':[]}
        result=project(service,owner_live=True,observer=report,at=100)
        self.assertTrue(result['actual_parallel_confirmed']);self.assertEqual(result['actual_parallel']['cards'],0)
        report['owner_pid']=6
        self.assertFalse(project(service,owner_live=True,observer=report,at=100)['actual_parallel_confirmed'])

    def test_pause_keeps_actual_but_stale_or_stopped_does_not_invent_zero(self):
        service={'state':'paused_by_user','updated':99,'actual_parallel_checked_at':99,
                 'actual_parallel':{'cards':3,'review':2,'correction':1},'workers':19,'slot_budget':{'cards':20}}
        self.assertEqual(project(service,owner_live=True,at=100)['actual_parallel']['cards'],3)
        self.assertIsNone(project(service,owner_live=True,at=140)['actual_parallel'])
        self.assertIsNone(project(service,owner_live=False,at=100)['actual_parallel'])


class CollectionIdentity(unittest.TestCase):
    def setUp(self):
        self.prompt='web-card-12345678-1234-1234-1234-123456789abc-source'
        self.url='https://chatgpt.com/c/original'
        self.attempt={'conversation_url':self.url,'actual_prompt_sha256':hashlib.sha256(self.prompt.encode()).hexdigest()}
        self.users=Mock();self.users.count.return_value=1;self.users.first.inner_text.return_value=self.prompt
        self.users.first.evaluate.return_value=[self.prompt,self.prompt]
        self.page=SimpleNamespace(url=self.url,locator=lambda selector:self.users)

    def test_original_complete_material_identity_is_accepted(self):
        from browser.web_card_pool import identify
        self.assertEqual(identify(self.page,self.attempt,self.prompt),'12345678-1234-1234-1234-123456789abc')

    def test_changed_formal_url_with_same_material_is_rejected(self):
        from browser.web_card_pool import identify
        self.page.url='https://chatgpt.com/c/other'
        with self.assertRaisesRegex(ValueError,'URL'):identify(self.page,self.attempt,self.prompt)

    def test_missing_or_changed_original_prompt_fingerprint_is_rejected(self):
        from browser.web_card_pool import identify
        for sha in (None,'changed'):
            self.attempt['actual_prompt_sha256']=sha
            with self.assertRaisesRegex(ValueError,'指纹'):identify(self.page,self.attempt,self.prompt)

    def test_duplicate_user_turns_are_not_collected(self):
        from browser.web_card_pool import identify
        self.users.count.return_value=2
        with self.assertRaisesRegex(ValueError,'不唯一'):identify(self.page,self.attempt,self.prompt)


class ObservedIdentity(unittest.IsolatedAsyncioTestCase):
    async def inspect(self,*,current_url=None,original_url=None,kind=None,lane=None,matching=True):
        from browser.web_card_pool import USER
        from web_gpt.core import ANSWER,STOP_BUTTON
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'attempt.json'
            pid='12345678-1234-1234-1234-123456789abc'
            prompt='web-card-'+pid+'-synthetic input'
            url=current_url or 'https://chatgpt.com/c/owned'
            receipt={'state':'submitted','target_id':'own','created':1,'conversation_url':original_url or url,
                     'actual_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest()}
            if kind:receipt['kind']=kind
            path.write_text(json.dumps(receipt));before=path.read_bytes();(root/'prompt-actual.txt').write_text(prompt)
            empty=Mock();empty.count=AsyncMock(return_value=0)
            stop=Mock();stop.count=AsyncMock(return_value=1);stop.nth.return_value.is_visible=AsyncMock(return_value=True)
            users=Mock();users.count=AsyncMock(return_value=1);users.first.inner_text=AsyncMock(return_value=prompt if matching else 'different input')
            users.first.evaluate=AsyncMock(return_value=[prompt,prompt] if matching else ['different input','different input'])
            page=Mock();page.url=url;page.evaluate=AsyncMock(return_value={'login':False,'streaming':True,'complete':False,'answers':0});page.locator.side_effect=lambda selector:{USER:users,ANSWER:empty,STOP_BUTTON:stop}.get(selector,empty)
            observer=PageObserver(root,SimpleNamespace(_loop=asyncio.get_running_loop()))
            if lane:observer.lanes={'own':{'kind':lane,'active_paper_id':pid}}
            result=await observer.inspect('own',page,[url],{'own':(path,receipt)})
            self.assertEqual(path.read_bytes(),before);self.assertFalse((root/'response-raw.txt').exists())
            return result

    async def test_original_formal_material_generation_is_counted(self):
        result=await self.inspect(kind='correction')
        self.assertTrue(result['streaming']);self.assertTrue(result['activity_verified']);self.assertEqual(result['kind'],'correction')

    async def test_changed_formal_url_or_material_never_confirms_activity(self):
        for options in ({'original_url':'https://chatgpt.com/c/another'},{'matching':False}):
            self.assertNotIn('activity_verified',await self.inspect(**options))

    async def test_legacy_correction_uses_bound_lane_metadata_without_rewriting_receipt(self):
        result=await self.inspect(lane='correction')
        self.assertEqual(result['kind'],'correction')


if __name__=='__main__':unittest.main()
