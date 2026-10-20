#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信推送层 —— 支持 Server酱 与 PushPlus，二者都通过微信公众号模板消息
送达个人微信，无需企业微信、无需备案域名。

配置（均为 GitHub Secrets，切勿硬编码进仓库）：
  PUSH_CHANNEL = serverchan | pushplus   （默认 serverchan）
  PUSH_KEY     = Server酱的 SendKey（sctp****）或 PushPlus 的 token

免费额度：Server酱 每天 5 条（我们每天 1 条足够）；PushPlus 每天 200 条。
"""
import json, os, urllib.request, urllib.parse


def _post(url, data=None, headers=None, timeout=20):
    body = urllib.parse.urlencode(data).encode() if isinstance(data, dict) else None
    req = urllib.request.Request(url, data=body, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', 'ignore')


def send(title, content_md, channel=None, key=None):
    """返回 (ok: bool, msg: str)。失败不抛异常，交由上层记录。"""
    channel = (channel or os.environ.get('PUSH_CHANNEL') or 'serverchan').lower()
    key = key or os.environ.get('PUSH_KEY', '').strip()
    if not key or key.startswith('YOUR_'):
        return False, '未配置 PUSH_KEY，已跳过推送'

    try:
        if channel == 'pushplus':
            payload = json.dumps(dict(token=key, title=title, content=content_md,
                                      template='markdown')).encode()
            r = _post('https://www.pushplus.plus/send', payload,
                      {'Content-Type': 'application/json'})
            ok = '"code":200' in r.replace(' ', '') or '"success"' in r
            return ok, r[:200]
        else:
            r = _post(f'https://sctapi.ftqq.com/{key}.send',
                      dict(title=title, desp=content_md))
            ok = '"code":0' in r.replace(' ', '') or 'success' in r.lower()
            return ok, r[:200]
    except Exception as e:
        return False, f'推送异常: {type(e).__name__}: {e}'
