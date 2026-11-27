"""Bound protocol/worker waits on the resident Playwright loop.

No thread, extra browser connection, retry or cancellation of the browser-side
action is implied. A creation timeout is still an unknown nonce receipt.
"""
import asyncio
from contextlib import contextmanager


async def _metadata_session_async(browser):
    """Share a read-only browser session on the original connection and loop.

    Shield only session acquisition: cancelling one reader must not cancel the
    other readers waiting for the same attachment. Page mutations never use it.
    """
    task=vars(browser).get('_paper_metadata_session')
    if task is None or task.cancelled() or task.done() and task.exception() is not None:
        task=asyncio.create_task(browser.new_browser_cdp_session())
        browser._paper_metadata_session=task
    return await asyncio.shield(task)


@contextmanager
def _metadata_session(browser):
    from playwright._impl._sync_base import SyncBase, mapping
    if not isinstance(browser,SyncBase):
        session=bounded_call(browser,'new_browser_cdp_session')
        try:yield session
        finally:bounded_call(session,'detach')
        return
    async def acquire():
        return await asyncio.wait_for(_metadata_session_async(browser._impl_obj),3)
    session=mapping.from_maybe_impl(browser._sync(acquire()))
    try:yield session
    except Exception as exc:
        if any(label in str(exc) for label in ('Session closed','Connection closed','Target closed')):
            task=vars(browser._impl_obj).get('_paper_metadata_session')
            if task and task.done() and not task.cancelled() and task.exception() is None and task.result() is session._impl_obj:
                del browser._impl_obj._paper_metadata_session
        raise


def _exception_record(exc,stage):
    return {'error_type':type(exc).__name__,'failed_stage':stage,
            'error':(type(exc).__name__+': '+(str(exc) or 'operation timed out or failed without a message'))[:700]}


def bounded_call(owner, method, *args, timeout=3):
    from playwright._impl._sync_base import SyncBase, mapping
    if not isinstance(owner, SyncBase):
        # Local protocol doubles have no driver loop; keep their normal API.
        return getattr(owner, method)(*args)
    async def invoke():
        return await asyncio.wait_for(getattr(owner._impl_obj, method)(*args), timeout)
    # Factories return implementation objects. Match the generated sync API's
    # mapping so subsequent calls use the same owner loop, not bare coroutines.
    return mapping.from_maybe_impl(owner._sync(invoke()))
