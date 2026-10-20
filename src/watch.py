#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股追踪 —— 取数与指标层（纯标准库）。

与主报告（IM 中证1000）完全独立：只跑 6 只自选股的日线/周线，外加
A50 夜盘、两融余额、个股公告三块 A 股侧信息，不重复宏观与海外市场。

数据源：
  个股日线/周线  腾讯 proxy.finance.qq.com（前复权，含换手率与成交额）
  A50 夜盘       新浪 hf_CHA50CFD（需 Referer，GBK）
  两融余额       东财 RPTA_RZRQ_LSHJ（T+1 披露）
  公告           东财 np-anotice-stock

约定：
  - 单只股票任一数据失败只降级为 None，不中断其它股票。
  - 盘中运行时最后一根 K 线未完成，必须剔除（否则换手率、量能全部失真）。
"""
import json
import datetime as dt

import fetch

# (腾讯代码, 名称, 板块, 代码)
STOCKS = [
    ('sh600497', '驰宏锌锗', '有色金属 / 铅锌锗', '600497'),
    ('sh600089', '特变电工', '输变电设备 / 多晶硅 / 煤炭', '600089'),
    ('sz300433', '蓝思科技', '消费电子玻璃盖板 / 折叠屏 / AI 硬件', '300433'),
    ('sz000962', '东方钽业', '稀有金属钽铌', '000962'),
    ('sz300496', '中科创达', '智能操作系统 / 端侧 AI / 智能汽车', '300496'),
    ('sz002436', '兴森科技', 'PCB / IC 载板 / 半导体测试板', '002436'),
]

TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).replace(tzinfo=None)


# ------------------------------------------------------------------ 行情
def _parse_kline(raw):
    """腾讯 K 线行 → dict 列表。

    行格式：[日期, 开, 收, 高, 低, 量(手), {}, 换手率%, 成交额(万元), ...]
    """
    out = []
    for r in raw or []:
        try:
            out.append(dict(day=r[0], open=float(r[1]), close=float(r[2]),
                            high=float(r[3]), low=float(r[4]),
                            vol=float(r[5] or 0),
                            turnover=float(r[7] or 0) if len(r) > 7 else 0.0,
                            amount=float(r[8] or 0) if len(r) > 8 else 0.0))
        except (ValueError, IndexError, TypeError):
            continue
    return out


def _trim_unfinished(bars):
    """剔除未完成的当日 K 线。

    早 8:30 跑时本来就没有当日 K 线；但手动在盘中触发时腾讯会返回一根
    只走了半天的 K 线（换手率、成交量都只有一小部分），必须扔掉，
    否则量能判断会得出「极度缩量」的完全错误结论。
    """
    if not bars:
        return bars
    last = bars[-1]
    if last['day'] == f'{TODAY:%Y-%m-%d}' and (TODAY.hour, TODAY.minute) < (15, 5):
        return bars[:-1]
    return bars


def kline(code, period='day', n=640):
    url = ('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'
           f'?param={code},{period},,,{n},qfq')
    txt = fetch.get(url)
    if not txt:
        return None
    try:
        d = json.loads(txt)['data'][code]
    except (KeyError, TypeError, ValueError):
        return None
    raw = d.get(f'qfq{period}') or d.get(period)
    return _trim_unfinished(_parse_kline(raw))


# ------------------------------------------------------------------ 指标
def ma(vals, n):
    """简单移动平均，返回末值（不足 n 根返回 None）。"""
    if not vals or len(vals) < n:
        return None
    return sum(vals[-n:]) / n


def rsi(closes, n):
    """通达信口径 RSI：SMA(MAX(C-REF(C,1),0),N,1) / SMA(ABS(C-REF(C,1)),N,1) * 100。

    递推式 Y = (X + (N-1)*Y') / N，首个子用首个差分初始化。
    返回与 closes 等长的列表，前两个元素为 None。
    """
    out = [None] * len(closes)
    up = dn = 0.0
    for i in range(1, len(closes)):
        ch = closes[i] - closes[i - 1]
        u, a = max(ch, 0.0), abs(ch)
        if i == 1:
            up, dn = u, a
        else:
            up = (u + (n - 1) * up) / n
            dn = (a + (n - 1) * dn) / n
        out[i] = 100.0 if dn == 0 else up / dn * 100.0
    return out


def rsi_zone(v):
    if v is None:
        return '—'
    if v < 20:
        return '超卖'
    if v < 40:
        return '偏弱'
    if v < 60:
        return '中性'
    if v < 80:
        return '偏强'
    return '超买'


def week20(bars_day, bars_week, base_close):
    """20 周线。周线最后一根本身是未完成周，必须用基准日收盘替换其 close，
    否则算出来的是上周五的收盘，会系统性偏移。"""
    if not bars_week:
        return None
    wc = [b['close'] for b in bars_week]
    last_week_day = dt.date.fromisoformat(bars_week[-1]['day'])
    base_day = dt.date.fromisoformat(bars_day[-1]['day'])
    if base_day >= last_week_day:
        wc = wc[:-1] + [base_close]
    return ma(wc, 20)


# ------------------------------------------------------------------ 回测
def _dedupe(idx, gap=5):
    """样本去重：相邻入选信号至少间隔 gap 个交易日，避免同一波行情被重复计数。"""
    keep, last = [], None
    for i in idx:
        if last is None or i - last >= gap:
            keep.append(i)
            last = i
    return keep


def _stats(bars, sig, horizon=10):
    """统计 sig 中每个信号日买入、持有 horizon 个交易日的表现。"""
    rets, dds, h5 = [], [], []
    for i in sig:
        if i + horizon >= len(bars):
            continue
        buy = bars[i]['close']
        if buy <= 0:
            continue
        rets.append((bars[i + horizon]['close'] / buy - 1) * 100)
        lows = [b['low'] for b in bars[i + 1:i + horizon + 1]]
        dds.append((min(lows) / buy - 1) * 100 if lows else 0.0)
        if i + 5 < len(bars):
            h5.append((bars[i + 5]['close'] / buy - 1) * 100)

    n = len(rets)
    if n == 0:
        return dict(n=0)
    s = sorted(rets)
    mid = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
    return dict(
        n=n,
        win=sum(1 for x in rets if x > 0) / n * 100,
        avg=sum(rets) / n,
        med=mid,
        best=max(rets),
        worst=min(rets),
        dd=sum(dds) / len(dds),
        win5=(sum(1 for x in h5 if x > 0) / len(h5) * 100) if h5 else None,
    )


def backtest(bars, r6, r12, cur6, cur12, horizon=10):
    """RSI6 历史概率回测，四个口径全部返回（与本地自选股报告口径一致）。

    A 就近匹配：历史 RSI6 落在当前值 ±N，N 从 3 逐级放宽到 12，
                取首个去重样本 ≥12 的档位；不足则如实标注实际样本量。
    B 同档位  ：按超卖/偏弱/中性/偏强/超买分档
    C 同档位+同向排列：在 B 基础上要求 RSI6 与 RSI12 的上下关系与当前一致
    D 全样本基准：无条件分布，作为比较基准 —— 胜率不显著高于它就没有信息量
    """
    n = len(bars)
    valid = [i for i in range(1, n) if r6[i] is not None]
    if not valid:
        return {}

    # D 基准
    base = _stats(bars, _dedupe(valid), horizon)

    # A 就近匹配
    near, near_band = None, None
    for band in (3, 4, 5, 6, 8, 10, 12):
        idx = _dedupe([i for i in valid if abs(r6[i] - cur6) <= band])
        st = _stats(bars, idx, horizon)
        if st.get('n', 0) >= 12:
            near, near_band = st, band
            break
        if near is None or st.get('n', 0) > near.get('n', 0):
            near, near_band = st, band

    # B / C 同档位
    zone = rsi_zone(cur6)
    same_dir = (cur6 > cur12) if cur12 is not None else None
    idx_b, idx_c = [], []
    for i in valid:
        if rsi_zone(r6[i]) != zone:
            continue
        idx_b.append(i)
        if r12[i] is None or same_dir is None:
            continue
        if ((r6[i] > r12[i]) if cur12 is not None else None) == same_dir:
            idx_c.append(i)

    return dict(
        near=dict(near or {}, band=near_band),
        zone=dict(_stats(bars, _dedupe(idx_b), horizon), zone=zone),
        zone_dir=dict(_stats(bars, _dedupe(idx_c), horizon), zone=zone),
        base=base,
    )


def confidence(n):
    if not n:
        return '极低'
    if n >= 30:
        return '高'
    if n >= 15:
        return '中'
    if n >= 8:
        return '偏低'
    return '极低'


# ------------------------------------------------------------------ A50 夜盘
def a50():
    """A50 期货（离岸中国资产风向标，北京时间凌晨仍在交易）。

    新浪字段：0现价 2买 3卖 4最高 5最低 6时间 7昨收 8开盘 9持仓量 12日期
    """
    txt = fetch.get('https://hq.sinajs.cn/list=hf_CHA50CFD',
                    headers={'Referer': 'https://finance.sina.com.cn'})
    if not txt or '"' not in txt:
        return None
    body = txt.split('"')[1] if '"' in txt else ''
    f = body.split(',')
    if len(f) < 9:
        return None
    try:
        last, prev = float(f[0]), float(f[7])
        return dict(last=last, prev=prev,
                    pct=(last / prev - 1) * 100 if prev else 0.0,
                    high=float(f[4]), low=float(f[5]),
                    open=float(f[8]),
                    oi=float(f[9]) if len(f) > 9 and f[9] else None,
                    time=f[6] if len(f) > 6 else '',
                    day=f[12] if len(f) > 12 else '')
    except (ValueError, IndexError):
        return None


# ------------------------------------------------------------------ 两融
def margin(days=61):
    """两融余额（T+1 披露，注意标注数据截止日）。返回按日期正序的列表。"""
    url = ('https://datacenter-web.eastmoney.com/api/data/v1/get'
           '?reportName=RPTA_RZRQ_LSHJ'
           '&columns=DIM_DATE,RZRQYE,RZYE,RQYE,RZJME'
           f'&source=WEB&client=WEB&sortColumns=DIM_DATE&sortTypes=-1'
           f'&pageSize={days}&pageNumber=1')
    txt = fetch.get(url)
    if not txt:
        return None
    try:
        rows = json.loads(txt)['result']['data']
    except (KeyError, TypeError, ValueError):
        return None
    out = []
    for r in reversed(rows):
        try:
            out.append(dict(day=r['DIM_DATE'][:10],
                            total=r['RZRQYE'] / 1e8,       # 亿元
                            rz=r['RZYE'] / 1e8,
                            rq=r['RQYE'] / 1e8,
                            net=r['RZJME'] / 1e8))          # 融资净买入
        except (KeyError, TypeError):
            continue
    return out or None


# ------------------------------------------------------------------ 公告
def notices(code, limit=6):
    """个股公告。云端没有搜索能力，用交易所披露的公告标题代替「重要新闻」。"""
    url = ('https://np-anotice-stock.eastmoney.com/api/security/ann'
           f'?sr=-1&page_size={limit}&page_index=1&ann_type=A'
           f'&client_source=web&stock_list={code}')
    txt = fetch.get(url)
    if not txt:
        return []
    try:
        rows = json.loads(txt)['data']['list']
    except (KeyError, TypeError, ValueError):
        return []
    out = []
    for r in rows:
        t = (r.get('title') or '').strip()
        d = (r.get('notice_date') or '')[:10]
        if not t:
            continue
        # 去掉标题前缀里的公司名，表格更干净
        for sep in ('：', ':'):
            if sep in t:
                head, tail = t.split(sep, 1)
                if len(head) <= 8:
                    t = tail.strip()
                break
        out.append(dict(day=d, title=t))
    return out


# ------------------------------------------------------------------ 单只股票
def one(code, name, sector, plain_code):
    """汇总单只股票的全部指标。任何一步失败返回 None。"""
    bars = kline(code, 'day', 640)
    if not bars or len(bars) < 70:
        return None
    weeks = kline(code, 'week', 60)

    closes = [b['close'] for b in bars]
    r6, r12, r24 = rsi(closes, 6), rsi(closes, 12), rsi(closes, 24)
    last = bars[-1]
    prev = bars[-2] if len(bars) > 1 else last

    turns = [b['turnover'] for b in bars if b['turnover'] > 0]
    t5 = ma(turns, 5)
    t20 = ma(turns, 20)
    cur_t = last['turnover']

    m = {k: ma(closes, k) for k in (5, 20, 34, 60)}
    cur6 = r6[-1] or 0.0
    cur12 = r12[-1] or 0.0

    return dict(
        code=code, name=name, sector=sector, plain=plain_code,
        day=last['day'], close=last['close'], prev=prev['close'],
        pct=(last['close'] / prev['close'] - 1) * 100 if prev['close'] else 0.0,
        high=last['high'], low=last['low'],
        turnover=cur_t,
        t5=t5, t20=t20,
        t_ratio=(cur_t / t20) if (t20 and cur_t) else None,
        amount=last['amount'],                                  # 万元
        ma=dict(m, w20=week20(bars, weeks, last['close'])),
        # 前一日各均线位置，用于判断突破/跌破
        prev_above={k: (prev['close'] > v) for k, v in m.items() if v},
        now_above={k: (last['close'] > v) for k, v in m.items() if v},
        r6=cur6, r12=cur12, r24=r24[-1] or 0.0,
        r6_prev=r6[-2] or 0.0, r12_prev=r12[-2] or 0.0,
        r6_series=[x for x in r6 if x is not None][-60:],
        bt=backtest(bars, r6, r12, cur6, cur12),
        notices=notices(plain_code),
        bars_n=len(bars),
    )


def collect():
    """取全部自选股。返回 (ok_list, failed_names)。"""
    out, failed = [], []
    for code, name, sector, plain in STOCKS:
        try:
            r = one(code, name, sector, plain)
        except Exception:
            r = None
        if r:
            out.append(r)
        else:
            failed.append(f'{name} {plain}')
    return out, failed
