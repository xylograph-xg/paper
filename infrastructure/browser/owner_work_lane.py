"""A cooperative worker on the resident driver's original thread and loop."""
import asyncio
import time
from greenlet import greenlet


class OwnerWorkLane:
    def __init__(self, pw, callback, *, interval=.5):
        self.pw=pw;self.callback=callback;self.interval=interval
        self.busy=False;self.closing=False;self.task=None;self.errors=[]
        self.completed=0;self.last_finished=None

    def start(self):
        self.task=self.pw._loop.create_task(self._run())

    async def _run(self):
        while not self.closing:
            if not self.busy:
                self.busy=True
                def invoke():
                    try:self.callback()
                    except Exception as exc:
                        self.errors.append(type(exc).__name__+': '+str(exc)[:500]);self.errors=self.errors[-20:]
                    finally:
                        self.busy=False;self.completed+=1;self.last_finished=time.time()
                fiber=greenlet(invoke,parent=self.pw._dispatcher_fiber)
                self.pw._loop.call_soon(fiber.switch)
            await asyncio.sleep(self.interval)

    def stop(self):
        self.closing=True
        if self.task:self.task.cancel()

    def drain(self):
        self.stop()
        while self.busy:self.pw._sync(asyncio.sleep(.1))
