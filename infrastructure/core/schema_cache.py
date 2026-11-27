"""Loaded-code-bound readiness for unchanged catalog initializers."""
import hashlib
import json
import re
from types import CodeType

MARKER='catalog_initialization_state'
CREATE=re.compile(r'CREATE\s+(?:UNIQUE\s+)?(?:TABLE|INDEX|TRIGGER)\s+IF\s+NOT\s+EXISTS\s+([a-zA-Z0-9_]+)',re.I)


def signature(functions):
    """Stable across processes; never stamp a mocked/uninspectable initializer."""
    required=set();records=[]
    def encode(value):
        if isinstance(value,CodeType):
            return {'bytes':value.co_code.hex(),'names':value.co_names,'variables':value.co_varnames,
                    'args':[value.co_argcount,value.co_posonlyargcount,value.co_kwonlyargcount,value.co_flags],
                    'free':value.co_freevars,'cells':value.co_cellvars,
                    'exceptions':getattr(value,'co_exceptiontable',b'').hex(),
                    'constants':[encode(x) for x in value.co_consts]}
        if isinstance(value,str):
            required.update(name for name in CREATE.findall(value) if not name.endswith('_'))
            return value
        if isinstance(value,bytes):return {'bytes':value.hex()}
        if isinstance(value,(tuple,list)):return [encode(x) for x in value]
        if isinstance(value,frozenset):return sorted((encode(x) for x in value),key=lambda x:json.dumps(x,sort_keys=True))
        if value is None or type(value) in (int,float,bool):return value
        return {'type':type(value).__name__}
    for function in functions:
        code=getattr(function,'__code__',None)
        if not isinstance(code,CodeType):return None,set()
        globals_={name:encode(function.__globals__[name]) for name in code.co_names
                  if name.isupper() and name in function.__globals__ and
                  isinstance(function.__globals__[name],(str,int,float,bool,tuple,frozenset))}
        records.append({'module':function.__module__,'code':encode(code),'globals':globals_})
    raw=json.dumps(records,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    return hashlib.sha256(raw.encode()).hexdigest(),required


def ready(db,fingerprint,required):
    if fingerprint is None:return False
    objects={row[0] for row in db.execute('SELECT name FROM sqlite_master')}
    if MARKER not in objects or not required<=objects or 'seed_control_compat' in objects:return False
    for table in ('papers','jobs','events','runs','auto_selection_checks','paper_reading_state','paper_card_scores','card_review_jobs','card_correction_jobs'):
        if table in objects and any('revision_'+table+'_'+operation not in objects for operation in ('insert','update','delete')):
            return False
    columns={row[1] for row in db.execute('PRAGMA table_info(paper_card_scores)')}
    if not {'key_findings','work_summary'}<=columns:return False
    row=db.execute(f"SELECT fingerprint FROM {MARKER} WHERE name='catalog-bootstrap-v1'").fetchone()
    return row is not None and row[0]==fingerprint


def record(db,fingerprint):
    if fingerprint is None:return
    db.execute(f'CREATE TABLE IF NOT EXISTS {MARKER}(name TEXT PRIMARY KEY,fingerprint TEXT NOT NULL)')
    db.execute(f"INSERT INTO {MARKER} VALUES('catalog-bootstrap-v1',?) ON CONFLICT(name) DO UPDATE SET fingerprint=excluded.fingerprint",(fingerprint,))
