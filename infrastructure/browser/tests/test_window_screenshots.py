import asyncio
import base64
import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from core.services import atomic_json
from browser import window_screenshots as screenshots


class WindowScreenshots(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.registry={'schema_version':1,'window_id':77,'created':1,
            'slots':[{'slot_id':f'{i:02d}','target_id':'t'+str(i)} for i in range(1,21)]}
        atomic_json(self.root/'shared-gpt-window.json',self.registry)
        atomic_json(self.root/'window-screenshot-control.json',{'enabled':True,'retain_rounds':2})
        self.payload=b'\xff\xd8'+b'jpeg fixture'*8+b'\xff\xd9'
        self.meta=SimpleNamespace(send=AsyncMock(side_effect=lambda method,args:{'windowId':77}))
        self.browser=SimpleNamespace(new_browser_cdp_session=AsyncMock(return_value=self.meta))
        self.session=SimpleNamespace(send=AsyncMock(return_value={'data':base64.b64encode(self.payload).decode()}),detach=AsyncMock())
        self.page=SimpleNamespace(url='https://chatgpt.com/',context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=self.session)))

    async def test_only_registered_targets_are_captured_and_errors_do_not_hide_other_slots(self):
        other=SimpleNamespace(url='https://example.com/',context=SimpleNamespace(new_cdp_session=AsyncMock()))
        result=await screenshots.capture(self.root,self.browser,{'t1':self.page,'user-page':other},{'t1'})
        self.assertEqual(result['captured'],1);self.assertEqual(len(result['images']),20)
        self.assertEqual(Path(result['images'][0]['path']).read_bytes(),self.payload)
        other.context.new_cdp_session.assert_not_called()
        self.assertTrue(self.session.detach.called)
        self.assertEqual(json.loads((self.root/'window-screenshots/latest.json').read_text())['captured'],1)

    async def test_window_moved_target_is_not_captured(self):
        self.meta.send.side_effect=lambda *args:{'windowId':999}
        r=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(r['captured'],0);self.page.context.new_cdp_session.assert_not_called()

    async def test_disabled_capture_never_uses_cdp_or_creates_files(self):
        atomic_json(self.root/'window-screenshot-control.json',{'enabled':False})
        r=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(r['state'],'disabled');self.browser.new_browser_cdp_session.assert_not_called()
        self.assertFalse((self.root/'window-screenshots').exists())

    async def test_changed_registration_after_screenshot_is_not_published_as_valid(self):
        async def send(*args):
            self.registry['slots'][0]['target_id']='changed'
            atomic_json(self.root/'shared-gpt-window.json',self.registry)
            return {'data':base64.b64encode(self.payload).decode()}
        self.session.send.side_effect=send
        r=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(r['captured'],0);self.assertFalse(list((self.root/'window-screenshots/rounds').rglob('*.jpg')))

    async def test_retention_preserves_pinned_issue_evidence(self):
        first=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        atomic_json(Path(first['round_dir'])/'pin.json',{'reason':'Observed issue under investigation'})
        second=await screenshots.capture(self.root,self.browser,{},set())
        await screenshots.capture(self.root,self.browser,{},set())
        await screenshots.capture(self.root,self.browser,{},set())
        self.assertTrue(Path(first['round_dir']).exists());self.assertFalse(Path(second['round_dir']).exists())

    async def test_page_deadline_covers_window_attach_capture_and_postcheck_together(self):
        async def position(*args):
            await asyncio.sleep(.02);return {'windowId':77}
        async def attach(*args):
            await asyncio.sleep(.02);return self.session
        async def capture(*args):
            await asyncio.sleep(.04)
            return {'data':base64.b64encode(self.payload).decode()}
        self.meta.send.side_effect=position
        self.page.context.new_cdp_session.side_effect=attach
        self.session.send.side_effect=capture
        with patch.object(screenshots,'PAGE_TIMEOUT_SECONDS',.06,create=True):
            result=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(result['captured'],0)
        row=result['images'][0]
        self.assertEqual(row['error_stage'],'capture')
        self.assertIn('TimeoutError',row['error'])
        self.assertGreater(row['stage_seconds']['capture'],0)
        self.assertLess(row['duration_seconds'],.15)
        self.assertFalse(list((self.root/'window-screenshots/rounds').rglob('*.jpg')))
        self.session.detach.assert_awaited_once()

    async def test_slow_first_pages_do_not_consume_later_fixed_slots_round_budget(self):
        active=0;maximum=0;pages={}
        async def send(index,*args):
            nonlocal active,maximum
            active+=1;maximum=max(maximum,active)
            try:
                await asyncio.sleep(.3 if index<=3 else .001)
                return {'data':base64.b64encode(self.payload).decode()}
            finally:active-=1
        for index in range(1,21):
            async def request(*args,i=index):return await send(i,*args)
            session=SimpleNamespace(send=AsyncMock(side_effect=request),detach=AsyncMock())
            pages['t'+str(index)]=SimpleNamespace(url='https://chatgpt.com/',context=SimpleNamespace(new_cdp_session=AsyncMock(return_value=session)))
        with patch.object(screenshots,'PAGE_TIMEOUT_SECONDS',.04,create=True),patch.object(screenshots,'ROUND_TIMEOUT_SECONDS',.25,create=True):
            result=await screenshots.capture(self.root,self.browser,pages,set(pages))
        self.assertEqual(result['captured'],17)
        self.assertEqual([x['state'] for x in result['images'][:3]],['capture_error']*3)
        self.assertEqual(result['images'][-1]['state'],'captured')
        self.assertLessEqual(maximum,3)
        self.assertTrue(all(s.context.new_cdp_session.await_count==1 for s in pages.values()))

    async def test_detach_uses_remaining_page_deadline_and_keeps_valid_image(self):
        async def detach():await asyncio.sleep(1)
        self.session.detach.side_effect=detach
        start=time.monotonic()
        with patch.object(screenshots,'PAGE_TIMEOUT_SECONDS',.04,create=True):
            result=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(result['captured'],1)
        row=result['images'][0]
        self.assertLess(time.monotonic()-start,.2)
        self.assertIn('TimeoutError',row['detach_error'])
        self.assertGreater(row['stage_seconds']['detach'],0)
        self.session.detach.assert_awaited_once()

    async def test_round_cancellation_retains_stage_and_detaches_original_session(self):
        async def capture(*args):await asyncio.sleep(1)
        self.session.send.side_effect=capture
        with patch.object(screenshots,'PAGE_TIMEOUT_SECONDS',1),patch.object(screenshots,'ROUND_TIMEOUT_SECONDS',.03):
            result=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        row=result['images'][0]
        self.assertEqual(row['state'],'capture_timeout')
        self.assertEqual(row['error_stage'],'capture')
        self.assertGreater(row['stage_seconds']['capture'],0)
        self.assertLess(row['duration_seconds'],.2)
        self.session.detach.assert_awaited_once()

    async def test_round_cancel_during_detach_retains_already_verified_image(self):
        async def detach():await asyncio.sleep(1)
        self.session.detach.side_effect=detach
        with patch.object(screenshots,'PAGE_TIMEOUT_SECONDS',1),patch.object(screenshots,'ROUND_TIMEOUT_SECONDS',.03):
            result=await screenshots.capture(self.root,self.browser,{'t1':self.page},{'t1'})
        self.assertEqual(result['captured'],1)
        row=result['images'][0]
        self.assertTrue(row['round_cancelled'])
        self.assertIn('CancelledError',row['detach_error'])
        self.assertGreater(row['stage_seconds']['detach'],0)
        self.assertLess(row['duration_seconds'],.2)
        self.assertEqual(Path(row['path']).read_bytes(),self.payload)
        self.session.detach.assert_awaited_once()
