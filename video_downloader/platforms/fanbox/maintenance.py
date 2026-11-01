"""Explicit resume-cache cleanup, confined to known partials; saved files survive."""
from __future__ import annotations
import time

from .downloader import resource_key
from .errors import FanboxError
from .models import Post
from .naming import confined


def clear_resume_cache(application,job_id,expected):
    repository=application.repository
    token,_=repository.acquire('job:'+job_id)
    if token is None:raise FanboxError('job_busy','任务仍在运行')
    try:
        state=repository.job(job_id)
        if state is None:raise FanboxError('job_not_found','归档任务不存在')
        if state['version']!=expected:raise FanboxError('stale_version','任务版本已改变，请刷新后重试')
        if state['status'] in {'running','queued'}:raise FanboxError('job_busy','任务仍在运行或排队')
        removed=busy=0;heartbeat=time.monotonic()
        for value in (state.get('scan') or {}).get('posts',[]):
            post=Post.from_dict(value)
            for asset in post.assets:
                if time.monotonic()-heartbeat>20:repository.heartbeat(token);heartbeat=time.monotonic()
                key=resource_key(post,asset);lease,_=repository.acquire('asset:'+key)
                if lease is None:busy+=1;continue
                try:
                    for suffix in ('.part','.json'):
                        path=confined(application.root,'.fanbox/parts/'+key+suffix)
                        if path.is_file():path.unlink();removed+=1
                finally:repository.release(lease)
        state['checkpoint']=None
        state['resume_after']=None
        if (state.get('scan') or {}).get('status')!='completed':state['scan']=None
        repository.save_job(state)
        return state,{'removed':removed,'busy':busy}
    finally:repository.release(token)
