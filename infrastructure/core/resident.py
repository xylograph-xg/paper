"""Install the two explicitly authorized user-session resident services."""
import argparse
import json
import os
import plistlib
import subprocess
from .paths import WorkspacePath as Path
from .catalog import ROOT,load_config,now
from .services import atomic_json


def definitions(config):
    folder=Path(config['catalog_path']).parent
    return {
      'local.paper.fetch': [str(Path.home() / 'venv/bin/python'),'-u','-m','fetch.fetch_service','--config',config['_config_path']],
      'local.paper.web-cards': [config['web_cards']['python'],'-u','-m','cards.web_card_service','run','--config',config['_config_path']],
      'local.paper.web-tab-watch': [config['web_cards']['python'],'-u','-m','maintenance.web_tab_watch','run','--config',config['_config_path']],
    }


def install(config):
    """Only called after user requests resident fetch/web; never unpauses local models."""
    folder=Path(config['catalog_path']).parent;logs=folder/'logs';logs.mkdir(parents=True,exist_ok=True)
    launch_dir=Path.home()/'Library/LaunchAgents';launch_dir.mkdir(parents=True,exist_ok=True)
    results={};domain=f'gui/{os.getuid()}'
    for label,args in definitions(config).items():
        path=launch_dir/(label+'.plist')
        if path.exists():
            with path.open('rb') as stream:old=plistlib.load(stream)
            if old.get('WorkingDirectory')!=str(ROOT):raise ValueError('常驻标签已被其他项目使用，不覆盖')
        spec={'Label':label,'ProgramArguments':args,'WorkingDirectory':str(ROOT),'RunAtLoad':True,
              'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':30,
              'StandardOutPath':str(logs/(label+'.log')),'StandardErrorPath':str(logs/(label+'.log')),
              'EnvironmentVariables':{'PATH':'/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'}}
        with path.open('wb') as stream:plistlib.dump(spec,stream)
        existing=subprocess.run(['launchctl','print',domain+'/'+label],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        result=subprocess.run(['launchctl','kickstart',domain+'/'+label] if existing.returncode==0 else ['launchctl','bootstrap',domain,str(path)],text=True,capture_output=True)
        results[label]={'plist':str(path),'returncode':result.returncode,'error':result.stderr[-700:]}
    atomic_json(folder/'resident-services.json',{'installed_at':now(),'services':results,'scope':'main fetch plus web cards only; local model controls untouched'})
    if any(x['returncode'] for x in results.values()):raise RuntimeError('部分常驻服务安装失败：'+json.dumps(results,ensure_ascii=False))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=('install','status'));p.add_argument('--config');a=p.parse_args();c=load_config(a.config)
    if a.command=='install':print(json.dumps(install(c),ensure_ascii=False,indent=2))
    else:
        from fetch.api import fetch_service__status as fetch_status
        from cards.api import web_card_service__status as web_status
        print(json.dumps({'fetch':fetch_status(c),'web_cards':web_status(c)},ensure_ascii=False,indent=2))
