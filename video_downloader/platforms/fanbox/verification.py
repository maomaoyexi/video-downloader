"""Explicit local verification. No network, file deletion or success-index mutation."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import threading
import time

from .errors import FanboxError
from .naming import confined


def report_header(report,version=None):
    if report is None:return None
    result={key:copy.deepcopy(value) for key,value in report.items() if key!='issues'}
    if version is not None and report['job_version']!=version:result['status']='stale'
    return result


def verify_file(root,record,cancel,on_bytes):
    digest=record.get('sha256');size=record.get('size')
    if not isinstance(digest,str) or re.fullmatch('[a-f0-9]{64}',digest) is None or type(size) is not int or size<0:
        return 'unverified'
    path=confined(root,record['path'])
    try:
        with path.open('rb') as file:
            before=os.fstat(file.fileno())
            if before.st_size!=size:return 'modified'
            actual=hashlib.sha256()
            while True:
                if cancel.is_set():raise FanboxError('cancelled','资源校验已停止')
                chunk=file.read(1024*1024)
                if not chunk:break
                actual.update(chunk);on_bytes(len(chunk))
            after=os.fstat(file.fileno());current=path.stat()
            if ((before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino)
                    or (current.st_ino,current.st_mtime_ns)!=(after.st_ino,after.st_mtime_ns)):
                return 'busy'
            return 'ok' if actual.hexdigest()==digest else 'modified'
    except FileNotFoundError:return 'missing'
    except OSError:return 'unreadable'


class VerificationService:
    def __init__(self,application,publish,*,progress_interval=.5):
        self.application=application;self.publish=publish;self.progress_interval=progress_interval
        self.lock=threading.RLock();self.thread=None;self.cancel_event=None;self.job_id=None

    def stop(self):
        with self.lock:
            if self.cancel_event:self.cancel_event.set()
            thread=self.thread
        if thread:thread.join(timeout=2)

    def cancel(self,job_id):
        with self.lock:
            if self.job_id==job_id and self.cancel_event:self.cancel_event.set()

    def start(self,job_id,version):
        with self.lock:
            if self.thread and self.thread.is_alive():
                if self.job_id==job_id:return self.application.repository.verification(job_id)
                raise FanboxError('verification_busy','另一个资源校验仍在进行')
            repository=self.application.repository;token,_=repository.acquire('job:'+job_id)
            if token is None:raise FanboxError('job_busy','任务仍在运行')
            try:
                state=repository.job(job_id)
                if state is None:raise FanboxError('job_not_found','归档任务不存在')
                if state['version']!=version:raise FanboxError('stale_version','任务版本已改变，请刷新后重试')
                if state['status'] in {'queued','running'}:raise FanboxError('job_busy','下载任务仍在运行或排队')
                records=[];paths=set()
                for files in state.get('files',{}).values():
                    for record in files.values():
                        path=record.get('path')
                        if record.get('status') not in {'completed','reused','degraded'} or not isinstance(path,str) or path.casefold() in paths:continue
                        paths.add(path.casefold());records.append(copy.deepcopy(record))
                if not records:raise FanboxError('nothing_to_verify','没有可校验的已下载资源')
                report=dict(status='running',job_version=version,total=len(records),checked=0,bytes_read=0,
                    ok=0,missing=0,modified=0,unreadable=0,unverified=0,busy=0,issues=[],truncated=False,
                    started=time.time(),updated=time.time())
                repository.save_verification(job_id,report)
                self.job_id=job_id;self.cancel_event=threading.Event()
                self.thread=threading.Thread(target=self._run,args=(job_id,records,report,token,self.cancel_event),
                                             name='fanbox-verify',daemon=True)
                self.thread.start();return copy.deepcopy(report)
            except BaseException:repository.release(token);raise

    def _run(self,job_id,records,report,token,cancel):
        repository=self.application.repository;last=[0.];asset_lease=[None]
        def save(force=False):
            now=time.monotonic()
            if not force and now-last[0]<self.progress_interval:return
            repository.heartbeat(token)
            if asset_lease[0]:repository.heartbeat(asset_lease[0])
            report['updated']=time.time()
            repository.save_verification(job_id,report);last[0]=now
            try:self.publish(job_id,report_header(report))
            except Exception:pass
        def progress(count):report['bytes_read']+=count;save()
        try:
            save(True)
            for record in records:
                if cancel.is_set():raise FanboxError('cancelled','资源校验已停止')
                key=record.get('key') or hashlib.sha256(record['path'].casefold().encode()).hexdigest()
                lease,_=repository.acquire('asset:'+str(key))
                asset_lease[0]=lease
                try:
                    if lease is None:status='busy'
                    else:
                        try:status=verify_file(self.application.root,record,cancel,progress)
                        except FanboxError as error:
                            if error.code=='cancelled':raise
                            status='unreadable'
                    report['checked']+=1;report[status]+=1
                    if status!='ok':
                        if len(report['issues'])<500:report['issues'].append({'path':record['path'],'status':status})
                        else:report['truncated']=True
                    save()
                finally:
                    asset_lease[0]=None
                    if lease:repository.release(lease)
            report['status']='completed' if report['ok']==report['total'] else 'partial'
        except FanboxError as error:report['status']='cancelled' if error.code=='cancelled' else 'failed'
        except Exception:report['status']='failed'
        finally:
            try:save(True)
            finally:repository.release(token)
