"""Local verified recovery snapshots. Restoration only creates isolated candidates."""
import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from core.api import paths__WorkspacePath as Path
import shutil
import sqlite3
from core.api import catalog__ROOT as ROOT, catalog__load_config as load_config
from core.api import services__atomic_json as atomic_json


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while block:=stream.read(1024*1024):h.update(block)
    return h.hexdigest()


def create(config,*,include_media=False,root=ROOT):
    raise RuntimeError("用户已禁用数据备份；不创建备份")


def verify(folder):
    folder=Path(folder).resolve();proof=json.loads((folder/'manifest.json').read_text())
    if proof.get('complete') is not True:raise ValueError('备份未完整完成')
    for name,item in proof['files'].items():
        path=folder/name
        if not path.resolve().is_relative_to(folder) or path.is_symlink() or sha(path)!=item['sha256'] or path.stat().st_size!=item['bytes']:
            raise ValueError('备份文件指纹或路径变化：'+name)
    for name,link in proof['symlinks'].items():
        path=folder/name
        if not path.is_symlink() or os.readlink(path)!=link or not path.resolve(strict=True).is_relative_to(folder):
            raise ValueError('备份软链接变化或越界：'+name)
    return {'verified_files':len(proof['files']),'verified_symlinks':len(proof['symlinks']),
            'media_included':proof['media_included'],'database_rows':proof['database_rows']}


def restore_candidate(folder,destination,*,include_media=True):
    """Never overwrite production or resume tasks from archived controls."""
    folder=Path(folder).resolve();destination=Path(destination).resolve()
    if destination.exists():raise ValueError('恢复候选目录必须不存在')
    if destination.is_relative_to(folder) or folder.is_relative_to(destination):raise ValueError('恢复候选与备份目录不能嵌套')
    verify(folder)
    shutil.copytree(folder,destination,symlinks=True,ignore=(lambda current,names: ['media'] if Path(current)==folder and not include_media else []))
    if not include_media:
        proof=json.loads((destination/'manifest.json').read_text())
        proof['files']={n:v for n,v in proof['files'].items() if not n.startswith('media/')}
        proof['symlinks']={n:v for n,v in proof['symlinks'].items() if not n.startswith('media/')}
        proof.update(media_included=False,source_backup_media_excluded=True)
        atomic_json(destination/'manifest.json',proof)
    atomic_json(destination/'RESTORE-NOT-ACTIVATED.json',{'runtime_activated':False,
        'requires_original_receipt_reconciliation':True,'note':'禁止将旧控制、未知提交或暂停快照直接覆盖生产；仅用于离线恢复核对'})
    return verify(destination)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['create','verify','restore-candidate']);p.add_argument('--config');p.add_argument('--media',action='store_true');p.add_argument('--state-only',action='store_true');p.add_argument('--folder');p.add_argument('--destination');a=p.parse_args()
    if a.command=='create':print(create(load_config(a.config),include_media=a.media))
    elif a.command=='verify':print(json.dumps(verify(a.folder),ensure_ascii=False))
    else:print(json.dumps(restore_candidate(a.folder,a.destination,include_media=not a.state_only),ensure_ascii=False))
