"""Expose the loopback workbench through a dedicated tailnet-only Serve port."""
import json
import shutil
import subprocess
from core.api import paths__WorkspacePath as Path


def setup(config,local_port):
    binary=shutil.which('tailscale') or '/Applications/Tailscale.app/Contents/MacOS/Tailscale'
    if not Path(binary).is_file():
        print('未找到 Tailscale，保留本机访问。',flush=True)
        return None
    def run(*args):
        result=subprocess.run([binary,*args],capture_output=True,text=True,timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        return result.stdout
    try:
        status=json.loads(run('status','--json'))
        if status.get('BackendState')!='Running':
            raise RuntimeError('请先连接 Tailscale')
        hostname=status['Self']['DNSName'].rstrip('.')
        remote_port=config.get('tailscale_port',8768)
        target=f'http://127.0.0.1:{local_port}'
        current=json.loads(run('serve','status','--json'))
        host=f'{hostname}:{remote_port}'
        if config.get('workbench_passwordless') is True and (current.get('AllowFunnel') or {}).get(host):
            raise RuntimeError(f'Tailscale 端口 {remote_port} 已启用公开 Funnel，免口令工作台仅提供本机访问')
        handlers=current.get('Web',{}).get(host,{}).get('Handlers',{})
        if str(remote_port) in current.get('TCP',{}):
            if handlers.get('/',{}).get('Proxy')!=target or len(handlers)!=1:
                raise RuntimeError(f'Tailscale 端口 {remote_port} 已供其他服务使用，未覆盖')
        else:
            run('serve','--bg',f'--http={remote_port}',target)
        url=f'http://{host}'
        print('Tailscale 工作台地址：'+url,flush=True)
        return url
    except (RuntimeError,OSError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
        print('Tailscale 链接配置未完成：'+str(exc)+'；保留本机访问。',flush=True)
        return None
