"""One read-only inbox for user actions, separate from automatic cooldowns."""
import argparse
import json
from .paths import WorkspacePath as Path
import sqlite3
import time
from .control import InvalidControl, pause_decision, provider_decisions, read_record


def snapshot(config):
    root = Path(config['catalog_path']).parent
    items = []

    def add(key, title, action, *, source='', url=None):
        items.append({'id': key, 'title': title, 'action': action, 'source': str(source), 'conversation_url': url})

    pause = pause_decision(config, 'web_cards', enabled=config.get('web_cards', {}).get('enabled', True))
    if pause.state == 'invalid':
        add('invalid-control', '网页制卡控制记录损坏', '核对控制记录；修复前不恢复提交', source=pause.source)
    from cards.api import web_card_service__owner_enabled as owner_enabled
    if not pause.allowed and not owner_enabled(config):
        return {'schema_version': 1, 'updated': time.time(), 'items': items}
    decisions = provider_decisions(root, policy=config.get('web_cards'))
    for provider, decision in decisions.items():
        if decision.requires_user_action:
            add('channel:' + provider, provider + ' 通道需要处理', decision.reason, source=decision.source)
    try:
        tabs = read_record(root / 'web-tab-check.json')
        if tabs and time.time() - tabs.get('updated', 0) < 120 and tabs.get('total_pages') == 0 and not tabs.get('errors'):
            add('browser-page', '专用浏览器没有可用页面', '主动点击GPT制卡启动以打开一个主页；后台不自动开页', source=root / 'web-tab-check.json')
        pool = read_record(root / 'gpt-window-pool.json')
        for target, entry in pool.get('windows', {}).items():
            if entry.get('state') == 'needs_inspection':
                add('page:' + target, '核对GPT原会话', entry.get('error') or '确认材料归属与原请求状态；不要重新发送',
                    source=root / 'gpt-window-pool.json', url=entry.get('conversation_url'))
    except (InvalidControl, TypeError, AttributeError) as exc:
        add('browser-record', '浏览器记录需要核对', str(exc), source=root / 'gpt-window-pool.json')
    # Time never proves termination. Surface overdue original receipts for
    # inspection, including archived records outside the current job view.
    from browser.api import attempt_history__index_attempts as index_attempts
    try:
        records,_=index_attempts(root)
        from browser.api import shared_page_health___uncollected_history as _uncollected_history
        targets={record.get('target_id') for record in records.values() if record.get('target_id')}
        for target in targets:
            history=[r for r in records.values() if r.get('target_id')==target]
            outstanding=set(_uncollected_history(target,history))
            for record in history:
                stamp=record.get('created')
                url=record.get('conversation_url','')
                if (record['_ledger_path'] not in outstanding or type(stamp) not in (int,float) or
                        time.time()-stamp<86400 or not url.startswith('https://chatgpt.com/c/') or 'local-chatgpt' in url):continue
                add('receipt:'+record['_ledger_path'], '原网页回执超过24小时未完整收取',
                    '核对原target、会话和材料标识；时间不能证明终止，不自动重发或关页',
                    source=record['_ledger_path'],url=url)
    except (OSError,ValueError) as exc:
        add('receipt-record','原提交账本需要核对',str(exc),source=root/'web_cards')
    path = Path(config['catalog_path']).resolve()
    if path.is_file():
        try:
            # No Catalog constructor, migrations, writes or browser calls.
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=.3) as db:
                db.row_factory = sqlite3.Row
                exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='web_card_jobs'").fetchone()
                if exists:
                    for row in db.execute("SELECT paper_id,title,error,folder FROM web_card_jobs WHERE state='needs_inspection' ORDER BY updated"):
                        add('job:' + row['paper_id'], row['title'], row['error'] or '核对原提交记录；不得盲目重发', source=row['folder'] or path)
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='card_review_jobs'").fetchone():
                    for row in db.execute("SELECT id,title,error,folder FROM card_review_jobs WHERE state='needs_user' ORDER BY priority IS NULL,priority DESC"):
                        add('review:'+row['id'],row['title'],row['error'] or '查看原文核对报告',source=row['folder'])
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='card_correction_jobs'").fetchone():
                    for row in db.execute("SELECT id,title,error,folder FROM card_correction_jobs WHERE state='needs_user' ORDER BY fifo_at,id"):
                        add('correction:'+row['id'],row['title'],row['error'] or '查看独立修正建议与原核验报告',source=row['folder'])
        except sqlite3.Error as exc:
            add('catalog', '任务目录暂不可读取', '核对本机数据库访问：' + str(exc), source=path)
    from .automatic_issue_handler import enabled, disposition
    if enabled(config):
        items = [{**item, 'handling':'automatic', 'stage':disposition(item)[0],
                  'automatic_action':disposition(item)[1]} for item in items]
    return {'schema_version': 1, 'updated': time.time(), 'items': items}


def publish(config):
    from .services import atomic_json
    result = snapshot(config)
    atomic_json(Path(config['catalog_path']).parent / 'action-inbox.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='只读待用户操作；--write显式更新本地收件箱')
    parser.add_argument('--config')
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    from .catalog import load_config
    config = load_config(args.config)
    print(json.dumps(publish(config) if args.write else snapshot(config), ensure_ascii=False, indent=2))
