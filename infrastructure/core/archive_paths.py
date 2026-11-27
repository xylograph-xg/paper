"""Durable directory moves that preserve relative runtime link destinations."""
import json
import os
from pathlib import Path

from .services import atomic_json


def move_with_links(source, destination):
    """Move a directory without copying target bytes; caller serializes writers.

    A durable, inode-bound journal resumes interrupted renames. Conflicting
    paths or changed links raise ValueError and retain the journal. Absolute
    links stay unchanged; internal links follow the moved directory.
    """
    source=Path(os.path.abspath(source));destination=Path(os.path.abspath(destination))
    if source==destination or source.is_relative_to(destination) or destination.is_relative_to(source):
        raise ValueError('移动目录必须互不包含')
    journal=destination.parent/('.'+destination.name+'.links-move.json')
    if journal.exists():
        record=json.loads(journal.read_text())
        if record.get('source')!=str(source) or record.get('destination')!=str(destination):
            raise ValueError('移动日志路径不匹配')
    else:
        if source.is_symlink() or not source.is_dir() or os.path.lexists(destination):
            raise ValueError('移动源无效或目标已存在')
        info=source.stat();links=[]
        for parent,dirs,files in os.walk(source,followlinks=False):
            for name in dirs+files:
                link=Path(parent)/name
                if not link.is_symlink():continue
                raw=os.readlink(link)
                if os.path.isabs(raw):continue
                target=Path(os.path.abspath(link.parent/raw))
                if target.is_relative_to(source):target=destination/target.relative_to(source)
                relative=link.relative_to(source)
                links.append({'path':str(relative),'old':raw,'new':os.path.relpath(target,(destination/relative).parent)})
        record={'schema_version':1,'source':str(source),'destination':str(destination),
                'inode':[info.st_dev,info.st_ino],'links':links}
        atomic_json(journal,record)
    if source.is_symlink() or destination.is_symlink():raise ValueError('移动根不能是软链接')
    if source.exists() and destination.exists():raise ValueError('移动路径冲突，不覆盖')
    root=source if source.exists() else destination
    info=root.stat()
    if [info.st_dev,info.st_ino]!=record['inode']:raise ValueError('移动根身份变化')
    for item in record['links']:
        relative=Path(item['path'])
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('移动日志含非法路径')
        link=root/relative
        if (not link.parent.resolve().is_relative_to(root.resolve()) or
                not link.is_symlink() or os.readlink(link) not in (item['old'],item['new'])):
            raise ValueError('归档链接已变化，不覆盖')
    if root==source:source.rename(destination)
    for item in record['links']:
        link=destination/item['path']
        if os.readlink(link)==item['new']:continue
        temporary=link.with_name('.'+link.name+'.move-link')
        if os.path.lexists(temporary):
            if not temporary.is_symlink() or os.readlink(temporary)!=item['new']:
                raise ValueError('移动临时链接冲突')
        else:temporary.symlink_to(item['new'])
        if os.readlink(link)!=item['old']:raise ValueError('归档链接并发变化')
        os.replace(temporary,link)
    journal.unlink()
    return str(destination)
