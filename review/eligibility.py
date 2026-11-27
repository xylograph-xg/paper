"""Completion eligibility without the retired automatic review watcher."""
import json,os,subprocess,sys
from core.api import paths__WorkspacePath as Path
from datetime import datetime
from .card_evaluation import ROOT,digest,published_evidence_available
from reading.api import reading_contract__verified_completion as verified_completion

def eligible(folder, *, include_incomplete=False, since=None):
    if not include_incomplete:
        document_python=os.environ.get('WEB_FEEDBACK_DOCUMENT_PYTHON')
        if document_python and Path(document_python).absolute()!=Path(sys.executable).absolute():
            # Producer/runtime checks belong to the document environment. The
            # browser venv deliberately lacks PDF/rendering dependencies.
            code='import json,sys; from reading.reading_contract import verified_completion; print(json.dumps(verified_completion(sys.argv[1])))'
            result=subprocess.run([document_python,'-c',code,str(Path(folder).resolve())],cwd=ROOT,
                                  capture_output=True,text=True,check=True,timeout=30)
            value=json.loads(result.stdout)
            if value is not None and not isinstance(value,dict):raise ValueError('完成合同子进程返回无效结果')
            return value
        return verified_completion(folder)
    # Diagnostic reviews may inspect failed final outputs; never upload live
    # generation checkpoints or relabel an incomplete card as complete.
    folder=Path(folder)
    try:
        card_path=folder/'card.json'
        if since and card_path.stat().st_mtime < datetime.fromisoformat(since).timestamp():return None
        before=digest(card_path)
        card=json.loads(card_path.read_text())
        if not isinstance(card,dict) or not card.get('title'):return None
        if not published_evidence_available(folder,card):return None
        source=digest(folder/'source.pdf')
        if digest(card_path)!=before:return None
        return {'card_sha256':before,'source_sha256':source,'diagnostic_review':True}
    except (OSError,ValueError,TypeError):
        return None
