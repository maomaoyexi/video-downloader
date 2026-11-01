"""Read-only scans with validated, resumable checkpoints; no attachment requests."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from collections import Counter

from .client import FanboxClient
from .errors import FanboxError
from .filters import post_reason
from .links import LinkCollector
from .models import Post
from .options import normalize_options, options_json
from .parsers import parse_post
from .urls import parse_source,source_for_options
from .listing import list_posts

_STOP_ERRORS = {"cancelled", "rate_limited", "challenge_required", "access_denied"}
_SUMMARY_KEYS = {"id", "creatorId", "title", "feeRequired", "publishedDatetime",
                 "updatedDatetime", "tags", "isRestricted"}


def write_json(path: Path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=path.name+".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(value, file, ensure_ascii=False, indent=2)
            file.flush();os.fsync(file.fileno())
        os.replace(name, path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


class ScanService:
    def __init__(self, client: FanboxClient):
        self.client = client

    def scan(self, url, options=None, *, checkpoint=None, save_checkpoint=None, auth_scope="anonymous",notify=None):
        options = normalize_options(options)
        source = source_for_options(url,options)
        digest = hashlib.sha256(options_json(options).encode()).hexdigest()
        if checkpoint is not None:
            state = self._restore(checkpoint, source.url, digest, auth_scope)
        else:
            state = {"schema_version":1, "source":source.url, "options_digest":digest,
                     "auth_scope":auth_scope, "pages":None, "page_index":0, "summaries":[],
                     "posts":{}, "errors":[], "list_complete":False, "limit_reached":False}
        state["errors"] = []

        def save():
            if save_checkpoint: save_checkpoint(copy.deepcopy(state))

        def failure(stage, error, post_id=None):
            state["errors"].append(dict(stage=stage, post_id=post_id, **error.to_dict()))
            save()

        maximum = options["filters"]["max_posts"]
        initial_details = {}
        try:
            if source.scope == "post":
                if not state["summaries"]:
                    post = self.client.post(source.post_id, source.creator_id)
                    initial_details[post["id"]] = post
                    state["summaries"].append({k:v for k,v in post.items() if k in _SUMMARY_KEYS})
                state["list_complete"] = True
            else:
                list_posts(self.client,source,state,options,save,notify,_SUMMARY_KEYS)
        except FanboxError as error:
            failure("listing", error)
            if error.code in _STOP_ERRORS:
                return self._result(state, options)

        selected = 0
        for summary in state["summaries"]:
            post_id = summary["id"]
            reason = post_reason(summary, options)
            if reason is not None:
                continue
            if maximum is not None and selected >= maximum:
                state["limit_reached"] = True
                break
            selected += 1
            if post_id in state["posts"]:
                if state["posts"][post_id]["comments_complete"]:
                    continue
            try:
                data = initial_details.get(post_id) or self.client.post(post_id, summary['creatorId'])
                post = parse_post(data, options)
                if options["content"]["comments"] and data.get("commentCount") != 0:
                    post.comments, post.comments_complete, warning = self.client.comments(
                        post_id, options["content"]["comment_max_pages"])
                    if warning: post.warnings.append(warning)
                    if options["content"]["links"]:
                        collector = LinkCollector(f"https://www.fanbox.cc/@{post.creator_id}/posts/{post.id}")
                        for link in post.links:
                            for occurrence in link.occurrences:
                                collector.add(link.url, source=occurrence["source"], index=occurrence["block_index"], context=occurrence["context"])
                        self._comment_links(post.comments, collector)
                        post.links = collector.links
                state["posts"][post_id] = post.to_dict()
                if notify:notify('post',{'id':post_id,'restricted':post.access=='restricted','files':sum(a.selected for a in post.assets)})
                save()
            except FanboxError as error:
                failure("post", error, post_id)
                if error.code in _STOP_ERRORS: break
        save()
        return self._result(state, options)

    @staticmethod
    def _comment_links(comments, collector, depth=0):
        if depth >= 20: return
        for item in comments:
            text = item.get("body", "")
            if isinstance(text, str): collector.text(text, source="comment", comment_id=str(item.get("id", "")))
            replies = item.get("replies", [])
            if isinstance(replies, dict): replies = replies.get("items", [])
            if isinstance(replies, list): ScanService._comment_links(replies, collector, depth+1)

    @staticmethod
    def _restore(checkpoint, url, digest, auth_scope):
        try:
            state = copy.deepcopy(checkpoint)
            if (type(state["schema_version"]) is not int or state["schema_version"] != 1 or state["source"] != url
                    or state["options_digest"] != digest or state["auth_scope"] != auth_scope
                    or type(state["page_index"]) is not int or state["page_index"] < 0
                    or not isinstance(state["summaries"], list) or not isinstance(state["posts"], dict)
                    or type(state["list_complete"]) is not bool or type(state["limit_reached"]) is not bool
                    or not (state["pages"] is None or isinstance(state["pages"], list))):
                raise ValueError
            from .parsers import require_post
            source=parse_source(url)
            creator=source.creator_id
            members=state.get('members')
            member_index=state.get('member_index',0)
            if source.scope=='following':
                if (members is not None and (not isinstance(members,list) or len(members)>10000)
                        or type(member_index) is not int or member_index<0 or members is not None and member_index>len(members)):
                    raise ValueError
                for member in members or []:
                    if parse_source('https://www.fanbox.cc/@'+member).creator_id!=member:raise ValueError
            def allowed(value):
                parsed=parse_source('https://www.fanbox.cc/@'+value)
                return (value in (members or []) if source.scope=='following' else
                        True if source.scope=='supporting' else parsed.creator_id==creator)
            for post in state["summaries"]:
                require_post(post, detail=False)
                if not allowed(post['creatorId']):raise ValueError
            for key, post in state["posts"].items():
                parsed = Post.from_dict(post)
                if key != parsed.id or not allowed(parsed.creator_id): raise ValueError
            if state["pages"] is not None:
                if state["page_index"] > len(state["pages"]): raise ValueError
                if source.scope=='following':creator=members[member_index]
                for page in state["pages"]: FanboxClient.page_url(page, creator)
            if source.scope in {'tag','supporting'}:
                if type(state.get('feed_started',False)) is not bool or not isinstance(state.get('visited',[]),list):raise ValueError
                for page in state.get('visited',[]):
                    if page!='first':FanboxClient.feed_url(page,source,state.get('tag_user_id'))
                if state.get('next_url') is not None:FanboxClient.feed_url(state['next_url'],source,state.get('tag_user_id'))
            return state
        except (KeyError, TypeError, ValueError,IndexError, FanboxError):
            raise FanboxError("invalid_checkpoint", "检查点无效，或来源、登录状态、配置已改变") from None

    @staticmethod
    def _result(state, options):
        posts = list(state["posts"].values())
        errors = state["errors"]
        incomplete = bool(errors) or any(post["warnings"] or not post["comments_complete"] for post in posts)
        listing_done = state["list_complete"] or state["limit_reached"]
        status = "completed" if listing_done and not incomplete else "partial" if posts else "failed"
        filtered = sum(post_reason(item, options) is not None for item in state["summaries"])
        reasons=dict(Counter(reason for item in state['summaries'] if (reason:=post_reason(item,options)) is not None))
        return {"schema_version":1, "source":state["source"], "status":status,
            "coverage":{"list_complete":state["list_complete"], "limit_reached":state["limit_reached"],"filtered":reasons},
            "counts":{"posts_seen":len(state["summaries"]), "posts_parsed":len(posts), "posts_filtered":filtered,
                      "restricted":sum(post["access"] == "restricted" for post in posts),
                      "assets_selected":sum(asset["selected"] for post in posts for asset in post["assets"]),
                      "links":sum(len(post["links"]) for post in posts)},
            "posts":posts, "errors":copy.deepcopy(errors), "checkpoint":copy.deepcopy(state)}
