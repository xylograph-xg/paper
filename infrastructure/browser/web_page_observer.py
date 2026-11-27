"""Ten-second observation on the existing Playwright connection, also during uploads.

Only async implementation objects are used by the scheduled task. No second CDP
connection, thread sharing of sync Page objects, sending, navigation or closing.
"""
import asyncio,hashlib,json,re,time
from contextlib import contextmanager
from core.api import paths__WorkspacePath as Path
from core.api import services__atomic_json as atomic_json

INTERVAL=10
PAGE_READ_TIMEOUT=3
PAGE_CHECK_TIMEOUT=5


def status_script():
    """One renderer round trip; no conversation reads on authentication hosts."""
    from .shared_page_health import LOGIN_UI_SCRIPT
    return r'''({answer, stop, send, receipt, user}) => {
      const account = (''' + LOGIN_UI_SCRIPT + r''')();
      if (account.login || location.hostname !== 'chatgpt.com') return account;
      const visible = el => {
        if (!el || el.closest('[hidden],[aria-hidden="true"],[inert]')) return false;
        const style = getComputedStyle(el), rect = el.getBoundingClientRect();
        return style.display !== 'none' && !['hidden','collapse'].includes(style.visibility)
          && rect.width > 0 && rect.height > 0;
      };
      const nodes = selector => Array.from(document.querySelectorAll(selector));
      const answers = nodes(answer.replace(/:visible\b/g, '')).filter(visible);
      const last = nodes('[data-talvt-turn-state]').at(-1);
      const assistant = '[data-message-author-role="assistant"],h4[data-conversation-role="assistant"],[data-chatgpt-search-unit-key$=":assistant"]';
      const assistantTurn = !!last && (last.matches(assistant) || !!last.querySelector(assistant)
        || answers.some(el => last.contains(el)));
      const box = nodes('#prompt-textarea,[role="textbox"],textarea,[contenteditable="true"]')
        .filter(visible).find(el => !el.closest('[data-message-author-role],[data-conversation-role],aside,nav'));
      const composer = box && (box.closest('form,[data-composer-body]') || box.parentElement?.parentElement);
      let button = null;
      for (const selector of send) {
        button = composer && Array.from(composer.querySelectorAll(selector)).find(visible);
        if (button) break;
      }
      const state = {...account,
        verification: nodes('#nocaptcha,[class*="captcha"]').some(visible),
        streaming: nodes(stop).some(visible),
        complete: assistantTurn && last.getAttribute('data-talvt-turn-state') === 'complete',
        answers: answers.length,
        send_button_present: !!button,
        send_button_disabled: button ? !!button.disabled || button.getAttribute('aria-disabled') === 'true' : null,
        upload_indicator_visible: !!composer && Array.from(composer.querySelectorAll(
          '[role="progressbar"],[data-testid*="progress"],[aria-label*="Uploading"],[aria-label*="上传中"]')).some(visible)
      };
      if (!receipt) return state;
      const texts = el => el ? [el.textContent || '',el.innerText || ''] : ['', ''];
      return {...state,receipt_schema:1,receipt_url:location.href,
        user_variants:nodes(user).map(texts),answer_variants:texts(answers.at(-1)),
        answer_busy:answers.at(-1)?.getAttribute('aria-busy') === 'true'};
    }'''


@contextmanager
def inspection_stage(result, name):
    previous=result.get('inspection_stage')
    result['inspection_stage']=name
    started=time.monotonic()
    try:yield
    except BaseException:raise
    else:result['inspection_stage']=previous or name
    finally:
        timings=result.setdefault('stage_seconds',{})
        timings[name]=round(timings.get(name,0)+time.monotonic()-started,6)


def inspection_error(result, exc):
    """Retain the real attempt identity and partial evidence on a deadline."""
    if result.get('state') not in (None,'inspection_error'):
        result['last_observed_state']=result['state']
    result.update(state='inspection_error',error=(type(exc).__name__+': '+str(exc))[:300],
                  error_type=type(exc).__name__,failed_stage=result.get('inspection_stage','unknown'))

@contextmanager
def responsive_lock(pw,timeout=180):
    """FIFO admission on the owner loop, plus the original cross-process lock."""
    from web_gpt.submission import submission_lock
    began=time.monotonic();deadline=began+timeout;ticket=object();context=None
    queue=vars(pw).setdefault('_paper_submission_waiters',[]);queue.append(ticket)
    metrics=vars(pw).setdefault('_paper_submission_metrics',{})
    try:
        while True:
            if queue[0] is ticket:
                candidate=submission_lock(timeout=0)
                try:candidate.__enter__();context=candidate;break
                except RuntimeError as exc:
                    if '等待网页提交锁超时' not in str(exc):raise
            if time.monotonic()>=deadline:
                metrics['timeouts']=metrics.get('timeouts',0)+1
                raise RuntimeError('等待网页提交锁超时；本次未取得提交锁')
            pw._sync(asyncio.sleep(.01))
        acquired=time.monotonic();wait=acquired-began
        metrics.update(acquisitions=metrics.get('acquisitions',0)+1,last_wait_seconds=round(wait,6),
                       max_wait_seconds=max(metrics.get('max_wait_seconds',0),round(wait,6)))
        yield
    finally:
        if context is not None:
            held=round(time.monotonic()-acquired,6)
            try:context.__exit__(None,None,None)
            finally:metrics.update(last_hold_seconds=held,max_hold_seconds=max(metrics.get('max_hold_seconds',0),held))
        queue.remove(ticket)

def _review_markers(user):
    # The frozen common contract names its schema with the same lexical
    # prefix as a review task. Only this known, qualified contract heading is
    # metadata; an unqualified/version-unknown token remains an identity
    # candidate and therefore cannot hide a second task or a duplicate ID.
    user=user.replace('制卡与核验共用同一合同（card-review-standard-v3）：','')
    return re.findall(r'card-review-([A-Za-z0-9_-]+)',user)


def _review_identity(user, review_id):
    # Compare the whole frozen job ID, including automatic-successor suffixes.
    # A shared base prefix or a second marker cannot identify this request.
    return _review_markers(user)==[review_id]


def response_identity(attempt,expected,user,url,urls,tid):
    from web_gpt.core import _dense
    from .web_card_transport import formal_gpt_url
    from .web_card_pool import MARKER
    identity=_review_identity(user,attempt['review_id']) if attempt.get('review_id') else len(MARKER.findall(user))==1
    original=attempt.get('conversation_url','')
    return (attempt.get('target_id')==tid and formal_gpt_url(url) and (not formal_gpt_url(original) or original==url) and urls.count(url)==1
            and identity and _dense(expected) in _dense(user)
            and hashlib.sha256(expected.encode()).hexdigest()==attempt.get('actual_prompt_sha256'))

class PageObserver:
    def __init__(self,root,pw):
        self.root=Path(root);self.pages={};self.lanes={};self.task=None;self.interval=INTERVAL
        self.loop=pw._loop;self.last_check=0;self.window_browser=None;self.window_targets=set()
        self._check_sequence=0;self._instance=str(time.time_ns());self._inflight={};self.loop_lag_seconds=0
        self.on_upload_network_failure=None
        previous=self.root/'web-upload-network.json'
        if previous.is_file():
            raw=previous.read_bytes();record=json.loads(raw)
            archive=self.root/'web-upload-network-history'/hashlib.sha256(raw).hexdigest()
            if not archive.exists():
                archive.parent.mkdir(parents=True,exist_ok=True)
                atomic_json(archive,record)
            self._network_events=[{**event,'historical':True,
                'observed_owner_pid':event.get('observed_owner_pid',record.get('owner_pid'))}
                for event in record.get('errors',[])[-100:]]
    def start(self):
        self.task=self.loop.create_task(self.run())
        from .window_screenshots import run as screenshot_worker
        self.screenshot_task=self.loop.create_task(screenshot_worker(self))
    def update(self,pages,*,lane_entries=None,shared_browser=None,registered_targets=None):
        self.pages={tid:p._impl_obj for tid,p in pages.items()}
        self.lanes={tid:{k:entry.get(k) for k in ('kind','review_id','active_paper_id','paper_id')} for tid,entry in (lane_entries or {}).items() if tid in pages}
        # Use the resident browser's async implementation on its original loop.
        # A supplied fixed registration is the only source of lookup targets.
        self.window_browser=shared_browser._impl_obj if shared_browser is not None else None
        self.window_targets={tid for tid in (registered_targets or ()) if isinstance(tid,str) and tid} if shared_browser is not None else set()
        self._update_network_pages()
    def stop(self):
        if self.task:self.task.cancel()
        if getattr(self,'screenshot_task',None):self.screenshot_task.cancel()
        self.pages={};self._update_network_pages()

    def _update_network_pages(self):
        tracked=getattr(self,'_network_pages',{})
        for tid,(page,callbacks) in list(tracked.items()):
            if self.pages.get(tid) is page and tid in self.window_targets:continue
            for event,callback in callbacks.items():
                try:page.remove_listener(event,callback)
                except (AttributeError,KeyError):pass
            tracked.pop(tid)
        for tid,page in self.pages.items():
            if tid in tracked or tid not in self.window_targets or not callable(getattr(page,'on',None)):continue
            callbacks={'request':lambda request,tid=tid,page=page:self._network_event(tid,page,request,phase='request'),
                       'requestfinished':lambda request,tid=tid,page=page:self._network_event(tid,page,request,phase='requestfinished'),
                       'requestfailed':lambda request,tid=tid,page=page:self._network_event(tid,page,request,phase='requestfailed'),
                       'response':lambda response,tid=tid,page=page:self._network_event(tid,page,response.request,response.status,phase='response',response_headers=getattr(response,'headers',None))}
            for event,callback in callbacks.items():page.on(event,callback)
            tracked[tid]=(page,callbacks)
        self._network_pages=tracked

    @staticmethod
    def _request_key(request):
        """Identity stable across the request, response and failure events."""
        for attribute in ('_guid','guid'):
            value=getattr(request,attribute,None)
            if isinstance(value,str) and value:return value
        return None

    def _network_event(self,tid,page,request,status=None,phase=None,response_headers=None):
        """Own fixed pages only; omit signed URLs, headers and payloads."""
        from urllib.parse import urlsplit
        from . import upload_trace
        if self.pages.get(tid) is not page or tid not in self.window_targets:return
        if status is not None and (type(status) is not int or not 100<=status<=599):return
        try:
            if not isinstance(request.url,str):return
            url=urlsplit(request.url);host=url.hostname or ''
            failure=request.failure if status is None else None
        except (AttributeError,ValueError):return
        upload=(bool(re.search(r'/(?:files?|uploads?)(?:/|$)',url.path,re.I)) or host.endswith(('.oaiusercontent.com','.blob.core.windows.net','.s3.amazonaws.com')))
        if not upload:return
        failure_code=re.search(r'net::ERR_[A-Z0-9_]+',str(failure or ''))
        key=self._request_key(request)
        counters=getattr(self,'_network_counters',{})
        if phase=='request':
            # Bind while the request is starting: the attempt that owns the page
            # now, not whichever task the target has when the answer arrives.
            if key is None:
                # Without a stable request identity nothing can ever be bound, so
                # the phase is counted visibly instead of vanishing one by one.
                counters['request_without_key']=counters.get('request_without_key',0)+1
                self._network_counters=counters
                return
            attempt_id=upload_trace.active(tid)
            if attempt_id is None:
                # Keep the observation as attributed=false rather than lose it;
                # after an owner restart the in-flight attempt is simply unknown.
                counters['request_unbound']=counters.get('request_unbound',0)+1
            else:
                counters['request_bound']=counters.get('request_bound',0)+1
                upload_trace.bind_request(key,attempt_id)
        else:
            attempt_id=upload_trace.lookup_request(key)
            if attempt_id is None and key is None:
                counters['late_without_key']=counters.get('late_without_key',0)+1
        self._network_counters=counters
        event={'at':time.time(),'phase':phase,'target_id':tid,'host':host,'method':request.method,
               'resource_type':request.resource_type,'status':status,
               'failure':failure_code[0] if failure_code else 'network_failure' if failure else '',
               'upload_attempt_id':attempt_id,'attributed':attempt_id is not None}
        if phase=='requestfinished' or status is not None and status<400:
            # A completed PUT is different from a settled native attachment.
            # Preserve successful responses without calling the error/cooldown
            # callback or changing the legacy last-error ring.
            try:upload_trace.record_network(event)
            except (OSError,ValueError,RuntimeError) as exc:
                self._network_write_error=(type(exc).__name__+': '+str(exc))[:300]
            return
        if isinstance(response_headers,dict):
            code=response_headers.get('x-ms-error-code')
            if isinstance(code,str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_.-]{0,79}',code):
                event['server_error_code']=code
            retry=response_headers.get('retry-after')
            if isinstance(retry,str) and re.fullmatch(r'\d{1,6}',retry):
                event['retry_after_seconds']=int(retry)
        events=getattr(self,'_network_events',[])
        events.append(dict(event))
        self._network_events=events[-100:]
        try:upload_trace.record_network(event)
        except (OSError,ValueError,RuntimeError) as exc:
            self._network_write_error=(type(exc).__name__+': '+str(exc))[:300]
        callback=getattr(self,'on_upload_network_failure',None)
        if callback:
            try:callback(dict(event))
            except Exception as exc:
                self._network_write_error='network_cooldown: '+type(exc).__name__+': '+str(exc)[:200]
    async def inspect_windows(self,browser,targets):
        """Read actual target positions on the resident CDP connection only."""
        if browser is None or not targets:return {},[]
        session=None;errors=[];shared=False
        def unavailable(tid,exc):
            return {'window_observed':False,'window_checked_at':time.time(),'window_error':(type(exc).__name__+': '+str(exc))[:300]}
        try:
            from playwright._impl._browser import Browser
            if isinstance(browser,Browser):
                from .owner_browser_calls import _metadata_session_async
                session=await asyncio.wait_for(_metadata_session_async(browser),3);shared=True
            else:session=await asyncio.wait_for(browser.new_browser_cdp_session(),3)
            async def position(tid):
                try:
                    reply=await asyncio.wait_for(session.send('Browser.getWindowForTarget',{'targetId':tid}),3)
                    wid=reply.get('windowId')
                    if not isinstance(wid,int) or isinstance(wid,bool) or wid<0:raise ValueError('窗口标识不可核对')
                    return tid,{'window_id':wid,'window_observed':True,'window_checked_at':time.time()}
                except Exception as exc:return tid,unavailable(tid,exc)
            results=dict(await asyncio.gather(*(position(tid) for tid in sorted(targets))))
        except Exception as exc:
            errors.append('窗口只读会话不可用：'+(type(exc).__name__+': '+str(exc))[:300])
            results={tid:unavailable(tid,exc) for tid in targets}
        finally:
            if session is not None and not shared:
                try:await asyncio.wait_for(session.detach(),2)
                except Exception as exc:errors.append('窗口只读会话释放失败：'+(type(exc).__name__+': '+str(exc))[:300])
        return results,errors
    async def inspect(self,tid,page,urls,ledgers,collect=True):
        from web_gpt.core import ANSWER,STOP_BUTTON,SEND_BUTTONS,_parses_as_json,_dense
        from .web_card_pool import USER
        result=self._inflight.get(tid)
        if result is None:result={'target_id':tid,'url':page.url,'checked_at':time.time()}
        snapshot={}
        try:
            async def read():
                nonlocal snapshot
                with inspection_stage(result,'page_state'):
                    value=await asyncio.wait_for(page.evaluate(status_script(),
                        {'answer':ANSWER,'stop':STOP_BUTTON,'send':SEND_BUTTONS,'receipt':collect,'user':USER}),PAGE_READ_TIMEOUT)
                snapshot=value
                if not isinstance(value,dict) or type(value.get('login')) is not bool:
                    raise ValueError('登录控件观测不完整')
                result.update({k:value.get(k) for k in ('login','login_detection_version','login_evidence',
                    'account_authenticated','authenticated_evidence','account_ready','composer_available',
                    'account_ui_blocked','send_button_present','send_button_disabled','upload_indicator_visible')})
                if value['login']:
                    self._record_login(tid,value)
                    result.update(checked_at=time.time(),state='login_required',streaming=False,complete=False,
                                  account_reason='等待手动登录；原页保留，新提交已暂停')
                    return None
                from urllib.parse import urlsplit
                if urlsplit(page.url).hostname!='chatgpt.com':
                    result.update(state='inspection_required',error='原固定页已离开ChatGPT；仅检查账户界面，保留原页')
                    return None
                if value.get('verification'):
                    from core.api import control__mutate_record as mutate_record, control__read_record as read_record
                    path=self.root/'web-channel-control.json';record=read_record(path);record['chatgpt']={'manual_verification_required':True,'reason':'10秒观察发现访问验证','observed':time.time()}
                    mutate_record(path,record,event='observer_manual_verification')
                    raise RuntimeError('访问验证，保留页面，不收取或重新提交')
                if (type(value.get('streaming')) is not bool or type(value.get('complete')) is not bool
                        or type(value.get('answers')) is not int or value['answers']<0):
                    raise ValueError('生成与回答状态观测不完整')
                result.update(checked_at=time.time(),streaming=value['streaming'],complete=value['complete'],
                              answers=value['answers'],state='generating' if value['streaming'] else
                              'complete' if value['complete'] and value['answers'] else 'idle')
                return value['streaming'],value['complete'],page.locator(ANSWER),value['answers']
            state=await read()
            if state is None:return result
            streaming,complete,answers,n=state
            if not collect:return result
            ledger=ledgers.get(tid)
            if not ledger:return result
            path,a=ledger
            if a.get('state') not in ('submitted','submission_started','needs_inspection','response_saved'):return result
            # Reuse/closure still requires the separate full health guards. A
            # saved, non-streaming page needs no repeated collection identity RPCs.
            if a.get('state')=='response_saved' and not streaming:
                result['collection_state']='already_saved';return result
            if snapshot.get('receipt_schema')==1:
                return await self._collect_snapshots(tid,page,urls,path,a,result,read,lambda:snapshot)
            result['inspection_stage']='receipt_identity'
            expected_path=path.parent/'prompt-actual.txt'
            if not expected_path.exists():return result
            users=page.locator(USER)
            if await users.count()!=1:return result
            from .web_message_text import read_user_text_async
            expected=expected_path.read_text();user=await read_user_text_async(users.first,expected)
            if not response_identity(a,expected,user,page.url,urls,tid):return result
            kind='review' if a.get('review_id') else a.get('kind','cards')
            if not a.get('review_id') and not a.get('kind'):
                from .web_card_pool import MARKER
                markers=MARKER.findall(user);entry=self.lanes.get(tid,{})
                if entry.get('kind')=='correction' and not entry.get('review_id') and len(markers)==1 and markers[0] in (entry.get('active_paper_id'),entry.get('paper_id')):
                    kind='correction'
            if kind not in ('cards','review','correction'):return result
            result.update(activity_verified=True,kind=kind,identity_checked_at=time.time())
            if streaming or not complete or not n or a.get('state')=='response_saved':return result
            async def text():
                variants=await answers.last.evaluate("el=>[el.textContent||'',el.innerText||'']")
                return next((s for s in variants if s and _parses_as_json(s)),next((s for s in variants if s),''))
            raw=await text()
            if not raw.strip():
                result.update(state='empty_response',error='assistant占位为空，未收取正式回答，保留原提交')
                return result
            result['inspection_stage']='answer_stability'
            for _ in range(2):
                await asyncio.sleep(.5)
                state=await read()
                if state is None:return result
                live_stream,live_complete,_,_=state
                if live_stream or not live_complete or await text()!=raw:return result
            # Collection is a separate read-only lane. It never acquires the
            # upload/send lock. The owner cannot reuse this target before its
            # raw receipt is saved; all awaited reads precede the final ledger
            # CAS, and there is no await between that CAS and durable writes.
            current=json.loads(path.read_text())
            if current.get('state') not in ('submitted','submission_started','needs_inspection') or current.get('created')!=a.get('created'):return result
            if not response_identity(current,expected,await read_user_text_async(users.first,expected),page.url,[p.url for p in self.pages.values()],tid):return result
            if (await answers.last.get_attribute('aria-busy'))=='true':return result
            state=await read()
            if state is None:return result
            live_stream,live_complete,_,_=state
            if live_stream or not live_complete or await text()!=raw:return result
            # The synchronous owner may have published a newer ledger while
            # the asynchronous DOM reads above yielded. Preserve that write.
            final=json.loads(path.read_text())
            if final!=current:return result
            from .shared_page_repair import atomic_text
            result['inspection_stage']='save_response'
            raw_path=path.parent/'response-raw.txt'
            if raw_path.exists() and raw_path.read_text()!=raw:
                raise ValueError('原回答已有不同保存物，不覆盖')
            atomic_text(raw_path,raw)
            final.update(state='response_saved',conversation_url=page.url,raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),tab_cleanup='preserved_reusable_window',reused_window=True,observed_complete_at=time.time())
            atomic_json(path,final);result['saved']=True

        except Exception as exc:inspection_error(result,exc)
        return result

    async def _collect_snapshots(self,tid,page,urls,path,attempt,result,read,snapshot):
        """One consistent DOM snapshot per stability point, all original guards."""
        from web_gpt.core import _parses_as_json
        from .web_message_text import select_user_text
        expected_path=path.parent/'prompt-actual.txt'
        if not expected_path.is_file():return result
        expected=expected_path.read_text()
        def identity(a,unique_urls):
            value=snapshot();users=value.get('user_variants',[])
            return (len(users)==1 and value.get('receipt_url')==page.url and
                response_identity(a,expected,select_user_text(users[0],expected),page.url,unique_urls,tid))
        def body():
            variants=snapshot().get('answer_variants',[])
            return next((s for s in variants if s and _parses_as_json(s)),next((s for s in variants if s),''))
        result['inspection_stage']='receipt_identity'
        if not identity(attempt,urls):return result
        kind='review' if attempt.get('review_id') else attempt.get('kind','cards')
        if not attempt.get('review_id') and not attempt.get('kind'):
            from .web_card_pool import MARKER
            markers=MARKER.findall(expected);entry=self.lanes.get(tid,{})
            if (entry.get('kind')=='correction' and not entry.get('review_id') and len(markers)==1
                    and markers[0] in (entry.get('active_paper_id'),entry.get('paper_id'))):kind='correction'
        if kind not in ('cards','review','correction'):return result
        result.update(activity_verified=True,kind=kind,identity_checked_at=time.time())
        if result['streaming'] or not result['complete'] or not result['answers']:return result
        raw=body()
        if not raw.strip():
            result.update(state='empty_response',error='assistant占位为空，未收取正式回答，保留原提交');return result
        result['inspection_stage']='answer_stability'
        for _ in range(2):
            await asyncio.sleep(.5)
            if await read() is None:return result
            if result['streaming'] or not result['complete'] or body()!=raw or not identity(attempt,urls):return result
        current=json.loads(path.read_text())
        if (current.get('state') not in ('submitted','submission_started','needs_inspection') or
                current.get('created')!=attempt.get('created')):return result
        if await read() is None:return result
        if (result['streaming'] or not result['complete'] or body()!=raw or snapshot().get('answer_busy') is not False
                or not identity(current,[p.url for p in self.pages.values()])):return result
        final=json.loads(path.read_text())
        if final!=current:return result
        from .shared_page_repair import atomic_text
        result['inspection_stage']='save_response';raw_path=path.parent/'response-raw.txt'
        if raw_path.exists() and raw_path.read_text()!=raw:raise ValueError('原回答已有不同保存物，不覆盖')
        atomic_text(raw_path,raw)
        final.update(state='response_saved',conversation_url=page.url,raw_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            tab_cleanup='preserved_reusable_window',reused_window=True,observed_complete_at=time.time())
        atomic_json(path,final);result['saved']=True;result['collection_state']='saved_from_consistent_snapshots'
        return result

    def _record_login(self,tid,account):
        """Persist the original target's UI proof; never click or clear a gate."""
        from core.api import control__read_record as read_record,control__mutate_record as mutate_record
        path=self.root/'web-channel-control.json';record=read_record(path)
        channel=dict(record.get('chatgpt',{}));targets=dict(channel.get('login_targets',{}))
        evidence=account.get('login_evidence',[])
        if channel.get('manual_verification_required') and targets.get(tid,{}).get('evidence')==evidence:return
        registry=read_record(self.root/'shared-gpt-window.json')
        slot=next((s.get('slot_id') for s in registry.get('slots',[]) if s.get('target_id')==tid),None)
        targets[tid]={'target_id':tid,'slot_id':slot,'observed':time.time(),'evidence':evidence}
        slots=sorted({v['slot_id'] for v in targets.values() if v.get('slot_id')})
        reason='需要手动登录'+('；第'+ '、'.join(slots)+'槽' if slots else '')
        channel.update(manual_verification_required=True,block_kind='login',reason=reason,
                       observed=time.time(),source='resident_dom_login_ui',login_targets=targets)
        mutate_record(path,{'chatgpt':channel},event='observer_login_required')
    async def check(self):
        start=time.monotonic();pages=dict(self.pages);urls=[p.url for p in pages.values()];ledgers={}
        self._check_sequence+=1
        round_id=f'{__import__("os").getpid()}:{self._instance}:{self._check_sequence}'
        window_browser=self.window_browser;window_targets=set(self.window_targets)
        from .attempt_history import index_attempts
        _,latest=await asyncio.to_thread(index_attempts,self.root) if pages or window_targets else ({},{})
        ledgers={tid:(Path(a['_ledger_path']),a) for tid,a in latest.items()}
        from .original_receipt_recovery import collection_ledgers
        try:
            for tid, ledger in collection_ledgers(self.root).items():
                if tid in self.window_targets:ledgers[tid]=ledger
        except (OSError,ValueError,KeyError) as exc:
            # A damaged recovery proof must not skip observations/collection on
            # the other nineteen fixed pages.
            atomic_json(self.root/'original-receipt-recovery-error.json',
                        {'at':time.time(),'error':str(exc)[:500]})
        async def bounded(tid,page):
            began=time.monotonic();record={'target_id':tid,'url':page.url,'checked_at':time.time(),
                'check_started_at':time.time(),'check_id':round_id+':'+tid,'round_id':round_id,'inspection_stage':'start'}
            self._inflight[tid]=record
            try:record.update(await asyncio.wait_for(self.inspect(tid,page,urls,ledgers,False),PAGE_CHECK_TIMEOUT))
            except Exception as exc:inspection_error(record,exc)
            finally:
                record.update(check_finished_at=time.time(),duration_seconds=round(time.monotonic()-began,6))
                self._inflight.pop(tid,None)
            return record
        results,(positions,window_errors)=await asyncio.gather(
            asyncio.gather(*(bounded(tid,p) for tid,p in pages.items())),self.inspect_windows(window_browser,window_targets))
        by_target={result['target_id']:result for result in results}
        for tid,position in positions.items():
            if tid not in by_target:
                by_target[tid]={'target_id':tid,'state':'not_observed'};results.append(by_target[tid])
            by_target[tid].update(position)
        self.last_check=time.time()
        from .account_readiness import recheck
        try:recheck(self.root,results,at=self.last_check)
        except Exception as exc:window_errors.append('账户恢复复查：'+str(exc)[:200])
        report={'updated':self.last_check,'owner_pid':__import__('os').getpid(),'activity_schema_version':1,'interval_seconds':INTERVAL,'page_count':len(pages),'duration_seconds':time.monotonic()-start,'pages':results}
        report.update(observer_schema_version=2,round_id=round_id,loop_lag_seconds=self.loop_lag_seconds)
        self._record_inspection_errors(report,[p for p in results if p.get('state')=='inspection_error'],'page_state')
        if window_browser is not None:report.update(window_schema_version=1,window_target_count=len(window_targets),window_errors=window_errors)
        atomic_json(self.root/'web-page-observer.json',report)
        atomic_json(self.root/'web-upload-network.json',self.network_report())

        # Publish all page states before expensive identity/body/collection reads.
        # A collection deadline cannot erase a successful status observation.
        async def receipt_check(record):
            tid=record['target_id'];ledger=ledgers.get(tid)
            if (tid not in pages or not ledger or record.get('state') not in ('generating','complete')
                    or ledger[1].get('state') not in ('submitted','submission_started','needs_inspection','response_saved')
                    or ledger[1].get('state')=='response_saved' and not record.get('streaming')):return None
            began=time.monotonic();probe=dict(record)
            probe.update(check_id=record['check_id']+':receipt',check_started_at=time.time(),
                         inspection_stage='receipt_identity',stage_seconds={})
            self._inflight[tid]=probe
            try:probe.update(await asyncio.wait_for(self.inspect(tid,pages[tid],urls,ledgers),PAGE_CHECK_TIMEOUT))
            except Exception as exc:inspection_error(probe,exc)
            finally:
                probe.update(check_finished_at=time.time(),duration_seconds=round(time.monotonic()-began,6))
                self._inflight.pop(tid,None)
            record['receipt_check_id']=probe['check_id']
            record['receipt_duration_seconds']=probe['duration_seconds']
            record['receipt_checked_at']=probe['check_finished_at']
            if probe.get('state')=='inspection_error':
                record.update(receipt_state='inspection_error',receipt_failed_stage=probe.get('failed_stage'),
                              receipt_error_type=probe.get('error_type'))
                # A proven identity remains separately timestamped; a timeout
                # before identity proof never creates activity_verified.
                if probe.get('activity_verified'):
                    record.update({k:probe[k] for k in ('activity_verified','kind','identity_checked_at') if k in probe})
                return probe
            for key in ('state','checked_at','streaming','complete','answers','activity_verified','kind',
                        'identity_checked_at','collection_state','saved','login','login_evidence',
                        'login_detection_version','account_reason','error','account_ui_blocked',
                        'account_ready','account_authenticated','authenticated_evidence','composer_available',
                        'send_button_present','send_button_disabled',
                        'upload_indicator_visible'):
                if key in probe:record[key]=probe[key]
            record['receipt_state']='checked'
            return None
        receipt_errors=[p for p in await asyncio.gather(*(receipt_check(p) for p in results)) if p]
        self._record_inspection_errors(report,receipt_errors,'receipt_collection')
        report.update(receipt_checks_completed_at=time.time(),receipt_inspection_errors=len(receipt_errors),
                      status_duration_seconds=report['duration_seconds'],duration_seconds=time.monotonic()-start)
        atomic_json(self.root/'web-page-observer.json',report)

    def _record_inspection_errors(self,report,pages,kind):
        if not pages:return
        try:
            with (self.root/'web-page-observer-errors.jsonl').open('a') as stream:
                for page in pages:
                    failure={k:page.get(k) for k in ('target_id','check_id','round_id','check_started_at',
                        'check_finished_at','checked_at','duration_seconds','stage_seconds','failed_stage',
                        'error_type','last_observed_state')}
                    stream.write(json.dumps({**failure,'owner_pid':report['owner_pid'],'diagnostic_kind':kind},ensure_ascii=False)+'\n')
        except OSError as exc:report['diagnostic_error']=type(exc).__name__

    def network_report(self):
        """Legacy web-upload-network.json shape plus durable attribution."""
        from . import upload_trace
        report=upload_trace.network_projection(self.last_check,targets=self.window_targets)
        ring=list(getattr(self,'_network_events',[]))[-100:]
        report['errors']=ring;report['network_event_count']=len(ring)
        report['attribution_counters']=dict(getattr(self,'_network_counters',{}))
        if getattr(self,'_network_write_error',None):report['durable_write_error']=self._network_write_error
        return report
    async def run(self):
        due=self.loop.time()
        while True:
            self.loop_lag_seconds=round(max(0,self.loop.time()-due),6)
            try:await self.check()
            except asyncio.CancelledError:raise
            except Exception as exc:atomic_json(self.root/'web-page-observer.json',{'updated':time.time(),'owner_pid':__import__('os').getpid(),'activity_schema_version':1,
                'interval_seconds':INTERVAL,'pages':[],'error':str(exc)[:400]})
            due+=self.interval
            if due<self.loop.time():due=self.loop.time()
            await asyncio.sleep(max(0,due-self.loop.time()))
