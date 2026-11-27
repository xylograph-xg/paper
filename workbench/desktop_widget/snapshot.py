"""Read-only shared project status; fetch and web cards are permanent categories."""
from core.api import paths__workspace_root as _workspace_root
import json
import os
import sys
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from zoneinfo import ZoneInfo
from core.api import paths__WorkspacePath as Path
from urllib.parse import quote
ROOT=_workspace_root()
sys.path.insert(0,str(ROOT))


def read(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {}


def alive(pid):
    if type(pid) is not int or pid<=0:return False
    try:os.kill(pid,0);return True
    except PermissionError:return True
    except OSError:return False


def projects(root):
    config_path = Path(root) / 'config/task_panel_projects.json'
    configured = read(config_path).get('projects')
    if configured:
        entries = [dict(p, root=str((config_path.parent / p['root']).resolve())) for p in configured]
        return [p for p in entries if Path(p['root']).is_dir()]
    return [{'name':'paper','root':str(root),'adapter':'paper'}]


def command_files(root):
    root=Path(root).resolve();commands=[]
    retired={'启动任务面板.command','read/配置阅读环境.command','read/启动资料卡.command','article/run.command','运行卡片评审.command'}
    for directory,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not d.startswith('.') and d not in {'data','studies','history','build','node_modules','__pycache__','venv','dist','workflow_versions','vendor','archive','archives','backups','environments','dependencies','cache'} and not (Path(directory)/d).is_symlink())
        for name in sorted(files):
            path=Path(directory)/name;relative=str(path.relative_to(root))
            if name.endswith('.command') and name!='启动任务面板.command' and relative not in retired and not path.is_symlink() and path.is_file():
                commands.append(dict(id=str(path),name=path.stem,path=str(path),relativePath=relative))
    return sorted(commands,key=lambda c:(c['relativePath']=='article/open_gpt.command',c['relativePath']))


def upload_issue(error):
    text=str(error).lower()
    if any(x in text for x in ('附件','上传','文件','attachment','upload','file')) and any(x in text for x in ('数量限制','数量上限','上传上限','上传限制','达到上限','超过上限','too many','upload limit','file limit','limit reached','maximum number','upload quota')):return '附件额度受限，自动切换备用网页通道'
    if '附件上传失败' in text or 'upload failed' in text:return '附件上传失败，待确认原因'
    return ''


def row(id,group,label,title,state,detail='',**kw):
    value=dict(id=str(id),group=group,label=label,title=title,state=state,detail=detail,issue='',icon='doc.text',elapsed=None,progress=None,resultPath=None,endedAt=None)
    value.update(kw);return value


def db_rows(path,sql):
    if not Path(path).is_file():return []
    try:
        with closing(sqlite3.connect('file:'+quote(str(Path(path).resolve()))+'?mode=ro',uri=True,timeout=.3)) as db:
            db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute(sql)]
    except (OSError,sqlite3.Error):return []


def app_formula_row(data, control, output):
    import http.client
    from desktop_widget.app_windows import app_windows
    conn = http.client.HTTPConnection('127.0.0.1',17841,timeout=.6)
    active_turns = None
    online = False
    try:
        conn.request('GET','/healthz')
        response = conn.getresponse()
        h = json.loads(response.read(65537))
        online = response.status==200 and h.get('status')=='ok' and h.get('mode')=='full' and h.get('accepting_turns') is True
        if online and type(h.get('active_browser_turns')) is int:
            active_turns = h['active_browser_turns']
    except (OSError,ValueError,AttributeError,http.client.HTTPException):
        pass
    finally:
        conn.close()
    enabled = control.get('enabled') is True
    receipt = read(output/'app-status.json')
    counts = {r['state']:r['n'] for r in db_rows(output/'queue.sqlite3',
              'select state,count(*) as n from batches group by state')}
    waiting = counts.get('app_queued',0)+counts.get('app_prepared',0)
    owner = alive(receipt.get('pid'))
    current = receipt.get('batch') if owner else None
    stage = receipt.get('state')
    names = {'dispatching':'处理批次','preparing':'准备图页','waiting_channel':'等待通道','waiting_app':'等待 App','finished':'队列已处理'}
    state = ('已暂停' if not enabled else 'App 未就绪' if not online
             else names.get(stage,'等待派发') if owner else '等待后台接续')
    detail = (f"仅行间公式 · GPT-6 Pro → 6.2 Extra High → High · App 待处理 {waiting} 批 · 已归档 {counts.get('done',0)} 批"
              f" · 待核对 {counts.get('review',0)+counts.get('held',0)} 批")
    if counts.get('queued'):
        detail += f" · 原队列保留 {counts['queued']} 批"
    if owner and receipt.get('batches'):
        detail += ' · 处理批号 '+ '、'.join(map(str,receipt['batches']))
    elif current:
        detail += f" · 当前第 {current} 批"
    if enabled and owner and stage in ('waiting_channel','waiting_app') and receipt.get('reason'):
        detail += ' · '+str(receipt['reason'])[:120]
    return row(data/'formula-only-control.json','paper · 公式整理','Codex Web GPT','公式整理',state,detail,
               formulaApp=True,formulaAppOnline=online,formulaAppTurns=active_turns,formulaEnabled=enabled,
               formulaAppWindows=app_windows(),
               formulaRetry=enabled and not owner,resultPath=str(output))


def formula_pilot_row(data):
    control = read(data / 'formula-only-control.json')
    if control.get('mode') == 'temporary_queue':
        display = control.get('extraction') == 'display-pages-v1'
        output = Path(control['folder'])/('display-equations' if display else 'automatic')
        if control.get('transport') == 'codex_web_gpt':
            return app_formula_row(data,control,output)
        status = read(output/'status.json')
        counts = status.get('counts', {})
        running = alive(status.get('pid'))
        enabled = control.get('enabled') is True
        names = {'waiting_attachment':'等待附件入口恢复','waiting_slot':'等待可用窗口','waiting_channel':'等待通道恢复','dispatching':'多页分发','finished':'排队处理结束','blocked':'受阻','collecting':'收取原回答','awaiting_answer':'等待原页回答','uploading':'上传中',
                 'preparing':'准备批次','checking_model':'核对模型','checking_account':'核对账户','waiting_browser':'等待专用浏览器'}
        stage = status.get('state')
        state = '已暂停' if not enabled else names.get(stage,'运行中') if running or stage in ('finished','blocked') else '待启动'
        detail = (f"GPT-6.2 High · 临时聊天 · 待排 {counts.get('queued',0)} 批 · 已收取 {counts.get('done',0)} 批"
                  f" · 待核对 {counts.get('review',0)+counts.get('held',0)} 批")
        if stage=='waiting_attachment' and 'eligible_slots' in status:
            probe = status.get('attachment_probe') or {}
            reasons = {'no_clean_slot':'没有可检查的干净窗口','no_document_input':'未见 ZIP 上传入口',
                       'document_input':'已见 ZIP 上传入口','disabled':'网页上传选项置灰',
                       'inspection_error':'本次未能读取网页'}
            detail += f" · 可候选窗口 {status['eligible_slots']} 个"
            if probe.get('reason'):
                detail += ' · ' + reasons.get(probe['reason'],'网页显示限制')
            if status.get('next_check') and status.get('attachment_mode')=='cooldown':
                detail += ' · 下次检查 ' + datetime.fromtimestamp(status['next_check'],ZoneInfo('Asia/Shanghai')).strftime('%H:%M')
        if counts.get('awaiting_answer'):
            detail += f" · 已发待收 {counts['awaiting_answer']} 批"
        if display:
            detail = '仅行间公式 · ' + detail
        if status.get('parallel_limit'):
            detail += f" · 并行处理 {len(status.get('workers',[]))}/{status['parallel_limit']} 批"
        if status.get('batch'):
            detail += f" · 当前第 {status['batch']} 批"
        from desktop_widget.formula_window import window_cells
        cells = window_cells(data,output,status,running) if display else None
        reason = status.get('reason','').splitlines()
        account_gate = read(data/'web-channel-control.json').get('chatgpt',{})
        if cells and enabled and running and account_gate.get('manual_verification_required'):
            login = '、'.join(c['id'] for c in cells if c['state']=='需登录')
            verification = '、'.join(c['id'] for c in cells if c['state']=='需验证')
            actions = ([f'{login} 号页需登录'] if login else []) + ([f'{verification} 号页需验证'] if verification else [])
            state = '等待登录或验证' if actions else '等待账户复核'
            if not actions:
                proof = read(data/'account-recovery.json')
                if (proof.get('owner_pid')==status.get('pid') and proof.get('state')=='blocked'
                        and 0<=time.time()-proof.get('checked_at',0)<=60):
                    waiting = set(proof.get('waiting_targets',[]))
                    registry = read(data/'shared-gpt-window.json')
                    ids = {s.get('slot_id') for s in registry.get('slots',[]) if s.get('target_id') in waiting}
                    for signal in ('网页加载中','未检测到输入框'):
                        affected = '、'.join(c['id'] for c in cells if c['id'] in ids and c.get('pageLoad')==signal)
                        if affected:
                            actions.append(f'{affected} 号页{signal}')
            reason = ['新派发已暂停 · '+('，'.join(actions) if actions else '正在复核专窗账户状态')]
        if reason:
            detail += ' · ' + reason[0]
        return row(data/'formula-only-control.json','paper · 公式整理','自动队列','公式整理',state,detail,
                   formulaSlots=cells,formulaEnabled=enabled,formulaRetry=enabled and not running and stage!='finished',resultPath=str(output))
    if control.get('mode') != 'temporary_pilot' or not control.get('pilot_folder'):
        return None
    folder = Path(control['pilot_folder'])
    status = read(folder / 'status.json')
    stage = status.get('state')
    enabled = control.get('enabled') is True
    attempt = folder / 'attempt.json'
    result = folder / 'formulas.jsonl'
    detail = f"临时聊天 · 两篇文献测试 · {control.get('model', '')} {control.get('effort', '')}"
    retry = False
    if stage == 'collected' and result.is_file():
        state = '已完成'
        detail += f" · 已保存 {status.get('count', 0)} 条公式"
    elif not enabled:
        state = '已暂停'
    elif stage == 'blocked':
        state = '受阻'
        reason = status.get('reason', '').splitlines()
        detail += ' · ' + ('专用浏览器连接失败' if reason and 'connect_over_cdp' in reason[0]
                            else reason[0] if reason else '请查看状态记录')
        retry = True
    elif stage in ('starting', 'waiting_browser', 'checking_account', 'checking_model', 'temporary_ui', 'uploading', 'collecting') and alive(status.get('pid')):
        state = {'starting': '启动中', 'waiting_browser': '等待专用浏览器', 'checking_account': '核对账户', 'checking_model': '核对模型', 'temporary_ui': '运行中',
                 'uploading': '上传测试包', 'collecting': '等待网页回答'}[stage]
    else:
        state = '待启动'
        retry = True
    receipt = read(attempt)
    collect_only = (receipt.get('state') in ('send_intent', 'submitted', 'raw_saved')
                    and receipt.get('zip_sha256') == control.get('pilot_zip_sha256') and receipt.get('temporary') is True)
    if retry and attempt.exists():
        detail += ' · 重试将收取原回答' if collect_only else ' · 原操作回执待核对'
    return row(data / 'formula-only-control.json', 'paper · 公式整理', '网页版测试',
               '公式整理', state, detail, formulaEnabled=enabled,
               formulaRetry=retry and (not attempt.exists() or collect_only) and not result.exists(),
               resultPath=str(result if result.is_file() else folder / 'status.json'))


def paper_rows(root,rows,ended,warnings):
    root=Path(root);config=read(root/'config/first_round.json')
    config.setdefault('catalog_path',str(root/'data/catalog.sqlite3'))
    data=Path(config['catalog_path']).parent
    formula = formula_pilot_row(data)
    if formula:
        rows.append(formula)
    from core.api import seed_focus__status as seed_status
    tracking=seed_status(config)
    trace_error=read(data/'seed-tracking-error.json')
    if trace_error.get('at',0)>tracking.get('checked_at',0):warnings.append('手选追踪检查失败，原追踪保留：'+trace_error.get('error','待核对'))
    for seed in tracking.get('items',[]):
        hours=seed.get('stalled_seconds',0)/3600
        state='成品卡完成' if seed.get('complete') else '停滞超过3小时' if seed.get('stalled') else seed.get('phase','等待核对')
        rows.append(row('seed-trace-'+seed['paper_id'],'paper · 手选追踪','全程追踪',seed['title'],state,
            f"{seed.get('phase','待核对')} · 已核验候选 {seed.get('progress',{}).get('reviewed',0)}/3 · 距上次进展 {hours:.1f}h",
            issue=seed.get('error',''),elapsed=int(seed.get('stalled_seconds',0)),resultPath=seed.get('evidence_manifest')))
    from literature.api import level1_status
    first=level1_status(config)
    if first['registered']:
        names={'running':'运行中','waiting':'等待新增或更新','paused':'已暂停','stopped':'已停止','error':'检查失败','awaiting_validation':'等待新版验收','starting':'启动中'}
        detail=(f"已检查 {first.get('completed',0)}/{first.get('total',0)} · 有核心标签 {first.get('matched',0)}"
                f" · 无法判断 {first.get('undetermined',0)} · 待处理 {first.get('queued',0)} · 失败 {first.get('failed',0)}"
                f" · 并行上限 {first['parallel']} / 当前 {first['actual_parallel']}")
        if first.get('last_finished_at'):
            detail+=' · 上次结束 '+datetime.fromisoformat(first['last_finished_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H.%M.%S')
        rows.append(row(data/'literature-level1-service.json','paper · 一级标签','常驻服务','全库标题摘要自动标注',
                        names.get(first['state'],first['state']),detail,issue=first.get('error',''),
                        actualParallel=first['actual_parallel'],actualParallelConfirmed=first['alive'],
                        progress=first.get('completed',0)/first['total'] if first.get('total') else None,
                        resultPath=str(data/'literature-level1-log.log')))
    from literature.api import level2_status
    first=level2_status(config)
    if first['registered']:
        names={'running':'运行中','waiting':'等待新增或更新','paused':'已暂停','stopped':'已停止','error':'检查失败','awaiting_validation':'等待新版验收','starting':'启动中'}
        detail=(f"已检查 {first.get('completed',0)}/{first.get('total',0)} · 有核心标签 {first.get('matched',0)}"
                f" · 无法判断 {first.get('undetermined',0)} · 待处理 {first.get('queued',0)} · 失败 {first.get('failed',0)}"
                f" · 等待原文 {first.get('awaiting_original',0)} · 来源阻断 {first.get('blocked',0)}"
                f" · 并行上限 {first['parallel']} / 当前 {first['actual_parallel']}")
        if first.get('last_finished_at'):
            detail+=' · 上次结束 '+datetime.fromisoformat(first['last_finished_at']).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H.%M.%S')
        rows.append(row(data/'literature-level2-service.json','paper · 二级标签','常驻服务','全库原文二级自动候选',
                        names.get(first['state'],first['state']),detail,issue=first.get('error',''),
                        actualParallel=first['actual_parallel'],actualParallelConfirmed=first['alive'],
                        progress=first.get('completed',0)/first['total'] if first.get('total') else None,
                        resultPath=str(data/'literature-level2-log.log')))
    from core.api import concurrency_control__settings as settings
    limits=settings(config)
    fetch=read(data/'fetch-service.json');paused=read(data/'fetch-control.json').get('paused_by_user',False) or tracking.get('enabled',False)
    live=alive(fetch.get('pid')) and time.time()-fetch.get('updated',0)<30 and fetch.get('state')=='running'
    counts=db_rows(data/'catalog.sqlite3',"SELECT count(*) total,sum(acquisition='available') available FROM papers")
    from core.api import continuous_status__status as continuous_status
    progress=continuous_status(data/'catalog.sqlite3')
    detail=f"{progress['downloaded']}/{progress['total']} · 下载中 {progress['active_fetch']} · 候选重试 {progress['pending']} · 阻止下载 {progress.get('blocked',0)}"
    def clock(value):
        try:return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%m-%d %H.%M.%S')
        except (TypeError,ValueError):return '未记录'
    fetch_times=db_rows(data/'catalog.sqlite3',"SELECT t.*,j.paper_id,j.kind,j.state,p.title FROM fetch_attempt_times t JOIN jobs j ON j.id=t.job_id LEFT JOIN papers p ON p.id=j.paper_id WHERE t.ended_at IS NOT NULL ORDER BY t.ended_at DESC LIMIT 20")
    if fetch_times:detail+=f" · 上次结束 {clock(fetch_times[0]['ended_at'])}"
    else:detail+=' · 上一篇结束：未记录'
    fetch_log=data/'logs/local.paper.fetch.log'
    rows.append(row(data/'fetch-service.json','paper · 拉取','常驻服务','文献发现与原文拉取','已暂停' if paused else '运行中' if live else '已停止',detail,concurrencyTarget='fetch',concurrencyValue=limits['fetch'],actualParallel=progress['active_fetch'] if live else None,actualParallelConfirmed=live,resultPath=str(fetch_log if fetch_log.exists() else data/'logs/fetch-service.log')))
    service=read(data/'web-card-service.json');active=alive(service.get('pid')) and service.get('state') not in ('stopped','stopping')
    control=read(data/'web-card-control.json');policy=config.get('web_cards',{});selection=service.get('selection',{})
    selected=read(data/'web-provider-selection.json')
    channel='仅GPT网页版' if selected.get('allowed_providers')==['chatgpt'] else 'GPT优先 / Qwen固定单窗口备用' if selected.get('reuse_qwen_window') else selected.get('provider') or 'GPT/Qwen'
    from browser.api import shared_workflow_activity__project as project
    activity=project(service,owner_live=active,observer=read(data/'web-page-observer.json'))
    actual=activity['actual_parallel'] or {}
    def actual_text(lane):return str(actual[lane]) if activity['actual_parallel_confirmed'] else '待观测'
    card_jobs=db_rows(data/'catalog.sqlite3',"SELECT state,count(*) count FROM web_card_jobs WHERE json_extract(selection,'$.rework.correction_id') IS NULL AND json_extract(selection,'$.rework.kind') IS NOT 'source_review' GROUP BY state")
    card_counts={r['state']:r['count'] for r in card_jobs}
    detail=f"卡片 {progress['cards']} · 实际并行 {actual_text('cards')} · 排队 {card_counts.get('queued',0)} · 原会话待核对 {card_counts.get('needs_inspection',0)} · 失败 {card_counts.get('failed',0)} · 上次结束 {clock(progress['last_card_completed'])}"
    check=read(data/'web-tab-check.json')
    if check and time.time()-check.get('updated',0)<120:
        detail+=f" · {'专用窗口' if check.get('shared_window') else '网页'} {check.get('total_pages',sum(check.get('counts',{}).values()))}/20"
        if check.get('over_limit'):warnings.append('网页数超过上限：'+', '.join(check['over_limit'])+'；保留其他项目及未收取页面，等待收取释放')
        if check.get('errors'):warnings.append('网页数量检查异常：'+check['errors'][0][:180])
    if check and time.time()-check.get('updated',0)<120 and check.get('total_pages')==0 and not service.get('workers'):service['state']='waiting_browser'
    web_log=data/'logs/local.paper.web-cards.log'
    providers=read(data/'web-provider-control.json')
    card_state='已暂停' if control.get('paused_by_user') else ({'waiting_browser':'等待浏览器','waiting_storage':'等待SSD','waiting_page_inspection':'等待页面核对'}.get(service.get('state'),'运行中')) if active else '已停止'
    card_issue=''
    gpt_limit=providers.get('chatgpt',{})
    if active and not control.get('paused_by_user') and gpt_limit.get('reason')=='quota' and gpt_limit.get('blocked_until',0)>time.time():
        card_state='等待附件额度恢复';card_issue='GPT附件额度受限'
    rows.append(row(data/'web-card-service.json','paper · 制卡','常驻服务','自动精选与网页制卡',card_state,detail,issue=card_issue,concurrencyTarget='cards',concurrencyValue=limits['cards'],reservedPages=limits['cards_min_pages'],actualParallel=actual.get('cards'),actualParallelConfirmed=activity['actual_parallel_confirmed'],resultPath=str(web_log if web_log.exists() else data/'logs/web-card-service.log')))
    from cards.api import seed_trials__status as seed_trial_status
    for trial in seed_trial_status(config):
        labels={'waiting':'等待原任务结束','reset_pending':'准备独立制卡','generating':'独立制卡中',
            'blocked':'流程阻塞','reviewing':'独立核验中','reviewed':'等待下一版','selecting':'三版择优中','selected':'已选最高通过版','repairing':'择优后继续修正'}
        scores=' / '.join(str(value) if value is not None else '未完成' for value in trial.get('scores',[]))
        rows.append(row('seed-trials-'+trial['paper_id'],'paper · 制卡','手选种子三版优选',trial.get('title',trial['paper_id']),
            labels.get(trial['state'],trial['state']),f"已核验 {trial['reviewed']}/3 · 本轮 {trial['round']}/3"+(f" · 真实核验分 {scores}" if scores else ''),resultPath=trial.get('result_path')))
    if config.get('card_review',{}).get('enabled'):
        from review.api import card_review_queue__status as review_status
        review=review_status(config);rc=review['counts']
        detail=f"实际并行 {actual_text('review')} · 排队 {rc.get('queued',0)+rc.get('preparing',0)+rc.get('ready',0)} · 完整核验通过 {rc.get('passed',0)} · 阻塞 {rc.get('needs_user',0)} · 上次结束 {clock(review.get('last_finished_at'))}"
        review_state='运行中' if review['enabled'] and active else '已暂停' if not review['enabled'] else '等待制卡后台'
        review_issue=''
        if active and review['enabled'] and gpt_limit.get('reason')=='quota' and gpt_limit.get('blocked_until',0)>time.time():
            review_state='等待附件额度恢复';review_issue='GPT附件额度受限'
        rows.append(row(data/'card_reviews','paper · 核验','常驻服务','原文科学核验',review_state,detail,issue=review_issue,concurrencyTarget='review',concurrencyValue=limits['review'],reservedPages=limits['review_min_pages'],actualParallel=actual.get('review'),actualParallelConfirmed=activity['actual_parallel_confirmed'],resultPath=str(data/'card_reviews')))
        for j in review['jobs']:
            labels={'queued':'排队中','preparing':'准备核对','ready':'等待核对页面','submitted':'核对中','passed':'原文核对通过','corrected':'等待新版核验','correction_queued':'已交修正队列','rework_queued':'已交修正队列','needs_user':'流程阻塞','response_saved':'核对报告已收取','applying':'核对结果处理中','trial_reviewed':'三版候选已核验'}
            item=row('card-review-'+j['id'],'paper · 核验','原文核验',('手选优先 · ' if j.get('seed_fast_lane') else '置顶 · ' if j.get('passed_correction_priority') else '')+j['title'],labels.get(j['state'],j['state']),f"文献质量 {j['priority'] if j['priority'] is not None else '信息不足'} · 核验 {str(j['review_score'])+'/100' if j['review_score'] is not None else '待评分'}",resultPath=str(data/'card_reviews'/j['paper_id']/j['id']))
            (ended if j['state'] in ('passed','corrected','correction_queued','rework_queued','needs_user','failed','superseded','trial_reviewed') else rows).append(item)
    if config.get('card_correction',{}).get('enabled'):
        from correction.api import card_correction_queue__status as correction_status
        correction=correction_status(config);cc=correction['counts']
        detail=f"实际并行 {actual_text('correction')} · 排队 {cc.get('queued',0)+cc.get('preparing',0)+cc.get('ready',0)} · 修正已应用 {cc.get('applied',0)} · 阻塞 {cc.get('needs_user',0)} · 上次结束 {clock(correction.get('last_finished_at'))}"
        correction_state='运行中' if correction['enabled'] and active else '已暂停' if not correction['enabled'] else '等待共享后台'
        if active and correction['enabled'] and correction.get('page_pending',0) and gpt_limit.get('reason')=='quota' and gpt_limit.get('blocked_until',0)>time.time():correction_state='等待附件额度恢复'
        rows.append(row(data/'card_corrections','paper · 修正','常驻服务','核验后独立修正',correction_state,detail,concurrencyTarget='correction',concurrencyValue=limits['correction'],reservedPages=limits['correction_min_pages'],actualParallel=actual.get('correction'),actualParallelConfirmed=activity['actual_parallel_confirmed'],resultPath=str(data/'card_corrections')))
        labels={'queued':'排队中','preparing':'准备修正','ready':'等待共享网页','submitted':'修正中','applied':'已修正 / 等待新版核验','needs_user':'流程阻塞','failed':'失败','superseded':'版本已变化'}
        for j in correction['jobs']:
            item=row('card-correction-'+j['id'],'paper · 修正',{'formatting':'排版','quote_location':'引文定位','source_rework':'原文重做'}.get(j['kind'],j['kind']),('手选优先 · ' if j.get('seed_fast_lane') else '置顶 · ' if j.get('passed_correction_priority') else '')+j['title'],labels.get(j['state'],j['state']),j.get('error',''),resultPath=j.get('folder'))
            (ended if j['state'] in ('applied','needs_user','failed','superseded') else rows).append(item)
    allowed=selected.get('allowed_providers') or ['chatgpt','qwen']
    for provider,control in read(data/'web-channel-control.json').items():
        if provider not in allowed:continue
        if control.get('manual_verification_required'):
            if control.get('block_kind')=='login':
                warnings.append(f"{provider} {control.get('reason') or '需要手动登录'}；已暂停新提交，保留原页面")
            else:warnings.append(f'{provider} 需要手动访问验证；已暂停新提交，保留验证页面')
    selected=read(data/'web-provider-selection.json')
    if selected.get('state')=='login_required':warnings.append(f"当前选择 {selected.get('provider')}：请先在专用浏览器登录，附件与完整收取尚待验证")
    for provider,status in providers.items():
        if provider not in allowed:continue
        if status.get('blocked_until',0)>time.time():
            minutes=int((status['blocked_until']-time.time()+59)//60)
            reset=datetime.fromtimestamp(status['blocked_until'],ZoneInfo('Asia/Shanghai')).strftime('%m月%d日 %H:%M')
            from core.api import control__explicit_reset as explicit_reset
            timing=f"网页提示 {reset} 恢复，约{minutes}分钟" if explicit_reset(status) else f"{minutes}分钟后探测恢复"
            if allowed==['chatgpt']:
                warnings.append('GPT额度受限' if status.get('reason')=='quota' else 'GPT网络不可用');continue
            warnings.append(f"{provider} {'附件/用量受限' if status.get('reason')=='quota' else '网络暂不可用'} · {timing} · {'等待GPT恢复，不切换通道' if allowed==['chatgpt'] else '当前转备用网页'}")
    jobs=db_rows(data/'catalog.sqlite3','SELECT * FROM web_card_jobs ORDER BY updated DESC')
    from core.api import workflow_priority__sort as sort_articles, workflow_priority__enabled as score_order
    if score_order(config) and (data/'catalog.sqlite3').is_file():
        with closing(sqlite3.connect((data/'catalog.sqlite3').resolve().as_uri()+'?mode=ro',uri=True,timeout=.3)) as db:
            db.row_factory=sqlite3.Row
            jobs=sort_articles(db,jobs,config)
    labels={'queued':'排队中','preparing':'准备材料','submitting':'运行中','submitted':'已提交 / 等待原会话','collecting':'收取中','completed':'制卡完成','protected':'已保留','needs_inspection':'需处理','failed':'失败'}
    shown=0
    for j in jobs:
        if json.loads(j.get('selection') or '{}').get('rework',{}).get('correction_id') or json.loads(j.get('selection') or '{}').get('rework',{}).get('kind')=='source_review':continue
        terminal=j['state'] in ('completed','protected','failed')
        if terminal and sum(r['group']=='paper · 制卡' for r in ended)>=30:continue
        if not terminal and shown>=100:continue
        if not terminal:shown+=1
        label=labels.get(j['state'],j['state'])
        if active and service.get('workers')==0 and not service.get('pool_busy') and j['state']=='preparing':label='等待恢复 / 无活动生成'
        if not active and j['state'] in ('preparing','submitting','submitted','collecting'):label='已停止 / 待核对'
        if j['state'] in ('preparing','submitting','submitted','collecting') and '已达20页' in (j.get('error') or ''):
            j['error']='正在重试；此前网页容量等待提示已过期，以当前页数为准'
        item=row('web-card-'+j['paper_id'],'paper · 制卡',j.get('provider') or selected.get('provider') or 'GPT优先',j['title'],label,'待核对' if j.get('error') else '',resultPath=j.get('folder'),endedAt=j.get('updated'))
        (ended if terminal else rows).append(item)
    for j in db_rows(data/'catalog.sqlite3',"SELECT j.*,p.title FROM jobs j LEFT JOIN papers p ON p.id=j.paper_id WHERE j.kind IN ('discover','acquire','acquire_fallback','import') AND j.state IN ('running','waiting_storage') ORDER BY j.updated DESC LIMIT 30"):
        starts=db_rows(data/'catalog.sqlite3',"SELECT started_at FROM fetch_attempt_times WHERE job_id='"+j['id'].replace("'","''")+"' ORDER BY attempt DESC LIMIT 1")
        start=starts[0]['started_at'] if starts else j['updated'] if j['state']=='running' else None
        info=f"开始 {clock(start)}"
        rows.append(row(j['id'],'paper · 拉取',j['kind'],j.get('title') or '主题检索','等待存储' if j['state']=='waiting_storage' else '运行中' if live else '已停止 / 待恢复',info,startedAt=start))
    for t in fetch_times:
        label={'done':'已结束','deferred':'延期重试','failed':'失败','needs_manual':'需人工处理','waiting_storage':'等待存储'}.get(t['result'],t['result'])
        ended.append(row('fetch-'+t['job_id']+'-'+str(t['attempt']),'paper · 拉取',t['kind'],t.get('title') or '导入原文',label,
                         f"结束 {clock(t['ended_at'])}",startedAt=t['started_at'],endedAt=t['ended_at']))


def question_rows(root,rows,ended,warnings):
    for folder in sorted((Path(root)/'studies').glob('*')):
        study=read(folder/'study.json')
        if not study:continue
        tasks=read(folder/'tasks.json');tasks=tasks if isinstance(tasks,list) else []
        done=sum(t.get('status')=='completed' for t in tasks)
        files=list((folder/'dashboard-jobs').glob('*.json'))
        files=[p for p in files if not p.name.endswith('.selection.json')]
        latest=read(max(files,key=lambda p:p.stat().st_mtime)) if files else {}
        live=latest.get('status')=='running' and alive(latest.get('process_pid'))
        complete=bool(tasks) and done==len(tasks)
        state='已完成' if complete else '运行中' if live else '待处理' if latest.get('status')=='failed' else '待继续'
        item=row(folder,'question · 研究生成',study.get('id','研究'),study.get('question','研究'),state,f"完成 {done}/{len(tasks)} · {latest.get('error') or study.get('status','')}",resultPath=str(folder),endedAt=study.get('updated_at'))
        (ended if complete else rows).append(item)


def snapshot(root=ROOT,question_root=None):
    root=Path(root);rows,ended,warnings,commands,actions=[],[],[],[],[]
    grid=None
    entries=projects(root)
    if question_root:entries.append({'name':'question','root':str(question_root),'adapter':'question'})
    for project in entries:
        path=Path(project['root']);adapter=project.get('adapter','generic')
        if adapter=='paper':
            paper_rows(path,rows,ended,warnings)
            if grid is None:
                from desktop_widget.page_grid import page_grid
                config=read(path/'config/first_round.json')
                data=Path(config.get('catalog_path',path/'data/catalog.sqlite3')).parent
                grid=page_grid(path,owner_live=alive(read(data/'web-card-service.json').get('pid')))
        elif adapter=='question':question_rows(path,rows,ended,warnings)
        else:
            state=read(path/'task-status.json')
            for item in state.get('tasks',[]):
                value=row(str(path)+str(item.get('id')),project['name'],item.get('label','任务'),item.get('title','任务'),item.get('state','待核对'),item.get('detail',''),resultPath=item.get('resultPath'))
                (ended if item.get('ended') else rows).append(value)
        for command in command_files(path):
            command['relativePath']=project['name']+' / '+command['relativePath'];commands.append(command)
    commands.sort(key=lambda c:(c['path'].endswith('/article/open_gpt.command'),c['relativePath']))
    ended.sort(key=lambda r:(r.get('title','').startswith('置顶 · '),r.get('endedAt') or ''),reverse=True)
    return dict(updated=time.time(),continuousRunning=any(r['label']=='常驻服务' and r['state'] not in ('已停止','已暂停') for r in rows if r['group'].startswith('paper ·')),commands=commands,rows=rows,ended=ended,warnings=list(dict.fromkeys(warnings)),actions=actions,pageGrid=grid,seedOnly=__import__('core.api',fromlist=['seed_focus__active']).seed_focus__active(read(root/'config/first_round.json')))


if __name__=='__main__':print(json.dumps(snapshot(),ensure_ascii=False))
