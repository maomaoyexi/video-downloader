"""Synchronous libcurl callbacks provide backpressure, bounded memory and metering.

The pinned Session's regular stream() uses an unbounded producer queue. Binary
archive requests deliberately use content_callback and HEADERFUNCTION instead.
"""
from __future__ import annotations

from .auth import load_credentials
from .errors import FanboxError
from .runtime import library
from .urls import validate_resource_url


class BinaryTransport:
    def __init__(self, credentials=None, *, proxy=None, speed=0):
        self.credentials=credentials or load_credentials()
        self.proxy,self.speed=proxy,speed

    def transfer(self,url,headers,on_headers,on_chunk,*,maximum=None,meter=None):
        validate_resource_url(url)
        requests=library('curl_cffi.requests')
        opt=library('curl_cffi').CurlOpt
        state={'status':0,'headers':{},'bytes':0,'checked':False,'error':None}

        def check_headers():
            if not state['checked']:
                on_headers(state['status'],state['headers'])
                state['checked']=True

        def header(line):
            try:
                state['bytes']+=len(line)
                if state['bytes']>65536:
                    raise FanboxError('response_too_large','资源响应头过大')
                if line.startswith(b'HTTP/'):
                    state['status']=int(line.split()[1])
                    state['headers']={}
                elif b':' in line:
                    key,value=line.split(b':',1)
                    state['headers'][key.decode('ascii').lower()]=value.decode('latin-1').strip()
                return len(line)
            except BaseException as error:
                state['error']=error
                return 0xFFFFFFFF  # curl_cffi 0.13 returns len(data) for other short writes.

        def write(chunk):
            charged=False
            try:
                check_headers()
                if meter:
                    meter(len(chunk))
                    charged=True
                on_chunk(chunk)
                return len(chunk)
            except BaseException as error:
                state['error']=error
                if meter and not charged:
                    try:
                        meter(len(chunk))
                    except BaseException:
                        pass
                return 0xFFFFFFFF

        curl_options={opt.NOPROXY:'',opt.HEADERFUNCTION:header,
                      opt.CONNECTTIMEOUT_MS:10000,opt.LOW_SPEED_LIMIT:1,opt.LOW_SPEED_TIME:5}
        if maximum is not None:
            curl_options[opt.MAXFILESIZE_LARGE]=max(1,maximum)
        with requests.Session(cookies=self.credentials.jar,impersonate='chrome',trust_env=False,
                verify=library('certifi').where(),proxies={'all':self.proxy or ''},
                headers={'Origin':'https://www.fanbox.cc','Referer':'https://www.fanbox.cc/'},
                curl_options=curl_options,timeout=None) as session:
            try:
                session.get(url,headers=dict(headers,**{'Accept-Encoding':'identity'}),
                            allow_redirects=False,content_callback=write,max_recv_speed=self.speed)
                if state['error'] is not None:
                    raise state['error']
                check_headers()
            except requests.exceptions.RequestException as error:
                if state['error'] is not None:
                    raise state['error'] from None
                if getattr(error,'code',None)==63:
                    raise FanboxError('quota_exceeded','资源大小超过当前可用下载额度') from None
                raise FanboxError('network_error','附件网络请求失败') from None
        return state['headers']
