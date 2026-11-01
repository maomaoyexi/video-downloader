"""Independently drawn fan cards; reuse the archive transfer and quota boundary."""
from __future__ import annotations

import copy
from pathlib import Path
from urllib.parse import urlsplit
import uuid
import warnings

from .errors import FanboxError
from .models import Asset,Post
from .naming import confined
from .runtime import library


def render_card(target,card,background=None):
    Image=library('PIL.Image');Draw=library('PIL.ImageDraw');Font=library('PIL.ImageFont');Ops=library('PIL.ImageOps')
    canvas=Image.new('RGB',(1280,800),'#292d34')
    if background:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error',Image.DecompressionBombWarning)
                with Image.open(background) as image:
                    if image.width*image.height>24_000_000:raise ValueError
                    canvas.paste(Ops.fit(image.convert('RGB'),(1280,800)),(0,0))
        except (OSError,ValueError,Image.DecompressionBombError,Image.DecompressionBombWarning):
            raise FanboxError('invalid_payload','粉丝卡背景图片无法安全解码') from None
    overlay=Image.new('RGBA',canvas.size,(0,0,0,0))
    draw=Draw.Draw(overlay);draw.rectangle((0,420,1280,800),fill=(12,17,24,220))
    canvas=Image.alpha_composite(canvas.convert('RGBA'),overlay).convert('RGB');draw=Draw.Draw(canvas)
    def font(size):
        for path in (Path('C:/Windows/Fonts/msyh.ttc'),Path('C:/Windows/Fonts/meiryo.ttc'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')):
            if path.is_file():return Font.truetype(str(path),size)
        return Font.load_default(size=size)
    def line(text,y,size,color='white'):
        text=' '.join(str(text).split())[:2000];face=font(size)
        while text and draw.textlength(text,font=face)>1150:text=text[:-2]+'…' if len(text)>2 else ''
        draw.text((64,y),text,font=face,fill=color)
    line('FANBOX  /  FAN CARD',48,28)
    line(card['creator_name'],452,48)
    line(f"{card['title']}  ·  ¥{card['fee']:,} / month",532,30)
    line('Since '+card['since'][:10],602,26,'#cbd3dd')
    if card['username']:line(card['username'],680,32)
    temporary=target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        canvas.save(temporary,format='PNG');temporary.replace(target)
    finally:temporary.unlink(missing_ok=True)


def save_card(root,client,downloader,creator,options,task_date):
    settings=options['fan_cards']
    card=client.fan_card(creator,show_username=settings['show_username'])
    background=None
    if card['background']:
        suffix=Path(urlsplit(card['background']).path).suffix.lower().lstrip('.')
        suffix=suffix if suffix in {'jpg','jpeg','png','webp','gif'} else 'bin'
        asset=Asset('background','image','background',suffix,card['background'])
        model=Post('fan-card',creator,'',card['title'],'fan_card',task_date,task_date,card['fee'],[],'accessible')
        transfer_options=copy.deepcopy(options)
        transfer_options['naming'].update(post_dir='{creator_id}/fan-cards',images='background.{ext}',layout='post_directory',conflict='overwrite')
        transfer_options['content']['image_fallback']='never'
        result=downloader.download(model,asset,transfer_options,task_date)
        if result['status'] not in {'completed','reused'}:raise FanboxError('card_background_failed','粉丝卡背景未能保存')
        background=confined(root,result['path'])
    # Keep the optional username out of paths, logs and the job's metadata.
    relative=f'{creator}/fan-cards/{task_date[:10]}-'+('named' if settings['show_username'] else 'anonymous')+'.png'
    target=confined(root,relative,create=True)
    render_card(target,card,background)
    return {'creator_id':creator,'status':'completed','path':relative}
