"""Read-only storage status works even with a worker from an older revision."""
import os
from .paths import WorkspacePath as Path


def status(config):
    volume=Path(config['archive_volume'])
    try:
        if not volume.is_dir() or (config.get('require_mounted_volume',True) and not volume.is_mount()):
            return {'state':'waiting_storage','reason':'外置 SSD 未挂载；拉取保持存活等待恢复，不回退到 Studio'}
        info=os.statvfs(volume)
        return {'state':'available','free_bytes':info.f_bavail*info.f_frsize}
    except OSError as exc:return {'state':'waiting_storage','reason':str(exc)}
