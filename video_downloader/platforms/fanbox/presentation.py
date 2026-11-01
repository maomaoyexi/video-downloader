"""Local UI projections. Resource credentials and source JSON stay in the archive."""
from __future__ import annotations

from .models import Asset,Post
from .naming import asset_path,post_directory
from .options import normalize_options
from .urls import source_for_options


def asset_rows(state,post,options):
    rows=[]
    for asset in post.assets:
        record=state.get('files',{}).get(post.id,{}).get(asset.id+':'+asset.variant,{})
        rows.append({'id':post.id+':'+asset.id+':'+asset.variant,'name':asset.name,'kind':asset.kind,
            'variant':asset.variant,'size':asset.size,'selected':asset.selected,'reason':asset.skip_reason,
            'status':record.get('status','excluded' if not asset.selected else 'pending'),'error':record.get('error'),
            'path':record.get('path') or asset_path(post,asset,options,state['task_date'])})
    return rows


def manifest(state):
    options=normalize_options(state['options'])
    posts=[]
    for value in (state.get('scan') or {}).get('posts',[]):
        post=Post.from_dict(value)
        posts.append({'id':post.id,'creator_id':post.creator_id,'title':post.title,'access':post.access,
            'published_at':post.published_at,'assets':asset_rows(state,post,options),
            'links':[{'url':link.url,'kind':link.kind} for link in post.links]})
    return {'schema_version':1,'source':state['source'],'status':state['status'],
            'counts':state.get('counts',{}),'coverage':state.get('scope',{}),'posts':posts}


def naming_preview(options,url='https://www.fanbox.cc/@creator'):
    options=normalize_options(options)
    source=source_for_options(url,options)
    date='2026-01-02T03:04:05+00:00'
    post=Post(source.post_id or '12345',source.creator_id or 'collection','67890','示例投稿','image',date,date,500,[],'accessible')
    assets=[Asset('image','image','illustration','png','',index=1),Asset('file','archive','attachment','zip','',index=2)]
    post.assets=assets
    return {'directory':post_directory(post,options,date),
            'files':[asset_path(post,asset,options,date) for asset in assets]}
