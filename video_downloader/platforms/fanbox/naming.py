"""Portable path templates and archive-root confinement, independent of IO policy."""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path
import re
import stat
import calendar
from zoneinfo import ZoneInfo

from .errors import FanboxError
from .options import timestamp

_RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[0-9¹²³]|LPT[0-9¹²³])(?:\.|$)', re.I)


def component(value):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', str(value)).strip().rstrip('. ')
    value = value or '_'
    if _RESERVED.match(value):
        value = '_'+value
    if len(value.encode('utf-8')) > 120:
        value = value.encode('utf-8')[:95].decode('utf-8','ignore')+'-'+hashlib.sha256(value.encode()).hexdigest()[:12]
    return value


def date_string(value, pattern):
    date = timestamp(value) if isinstance(value,str) else value
    mapping = dict(YYYY=f'{date.year:04}', MM=f'{date.month:02}', DD=f'{date.day:02}',
                   hh=f'{date.hour:02}', mm=f'{date.minute:02}', ss=f'{date.second:02}',
                   YY=f'{date.year%100:02}',MMM='Sept' if date.month==9 else calendar.month_abbr[date.month],
                   MMMM=calendar.month_name[date.month])
    return re.sub('YYYY|YY|MMMM|MMM|MM|DD|hh|mm|ss',lambda m:mapping[m[0]],pattern)


def render(template, values):
    if not template or template.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:',template):
        raise FanboxError('unsafe_path','文件名模板必须是相对路径')
    if '\\' in template or any(p in {'.','..'} for p in template.split('/')):
        raise FanboxError('unsafe_path','文件名模板包含越界路径')
    leftover=re.sub(r'\{[^{}]+\}','',template)
    if '{' in leftover or '}' in leftover:
        raise FanboxError('invalid_template','文件名模板格式无效')
    def token(match):
        if match[1] not in values:
            raise FanboxError('invalid_template','文件名模板包含未知变量')
        return component(values[match[1]]) if str(values[match[1]]) else ''
    value = re.sub(r'\{([^{}]+)\}',token,template)
    parts = [component(part) for part in value.split('/') if part.strip()]
    if not parts or len(parts)>10:
        raise FanboxError('unsafe_path','文件名路径层级无效')
    return '/'.join(parts)


def values_for(post, asset, options, task_date):
    naming = options['naming']
    counts = {k:sum(a.kind==k for a in post.assets if a.selected) for k in ('image','video','audio')}
    pva = ''.join(f'{counts[k]}{v}' for k,v in [('image','P'),('video','V'),('audio','A')] if counts[k])
    result = dict(creator_id=post.creator_id,user_id=post.user_id,post_id=post.id,title=post.title,
                  user=(post.source or {}).get('user',{}).get('name',post.creator_id),
                  tags=','.join(post.tags),fee=post.fee,PVA=f'【{pva}】' if pva else '',
                  date=date_string(timestamp(post.published_at).astimezone(ZoneInfo(naming['timezone'])),naming['date_format']),
                  task_date=date_string(timestamp(task_date).astimezone(ZoneInfo(naming['timezone'])),naming['date_format']), name=asset.name if asset else 'post',
                  ext=asset.extension if asset else '',index=(str(asset.index).zfill(naming['pad_width'])
                      if naming['zero_pad'] else str(asset.index)) if asset else '')
    result.update(postid=post.id,create_id=post.creator_id,uid=post.user_id)
    return result


def post_directory(post, options, task_date):
    return render(options['naming']['post_dir'],values_for(post,None,options,task_date))


def asset_path(post, asset, options, task_date):
    values = values_for(post,asset,options,task_date)
    if asset.kind=='cover':
        relative = post_directory(post,options,task_date)+'/cover'
    else:
        from .options import DEFAULT_OPTIONS
        slot='images' if asset.kind=='image' else 'attachments'
        template = options['naming'][slot] or DEFAULT_OPTIONS['naming'][slot]
        relative = render(template,values)
        if options['naming']['layout']=='post_directory':
            relative = post_directory(post,options,task_date)+'/'+relative
    extension = re.sub('[^a-zA-Z0-9]','',asset.extension)[:16] or 'bin'
    if not relative.lower().endswith('.'+extension.lower()):
        relative += '.'+extension
    # Keep headroom for temporary suffixes in Windows installations.
    if len(relative)>195:
        path=Path(relative)
        relative='/'.join([component(post.creator_id),post.id,path.name[:80]+'-'+hashlib.sha256(relative.encode()).hexdigest()[:12]+'.'+extension])
    return relative


def confined(root, relative, *, create=False):
    root = Path(root).absolute()
    path = Path(relative)
    if path.is_absolute() or not path.parts or any(p in {'.','..'} for p in path.parts) or ':' in str(path):
        raise FanboxError('unsafe_path','归档路径超出目录范围')
    current = root
    for part in ('',*path.parts):
        if part: current /= part
        if current.exists() or current.is_symlink():
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
                raise FanboxError('unsafe_path','归档路径包含链接或重解析点')
    target=root/path
    if not target.resolve().is_relative_to(root.resolve()):
        raise FanboxError('unsafe_path','归档路径超出目录范围')
    if create:
        target.parent.mkdir(parents=True,exist_ok=True)
        return confined(root,relative)
    return target
