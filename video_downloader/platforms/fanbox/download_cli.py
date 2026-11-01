"""Native archive CLI independent of video executables and WebUI."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import threading

from .archive import ArchiveApplication
from .auth import load_credentials
from .cli import read_config, _read_json
from .errors import FanboxError
from .options import normalize_options


def main(argv=None,*,root=None):
    parser=argparse.ArgumentParser(description='FANBOX 内容归档')
    parser.add_argument('url',nargs='?')
    parser.add_argument('--directory',type=Path)
    parser.add_argument('--cookies',type=Path)
    parser.add_argument('--anonymous',action='store_true')
    parser.add_argument('--options',type=Path)
    parser.add_argument('--max-posts',type=int)
    parser.add_argument('--resume')
    parser.add_argument('--preview',action='store_true')
    args=parser.parse_args(argv)
    root=Path(root or Path(__file__).resolve().parents[3])
    try:
        if args.cookies and args.anonymous:
            raise FanboxError('invalid_config','匿名模式不能同时指定凭据文件')
        config=read_config(root)
        if not int(config.get('FANBOX_ENABLED',1)):
            raise FanboxError('platform_disabled','FANBOX 已关闭')
        options=_read_json(args.options,65536) if args.options else json.loads(config.get('FANBOX_OPTIONS','{}'))
        options=normalize_options(options)
        if args.max_posts is not None:options.setdefault('filters',{})['max_posts']=args.max_posts
        cookie=args.cookies or Path(config.get('FANBOX_COOKIE_FILE') or root/'cookies.txt')
        if not cookie.is_absolute():cookie=root/cookie
        use_cookies=not (args.anonymous or int(config.get('FANBOX_ANONYMOUS',0))) and (args.cookies is not None or int(config.get('USE_COOKIES',1)))
        credentials=load_credentials(cookie if use_cookies and (cookie.exists() or args.cookies is not None) else None)
        application=ArchiveApplication(args.directory or root/'download'/'Fanbox')
        if args.resume:
            job_id=args.resume
        else:
            if not args.url:raise FanboxError('invalid_url','请提供创作者主页或单帖链接')
            job_id=application.create(args.url,options)['id']
        cancel=threading.Event()
        try:
            result=application.run(job_id,credentials=credentials,config=config,cancel=cancel,preview=args.preview)
        except KeyboardInterrupt:
            cancel.set()
            return 130
        print(json.dumps(result,ensure_ascii=False))
        return 0 if result['status'] in {'completed','preview_ready'} else 2
    except (FanboxError,OSError):
        print(json.dumps({'status':'failed','error':'FANBOX 归档失败，请检查来源、配置与运行依赖'},ensure_ascii=False))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
