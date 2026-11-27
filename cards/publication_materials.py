"""Copy verified publication evidence while respecting existing SSD aliases."""
import shutil
from core.api import paths__WorkspacePath as Path
from .web_card_inputs import digest


def copy(folder,output):
    folder=Path(folder);output=Path(output)
    source=folder/'source.pdf';destination=output/'source.pdf'
    expected=digest(source)
    if not (destination.exists() and source.samefile(destination)):
        shutil.copy2(source,destination)
    if digest(destination)!=expected:raise ValueError('发布原文复制指纹不一致')
    pages=folder/'pages';target=output/'pages'
    if not (target.exists() and pages.samefile(target)):
        shutil.copytree(pages,target,dirs_exist_ok=True)
