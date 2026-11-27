"""Cooperative page submissions on the one resident Playwright thread/loop.

Sync Playwright already yields through its dispatcher greenlet. Each bounded
page job uses that same dispatcher; no threads or browser connections are added.
"""
import asyncio
import time
from greenlet import greenlet,getcurrent


def unstarted_proof(attempt, *, page_touched, local_file_paths=False):
    """Evidence about this callback only; never permission to reuse its page."""
    attempt=attempt or {};diagnostic=attempt.get('upload_diagnostic') or {}
    if attempt.get('send_click_started') or diagnostic.get('local_file_write_state') is not None:return None
    if page_touched and not local_file_paths:return None
    return {'native_file_write_started':False,'send_click_started':False,'page_touched':bool(page_touched),
        'upload_attempt_id':attempt.get('upload_attempt_id'),
        'basis':'no_page_use' if not page_touched else 'local_file_writer_not_entered'}


def active_lease_targets(root):
    """Only the current live owner can pin leases; never infer a request result."""
    import json,hashlib,os
    from core.api import paths__WorkspacePath as Path
    path=Path(root)/'owner-upload-leases.json'
    if not path.exists():return set()
    data=json.loads(path.read_text());owner=json.loads((Path(root)/'web-card-service.json').read_text())
    pid=data.get('owner_pid');token=owner.get('token')
    if (type(pid) is not int or pid!=owner.get('pid') or not token or
            data.get('owner_token_sha256')!=hashlib.sha256(token.encode()).hexdigest()):return set()
    try:os.kill(pid,0)
    except ProcessLookupError:return set()
    return set(data.get('targets',[]))


class OwnerUploadJobs:
    def __init__(self, pw, limit=5, *, byte_limit=None, large_limit=None, large_threshold=8_000_000):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError('并行上传范围为1–5')
        self.pw=pw;self.limit=limit;self.jobs={};self.results=[];self.closing=False;self.retained={};self.lanes={}
        self.released={};self._missing={}
        if byte_limit is not None and (type(byte_limit) is not int or byte_limit<=0):
            raise ValueError('上传材料总量预算必须是正整数字节')
        if large_limit is not None and (type(large_limit) is not int or not 1 <= large_limit <= limit):
            raise ValueError('大包上传并行范围必须为1–总并行数')
        if type(large_threshold) is not int or large_threshold<=0:
            raise ValueError('大包阈值必须是正整数字节')
        self.byte_limit=byte_limit;self.sizes={}
        self.large_limit=large_limit;self.large_threshold=large_threshold
        self._unstarted={};self._published_leases=None

    def _publish_leases(self):
        import json,hashlib,os
        from . import upload_trace
        from core.api import services__atomic_json as atomic_json
        root=upload_trace.root()
        if root is None or not root.exists() or not (root/'web-card-service.json').is_file():return
        owner=json.loads((root/'web-card-service.json').read_text())
        if owner.get('pid')!=os.getpid() or not owner.get('token'):return
        key=(owner['pid'],hashlib.sha256(owner['token'].encode()).hexdigest(),tuple(sorted(self.jobs)))
        if key==self._published_leases:return
        atomic_json(root/'owner-upload-leases.json',{'owner_pid':key[0],'owner_token_sha256':key[1],
            'targets':list(key[2]),'checked_at':time.time(),'basis':'original_owner_callback_lifetime'})
        self._published_leases=key

    def note_unstarted(self,target,proof):
        if getcurrent() is not self.jobs.get(target):return False
        if (not isinstance(proof,dict) or proof.get('native_file_write_started') is not False
                or proof.get('send_click_started') is not False
                or proof.get('basis') not in ('no_page_use','local_file_writer_not_entered')):
            raise ValueError('没有明确未开始附件写入的证明，不释放上传预算')
        self._unstarted[target]=dict(proof);return True

    @property
    def admitted_zip_bytes(self):
        return sum(self.sizes.get(tid,self.byte_limit or 0) for tid in self.budget_targets)

    def large_packages(self):
        return sum(1 for tid in self.budget_targets
                   if self.sizes.get(tid,self.byte_limit or 0)>=self.large_threshold)

    def can_accept(self,zip_bytes):
        if not self.available:return False
        size=zip_bytes if type(zip_bytes) is int and zip_bytes>0 else (self.byte_limit or 0)
        # Large and small packages have separate engineering budgets.  A large
        # package may run alone when the queue is empty, but never beyond the
        # configured number of concurrent large transfers.
        if (self.budget_targets and self.large_limit is not None
                and size>=self.large_threshold and self.large_packages()>=self.large_limit):
            return False
        if self.byte_limit is None:return True
        # The highest-ranked large package may run alone; never skip it or
        # starve it merely because it exceeds the aggregate engineering budget.
        return not self.budget_targets or self.admitted_zip_bytes+size<=self.byte_limit

    @property
    def targets(self):
        return set(self.jobs)

    @property
    def available(self):
        return not self.closing and len(self.budget_targets)<self.limit

    @property
    def budget_targets(self):return set(self.jobs)|set(self.retained)

    @property
    def pending_by_lane(self):
        return {lane:sum(self.lanes.get(tid)==lane for tid in self.budget_targets)
                for lane in ('cards','review','correction')}

    @property
    def pending_targets_by_lane(self):
        return {lane:{tid for tid in self.budget_targets if self.lanes.get(tid)==lane}
                for lane in ('cards','review','correction')}

    def release_observed(self,health):
        # The original repair owner reports replacements only after archive,
        # confirmed close, registry CAS and a ready replacement. The retired
        # target can never appear in later health snapshots to release itself.
        replaced={r.get('old_target_id') for r in health.get('replaced',[])
            if isinstance(r,dict) and isinstance(r.get('old_target_id'),str)
            and isinstance(r.get('new_target_id'),str) and r['new_target_id']
            and r['old_target_id']!=r['new_target_id'] and r.get('journal')}
        replacement_at=health.get('finished_at')
        for target,finished in list(self.retained.items()):
            snapshot=health.get('pages',{}).get(target,{}).get('evidence',{}).get('snapshot',{})
            stamp=snapshot.get('checked_at')
            if (snapshot.get('inspection_complete') is True and snapshot.get('uploading') is False
                    and type(stamp) in (int,float) and stamp>=finished):
                self.retained.pop(target,None)
                self.lanes.pop(target,None)
                self.sizes.pop(target,None)
            elif (target in replaced and health.get('state') in ('checked','pending')
                    and type(replacement_at) in (int,float) and replacement_at>=finished):
                self.retained.pop(target,None)
                self.lanes.pop(target,None)
                self.sizes.pop(target,None)

    def release_missing(self, live_targets, *, complete, epoch, archive, at=None):
        """Release capacity only, after two complete inventories 30s apart.

        Original request/queue/ledger states stay unknown or protected. Absence
        never authorizes another submission of the original material.
        """
        at=time.time() if at is None else at
        if not complete:
            self._missing.clear();return
        for target,finished in list(self.retained.items()):
            if target in live_targets:
                self._missing.pop(target,None);continue
            proof=self._missing.get(target)
            binding=(epoch,finished)
            if not proof or proof['binding']!=binding:
                self._missing[target]={'binding':binding,'first_checked_at':at};continue
            if at-proof['first_checked_at']<30:continue
            archive({'target_id':target,'callback_finished_at':finished,'epoch':epoch,
                     'first_checked_at':proof['first_checked_at'],'second_checked_at':at,
                     'action':'release_upload_capacity_only','original_request_unchanged':True})
            self.retained.pop(target,None);self.lanes.pop(target,None);self._missing.pop(target,None)
            self.sizes.pop(target,None)
            self.released[target]=at

    def start(self, target, callback, *, lane=None, zip_bytes=None):
        if lane not in (None,'cards','review','correction'):raise ValueError('未知上传队列')
        if not self.can_accept(zip_bytes) or target in self.budget_targets:
            return False
        def invoke():
            submitted=False;completed=False
            try:
                result=callback()
                completed=True
                # True is returned only after native attachment settlement,
                # the original guarded send, and durable submitted receipt.
                submitted=result is True
                self.results.append({'target_id':target,'finished':time.time(),'result':result})
            except Exception as exc:
                self.results.append({'target_id':target,'finished':time.time(),'error':type(exc).__name__+': '+str(exc)[:500]})
            finally:
                proof=self._unstarted.pop(target,None);unstarted=False
                if completed and not submitted and proof is not None:
                    try:
                        from . import upload_trace
                        if upload_trace.root() is not None:
                            upload_trace.append({'kind':'upload_capacity_released_unstarted',
                                'event':'upload_capacity_released_unstarted',**upload_trace.owner_identity(),
                                'target_id':target,'lane':self.lanes.get(target),'at':time.time(),
                                'upload_attempt_id':proof.get('upload_attempt_id'),
                                'admitted_zip_bytes':self.sizes.get(target),'proof':proof})
                        unstarted=True
                    except Exception as exc:
                        self.results.append({'target_id':target,'finished':time.time(),
                            'error':'未开始上传的释放证据未保存：'+type(exc).__name__+': '+str(exc)[:300]})
                if submitted:
                    self.released[target]=time.time();self.lanes.pop(target,None)
                    self.sizes.pop(target,None)
                elif unstarted:
                    self.lanes.pop(target,None);self.sizes.pop(target,None)
                    # No watermark: an older *actual* upload in health still counts.
                else:self.retained[target]=time.time()
                self.jobs.pop(target,None)
                try:self._publish_leases()
                except Exception as exc:self.results.append({'target_id':target,'error':'上传领取结束证据待保存：'+str(exc)[:300]})
        fiber=greenlet(invoke,parent=self.pw._dispatcher_fiber)
        self.jobs[target]=fiber
        self.sizes[target]=zip_bytes if type(zip_bytes) is int and zip_bytes>0 else self.byte_limit or 0
        self.released.pop(target,None)
        self._unstarted.pop(target,None)
        self.lanes[target]=lane
        try:self._publish_leases()
        except Exception:
            self.jobs.pop(target,None);self.sizes.pop(target,None);self.lanes.pop(target,None)
            raise  # No durable callback lease means no page operation.
        self.pw._loop.call_soon(fiber.switch)
        return True

    def pump(self):
        self._publish_leases()
        """Run scheduled fibers even when page reads complete from local caches."""
        if self.jobs:self.pw._sync(asyncio.sleep(0))

    def reap(self):
        results=self.results;self.results=[]
        return results

    def drain(self):
        # Caller first sets stop: each original job then exits at its existing
        # pre-send guards. Never cancel an unknown click or disconnect mid-job.
        self.closing=True
        while self.jobs:
            self.pw._sync(asyncio.sleep(.1))
