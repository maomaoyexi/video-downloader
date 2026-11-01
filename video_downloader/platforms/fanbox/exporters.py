"""Offline, escaped archives; no remote scripts, embedded HTML or remote media."""
from __future__ import annotations

import html
import os
import tempfile
from pathlib import Path
from urllib.parse import quote

from .naming import confined, post_directory
from .links import clean_link
from .service import write_json


def write_text(path,text):
    path=Path(path)
    descriptor,name=tempfile.mkstemp(prefix=path.name+'.',suffix='.tmp',dir=path.parent)
    temporary=Path(name)
    try:
        with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as file:
            file.write(text);file.flush();os.fsync(file.fileno())
        os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)


def comment_lines(items,depth=0):
    if depth>=20:return
    for item in items:
        if not isinstance(item,dict):continue
        user=item.get('user');name=user.get('name','') if isinstance(user,dict) else ''
        value=item.get('body','')
        if isinstance(value,str):yield ('  '*depth)+(name+': ' if isinstance(name,str) and name else '')+value
        replies=item.get('replies',[])
        if isinstance(replies,dict):replies=replies.get('items',[])
        if isinstance(replies,list):yield from comment_lines(replies,depth+1)


def paragraph_html(block):
    text=block.get('text','')
    units=text.encode('utf-16-le')
    spans=[]
    for key in ('styles','links'):
        for span in block.get(key,[]):
            if not isinstance(span,dict):continue
            start,length=span.get('offset'),span.get('length')
            if type(start) is not int or type(length) is not int or start<0 or length<=0 or (start+length)*2>len(units):continue
            spans.append((start*2,(start+length)*2,span,key))
    points=sorted({0,len(units),*(point for a,b,_,_ in spans for point in (a,b))})
    result=[]
    for start,end in zip(points,points[1:]):
        fragment=html.escape(units[start:end].decode('utf-16-le','replace')).replace('\n','<br>')
        active=[(span,key) for a,b,span,key in spans if a<=start and end<=b]
        if any(span.get('type')=='bold' for span,key in active if key=='styles'):
            fragment='<strong>'+fragment+'</strong>'
        link=next((clean_link(span.get('url'),'https://www.fanbox.cc/') for span,key in active if key=='links'),None)
        if link:
            fragment='<a rel="noopener noreferrer" href="'+html.escape(link,quote=True)+'">'+fragment+'</a>'
        result.append(fragment)
    return ''.join(result)


def export_index(root,state):
    from .urls import parse_source
    source=parse_source(state['source'])
    creator=source.creator_id or '_collections/'+source.scope
    relative=f'{creator}/_jobs/{state["id"]}/index.html'
    target=confined(root,relative,create=True)
    titles={p['id']:p['title'] for p in state['scan']['posts']}
    links=[]
    for entry in state['archives']:
        path=confined(root,entry['index'])
        href=quote(Path(os.path.relpath(path,target.parent)).as_posix(),safe='/')
        links.append('<li><a href="'+html.escape(href,quote=True)+'">'+html.escape(titles[entry['post_id']])+'</a></li>')
    for card in state.get('fan_cards',[]):
        if card['status']!='completed':continue
        path=confined(root,card['path'])
        href=quote(Path(os.path.relpath(path,target.parent)).as_posix(),safe='/')
        links.append('<li><a href="'+html.escape(href,quote=True)+'">粉丝卡 · '+html.escape(card['creator_id'])+'</a></li>')
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<style>body{max-width:900px;margin:2rem auto;padding:0 1rem;font-family:system-ui;line-height:1.8;overflow-wrap:anywhere}a{color:#2369a8}@media(prefers-color-scheme:dark){body{background:#202124;color:#eee}a{color:#8ab4f8}}</style>'''
    page+='<title>'+html.escape(creator)+'</title><h1>'+html.escape(creator)+'</h1><p>'+html.escape(state['status'])+'</p><ul>'+''.join(links)+'</ul></html>'
    write_text(target,page)
    return relative


def export_post(root,repository,post,options,task_date,files):
    candidate=post_directory(post,options,task_date)
    if not any(token in options['naming']['post_dir'] for token in ('{post_id}','{postid}')):
        candidate+=f' [{post.id}]'
    folder=repository.allocate('post:'+post.creator_id+':'+post.id,candidate,
                               exists=lambda name:confined(root,name).exists())
    directory=confined(root,folder+'/post.json',create=True).parent
    records=[]
    for asset in post.assets:
        result=files.get(asset.id+':'+asset.variant,{})
        records.append(dict({'asset_id':asset.id,'kind':asset.kind,'name':asset.name,
                            'selected':asset.selected,'variant':asset.variant},**result))
    write_json(confined(root,folder+'/post.json'),dict(post.to_dict(),files=records))
    if options['content']['comments']:
        write_json(confined(root,folder+'/comments.json'),{'complete':post.comments_complete,'comments':post.comments})
    if options['content']['links']:
        write_json(confined(root,folder+'/links.json'),[dict(url=l.url,kind=l.kind,occurrences=l.occurrences) for l in post.links])
        write_text(confined(root,folder+'/links.txt'),'\n\n'.join(l.url+'\n'+'\n'.join(o.get('context','') for o in l.occurrences) for l in post.links))
    text=[post.title,post.published_at]
    body=[]
    escape=lambda value:html.escape(str(value),quote=True)
    for block in post.blocks:
        kind=block['type']
        if 'text' in block:
            text.append(block['text'])
            tag='h2' if kind=='header' else 'p'
            body.append(f'<{tag}>'+paragraph_html(block)+f'</{tag}>')
        elif kind in {'image','file'}:
            asset=next((a for a in post.assets if a.id==block.get('asset_id')),None)
            result=files.get(asset.id+':'+asset.variant,{}) if asset else {}
            label=asset.name if asset else '缺失资源'
            if result.get('status') in {'completed','reused','degraded'}:
                target=confined(root,result['path'])
                relative=quote(Path(os.path.relpath(target,directory)).as_posix(),safe='/')
                text.append(label+' '+relative)
                body.append(f'<figure><img loading="lazy" src="{escape(relative)}" alt="{escape(label)}"><figcaption>{escape(label)}</figcaption></figure>'
                            if kind=='image' else f'<p><a href="{escape(relative)}">{escape(label)}</a></p>')
            else:
                text.append('['+label+']')
                body.append('<p class="missing">['+escape(label)+']</p>')
        elif kind=='embed':
            for url in block.get('urls',[]):
                body.append(f'<p><a rel="noopener noreferrer" href="{escape(url)}">{escape(url)}</a></p>')
                text.append(url)
        else:
            body.append('<p class="missing">[未知内容]</p>')
    if options['content']['comments']:
        comments=list(comment_lines(post.comments))
        if comments:
            text.extend(['评论',*comments]);body.append('<section><h2>评论</h2>'+''.join('<p>'+escape(line).replace('\n','<br>')+'</p>' for line in comments)+'</section>')
        if not post.comments_complete:
            text.append('[评论未完整]');body.append('<p class="missing">评论未完整</p>')
    if options['content']['body']:
        for fmt in options['content']['body_formats']:
            if fmt in {'txt','md'}:
                write_text(confined(root,folder+'/post.'+fmt),'\n\n'.join(text))
            elif fmt=='html':
                document='''<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' file:; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<style>body{max-width:900px;margin:2rem auto;padding:0 1rem;font-family:system-ui;line-height:1.7;overflow-wrap:anywhere}img{max-width:100%;height:auto}figure{margin:1rem 0}.missing{color:#777}a{color:#1a6bbe}@media(prefers-color-scheme:dark){body{background:#202124;color:#eee}a{color:#8ab4f8}}</style>'''
                document+='<title>'+escape(post.title)+'</title><h1>'+escape(post.title)+'</h1>'+''.join(body)+'</html>'
                write_text(confined(root,folder+'/post.html'),document)
    return {'post_id':post.id,'directory':folder,'index':folder+('/post.html' if options['content']['body'] and 'html' in options['content']['body_formats'] else '/post.json')}
