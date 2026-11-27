"""Formula window display, based on the registered owner's timestamped observations."""
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from .page_grid import _read

FRESH_SECONDS = 60


def load_description(page):
    load = page.get('page_load') or {}
    if not load:
        return ''
    if load.get('browser_error'):
        return '浏览器加载失败' + (' · '+load['error_code'] if load.get('error_code') else '')
    if load.get('ready_state') == 'loading':
        return '网页加载中'
    if load.get('ready_state') in ('interactive','complete') and page.get('composer_available') is False:
        return '未检测到输入框'
    if load.get('was_discarded'):
        return '此页曾被 Chrome 回收后重载'
    return ''


def effort_description(page):
    control = page.get('effort_control') or {}
    value = control.get('effort')
    labels = {'high':'High','medium':'中','low':'低','minimal':'最低','none':'即时','xhigh':'极高'}
    if value in labels:
        return '当前强度 · '+labels[value]
    return '强度未确认'


def page_state(page, receipt_state):
    for flag, label in (('login','需登录'), ('verification','需验证'), ('quota','额度受限'),
                        ('errors','网页报错'), ('uploading','上传中'), ('streaming','生成中')):
        if page.get(flag):
            return label
    if receipt_state == 'blocked_before_send':
        return '发送前受阻'
    if receipt_state == 'left_archived_chat':
        return '已离开原会话'
    if receipt_state == 'raw_saved':
        return '回答已保存'
    if page.get('terminal_stopped'):
        return '生成已停止'
    if page.get('terminal_complete') and not page.get('has_answer'):
        return '空回答'
    if receipt_state == 'submitted':
        return '待收回答'
    if page.get('has_draft') or page.get('has_attachments'):
        return '有草稿或附件'
    if page.get('pool_state') in ('opening','ready_blank') and page.get('account_ready') and not (
            page.get('has_users') or page.get('answer_element_count')) and page.get('url') in (
            'https://chatgpt.com/','https://chatgpt.com/?temporary-chat=true'):
        return '空闲'
    return '待核对'


def window_cells(data, output, status, running, now=None):
    now = time.time() if now is None else now
    registry = _read(data/'shared-gpt-window.json')
    observation = _read(output/'window-observation.json')
    slots = {s['slot_id']:s.get('target_id') for s in registry.get('slots',[]) if isinstance(s,dict) and 'slot_id' in s}
    same_owner = (running and observation.get('pid') == status.get('pid') and
                  observation.get('window_id') == registry.get('window_id'))
    cells = []
    for number in range(1,21):
        slot = f'{number:02d}'
        tid = slots.get(slot)
        page = observation.get('pages',{}).get(tid,{})
        stamp = page.get('checked_at') or 0
        fresh = same_owner and page.get('inspection_complete') and 0 <= now-stamp <= FRESH_SECONDS
        label = '待观测' if tid else '未登记'
        warning = False
        batch = None
        previous = ''
        if tid and same_owner and page.get('inspection_complete') and stamp:
            health = page.get('image_health') or {}
            warning = bool(health.get('image_notice') or health.get('broken_images'))
            job = page.get('job') or ''
            match = re.fullmatch(r'formula-display-(\d+)',job)
            receipt_state = None
            if match:
                candidate = int(match[1])
                folder = output/'batches'/f'{candidate:06d}'
                receipt = _read(folder/'attempt.json')
                if (receipt.get('job_id') == job and receipt.get('window_target') == tid and
                        receipt.get('url') and receipt['url'] == page.get('url')):
                    batch = candidate
                    receipt_state = receipt.get('state')
                elif (receipt.get('job_id')==job and receipt.get('window_target')==tid and
                      receipt.get('state')=='upload_preparation' and page.get('pool_state')=='busy' and
                      _read(folder/'status.json').get('state')=='blocked'):
                    batch, receipt_state = candidate,'blocked_before_send'
                elif (receipt.get('state')=='raw_saved' and receipt.get('job_id')==job and
                      receipt.get('window_target')==tid and page.get('pool_state')=='ready' and
                      receipt.get('url') and page.get('url') in ('https://chatgpt.com/','https://chatgpt.com/?temporary-chat=true')
                      and not any(page.get(k) for k in ('has_draft','has_attachments','has_users','has_answer'))):
                    batch, receipt_state = candidate,'left_archived_chat'
            label = page_state(page,receipt_state)
            if not fresh:
                previous = label + (' · 图片异常' if warning else '')
                label, warning, batch = '待观测', False, None
        current = next((event for event in status.get('workers',[]) if event.get('target') == tid),status)
        if (fresh and current in status.get('workers',[]) and current.get('target')==tid and
                label in ('上传中','生成中') and page.get('job')==f"formula-display-{current.get('batch')}"):
            batch = current['batch']
        event_time = current.get('time') or 0
        if (same_owner and tid and tid == current.get('target') and event_time <= now
                and (stamp <= event_time or current in status.get('workers',[]))
                and now-event_time <= FRESH_SECONDS
                and label in ('空闲','回答已保存','待核对','待收回答','有草稿或附件','待观测')):
            event = {'checking_model':'核对模型','temporary_ui':'核对模型','uploading':'准备上传',
                     'collecting':'收取中'}.get(current.get('state'))
            if event:
                if batch != current.get('batch'):
                    warning = False
                batch, label = current.get('batch'), event
        checked = datetime.fromtimestamp(stamp,ZoneInfo('Asia/Shanghai')).strftime('%H:%M:%S') if stamp else ''
        cells.append(dict(id=slot,state=label,imageWarning=warning,checked=checked,batch=batch,previous=previous,pageLoad=load_description(page) if fresh else '',
                          effort=effort_description(page) if fresh else '强度待观测'))
    return cells
