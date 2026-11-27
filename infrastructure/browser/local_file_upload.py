"""Assign an existing local ZIP without copying its bytes through Playwright.

Only the resident owner's registered local Chrome and exact input are eligible.
The same connection carries small CDP commands; no browser or connection opens.
An uncertain assignment is persisted and never falls back to another writer.
"""
import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit


def _local_browser(root, target):
    from .shared_browser_window import validate_registry
    from .shared_window_owner import check_endpoint
    from .browser_recovery import main_chrome_pid
    registry=json.loads((root/'shared-gpt-window.json').read_text())
    validate_registry(registry);check_endpoint(registry)
    endpoint=urlsplit(registry['endpoint'])
    if (endpoint.scheme!='http' or endpoint.hostname not in ('127.0.0.1','localhost','::1')
            or not endpoint.port or target not in {s['target_id'] for s in registry['slots']}):
        raise ValueError('本机文件赋值仅允许原登记本机Chrome及固定target')
    profile=Path(os.environ.get('WEB_GPT_CHROME_PROFILE',str(Path.home()/'ChromeProfiles/chatgpt_auto'))).resolve()
    if not main_chrome_pid(profile,endpoint.port):
        raise ValueError('本机专用Chrome进程归属未确认，不交付本机文件路径')



def _runtime_object_id(session, marker):
    """Return a CDP object id even when the input lives in a shadow root.

    ``DOM.querySelector`` only walks the light DOM of the document node; a
    review/editor surface may keep its file input in a shadow root.  Runtime
    evaluation in the page's main world can traverse those roots, and
    ``DOM.setFileInputFiles`` accepts the resulting objectId directly.
    """
    from .owner_browser_calls import bounded_call
    expression = """(marker) => {
      const seen = new Set();
      function walk(root) {
        if (!root || seen.has(root)) return null;
        seen.add(root);
        if (root.querySelector) {
          const direct = root.querySelector('input[data-paper-local-upload="' + marker + '"]');
          if (direct) return direct;
        }
        if (root.querySelectorAll) {
          for (const node of root.querySelectorAll('*')) {
            if (node.shadowRoot) {
              const found = walk(node.shadowRoot);
              if (found) return found;
            }
          }
        }
        return null;
      }
      return walk(document);
    }"""
    reply=bounded_call(session,'send','Runtime.evaluate',{
        'expression':f'({expression})({json.dumps(marker)})',
        'returnByValue':False,'awaitPromise':False},timeout=3)
    if not isinstance(reply,dict) or reply.get('exceptionDetails'):
        return None
    result=reply.get('result')
    object_id=result.get('objectId') if isinstance(result,dict) else None
    return object_id if isinstance(object_id,str) and object_id else None

def writer_for(page, context, guard):
    if context.get('local_file_paths') is not True:return None
    def write(locator, filename):
        from . import upload_trace
        from .owner_browser_calls import bounded_call
        root=upload_trace.root()
        if root is None:raise ValueError('原上传证据目录未登记')
        target=context['target_id'];bundle=context['bundle'];path=Path(filename).resolve()
        expected=Path(bundle['zip_path']).resolve()
        def unchanged():
            if (not path.is_file() or path.stat().st_size!=bundle['size'] or
                    hashlib.sha256(path.read_bytes()).hexdigest()!=bundle['zip_sha256']):
                raise ValueError('本机上传ZIP指纹变化，保留原材料')
        if path != expected:
            # The upload kernel may repack the same frozen inputs into its own
            # ZIP path.  Accept that path only when the complete bytes match;
            # never trust a merely similar filename.
            unchanged()
        unchanged();guard();_local_browser(root,target)
        session=None;marker=uuid.uuid4().hex;marked=False
        diagnostic=context['upload_diagnostic']
        def event(state):
            diagnostic.update(attachment_write_transport='local_cdp_path',local_file_write_state=state)
            upload_trace.append({'kind':'attachment_write','event':'attachment_write',
                **upload_trace.identity_fields(context),**upload_trace.owner_identity(),
                'at':time.time(),'transport':'local_cdp_path','state':state})
            callback=context.get('on_identified')
            if callback:callback(context['upload_attempt_id'],diagnostic)
        try:
            session=bounded_call(page.context,'new_cdp_session',page)
            info=bounded_call(session,'send','Target.getTargetInfo')
            if info['targetInfo']['targetId']!=target:raise ValueError('文件控件原target归属变化')
            locator.evaluate("(el,marker)=>{if(el.tagName!=='INPUT'||el.type!=='file'||el.disabled)throw Error('file input unavailable');el.setAttribute('data-paper-local-upload',marker)}",marker,timeout=3000)
            marked=True
            object_id=None
            try:object_id=_runtime_object_id(session,marker)
            except Exception:object_id=None
            node_id=None
            if object_id is None:
                document=bounded_call(session,'send','DOM.getDocument',{'depth':0})
                node=bounded_call(session,'send','DOM.querySelector',{'nodeId':document['root']['nodeId'],
                    'selector':'input[data-paper-local-upload="'+marker+'"]'})
                node_id=node.get('nodeId') if isinstance(node,dict) else None
            if not object_id and not node_id:
                # No assignment has happened yet.  Playwright can resolve the
                # exact locator (including iframes) and uses a local path; keep
                # this only as a bounded fallback, never after an uncertain CDP
                # write.
                diagnostic.update(attachment_write_transport='playwright_local_path_fallback',
                                  local_file_write_node='locator')
                unchanged();guard();event('intent')
                try:locator.set_input_files(str(path))
                except Exception:
                    event('unknown');raise
                event('written');return
            unchanged();guard();event('intent')
            try:
                diagnostic.update(local_file_write_node='objectId' if object_id else 'nodeId')
                params={'files':[str(path)]}
                if object_id:params['objectId']=object_id
                else:params['nodeId']=node_id
                bounded_call(session,'send','DOM.setFileInputFiles',params,timeout=5)
            except Exception:
                event('unknown');raise
            event('written')
        finally:
            if marked:
                try:locator.evaluate("(el,marker)=>{if(el.getAttribute('data-paper-local-upload')===marker)el.removeAttribute('data-paper-local-upload')}",marker,timeout=3000)
                except Exception:pass
            if session is not None:
                try:bounded_call(session,'detach')
                except Exception:pass
    return write
