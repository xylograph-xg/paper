"""Immutable historical card snapshots become visible only after a verified complete copy."""
import os,shutil,tempfile,json
from core.api import paths__WorkspacePath as Path
from reading.api import reading_contract__file_digest as file_digest
from core.api import services__atomic_json as atomic_json

def preserve(target,asset_hash):
 target=Path(target);history=target/'history';history.mkdir(exist_ok=True)
 card_hash=file_digest(target/'card.json');source_hash=file_digest(target/'source.pdf') if (target/'source.pdf').exists() else asset_hash
 if not source_hash:raise ValueError('历史快照缺少原文身份')
 destination=history/(card_hash[:16]+'_'+source_hash[:16])
 if destination.exists():
  manifest=destination/'snapshot-complete.json'
  if manifest.exists():
   proof=json.loads(manifest.read_text())
   if all(file_digest(destination/k)==v for k,v in proof['files'].items()):return destination
  # A previous interrupted copy is preserved, never trusted or overwritten.
  destination.rename(history/(destination.name+'_incomplete_'+__import__('uuid').uuid4().hex))
 stage=Path(tempfile.mkdtemp(prefix='.snapshot-',dir=history))
 try:
  for path in target.iterdir():
   if path.name in ('history','worker.log'):continue
   if path.is_dir():shutil.copytree(path,stage/path.name)
   elif path.is_file():shutil.copyfile(path,stage/path.name)
  hashes={str(p.relative_to(stage)):file_digest(p) for p in stage.rglob('*') if p.is_file()}
  if hashes.get('card.json')!=card_hash:raise ValueError('历史卡片在复制期间改变')
  atomic_json(stage/'snapshot-complete.json',{'files':hashes,'source_sha256':source_hash})
  os.replace(stage,destination)
  fd=os.open(history,os.O_RDONLY)
  try:os.fsync(fd)
  finally:os.close(fd)
  return destination
 finally:
  if stage.exists():shutil.rmtree(stage)
