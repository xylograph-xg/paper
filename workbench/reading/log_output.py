"""Bound Python child logs in the child, surviving a one-shot launcher exit."""
import logging
from logging.handlers import RotatingFileHandler
import re
import subprocess
import sys

class OperationalHandler(RotatingFileHandler):
    def handleError(self,record):
        # Never recurse through the redirected stderr on a full disk.
        if sys.__stderr__:
            sys.__stderr__.write('operational log write failed\n');sys.__stderr__.flush()

class LogStream:
    def __init__(self,handler):self.handler=handler
    def write(self,text):
        clean=re.sub(r'(#access=|PaperSession=|X-Paper-Token[:=] ?)[A-Za-z0-9_-]+',r'\1[redacted]',text)
        for offset in range(0,len(clean),8192):
            self.handler.emit(logging.LogRecord('child',logging.INFO,'',0,clean[offset:offset+8192].rstrip('\n'),(),None))
        return len(text)
    def flush(self):self.handler.flush()
    def isatty(self):return False


def run_logged():
    import runpy
    path,*arguments=sys.argv[1:]
    while arguments and arguments[0]=='-u':arguments.pop(0)
    handler=OperationalHandler(path,maxBytes=5*1024*1024,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    sys.stdout=sys.stderr=LogStream(handler)
    mode,target,*rest=arguments
    if mode=='-m':
        sys.argv=[target,*rest];runpy.run_module(target,run_name='__main__',alter_sys=True)
    elif mode=='-c':
        sys.argv=['-c',*rest];exec(compile(target,'<string>','exec'),{'__name__':'__main__'})
    else:raise ValueError('日志入口只支持Python -m/-c')


def spawn_logged(args, path, **kwargs):
    arguments=list(args[1:])
    while arguments and arguments[0]=='-u':arguments.pop(0)
    if not arguments or arguments[0] not in ('-m','-c'):raise ValueError('日志入口只支持Python -m/-c')
    # Same child process and PID; no parent-owned drain thread or extra daemon.
    return subprocess.Popen([args[0],'-u','-c','from reading.log_output import run_logged; run_logged()',str(path),*arguments],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**kwargs)
