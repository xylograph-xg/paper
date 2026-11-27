"""Read-only catalog counts and current fetch/card progress for both panels."""
import json
import sqlite3
import time
from contextlib import closing
from .paths import WorkspacePath as Path
from datetime import datetime
from zoneinfo import ZoneInfo


def clock(value):
    try:
        dt=datetime.fromtimestamp(value,ZoneInfo('Asia/Shanghai')) if isinstance(value,(float,int)) else datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Shanghai'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except (TypeError,ValueError):return '暂无记录'


def status(catalog_path):
    result={'total':0,'downloaded':0,'cards':0,'last_card_completed':None,'last_card_completed_shanghai':'暂无记录','fetch_reason':'等待目录状态','pending':0,'eligible':0,'next_retry':None,'next_retry_shanghai':'暂无记录','active_fetch':0,'card_jobs':{}}
    path=Path(catalog_path).resolve()
    if not path.exists():return result
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)) as db:
        db.row_factory=sqlite3.Row
        r=db.execute("SELECT count(*) total,sum(acquisition='available') downloaded,sum(card_path IS NOT NULL) cards FROM papers").fetchone()
        result.update({k:r[k] or 0 for k in ('total','downloaded','cards')})
        last=db.execute("SELECT created FROM events WHERE kind='web_card_generated' ORDER BY id DESC LIMIT 1").fetchone()
        if last:result.update(last_card_completed=last['created'],last_card_completed_shanghai=clock(last['created']))
        try:
            result['card_jobs']={r['state']:r['n'] for r in db.execute('SELECT state,count(*) n FROM web_card_jobs GROUP BY state')}
        except sqlite3.OperationalError:pass
        result['active_fetch']=db.execute("SELECT count(*) FROM jobs WHERE kind IN ('acquire','acquire_fallback','import') AND state='running'").fetchone()[0]
        result['pending']=db.execute("SELECT count(*) FROM discovery_pending WHERE state='pending'").fetchone()[0]
        result['eligible']=db.execute("SELECT count(*) FROM discovery_pending WHERE state='pending' AND retry_at<=?",(time.time(),)).fetchone()[0]
        retry=db.execute("SELECT min(retry_at) FROM discovery_pending WHERE state='pending' AND retry_at>?",(time.time(),)).fetchone()[0]
        result.update(next_retry=retry,next_retry_shanghai=clock(retry))
        result['blocked']=db.execute("SELECT count(*) FROM discovery_pending WHERE state='blocked_fetch'").fetchone()[0]
        latest=db.execute('SELECT created,result FROM runs ORDER BY created DESC LIMIT 1').fetchone()
        recent={}
        if latest:
            try:recent=json.loads(latest['result'])
            except (ValueError,TypeError):pass
            result['last_discovery_shanghai']=clock(latest['created'])
            result['discovered_records']=recent.get('metadata_count',0)
            result['new_download_jobs']=len(recent.get('queued_acquisitions',[]))
        if result['active_fetch']:
            reason=f"正在下载/兜底 {result['active_fetch']} 篇"
        elif result['eligible']:
            reason=f"可重试候选 {result['eligible']} 篇，等待调度"
        else:
            reason=f"当前无可立即下载候选；{result['pending']} 篇等待退避重试"
        if latest and not recent.get('queued_acquisitions'):
            reason+=f"；最近检索返回 {recent.get('metadata_count',0)} 条，新增下载任务 0（去重/领域筛选/已处理/重试保护后）"
        if retry:reason+=f"；下一次候选重试 {clock(retry)}"
        result['fetch_reason']=reason
    return result
