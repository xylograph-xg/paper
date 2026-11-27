"""Shared ZIP prestore for newly submitted web-card materials; never alters old attempts."""
from core.api import paths__WorkspacePath as Path
from codex_desktop_chat.api import bundles__prepare_upload_bundle as prepare_upload_bundle
from cards.api import web_card_inputs__digest as digest

ZIP_INSTRUCTION = '\n附件为一个ZIP材料包。请先解压并核对文件清单，再逐一读取原文、视觉证据与上下文；如果不能解压或任一文件不可读，明确标注缺失输入，不猜测内容，不声明科学核验完成。'

class UploadSizeError(ValueError):
    """A local deterministic limit, never an account quota or network failure."""

def check_zip_size(bundle):
    if bundle.get('size',0)>50*1024*1024:
        raise UploadSizeError('冻结ZIP超过本地远程浏览器50MiB传输能力；保留原包，未启动附件上传')

def prepare_web_upload(folder, packet):
    folder=Path(folder)
    for name,expected in packet['input_hashes'].items():
        if digest(folder/name)!=expected:raise ValueError('冻结材料指纹变化，不能打包上传')
    bundle=prepare_upload_bundle([str(folder/n) for n in packet['files']])
    check_zip_size(bundle)
    return bundle,(folder/'prompt.txt').read_text()+ZIP_INSTRUCTION
