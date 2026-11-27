"""Final frozen-input and human-decision checks for shared source-only sends."""
import json
from core.api import paths__WorkspacePath as Path
from cards.api import web_card_inputs__digest as digest


def check(catalog,config,job,folder,packet):
    paper=catalog.get(job['paper_id'])
    if json.loads((Path(folder)/'packet.json').read_text())!=packet:
        raise ValueError('冻结材料清单或版本变化，不发送')
    with catalog.connect() as db:
        row=db.execute('SELECT state,selection,source_sha256 FROM web_card_jobs WHERE paper_id=?',(job['paper_id'],)).fetchone()
        human=db.execute("SELECT 1 FROM events WHERE paper_id=? AND kind='human_decision'",(job['paper_id'],)).fetchone()
    if row is None or row['state']!='preparing' or row['selection']!=job['selection'] or row['source_sha256']!=job['source_sha256']:
        raise ValueError('领取的任务版本或队列状态变化，不发送')
    if any(paper['metadata'].get(k) for k in ('identity_review_required','version_review_required','out_of_scope')):
        raise ValueError('身份、版本或范围待确认，不发送')
    if paper.get('asset_hash')!=job['source_sha256'] or digest(paper['asset_path'])!=job['source_sha256'] or packet['source_original_sha256']!=job['source_sha256']:
        raise ValueError('原文指纹变化，不发送')
    for name,expected in packet['input_hashes'].items():
        if digest(Path(folder)/name)!=expected:raise ValueError('冻结输入指纹变化，不发送')
    from cards.api import web_card_rework__authorization as authorization
    rework=authorization(job,paper)
    from cards.api import seed_trials__check_request as check_trial
    check_trial(catalog,config,job,packet)
    if rework and rework.get('kind') in ('source_review','manual_seed_trial'):
        if human or paper['decision']!='unreviewed':raise ValueError('入队后出现人工决定，只保留修正建议')
        path=Path(paper.get('card_path') or '')
        if not path.is_file() or digest(path)!=rework['old_sha256']:raise ValueError('修正原卡版本变化，不发送')
    elif not rework:
        target=Path(config['studio_library_root'])/job['paper_id']/'card.json'
        if human or paper['decision']!='unreviewed' or paper.get('card_path') or target.exists():
            raise ValueError('已有卡片或人工决定，不发送')
    return paper
