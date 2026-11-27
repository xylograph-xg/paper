import asyncio
import unittest
from types import SimpleNamespace
from playwright._impl._sync_base import SyncBase
from browser.owner_browser_calls import bounded_call


class OwnerLoop(SyncBase):
    def __init__(self, implementation):
        self._impl_obj=implementation

    def _sync(self, operation):
        return asyncio.run(operation)


class BoundedOwnerCalls(unittest.TestCase):
    def test_real_protocol_factory_returns_sync_session_on_original_loop(self):
        from playwright.sync_api import sync_playwright, CDPSession
        with sync_playwright() as driver:
            browser=driver.chromium.launch(headless=True,
                executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
            try:
                session=bounded_call(browser,'new_browser_cdp_session')
                self.assertIsInstance(session,CDPSession)
                try:
                    result=bounded_call(session,'send','Target.getTargets')
                    self.assertIsInstance(result['targetInfos'],list)
                finally:bounded_call(session,'detach')
            finally:browser.close()

    def test_protocol_timeout_keeps_loop_responsive_and_never_repeats_command(self):
        calls=[];ticks=[];cancelled=[]
        async def send(method,params):
            calls.append((method,params))
            async def observer():
                await asyncio.sleep(.005);ticks.append('observed')
            asyncio.create_task(observer())
            try:await asyncio.sleep(60)
            finally:cancelled.append(True)
        owner=OwnerLoop(SimpleNamespace(send=send))
        with self.assertRaises(TimeoutError):
            bounded_call(owner,'send','Extensions.loadUnpacked',{'path':'synthetic'},timeout=.03)
        self.assertEqual(len(calls),1);self.assertEqual(ticks,['observed']);self.assertEqual(cancelled,[True])

    def test_worker_result_preserves_exact_window_and_inactive_props(self):
        props={'windowId':77,'active':False};calls=[]
        async def evaluate(expression,arg):
            calls.append((expression,arg));return {'id':1,**arg}
        result=bounded_call(OwnerLoop(SimpleNamespace(evaluate=evaluate)),'evaluate','synthetic',props)
        self.assertEqual(calls,[('synthetic',props)]);self.assertEqual(result['windowId'],77)
        self.assertIs(result['active'],False)
