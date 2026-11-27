"""Evidence-based literature quality rubric, independent of generated card review."""
import math

VERSION='paper-evaluation-v2'
RUBRIC={
    'contribution':{'label':'研究贡献','weight':30,'description':'依据本文问题与原文对既有工作的比较，评估实际推进了多少认识、方法或能力；完成常规任务不等于重要贡献。'},
    'method_rigor':{'label':'方法严谨性','weight':25,'description':'研究设计、对照或比较、理论假设与推导是否足以支持问题；方法复杂或名称新颖本身不加分。'},
    'evidence_strength':{'label':'证据强度','weight':25,'description':'证据覆盖、独立验证、重复性或稳健性、不确定性与替代解释检查；按实验、理论、方法或综述的实际证据类型判断。'},
    'claim_support':{'label':'结论支撑','weight':15,'description':'主张与证据是否相称，是否区分观察、计算、拟合、解释和推测，因果与机制是否得到实际支持。'},
    'scope_limits':{'label':'适用边界','weight':5,'description':'必要条件、适用范围、局限与未解决问题是否清楚，是否验证或诚实限定推广范围。'},
}


def dimension_schema():
    return {name:{'score':None,'reason':'','source_pages':[]} for name in RUBRIC}


def weighted_score(dimensions):
    """Unknown dimensions keep the total unknown; no renormalizing or default scores."""
    if not isinstance(dimensions,dict) or set(dimensions)!=set(RUBRIC):
        raise ValueError('文献质量分项缺失或多余')
    scores=[]
    for name,rule in RUBRIC.items():
        item=dimensions[name]
        if not isinstance(item,dict):raise ValueError('文献质量分项无效 '+name)
        score=item.get('score')
        if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=10):
            raise ValueError('文献质量分项须为0–10或null '+name)
        scores.append((score,rule['weight']))
    if any(score is None for score,_ in scores):return None
    return round(sum(score*weight/10 for score,weight in scores),2)


def validate(item,page_count=None):
    """Accept the webpage's overall score; never recompute dimension totals."""
    if not isinstance(item,dict):raise ValueError('缺少总体质量评价')
    score=item.get('score')
    if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=100):
        raise ValueError('文献分数无效 overall_quality')
    if not isinstance(item.get('reason'),str) or not item['reason'].strip():
        raise ValueError('缺少评分依据 overall_quality')
    pages=item.get('source_pages')
    if not isinstance(pages,list) or any(type(p) is not int or p<1 or page_count is not None and p>page_count for p in pages):
        raise ValueError('评分依据页码无效 overall_quality')
    if score is not None and not pages:raise ValueError('分数缺少原文依据页码 overall_quality')
    return score
