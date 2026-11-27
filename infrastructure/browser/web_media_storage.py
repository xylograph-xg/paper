"""Keep web input payloads on the mounted SSD, receipts in the local catalog tree."""
import os
from core.api import paths__WorkspacePath as Path


def require_volume(media_root, media_volume):
    if not media_root:
        return
    volume = Path(media_volume or '')
    if not media_volume or not volume.is_mount():
        raise OSError('外置SSD未挂载，等待恢复；不在内部磁盘创建材料副本')
    if not Path(media_root).resolve().is_relative_to(volume.resolve()):
        raise ValueError('材料目录必须位于指定SSD内')


def bind_inputs(folder, paper_id, media_root=None, media_volume=None):
    if not media_root:
        return
    require_volume(media_root, media_volume)
    folder = Path(folder)
    if Path(paper_id).name != paper_id or paper_id in ('.', '..'):
        raise ValueError('无效材料ID')
    target = Path(media_root)/paper_id
    target.mkdir(parents=True, exist_ok=True)
    (target/'pages').mkdir(exist_ok=True)
    for name in ('pages', 'source.pdf', 'visual.pdf'):
        path = folder/name
        # Never redirect already prepared/frozen files; migration handles those separately.
        if path.exists() or path.is_symlink():
            continue
        path.symlink_to(os.path.relpath(target/name, folder), target_is_directory=name=='pages')


def require_config_storage(config):
    media = config.get('web_cards', {}).get('media_root')
    if media:
        require_volume(media, config['archive_volume'])
