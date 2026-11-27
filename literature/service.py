"""Join a live public catalog snapshot with sidecar labels and collections."""
from pathlib import Path

from core.api import literature_catalog__metadata_rows as metadata_rows
from .store import Store, DIMENSIONS, fingerprint, normalize, rules, text
from .classifier import classify, metadata_fingerprint
from .inputs import load_documents


class Library:
    def __init__(self, catalog_path, store_path=None):
        self.catalog_path = Path(catalog_path)
        target = Path(store_path or self.catalog_path.parent / 'literature.sqlite3')
        if target.resolve() == self.catalog_path.resolve(): raise ValueError('标签数据库必须独立于主Catalog')
        self.store = Store(target)

    def _rows(self):
        return metadata_rows(self.catalog_path)

    def _annotated_rows(self):
        rows = self._rows(); by_paper = {}
        for a in self.store.annotations(): by_paper.setdefault(a['paper_id'], []).append(a)
        for p in rows:
            p['annotations'] = by_paper.get(p['id'], [])
            # Scientific basis deliberately excludes old cards, scores and personal notes.
            m = p['metadata']
            p['metadata_fingerprint'] = fingerprint({k: m.get(k) for k in ('title','abstract','keywords','authors','year','doi')})
        automatic={r['paper_id']:r for r in self.store.automatic_results()}
        first={r['paper_id']:r for r in self.store.automatic_results(scope='level1')}
        second={r['paper_id']:r for r in self.store.automatic_results(scope='level2')}
        vocab={t['id']:t for t in self.store.tags()}
        for p in rows:
            old=second.get(p['id']) or automatic.get(p['id']); one=first.get(p['id']) or automatic.get(p['id']); p['automatic_labeling']=None
            if not old and not one: continue
            first_run=one or old
            meta=metadata_fingerprint(p)
            first_current=first_run['metadata_fingerprint']==meta
            second_current=bool(old and old['metadata_fingerprint']==meta and old['source_fingerprint']==p['source_fingerprint'])
            p['automatic_labeling']={'run_id':first_run['run_id'],
                'level1_state':first_run['level1_state'] if first_current else 'stale_input',
                'level2_state':old['level2_state'] if second_current else 'stale_input' if old else 'not_requested',
                'level1_run_id':first_run['run_id'], 'level2_run_id':old['run_id'] if old else None,
                'input_fingerprint':first_run['input_fingerprint'],
                'input_current':first_current and (second_current if old else True),
                'level1_input_current':first_current, 'level2_input_current':second_current,
                'limitations':list(dict.fromkeys(first_run['limitations']+(old['limitations'] if old and one else []))),
                'rule_version':first_run['rule_version'],
                'selection_policy':first_run.get('selection_policy'), 'count_guidance':first_run.get('count_guidance')}
            protected={a['tag_id'] for a in p['annotations'] if a['actor']=='manual'}
            labels=[]
            for run,level,current in ((first_run,1,first_current),(old,2,second_current)):
                if not run or not current: continue
                labels.extend({**label,'run_id':run['run_id'],'generator_version':run['rule_version'],
                               'input_fingerprint':run['input_fingerprint']}
                              for key in ('level1','level2','supporting_labels','inherited_labels')
                              for label in run.get(key,[]) if label['level']==level)
            for label in labels:
                tag=vocab.get(label['tag_id'])
                if not tag or tag['status']=='rejected' or label['tag_id'] in protected:continue
                p['annotations'].append({'paper_id':p['id'],'tag_id':label['tag_id'],'dimension':label['dimension'],
                    'name_zh':tag['name_zh'],'name_en':tag['name_en'],'vocabulary_status':tag['status'],
                    'state':'automatic','actor':'automatic','version':1,'level':label['level'],
                    'run_id':label['run_id'],'generator_version':label['generator_version'],
                    'input_fingerprint':label['input_fingerprint'],
                    'evidence':[{**e,'input_fingerprint':label['input_fingerprint'],'generator_version':label['generator_version']} for e in label['evidence']],
                    'importance':label.get('importance','core'),'selection_basis':label.get('selection_basis'),
                    'hierarchy_basis':label.get('hierarchy_basis')})
        return rows

    def _matches(self, p, filters):
        m = p['metadata']; active = [a for a in p['annotations'] if a['state'] != 'rejected' and a['vocabulary_status'] != 'rejected' and a.get('importance') != 'supporting']
        if filters.get('state', 'all') != 'all': active = [a for a in active if a['state'] == filters['state']]
        # OR inside each dimension, AND between dimensions; parent includes descendants.
        tags = self._tag_tree
        for dim, wanted in filters.get('tags', {}).items():
            expanded = set(wanted)
            for _ in range(3): expanded.update(t['id'] for t in tags if t['parent_id'] in expanded)
            if wanted and not any(a['dimension'] == dim and a['tag_id'] in expanded for a in active): return False
        if filters.get('state', 'all') != 'all' and not active: return False
        if 'has_pdf' in filters and p['has_pdf'] != filters['has_pdf']: return False
        if 'year_from' in filters or 'year_to' in filters:
            try: year = int(m.get('year'))
            except (TypeError, ValueError): return False
            if not filters.get('year_from', 1000) <= year <= filters.get('year_to', 3000): return False
        aliases = [label for t in tags if any(a['tag_id'] == t['id'] for a in active) for label in t['aliases']]
        haystack = normalize(' '.join(str(v or '') for v in (p['title'], m.get('abstract'), m.get('authors'), m.get('doi'), m.get('venue'), m.get('year'), m.get('keywords'), m.get('language'), m.get('publication_kind'), p['note'], *aliases)))
        return all(word in haystack for word in normalize(filters.get('q', '')).split())

    def query(self, filters=None, *, limit=50, offset=0, collection_id=None):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0: raise ValueError('分页参数不合法')
        filters = rules(filters or {}); self.store.validate_filter_tags(filters)
        self._tag_tree = self.store.tags()
        rows = self._annotated_rows()
        if collection_id:
            c = next((c for c in self.store.collections() if c['id'] == collection_id), None)
            if not c: raise KeyError('集合不存在')
            members = {r['paper_id']: r for r in self.store.members(collection_id)}
            selected = []
            for p in rows:
                member = members.get(p['id'])
                if member and member['mode'] == 'exclude': continue
                # Empty rules = manual-only collection, never implicitly includes the entire library.
                match = bool(c['rules']) and self._matches(p, c['rules'])
                if not (member and member['mode'] == 'include') and not match: continue
                p['membership'] = member or {'mode':'auto','role':'foundation','position':100000,'progress':'unread','note':'','version':0}
                selected.append(p)
            rows = sorted(selected, key=lambda p:(p['membership']['position'],p['id']))
        matched = [p for p in rows if self._matches(p, filters)]
        return {'papers': matched[offset:offset+limit], 'total': len(matched), 'limit': limit, 'offset': offset}

    def detail(self, paper_id):
        p = next((p for p in self._annotated_rows() if p['id'] == paper_id), None)
        if not p: raise KeyError('文献不存在')
        auto=[a for a in p['annotations'] if a['actor']=='automatic' and a['state']=='automatic']
        p['annotations'] = self.store.annotations(paper_id)+auto
        for annotation in p['annotations']:
            for evidence in annotation['evidence']:
                if annotation['state']=='automatic':evidence['input_current']=True
                else:
                    current = p['source_fingerprint'] if evidence['scope']=='fulltext' else p['metadata_fingerprint']
                    evidence['input_current'] = bool(current and evidence['input_fingerprint']==current)
        return p

    def annotate(self, records):
        raise ValueError('已停用逐篇人工标注；请运行一二级自动标注')

    def auto_label(self, paper_ids, fallback_pdf=False):
        if type(fallback_pdf) is not bool:raise ValueError('补解析设置须为布尔值')
        documents=load_documents(self.catalog_path,paper_ids,fallback_pdf=fallback_pdf)
        output=[]
        for document in documents:
            result=classify(document)
            # Recheck metadata and source identity after local preparation, before publication.
            from core.api import literature_catalog__source_records as source_records
            current=source_records(self.catalog_path,[document['paper_id']])[0]
            if metadata_fingerprint(current)!=document['metadata_fingerprint'] or current['asset_hash']!=document['source_fingerprint']:
                raise Conflict('原文或元信息已变化，保留本次材料并等待重新检查')
            output.append(self.store.save_automatic_run(document,result))
        return {'results':output,'papers_processed':len(output),'models_used':False}

    def save_member(self, **data):
        if data.get('paper_id') not in {p['id'] for p in self._rows()}: raise ValueError('文献不存在')
        return self.store.save_member(**data)

    def dispatch(self, operation, data):
        """Explicit operation allowlist, used by CLI and the authenticated workbench."""
        if not isinstance(data, dict): raise ValueError('请求须为JSON对象')
        operations = {
            'query': self.query, 'detail': self.detail, 'tags': self.store.tags,
            'save_tag': self.store.save_tag, 'annotate': self.annotate,
            'collections': self.store.collections, 'save_collection': self.store.save_collection,
            'members': self.store.members, 'save_member': self.save_member,
            'import_oled_vocabulary': self.import_oled_vocabulary,
            'auto_label': self.auto_label,
        }
        if operation not in operations: raise ValueError('未知文献整理操作')
        if operation == 'annotate':raise ValueError('已停用逐篇人工标注；请运行一二级自动标注')
        try: return operations[operation](**data)
        except TypeError as exc: raise ValueError('请求字段不匹配') from exc

    def import_oled_vocabulary(self):
        """Explicit, idempotent candidate import; never assigns labels to papers."""
        from .vocabulary import OLED_TERMS
        created = []; skipped = []
        for dimension, zh, en, aliases in OLED_TERMS:
            existing = {self.store.resolve(label, dimension) for label in (zh,en,*aliases)} - {None}
            if existing:
                skipped.append({'name':zh,'existing_ids':sorted(existing)})
                continue
            from .store import Conflict
            try:
                created.append(self.store.save_tag(dimension=dimension, name_zh=zh, name_en=en, aliases=list(aliases), status='candidate'))
            except Conflict:
                # Another request imported/edited this alias after our read. Preserve it.
                skipped.append({'name':zh,'reason':'词表已变化，保留现有人工记录'})
        return {'created':created,'skipped':skipped,'papers_annotated':0}
