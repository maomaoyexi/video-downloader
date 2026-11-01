"""Import URL history as hints, never as proof of locally verified content."""
from __future__ import annotations

from urllib.parse import urlsplit,unquote

from .errors import FanboxError
from .urls import validate_resource_url


def resource_record_key(value):
    """Project a URL already checked by the transfer/parser boundary."""
    parsed=urlsplit(value)
    if not parsed.hostname:return ''
    return parsed.path if parsed.hostname.lower()=='downloads.fanbox.cc' else parsed.scheme+'://'+parsed.netloc+parsed.path


def record_path(value):
    if not isinstance(value,str) or not value or len(value)>8000 or any(ord(c)<32 for c in value) or '\\' in value:
        raise ValueError
    if '://' in value:
        try:validate_resource_url(value)
        except FanboxError:raise ValueError from None
        path=urlsplit(value).path
    else:
        if value.startswith('//') or ':' in value.split('/')[0]:raise ValueError
        path=urlsplit('/'+value.lstrip('/')).path
    decoded=unquote(path)
    if (not path.strip('/') or any(part in {'.','..'} for part in decoded.split('/'))
            or '\\' in decoded or any(ord(c)<32 for c in decoded)):raise ValueError
    return resource_record_key(value) if '://' in value else path


def preview_records(value):
    if not isinstance(value,list) or len(value)>1000:
        raise FanboxError('invalid_request','记录批次必须是最多 1000 项的数组')
    paths=[];rejected=[]
    for index,item in enumerate(value):
        try:paths.append(record_path(item.get('url') if isinstance(item,dict) else None))
        except ValueError:rejected.append(index)
    return list(dict.fromkeys(paths)),{'accepted':len(set(paths)),'duplicates':len(paths)-len(set(paths)),
                                     'rejected':len(rejected),'rejected_indices':rejected}
