"""Persisted desired concurrency; running tasks drain rather than being killed."""
import argparse,json,time
from .paths import WorkspacePath as Path
from .catalog import load_config,validate_fetch_capacity
from .control import read_record,mutate_record

MAX_FETCH=150
MAX_CARDS=20
MAX_CORRECTION=20
DEFAULT_CARDS_MIN_PAGES=8
LANE_LABELS={"cards":"制卡","review":"核验","correction":"修正"}

def _values(config,record):
    policy=config.get('fetch_pipeline',{});cards=config.get('web_cards',{})
    values={'fetch':record.get('fetch',policy.get('download_workers',4)+policy.get('fallback_workers',2)),
            'cards':record.get('cards',cards.get('max_parallel_jobs',cards.get('target_pool_pages',10))),
            'review':record.get('review',config.get('card_review',{}).get('parallel_jobs',4)),
            'correction':record.get('correction',config.get('card_correction',{}).get('parallel_jobs',4)),
            'updated':record.get('updated',0)}
    # Old records can already contain a smaller user-selected card limit. Read
    # the new default without silently increasing that saved limit or rewriting
    # any pause record. An explicit reservation is validated below.
    default_min=min(cards.get('min_reserved_pages',DEFAULT_CARDS_MIN_PAGES),values['cards']) if type(values['cards']) is int else DEFAULT_CARDS_MIN_PAGES
    values['cards_min_pages']=record.get('cards_min_pages',default_min)
    for lane,default in [('review',4),('correction',3)]:
        limit=values[lane]
        fallback=min(config.get('card_'+lane,{}).get('min_reserved_pages',default),limit) if type(limit) is int else default
        values[lane+'_min_pages']=record.get(lane+'_min_pages',fallback)
    for key,limit in [('fetch',MAX_FETCH),('cards',min(MAX_CARDS,cards.get('max_total_pages',20))),
                      ('review',MAX_CARDS),('correction',MAX_CORRECTION),('cards_min_pages',MAX_CARDS),
                      ('review_min_pages',MAX_CARDS),('correction_min_pages',MAX_CORRECTION)]:
        if type(values[key]) is not int or not 1<=values[key]<=limit:raise ValueError('并行数量超出允许范围')
    from browser.api import shared_browser_window__enabled as shared_enabled
    if (shared_enabled(config) or 'cards_min_pages' in record or 'min_reserved_pages' in cards) and values['cards']<values['cards_min_pages']:
        raise ValueError('制卡并行上限不能低于制卡预留页数；请先调整预留页数')
    for lane in ('review','correction'):
        if values[lane]<values[lane+'_min_pages']:raise ValueError(LANE_LABELS[lane]+'并行上限不能低于最低并行数量')
    if shared_enabled(config) and sum(values[lane+'_min_pages'] for lane in LANE_LABELS)>20:
        raise ValueError('制卡、核验、修正的最低并行合计不能超过20；请先降低其他任务的最低并行')
    return values

def settings(config):
    """Read desired limits only; absent new fields never resume or rewrite tasks."""
    path=Path(config['catalog_path']).parent/'concurrency-control.json'
    return _values(config,read_record(path))

def apply(config):
    values=settings(config)
    from browser.api import shared_browser_window__enabled as shared_enabled
    fixed=shared_enabled(config)
    cards=config.setdefault('web_cards',{})
    if fixed or 'min_reserved_pages' in cards:
        cards['min_reserved_pages']=values['cards_min_pages']
    if fixed:
        for lane in ('review','correction'):config.setdefault('card_'+lane,{})['min_reserved_pages']=values[lane+'_min_pages']
    if config.get('card_correction',{}).get('enabled'):
        config['card_correction']['parallel_jobs']=values['correction']
    if config.get('card_review',{}).get('enabled'):
        config['card_review']['parallel_jobs']=values['review']
        from .control import pause_decision
        reviews=values['review'] if pause_decision(config,'card_review').allowed else 0
        config['web_cards']['target_pool_pages']=20 if fixed else min(config['web_cards'].get('max_total_pages',20),values['cards']+reviews)
    elif fixed:config['web_cards']['target_pool_pages']=20
    if not (Path(config['catalog_path']).parent/'concurrency-control.json').exists():return values
    total=values['fetch'];fast=max(1,(total*2+2)//3)
    config.setdefault('fetch_pipeline',{}).update(download_workers=fast,fallback_workers=total-fast,seed_workers=min(10,max(1,total//2)),topic_workers=min(4,max(1,total//6)))
    validate_fetch_capacity(config['fetch_pipeline'])
    target=20 if fixed else config['web_cards']['target_pool_pages'] if config.get('card_review',{}).get('enabled') else values['cards']
    config.setdefault('web_cards',{}).update(max_parallel_jobs=values['cards'],target_pool_pages=target)
    config['web_cards'].setdefault('refill_min_pending',20)
    return values

def set_limits(config,changes,*,auto_raise_cards=False,auto_raise_lane=None):
    """Atomically edit lane limits or their reservations, keeping other fields.

    A card maximum and reservation may be changed together. Minimum-only edits
    may explicitly raise the current maximum under the control write lock.
    No task is started,
    paused, cancelled, sent or moved between queues by this local control edit.
    """
    if not isinstance(changes,dict) or not changes or not set(changes)<={'fetch','cards','review','correction','cards_min_pages','review_min_pages','correction_min_pages'}:
        raise ValueError('未知任务或并行设置')
    if type(auto_raise_cards) is not bool or (auto_raise_cards and set(changes)!={'cards_min_pages'}):
        raise ValueError('自动提高制卡上限仅用于最低并行数量设置')
    lane='cards' if auto_raise_cards else auto_raise_lane
    if lane is not None and (lane not in LANE_LABELS or set(changes)!={lane+'_min_pages'}):
        raise ValueError('自动提高上限仅用于对应任务的最低并行设置')
    for target,value in changes.items():
        limit=MAX_FETCH if target=='fetch' else min(MAX_CARDS,config.get('web_cards',{}).get('max_total_pages',20))
        if type(value) is not int or not 1<=value<=limit:raise ValueError('并行数量超出允许范围')
    path=Path(config['catalog_path']).parent/'concurrency-control.json'
    def validate(record):
        from browser.api import shared_browser_window__enabled as shared_enabled
        if shared_enabled(config) or 'cards_min_pages' in record or 'min_reserved_pages' in config.get('web_cards',{}):
            # The first explicit edit persists the compatible old reservation.
            # Read it under mutate_record's lock so lowering the maximum cannot
            # lower the reservation implicitly, or overwrite a parallel edit.
            if 'cards_min_pages' not in record:
                record['cards_min_pages']=_values(config,read_record(path))['cards_min_pages']
        for other in ('review','correction'):
            if other+'_min_pages' not in record:record[other+'_min_pages']=_values(config,read_record(path))[other+'_min_pages']
        if lane is not None:
            current_max=record.get(lane,config.get('web_cards',{}).get('max_parallel_jobs',10) if lane=='cards' else config.get('card_'+lane,{}).get('parallel_jobs',4))
            if type(current_max) is int:
                record[lane]=max(current_max,record[lane+'_min_pages'])
        _values(config,record)
    mutate_record(path,{**changes,'updated':time.time()},event='user_concurrency_change',validate=validate)
    return apply(config)

def set_limit(config,target,value):
    return set_limits(config,{target:value})

def set_minimum(config,value,lane="cards"):
    """Set a lane minimum, raising only its smaller maximum without resuming."""
    if lane not in LANE_LABELS:raise ValueError('未知任务')
    return set_limits(config,{lane+'_min_pages':value},auto_raise_cards=lane=='cards',auto_raise_lane=lane if lane!='cards' else None)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--target',choices=['fetch','cards','review','correction','cards_min_pages','review_min_pages','correction_min_pages'],required=True);parser.add_argument('--value',type=int,required=True);parser.add_argument('--config');args=parser.parse_args()
    config=load_config(args.config);result=set_minimum(config,args.value,args.target.removesuffix('_min_pages')) if args.target.endswith('_min_pages') else set_limit(config,args.target,args.value)
    # Wake the watcher via the control revision; never restart running jobs.
    print(json.dumps(result,ensure_ascii=False))
