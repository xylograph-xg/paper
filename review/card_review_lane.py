"""Parallel reviewer conversations on the card keeper's existing CDP connection."""
import json
import sqlite3
import time
from core.api import paths__WorkspacePath as Path

from core.api import catalog__Catalog as Catalog
from core.api import services__atomic_json as atomic_json
from browser.api import shared_pool_store__begin_request as begin_request, shared_pool_store__failed_request as failed_request
from cards.api import web_card_inputs__digest as digest
from . import card_review_queue as queue


class ReviewLane:
    def __init__(self,config):
        self.config=config;self.catalog=Catalog(config['catalog_path'])
        queue.install(self.catalog)
        self.producer=queue.ReviewProducer(config);self.producer.start()
    def blocked_state(self):
        return 'failed' if self.config.get('review_standard',{}).get('no_user_state') is True else 'needs_user'
    def stop(self):self.producer.stop()

    def ledgers(self, *, targets=None, states=None, include_jobs=True):
        from browser.api import attempt_history__read_attempt as read_attempt
        with self.catalog.connect() as db:
            where=' WHERE state IN (SELECT value FROM json_each(?))' if states is not None else ''
            refs=[dict(row) for row in db.execute('SELECT id,folder FROM card_review_jobs'+where+
                ' ORDER BY priority IS NULL,priority DESC,novelty IS NULL,novelty DESC,id',
                (json.dumps(sorted(states)),) if states is not None else ())]
        for ref in refs:
            path=Path(ref['folder'])/'attempt.json'
            if not path.exists():continue
            record=read_attempt(path)
            a={k:v for k,v in record.items() if k not in ('_ledger_path','_ledger_sha256')}
            if targets is not None and a.get('target_id') not in targets:continue
            job=ref
            if include_jobs:
                with self.catalog.connect() as db:
                    row=db.execute('SELECT * FROM card_review_jobs WHERE id=?',(ref['id'],)).fetchone()
                if row is None or row['folder']!=ref['folder']:continue
                job=dict(row)
            yield path,a,job

    def latest(self):
        return [{**a,'_ledger_path':str(p)} for p,a,_ in self.ledgers(include_jobs=False) if a.get('target_id')]

    def reconcile_submissions(self,entries,*,excluded_targets=()):
        """Repair a lost queue acknowledgement from its ended original receipt.

        No page is released and no job becomes ready. An active callback or an
        unknown receipt has no recovery path here. This also survives restart.
        """
        repaired=[]
        for path,a,job in self.ledgers(states={'submitting'}):
            tid=a.get('target_id')
            if job['state']!='submitting' or tid in excluded_targets or a.get('review_id')!=job['id']:continue
            if a.get('state')=='not_sent' and a.get('send_click_started') is False and a.get('finished'):
                state=self.blocked_state()
            elif a.get('state')=='submitted' and a.get('send_click_started') is True:
                state='submitted'
            else:continue
            if a.get('inputs')!=queue.check_packet(path.parent)['input_hashes']:continue
            with self.catalog.connect() as db:
                cursor=db.execute("UPDATE card_review_jobs SET state=?,error=?,updated=? WHERE id=? AND state='submitting'",
                    (state,'原结束回执恢复队列确认；页面仍按实时证据保护',queue.now(),job['id']))
            if cursor.rowcount:
                if state in ('needs_user','failed') and self.owns(entries,tid,job['id']):
                    entries[tid].update(state='needs_inspection',error=a.get('error','原上传已结束，待原所有者核对'))
                repaired.append(job['id'])
        return repaired

    @staticmethod
    def owns(entries,tid,review_id):
        entry=entries.get(tid,{})
        return entry.get('kind')=='review' and entry.get('review_id')==review_id

    def collect(self,pages,entries,observed,router,lock_factory,stopping):
        from browser.api import web_card_transport__require_no_verification as require_no_verification, web_card_transport__collect_owned as collect_owned
        from browser.api import web_card_pool__USER as USER, web_card_pool__record_channel_failure as record_channel_failure
        from web_gpt.core import ANSWER,STOP_BUTTON,_message_text,_dense
        active=0
        for path,a,job in self.ledgers(targets=set(pages)):
            tid=a.get('target_id');page=pages.get(tid)
            if not page or a.get('state') not in ('submitted','submission_started','needs_inspection','response_saved'):continue
            from core.api import automatic_issue_handler__enabled as automatic_enabled
            collect_pending = (automatic_enabled(self.config) and job['state'] == 'needs_user' and
                (json.loads(job.get('result') or '{}') == {} or json.loads(job.get('result') or '{}').get('material_recheck_pending') is True) and
                a.get('state') in ('submitted','submission_started','needs_inspection'))
            if (job['state'] in queue.TERMINAL and not collect_pending) or job['state'] in ('response_saved','applying'):continue
            # A returned target never grants permission to adopt a different conversation.
            if not self.owns(entries,tid,job['id']):continue
            try:
                require_no_verification(page)
                from browser.api import web_message_text__read_user_text as read_user_text
                users=page.locator(USER);expected=path.parent/'prompt-actual.txt'
                if (users.count()!=1 or digest(expected)!=a['actual_prompt_sha256'] or
                        _dense(expected.read_text()) not in _dense(read_user_text(users.first,expected.read_text()))):
                    raise ValueError('核对原会话材料不唯一或提示变化；不重发')
                if not page.url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in page.url:
                    raise ValueError('核对缺少正式会话URL；不重发')
                if a.get('conversation_url','').startswith('https://chatgpt.com/c/') and page.url!=a['conversation_url']:
                    raise ValueError('核对原会话URL变化；不接受其他回答')
                if sum(p.url==page.url for p in pages.values())!=1:raise ValueError('核对会话URL不唯一')
                stops=page.locator(STOP_BUTTON);streaming=any(stops.nth(i).is_visible() for i in range(stops.count()))
                entry=entries.setdefault(tid,{})
                entry.update(kind='review',review_id=job['id'],paper_id=job['paper_id'],conversation_url=page.url)
                if streaming or not (observed.get(tid,{}).get('complete') or a.get('state')=='response_saved'):
                    if a['state']=='needs_inspection' and not streaming:continue
                    entry['state']='busy';active+=1;continue
                if a['state']=='response_saved':
                    raw=(path.parent/'response-raw.txt').read_text()
                    if digest(path.parent/'response-raw.txt')!=a['raw_sha256']:raise ValueError('核对已收取回答指纹变化')
                else:raw=collect_owned(page,a.get('prior_count',0),'chatgpt',(ANSWER,STOP_BUTTON,_message_text),30,stopping)
                with lock_factory(timeout=30):
                    if not self.owns(entries,tid,job['id']):continue
                    queue.check_packet(path.parent)
                    if _dense(expected.read_text()) not in _dense(read_user_text(users.first,expected.read_text())) or any(stops.nth(i).is_visible() for i in range(stops.count())):
                        raise ValueError('核对收取期间页面变化')
                    if _message_text(page.locator(ANSWER).last)!=raw:raise ValueError('核对正式回答实时变化')
                    if not raw.strip():raise ValueError('核验原会话没有正式回答，不释放或重发')
                    (path.parent/'response-raw.txt').write_text(raw)
                    a.update(state='response_saved',conversation_url=page.url,raw_sha256=digest(path.parent/'response-raw.txt'),
                        tab_cleanup='preserved_reusable_window',reused_window=True,finished=time.time())
                    atomic_json(path,a)
                    entry.update(state='ready',raw_path=str(path.parent/'response-raw.txt'),raw_sha256=a['raw_sha256'])
                    queue.update(self.catalog,job['id'],'response_saved')
                    from browser.api import shared_page_backlog__enabled as backlog_enabled
                    if backlog_enabled(self.config):
                        from browser.api import shared_workflow_queue__release_claim as release_claim
                        release_claim(self.catalog,'review',job['id'],tid)
            except Exception as exc:
                if not self.owns(entries,tid,job['id']):continue
                current=json.loads(path.read_text())
                if (current.get('state')=='response_saved' and current.get('created')==a.get('created')
                        and current.get('target_id')==tid and current.get('inputs')==a.get('inputs')):
                    atomic_json(path.parent/'collection-followup-error.json',
                        {'checked_at':time.time(),'error':str(exc)[:700],'original_receipt_preserved':True})
                    continue
                a.update(state='needs_inspection',error=str(exc)[:700]);atomic_json(path,a)
                entries.setdefault(tid,{}).update(state='needs_inspection',kind='review',review_id=job['id'],error=str(exc)[:700])
                queue.update(self.catalog,job['id'],self.blocked_state(),str(exc));record_channel_failure(router,exc,page)
        return active

    def submit(self,pages,entries,active,router,lock_factory,stopping,*,allowed_targets=None,parallel_limit=None,page_guard=None,job_id=None,
               assigned_target_id=None,use_backlog=False,persist_pool=None,parallel_upload=False,on_unstarted=None,on_submitted=None):
        from browser.api import owner_upload_jobs__unstarted_proof as unstarted_proof
        def unstarted():
            if on_unstarted:on_unstarted(unstarted_proof({},page_touched=False))
            return False
        def rejected(reason, rejected_job_id=None, *, final=True):
            atomic_json(self.catalog.path.parent/'review-dispatch-rejection.json',
                {'checked_at':time.time(),'job_id':rejected_job_id or job_id,'target_id':assigned_target_id,'reason':reason})
            if final:return unstarted()
            return False
        from browser.api import web_card_transport__submit_gpt_background as submit_gpt_background, web_card_transport__DeferredWeb as DeferredWeb
        from browser.api import web_card_transport__UploadStageFailure as UploadStageFailure
        from browser.api import web_card_pool__record_channel_failure as record_channel_failure
        from browser.api import (upload_retry_policy__first_eligible as upload_first_eligible,
                                 upload_retry_policy__guard as upload_guard,
                                 upload_retry_policy__record_failure as upload_record_failure,
                                 upload_retry_policy__settle_success as upload_settle_success,
                                 upload_retry_policy__PolicyIntegrityError as PolicyIntegrityError,
                                 upload_trace__desensitize as desensitize)
        def policy_error(exc, *, attempt=None, path=None, diagnostic_key=None):
            message=type(exc).__name__+': '+(desensitize(str(exc)) or '')
            if attempt is not None and path is not None and diagnostic_key:
                attempt[diagnostic_key]=message
                try:atomic_json(path,attempt)
                except (OSError,ValueError):pass  # Preserve the original receipt.
            try:rejected('upload_policy_error: '+message,final=False)
            except (OSError,ValueError):pass
            # A diagnostic write failure must not bypass request-state cleanup.
            print(json.dumps({'event':'review_upload_policy_error','job_id':job_id,
                              'target_id':assigned_target_id,'reason':message}),flush=True)
        if not queue.enabled(self.config) or stopping():return rejected('paused_or_stopping')
        limit=self.config.get('card_review',{}).get('parallel_jobs',4)
        if parallel_limit is not None:limit=min(limit,parallel_limit)
        if active>=limit:return rejected('active_limit')
        try:
            if router.choose()!='chatgpt':return rejected('channel_not_chatgpt')
        except DeferredWeb:return rejected('channel_deferred')
        ready=[(t,pages[t]) for t,e in entries.items() if t in pages and e.get('state') in ('ready','ready_blank')
               and (allowed_targets is None or t in allowed_targets)
               and (assigned_target_id is None or t==assigned_target_id)]
        if not ready:return rejected('page_not_reusable')
        tid,page=ready[0]
        if use_backlog and (not job_id or not assigned_target_id):return rejected('missing_backlog_identity')
        with self.catalog.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if use_backlog:
                from browser.api import shared_page_backlog__check_head_binding as check_head_binding
                if not check_head_binding(db,self.config,'review',job_id,tid):return rejected('head_binding_changed')
            if job_id is not None:
                row=db.execute("SELECT * FROM card_review_jobs WHERE state='ready' AND id=?",(job_id,)).fetchone()
            else:
                candidates=db.execute("SELECT j.* FROM card_review_jobs j LEFT JOIN shared_workflow_arrivals a ON a.lane='review' AND a.job_id=j.id WHERE state='ready' ORDER BY a.queued_at,a.sequence,j.id").fetchall()
                try:
                    diagnostics=[]
                    row=upload_first_eligible(db,candidates,self.config,diagnostics=diagnostics)
                    for diagnostic in diagnostics:
                        rejected('upload_policy_error: '+diagnostic['reason'],diagnostic['job_id'],final=False)
                except (ValueError,OSError,sqlite3.Error) as exc:
                    # Damaged policy evidence refuses this one claim only; the
                    # material keeps its row, state and FIFO place and the owner
                    # dispatch cycle is never entered by this exception.
                    policy_error(exc)
                    return unstarted()
                if row is None and diagnostics:return unstarted()
                if row is None:return rejected('upload_cooldown' if candidates else 'job_not_ready')
            if not row:return rejected('job_not_ready')
            job=dict(row)
            from core.api import seed_focus__allowed as seed_allowed
            if not seed_allowed(self.config,job['paper_id']):return rejected('seed_focus_only')
            from browser.api import original_upload_http1__material_intent as material_intent
            try:frozen=json.loads((Path(job['folder'])/'packet.json').read_text())
            except (OSError,ValueError):frozen={}
            if material_intent(self.catalog.path.parent,'review',job['id'],job['paper_id'],frozen.get('upload_bundle',{}).get('zip_sha256')):
                return rejected('原附件PUT已有持久意图，保留原材料，不重传',job['id'])
            # Recheck the exact material wait for the row actually claimed here,
            # including the non-mixed entry that never consulted the page head.
            try:
                upload_guard(db,self.config,job['id'],job['folder'])
            except ValueError as exc:
                return rejected('upload_cooldown: '+str(exc)[:200])
            if use_backlog:
                from browser.api import shared_page_backlog__mark_claimed as mark_claimed
                if not mark_claimed(db,'review',job_id,tid):return rejected('head_claim_failed')
            db.execute("UPDATE card_review_jobs SET state='submitting' WHERE id=?",(job['id'],))
        folder=Path(job['folder']);path=folder/'attempt.json'
        if path.exists():
            queue.update(self.catalog,job['id'],self.blocked_state(),'已有核对提交账本，不重发');return rejected('prior_submission_ledger')
        try:
            packet_version=json.loads((folder/'packet.json').read_text()).get('review_images_version')
        except (OSError,ValueError,AttributeError) as exc:
            if use_backlog:
                from browser.api import shared_claim_recovery__release_untouched as release_untouched
                release_untouched(self.catalog,'review',job['id'],tid)
            queue.update(self.catalog,job['id'],self.blocked_state(),'核验材料清单需核对：'+str(exc))
            return rejected('packet_not_ready')
        if packet_version!=1:
            if use_backlog:
                from browser.api import shared_claim_recovery__release_untouched as release_untouched
                release_untouched(self.catalog,'review',job['id'],tid)
            queue.update(self.catalog,job['id'],self.blocked_state(),'旧冻结材料缺少当前图像合同，保留证据并停止循环领取')
            return rejected('image_upgrade_preparation')
        import os
        from core.api import control__read_record as read_record
        owner=read_record(self.catalog.path.parent/'web-card-service.json')
        a={'provider':'chatgpt','state':'ready','created':time.time(),'target_id':tid,'review_id':job['id'],'kind':'review','paper_id':job['paper_id'],'send_click_started':False,'reused_window':True,
           'owner_pid':os.getpid(),'owner_token':owner.get('token')}
        page_touched=False
        original_entry=dict(entries[tid])
        try:
            queue.current(self.catalog,job,self.config);packet=queue.check_packet(folder)
            a.update(inputs=packet['input_hashes'],actual_prompt_sha256=packet['actual_prompt_sha256'],
                     upload_bundle=packet['upload_bundle'])
            atomic_json(path,a)
            from browser.api import web_upload_bundle__check_zip_size as check_zip_size
            check_zip_size(packet['upload_bundle'])
            with lock_factory(timeout=30):
                if stopping() or not queue.enabled(self.config):raise DeferredWeb('Paused before page inspection')
            from web_gpt.core import ANSWER,STOP_BUTTON,_message_text,wait_prompt_box,_box_text
            from browser.api import web_card_pool__USER as USER
            from browser.api import shared_window_owner__require_reusable as require_reusable
            require_reusable(page,entries[tid])
            with lock_factory(timeout=30):
                if stopping() or not queue.enabled(self.config):raise DeferredWeb('核对已暂停，未发送')
                if page_guard:page_guard(tid)
                if use_backlog:
                    from browser.api import shared_workflow_queue__check_claim as check_claim
                    check_claim(self.catalog,'review',job['id'],tid)
                begin_request(entries[tid],'review',job['paper_id'],review_id=job['id'])
                if persist_pool:persist_pool()
                page_touched=True
            if stopping() or not queue.enabled(self.config):raise DeferredWeb('Paused before page preparation')
            if page_guard:page_guard(tid)
            from browser.api import reusable_home__prepare as prepare_home
            a['page_preparation']=prepare_home(page)
            from browser.api import gpt_model_policy__configure_session as configure_session
            s=configure_session(page,self.catalog.path.parent)
            a.update(settings=s.settings,conversation_url=page.url);atomic_json(path,a)
            def before_send():
                if stopping() or not queue.enabled(self.config):raise DeferredWeb('核对已暂停，未点击发送')
                if router.choose()!='chatgpt':raise DeferredWeb('附件通道不可用，未点击发送')
                if page_guard:page_guard(tid)
                if use_backlog:check_claim(self.catalog,'review',job['id'],tid)
                queue.current(self.catalog,job,self.config);queue.check_packet(folder)
                # The final guard runs inside the shared submission lock, before
                # any send intent: an expiry never grants page reuse or a send.
                with self.catalog.connect() as guard_db:
                    upload_guard(guard_db,self.config,job['id'],job['folder'])
                a.update(state='submission_started',send_click_started=True);atomic_json(path,a)
            def identified(identifier,detail):
                a.update(upload_attempt_id=identifier,upload_diagnostic=detail);atomic_json(path,a)
            def stage(name):
                a.update(stage=name)
                if not a.get('send_click_started'):atomic_json(path,a)
            prior=submit_gpt_background(s,(folder/'prompt-actual.txt').read_text(),[packet['upload_bundle']['zip_path']],
                on_before_send=before_send,upload_timeout=((self.config['web_cards'].get('upload_large_settle_timeout_seconds',
                    self.config['web_cards'].get('upload_settle_timeout_seconds',180)))
                    if isinstance(packet.get('upload_bundle',{}).get('size'),int)
                    and packet['upload_bundle']['size']>=self.config['web_cards'].get('parallel_uploads',{}).get('large_zip_threshold',8_000_000)
                    else self.config['web_cards'].get('upload_settle_timeout_seconds',180))*1000,
                stopping=lambda:stopping() or not queue.enabled(self.config),lock_factory=lock_factory,parallel_upload=parallel_upload,
                page_guard=(lambda:page_guard(tid)) if page_guard else None,
                upload_context={'lane':'review','paper_id':job['paper_id'],'job_id':job['id'],
                    'local_file_paths':self.config['web_cards'].get('parallel_uploads',{}).get('local_file_paths') is True,
                    'target_id':tid,'bundle':packet['upload_bundle'],'on_identified':identified,'on_stage':stage})
            from browser.api import web_card_transport__commit_submitted as commit_submitted
            commit_submitted(path,a,prior_count=prior,conversation_url=page.url)
            if on_submitted:on_submitted(a)
            else:entries[tid].update(conversation_url=page.url)
            # A durable sent receipt ends the streak only; totals stay on file.
            # The request is already sent and the conversation is generating, so
            # this bookkeeping call has no authority to downgrade it: damaged
            # policy evidence and a busy write lock are both recorded instead of
            # rewriting the ledger state, the queue row or the page.
            try:
                upload_settle_success(self.catalog,config=self.config,job_id=job['id'],attempt=a)
            except (ValueError,OSError,sqlite3.Error) as policy_exc:
                policy_error(policy_exc,attempt=a,path=path,diagnostic_key='upload_settle_policy_error')
            with self.catalog.connect() as db:
                db.execute("UPDATE card_review_jobs SET state='submitted',updated=? WHERE id=? AND state='submitting'",
                    (queue.now(),job['id']))
            return True
        except Exception as exc:
            import traceback
            detail={'error_type':type(exc).__name__,'failed_stage':a.get('stage','lease_preflight'),
                    'error':(type(exc).__name__+': '+(str(exc) or 'operation timed out or failed without a message'))[:700]}
            if a.get('send_click_started') and path.is_file() and json.loads(path.read_text()).get('state')=='response_saved':
                from browser.api import web_card_transport__commit_submitted as commit_submitted
                commit_submitted(path,a,prior_count=None,conversation_url=page.url)
                a['submission_followup_error']=detail;atomic_json(path,a);return True
            if a.get('state')=='submitted':
                # A queue ACK/diagnostic error cannot revoke the sent receipt.
                policy_error(exc,attempt=a,path=path,diagnostic_key='queue_ack_error')
                return True
            if (isinstance(exc,DeferredWeb) and not page_touched and not a.get('send_click_started')
                    and (stopping() or not queue.enabled(self.config))):
                a.update(state='not_sent',error=str(exc)[:700],finished=time.time(),archive_reason='paused_before_page_use')
                atomic_json(path,a)
                history=folder/'history'/('paused-before-send-'+str(time.time_ns()))
                history.mkdir(parents=True,exist_ok=False);path.replace(history/'attempt.json')
                queue.update(self.catalog,job['id'],'ready','核验已暂停；未使用页面，保留原入队顺序')
                if use_backlog:
                    from browser.api import shared_workflow_queue__rollback_claim as rollback_claim
                    rollback_claim(self.catalog,'review',job['id'],tid)
                return rejected('paused_before_page_use')
            if use_backlog and not page_touched and not a.get('send_click_started'):
                from browser.api import shared_claim_recovery__release_untouched as release_untouched
                release_untouched(self.catalog,'review',job['id'],tid)
            # No implicit reset or retry of any uncertain reviewer request.
            if path.exists():
                a.update(state='needs_inspection' if a.get('send_click_started') else 'not_sent',finished=time.time(),**detail)
                (folder/'error-trace.txt').write_text(traceback.format_exc())
                if isinstance(exc,UploadStageFailure):a['upload_failure_stage']=exc.stage
                try:
                    if a.get('send_click_started'):a['conversation_url']=page.url
                    else:a['observed_page_url']=page.url
                except Exception:pass
                atomic_json(path,a)
            # Count only after the durable receipt, so a repeated scan cannot
            # add a failure and a lost write cannot look like a clean attempt.
            try:
                upload_record_failure(self.catalog,config=self.config,job_id=job['id'],attempt=a,
                    reason=desensitize(str(exc)) or type(exc).__name__)
            except (ValueError,OSError,sqlite3.Error) as policy_exc:
                policy_error(policy_exc,attempt=a,path=path,diagnostic_key='upload_failure_policy_error')
            failed_request(entries[tid],original_entry,page_touched=page_touched,error=exc)
            from browser.api import shared_browser_window__WindowIsolationError as WindowIsolationError
            queue.update(self.catalog,job['id'],self.blocked_state(),detail['error'])
            if not isinstance(exc,WindowIsolationError):
                record_channel_failure(router,exc,page,page_guard=(lambda:page_guard(tid)) if page_guard else None)
            proof=unstarted_proof(a,page_touched=page_touched,
                local_file_paths=self.config['web_cards'].get('parallel_uploads',{}).get('local_file_paths') is True)
            if proof is not None and on_unstarted:on_unstarted(proof)
            return False
