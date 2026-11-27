"""Protect the exact independently reviewed snapshot without rewriting card text."""
from core.api import paths__workspace_root as _workspace_root
import json
from core.api import paths__WorkspacePath as Path
from reading.api import reading_contract__file_digest as file_digest
REVIEWS_ROOT=_workspace_root()/'data/quality_reviews'


def protection(folder, reviews_root=None):
    folder=Path(folder)
    if not (folder/'card.json').is_file():return None
    card_hash=file_digest(folder/'card.json')
    source_hash=file_digest(folder/'source.pdf') if (folder/'source.pdf').is_file() else None
    reviews_root=Path(reviews_root or REVIEWS_ROOT)
    for run_path in sorted(reviews_root.glob('*/run.json'),reverse=True):
        sample=None
        try:
            run=json.loads(run_path.read_text())
            for sample in run.get('samples',[]):
                if sample.get('card_sha256')!=card_hash:continue
                kind=sample['kind'];review=run_path.parent/kind
                assessment={'pass':False,'verification':'旧评审回执未完成完整性核验；保留快照保护'}
                try:attempt=json.loads((review/'web-attempt.json').read_text())
                except (OSError,ValueError):return {'run':str(run_path.parent),'card_sha256':card_hash,'source_changed':sample.get('source_sha256')!=source_hash,**assessment}
                if attempt.get('state')!='feedback_received':return {'run':str(run_path.parent),'card_sha256':card_hash,'source_changed':sample.get('source_sha256')!=source_hash,**assessment}
                from .card_evaluation import assess_feedback
                feedback=json.loads((review/'feedback.json').read_text())
                assessment=assess_feedback(feedback,kind)
                if not (review/'feedback-raw.txt').is_file():raise ValueError('缺少原始评审响应')
                if not attempt.get('feedback_sha256') or not attempt.get('raw_sha256'):
                    assessment={'pass':False,'verification':'旧回执缺少摘要，保留历史快照但不接受科学评分'}
                elif attempt.get('assessment')!=assessment:
                    assessment={'pass':False,'verification':'回执评估与重算不一致，需核验'}
                if attempt.get('feedback_sha256') and attempt['feedback_sha256']!=file_digest(review/'feedback.json'):
                    assessment={'pass':False,'verification':'评审 JSON 在收取后变化，需要核对原始记录'}
                if attempt.get('raw_sha256') and attempt['raw_sha256']!=file_digest(review/'feedback-raw.txt'):
                    assessment={'pass':False,'verification':'评审原始响应在收取后变化，需要核对原始记录'}
                if not source_hash or sample.get('source_sha256')!=source_hash:
                    assessment={**assessment,'pass':False,'verification':'原文版本变化；历史评分不作为当前科学通过'}
                return {'run':str(run_path.parent),'card_sha256':card_hash,'source_sha256':sample.get('source_sha256'),'source_changed':sample.get('source_sha256')!=source_hash,**assessment}
        except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
            # A matching reviewed snapshot cannot become unprotected due to corruption.
            if isinstance(sample,dict) and sample.get('card_sha256')==card_hash:
                return {'run':str(run_path.parent),'card_sha256':card_hash,'source_changed':sample.get('source_sha256')!=source_hash,'pass':False,'verification':'回执无法核验，保留快照保护：'+type(exc).__name__}
            continue
    return None
