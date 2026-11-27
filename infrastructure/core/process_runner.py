"""Bounded child sessions with kernel-backed parent leases for nested bridges."""
import os,signal,subprocess

def watch_parent():
    lease=os.environ.pop('PAPER_PARENT_LEASE_FD',None)
    if lease is not None:
        from .runtime import watch_supervisor
        return watch_supervisor(int(lease))

def run(args,*,timeout=None,input=None,check=False,capture_output=False,**kwargs):
    if capture_output:kwargs.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    read_fd,write_fd=os.pipe();process=None
    env=dict(kwargs.pop('env',os.environ));env['PAPER_PARENT_LEASE_FD']=str(read_fd)
    inherited=tuple(kwargs.pop('pass_fds',()))
    try:
        process=subprocess.Popen(args,start_new_session=True,stdin=subprocess.PIPE if input is not None else kwargs.pop('stdin',None),env=env,pass_fds=(*inherited,read_fd),**kwargs)
        os.close(read_fd);read_fd=None
        try:out,err=process.communicate(input,timeout=timeout)
        except BaseException:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.communicate();raise
        result=subprocess.CompletedProcess(args,process.returncode,out,err)
        if check and result.returncode:raise subprocess.CalledProcessError(result.returncode,args,out,err)
        return result
    finally:
        os.close(write_fd)
        if read_fd is not None:os.close(read_fd)
