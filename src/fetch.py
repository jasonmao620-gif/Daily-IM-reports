#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一取数层 —— 纯标准库，无第三方依赖，可直接跑在 GitHub Actions 上。

设计要点：
  1. 云端网络正常，不需要本机那套 dig+curl --resolve 降级；但仍保留多源回退。
  2. 每个源独立 try，失败只降级为 None，绝不中断整条流水线。
  3. 全部带超时 + 重试，避免单一源抖动导致当天报告出不来。
"""
import json, re, ssl, time, datetime as dt
import urllib.request, urllib.error

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')
SINA_REF = {'Referer': 'https://finance.sina.com.cn', 'User-Agent': UA}
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE


def _via_curl(url, headers, timeout, resolve_ip=None):
    """降级通道：curl 直连（可选 --resolve 绕过 DNS 故障）。"""
    import subprocess, os
    cmd = ['curl', '-sS', '--max-time', str(timeout), '--noproxy', '*']
    for k, v in (headers or {}).items():
        cmd += ['-H', f'{k}: {v}']
    if resolve_ip:
        from urllib.parse import urlparse
        host = urlparse(url).hostname
        port = 443 if url.startswith('https') else 80
        cmd += ['--resolve', f'{host}:{port}:{resolve_ip}']
    cmd.append(url)
    env = os.environ.copy()
    for k in ('http_proxy', 'https_proxy', 'all_proxy',
              'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY'):
        env.pop(k, None)
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout + 10, env=env)
        return r.stdout.decode('utf-8', 'ignore') or None
    except Exception:
        return None


def _dig(host, server='223.5.5.5'):
    """用公共 DNS 解析出 A 记录，供 --resolve 使用。"""
    import subprocess
    try:
        r = subprocess.run(['dig', '@' + server, host, '+short'],
                           capture_output=True, timeout=10)
        for line in r.stdout.decode('utf-8', 'ignore').split('\n'):
            line = line.strip()
            # 只认真正的 IPv4。dig 会先返回 CNAME（形如 xxx.trafficmanager.cn.），
            # 拿它去 --resolve 会失败。
            if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', line):
                return line
    except Exception:
        pass
    return None


def get(url, headers=None, timeout=15, retries=2, encoding='utf-8'):
    """三级取数：① urllib 直连 → ② curl 绕过代理 → ③ 公共DNS解析后 curl --resolve。

    云端正常时第①级就成功；本机 DNS/代理故障时会走到 ②③。
    失败返回 None（不抛异常），保证单个源挂掉不中断整条流水线。
    """
    from urllib.parse import urlparse
    h = {'User-Agent': UA}
    if headers:
        h.update(headers)
    for i in range(retries):                                  # ① urllib
        try:
            req = urllib.request.Request(url, headers=h)
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                txt = r.read().decode(encoding, 'ignore')
                if txt:
                    return txt
        except Exception:
            pass
        time.sleep(1.0)
    txt = _via_curl(url, h, timeout)                           # ② curl
    if txt:
        return txt
    ip = _dig(urlparse(url).hostname)                         # ③ DNS + --resolve
    if ip:
        return _via_curl(url, h, timeout, resolve_ip=ip)
    return None


def gb2u8(s):
    """新浪/中金所部分接口返回 GBK，这里做一次安全转码。"""
    if s is None:
        return None
    try:
        return s.encode('latin-1', 'ignore').decode('gbk', 'ignore')
    except Exception:
        return s


# ---------------------------------------------------------------- 现货
def spot_kline(datalen=800):
    """中证1000 现货日线（新浪，实测可拿 800 根）。"""
    url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
           f'CN_MarketData.getKLineData?symbol=sh000852&scale=240&ma=no&datalen={datalen}')
    txt = get(url, SINA_REF)
    if not txt:
        return None
    m = re.search(r'\[.*\]', txt, re.S)
    if not m:
        return None
    try:
        rows = json.loads(m.group(0))
    except Exception:
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(day=r['day'], open=float(r['open']), high=float(r['high']),
                            low=float(r['low']), close=float(r['close'])))
        except Exception:
            continue
    return out or None


def spot_today():
    """东财现货实时快照。用于补当日 K 线 —— 新浪日线常延迟到次日才更新，
    20:00 跑任务时若不补全，报告会整体错一天。"""
    url = ('https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&'
           'secids=1.000852&fields=f2,f3,f4,f12,f14,f15,f16,f17,f18')
    txt = get(url)
    if not txt:
        return None
    try:
        d = json.loads(txt)['data']['diff'][0]
    except Exception:
        return None
    if not d.get('f2') or not d.get('f17'):
        return None
    return dict(last=float(d['f2']), chg=float(d.get('f3') or 0),
                chgamt=float(d.get('f4') or 0), open=float(d['f17']),
                high=float(d['f15']), low=float(d['f16']),
                prev=float(d['f18']))


def merge_today(kl, snap, today=None):
    """若日线最后一根不是今天，且实时快照的昨收与日线末根收盘一致，则补一根当日 K 线。

    一致性校验很重要：若两者对不上（比如实时快照还没更新），宁可不加，
    避免把昨日数据当成今日造成整份报告错位。
    """
    if not kl or not snap:
        return kl, False
    today = today or dt.date.today()
    if kl[-1]['day'] >= f'{today:%Y-%m-%d}':
        return kl, False
    if abs(snap['prev'] - kl[-1]['close']) > 0.5:
        return kl, False
    kl = kl + [dict(day=f'{today:%Y-%m-%d}', open=snap['open'], high=snap['high'],
                    low=snap['low'], close=snap['last'])]
    return kl, True


def ndx_kline(lmt=800):
    """纳斯达克日线（东财 push2his，美股指数不受 lmt 限制，实测 800 根可用）。"""
    url = ('https://push2his.eastmoney.com/api/qt/stock/kline/get?'
           f'secid=100.NDX&fields1=f1,f2,f3&fields2=f51,f53&klt=101&fqt=0&end=20500101&lmt={lmt}')
    txt = get(url)
    if not txt:
        return None
    try:
        kl = json.loads(txt)['data']['klines']
    except Exception:
        return None
    out = []
    for r in kl:
        d, c = r.split(',')
        out.append((d, float(c)))
    return out or None


# ---------------------------------------------------------------- IM 期货
def im_contract_codes(today=None):
    """构造候选 IM 合约：当月/下月/随后两季月。实际挂牌的由抓取结果筛选。"""
    today = today or dt.date.today()
    y, m = today.year % 100, today.month
    cands = []
    for i in range(0, 3):                      # 当月、次月、再次月
        mm = m + i
        yy = y + (mm - 1) // 12
        mm = (mm - 1) % 12 + 1
        cands.append(f'IM{yy:02d}{mm:02d}')
    for q in (3, 6, 9, 12):                    # 季月
        yy = y + (1 if q < m else 0)
        cands.append(f'IM{yy:02d}{q:02d}')
    seen, out = set(), []
    for c in cands:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def im_kline(code):
    """单个 IM 合约日线（含持仓量 p 字段）。"""
    url = ('http://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/'
           f'InnerFuturesNewService.getDailyKLine?symbol={code}')
    txt = get(url, SINA_REF)
    if not txt:
        return None
    m = re.search(r'\((\[.*\])\)', txt, re.S) or re.search(r'\[.*\]', txt, re.S)
    if not m:
        return None
    try:
        rows = json.loads(m.group(1) if m.groups() else m.group(0))
    except Exception:
        return None
    out = []
    for r in rows:
        try:
            out.append(dict(day=r['d'], open=float(r['o']), high=float(r['h']),
                            low=float(r['l']), close=float(r['c']),
                            vol=int(r['v']), oi=int(r['p'])))
        except Exception:
            continue
    return out or None


def im_all(today=None):
    """抓取全部挂牌 IM 合约，返回 {code: bars}（已剔除无数据/已退市）。"""
    res = {}
    for code in im_contract_codes(today):
        bars = im_kline(code)
        if bars and len(bars) >= 2:
            res[code] = bars
    return res


# ---------------------------------------------------------------- 中金所
def cffex_top20(d):
    """中金所前20名会员持仓（IM_1.csv）。必须 http + 文件名 IM_1，GBK 编码。
    列索引(0基)：0交易日 1合约 2排名 | 7持买单量 8买单增减 | 10持卖单量 11卖单增减"""
    url = f'http://www.cffex.com.cn/sj/ccpm/{d:%Y%m}/{d:%m%d}/IM_1.csv'
    raw = get(url, retries=2)
    if not raw:
        return None
    txt = gb2u8(raw) or raw
    rows, data = txt.split('\n'), {}
    for r in rows:
        p = r.strip().split(',')
        if len(p) < 12 or not p[0].startswith('20'):
            continue
        try:
            code = p[1]
            b, bd, s, sd = int(p[7]), int(p[8]), int(p[10]), int(p[11])
        except Exception:
            continue
        a = data.setdefault(code, {'b': 0, 'bd': 0, 's': 0, 'sd': 0})
        a['b'] += b; a['bd'] += bd; a['s'] += s; a['sd'] += sd
    return data or None


def mo_quotes():
    """中金所 MO 期权全合约（官方 quote_MO.txt）。
    字段：instrument,position,volume,lastprice,updown,bprice,bamount,sprice,samount"""
    txt = get('http://www.cffex.com.cn/quote_MO.txt', retries=2)
    if not txt:
        return None
    out = []
    for line in txt.split('\n'):
        line = line.strip()
        if not line or line.startswith('instrument'):
            continue
        p = line.split(',')
        if len(p) < 9:
            continue
        try:
            out.append(dict(inst=p[0], pos=int(p[1]), vol=int(p[2]),
                            last=float(p[3]), updown=float(p[4]),
                            bid=float(p[5]), ask=float(p[7])))
        except ValueError:
            continue
    return out or None


# ---------------------------------------------------------------- 外围
def global_indices():
    """东财 push2 多标的快照。f2最新 f3涨跌幅 f4涨跌额 f15高 f16低 f17开 f18昨收"""
    ids = '100.NDX,100.SPX,100.DJIA,100.N225,100.KS11,100.HSI'
    url = ('https://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&'
           f'secids={ids}&fields=f2,f3,f4,f12,f14,f15,f16,f17,f18,f124')
    txt = get(url)
    if not txt:
        return None
    try:
        diff = json.loads(txt)['data']['diff']
    except Exception:
        return None
    return {d['f12']: dict(name=d.get('f14'), last=d.get('f2'), chg=d.get('f3'),
                           chgamt=d.get('f4'), high=d.get('f15'), low=d.get('f16'),
                           open=d.get('f17'), prev=d.get('f18'), ts=d.get('f124'))
            for d in diff}


def vix():
    """新浪 znb_VIX：字段 当前,涨跌额,涨跌幅%,...,昨收,今开,最高,最低"""
    txt = get('https://hq.sinajs.cn/list=znb_VIX', SINA_REF)
    if not txt:
        return None
    txt = gb2u8(txt) or txt
    m = re.search(r'"([^"]+)"', txt)
    if not m:
        return None
    p = m.group(1).split(',')
    try:
        return dict(name=p[0], last=float(p[1]), chgamt=float(p[2]), chg=float(p[3]),
                    date=p[6], prev=float(p[8]), open=float(p[9]),
                    high=float(p[10]), low=float(p[11]))
    except Exception:
        return None


def ust10y():
    """FRED 美债10Y，官方滞后约 1 日。返回 [(date, value)] 尾部若干。"""
    txt = get('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10', timeout=25)
    if not txt:
        return None
    out = []
    for line in txt.strip().split('\n')[1:]:
        p = line.split(',')
        if len(p) < 2 or not p[0].startswith('20'):
            continue
        try:
            out.append((p[0], float(p[1])))
        except ValueError:
            out.append((p[0], None))      # 节假日空值保留占位
    return out[-20:] or None


def gold_oil():
    """新浪外盘商品 hf_GC / hf_CL / hf_OIL。字段8=昨收 字段9=今开"""
    txt = get('https://hq.sinajs.cn/list=hf_GC,hf_CL,hf_OIL', SINA_REF)
    if not txt:
        return None
    txt = gb2u8(txt) or txt
    out = {}
    for m in re.finditer(r'hq_str_(hf_\w+)="([^"]*)"', txt):
        code, p = m.group(1), m.group(2).split(',')
        if len(p) < 10:
            continue
        try:
            out[code] = dict(name=p[13] if len(p) > 13 else code,
                             last=float(p[0]), prev=float(p[7]), open=float(p[8]))
        except Exception:
            continue
    return out or None


def margin_balance(n=6):
    """两融余额（东财 datacenter，倒序返回）。返回 [{date, rzrqye, rzye, rzjme}] 正序。"""
    url = ('https://datacenter-web.eastmoney.com/api/data/v1/get?'
           'reportName=RPTA_RZRQ_LSHJ&columns=ALL&sortColumns=dim_date&sortTypes=-1&'
           f'pageSize={n}&source=WEB&client=WEB')
    txt = get(url)
    if not txt:
        return None
    try:
        data = json.loads(txt)['result']['data']
    except Exception:
        return None
    rows = []
    for d in data:
        try:
            rows.append(dict(date=d['DIM_DATE'][:10], rzrqye=float(d['RZRQYE']),
                             rzye=float(d['RZYE']), rzjme=float(d['RZJME'])))
        except Exception:
            continue
    rows.reverse()          # 转为正序，日变化自行计算
    return rows or None
