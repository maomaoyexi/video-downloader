"""Resumable list strategies: creator pages, account feed and tagged feed."""
from __future__ import annotations

from .errors import FanboxError
from .filters import post_reason


def list_posts(client,source,state,options,save,notify,summary_keys):
    maximum=options['filters']['max_posts']
    seen={post['id']:post['creatorId'] for post in state['summaries']}
    def at_limit():
        reached=maximum is not None and sum(post_reason(post,options) is None for post in state['summaries'])>=maximum
        if reached:state['limit_reached']=True
        return reached
    def add(batch):
        for post in batch:
            if post['id'] in seen:
                if seen[post['id']]!=post['creatorId']:raise FanboxError('schema_changed','投稿标识对应多个作者')
            else:
                seen[post['id']]=post['creatorId']
                state['summaries'].append({k:v for k,v in post.items() if k in summary_keys})
    def event(pages):
        if notify:notify('listing',{'pages':pages,'posts':len(state['summaries'])})
        save()
    if source.scope in {'tag','supporting'}:
        if source.scope=='tag' and 'tag_user_id' not in state:
            user_id=client.creator(source.creator_id)['user'].get('userId')
            if not isinstance(user_id,str) or not user_id.isascii() or not user_id.isdigit():
                raise FanboxError('schema_changed','标签作者数字 ID 响应结构变化')
            state['tag_user_id']=user_id;save()
        if state.get('feed_started') and state.get('next_url') is None:
            state['list_complete']=True;return
        while not at_limit():
            visited=state.setdefault('visited',[])
            url=state.get('next_url')
            marker=url or 'first'
            if marker in visited or len(visited)>=10000:raise FanboxError('pagination_cycle','帖子分页重复或超过保护上限')
            batch,next_url=client.feed_page(source,url,state.get('tag_user_id'))
            add(batch);visited.append(marker);state['feed_started']=True;state['next_url']=next_url
            if next_url is None:state['list_complete']=True
            event(len(visited))
            if next_url is None:return
        return
    if source.scope=='following':
        if state.get('members') is None:
            state['members']=client.following_creators();state['member_index']=0;save()
        members=state['members']
    else:members=[source.creator_id]
    while state.get('member_index',0)<len(members):
        if at_limit():return
        creator=members[state.get('member_index',0)]
        if state['pages'] is None:
            state['pages']=client.pages(creator);save()
        if len(state['pages'])>10000:raise FanboxError('page_limit','分页数量超过本地保护上限')
        while state['page_index']<len(state['pages']):
            if at_limit():return
            batch=client.page(state['pages'][state['page_index']],creator)
            add(batch);state['page_index']+=1
            state['listed_pages']=state.get('listed_pages',0)+1;event(state['listed_pages'])
        if source.scope!='following':break
        state['member_index']+=1;state['pages']=None;state['page_index']=0;save()
    state['list_complete']=True
