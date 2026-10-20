#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技术指标与历史概率 —— 全部本地重算，禁止沿用往期报告数值。"""
import datetime as dt


def ema(a, p):
    k = 2 / (p + 1)
    out = [a[0]]
    for x in a[1:]:
        out.append(out[-1] + (x - out[-1]) * k)
    return out


def sma(a, p):
    return [None if i < p - 1 else sum(a[i - p + 1:i + 1]) / p for i in range(len(a))]


def macd(closes, fast=12, slow=26, sig=9):
    e12, e26 = ema(closes, fast), ema(closes, slow)
    dif = [a - b for a, b in zip(e12, e26)]
    dea = ema(dif, sig)
    hist = [(a - b) * 2 for a, b in zip(dif, dea)]
    return dif, dea, hist


def rsi(closes, p=14):
    """Wilder 平滑 RSI。"""
    if len(closes) < p + 1:
        return [None] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[:p]) / p
    al = sum(losses[:p]) / p
    out = [None] * p
    out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    for i in range(p, len(gains)):
        ag = (ag * (p - 1) + gains[i]) / p
        al = (al * (p - 1) + losses[i]) / p
        out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return out


def boll(closes, p=20, k=2):
    mid = sma(closes, p)
    up, lo = [None] * len(closes), [None] * len(closes)
    for i in range(p - 1, len(closes)):
        w = closes[i - p + 1:i + 1]
        m = sum(w) / p
        sd = (sum((x - m) ** 2 for x in w) / p) ** 0.5
        up[i], lo[i] = m + k * sd, m - k * sd
    return up, mid, lo


def atr(highs, lows, closes, p=14):
    tr = []
    for i in range(1, len(closes)):
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]),
                      abs(lows[i] - closes[i - 1])))
    if len(tr) < p:
        return None
    return sum(tr[-p:]) / p


def core(kl):
    """输入现货日线（含 day/open/high/low/close），输出全套指标。"""
    c = [r['close'] for r in kl]
    h = [r['high'] for r in kl]
    l = [r['low'] for r in kl]
    o = [r['open'] for r in kl]
    dif, dea, hist = macd(c)
    r6, r14 = rsi(c, 6), rsi(c, 14)
    up, mid, lo = boll(c)
    i = len(c) - 1
    return dict(
        day=kl[i]['day'], close=c[i], open=o[i], high=h[i], low=l[i],
        prev=c[i - 1], chg=c[i] - c[i - 1], pct=(c[i] / c[i - 1] - 1) * 100,
        ampl=(h[i] - l[i]) / c[i - 1] * 100,
        ma5=sma(c, 5)[i], ma10=sma(c, 10)[i], ma20=sma(c, 20)[i],
        ma34=sma(c, 34)[i], ma60=sma(c, 60)[i],
        boll_up=up[i], boll_mid=mid[i], boll_lo=lo[i],
        dif=dif[i], dea=dea[i], hist=hist[i],
        dif_prev=dif[i - 1], dea_prev=dea[i - 1],
        rsi6=r6[i], rsi14=r14[i], atr14=atr(h, l, c),
        closes=c, highs=h, lows=l, opens=o, days=[r['day'] for r in kl], difs=dif,
    )


def divergence(c):
    """底背离检测（60日窗口）：收盘创60日新低 且 DIF 未创60日新低。

    返回 (signals, latest_state)
      latest_state: 'formed'      当日成立
                    'unconfirmed' 此前成立、今日价未新低但 DIF 仍走低
                    'none'        无信号
    """
    closes = c['closes']
    difs = c['difs']
    n = len(closes)
    sigs = []
    for i in range(60, n - 1):
        if closes[i] == min(closes[i - 60:i + 1]) and closes[i] < closes[i - 1]:
            if difs[i] > min(difs[i - 60:i]):
                sigs.append(i)
    # 最新状态判定
    state = 'none'
    if sigs:
        last = sigs[-1]
        if last == n - 1:
            state = 'formed'
        elif last >= n - 10:                       # 近10日内曾成立
            state = 'unconfirmed'
    return sigs, state


def backtest_divergence(c):
    """历史底背离信号后的表现 + 回撤（回撤必须报，只报胜率会误导）。"""
    closes, lows, days = c['closes'], c['lows'], c['days']
    n = len(closes)
    sigs, _ = divergence(c)
    res = {}
    for hz in (1, 3, 5, 10, 20):
        wins = tot = 0
        for i in sigs:
            if i + hz < n:
                tot += 1
                wins += closes[i + hz] > closes[i]
        res[hz] = (wins, tot)
    dd = []
    for i in sigs:
        if i + 11 <= n:
            dd.append((min(lows[i + 1:i + 11]) / closes[i] - 1) * 100)
    return dict(signals=len(sigs), wins=res,
                dd_avg=(sum(dd) / len(dd)) if dd else None,
                dd_worst=min(dd) if dd else None, dd_n=len(dd))


def overnight_transmit(ndx, kl):
    """纳指大跌 → A股次日传导。

    配对规则（关键）：纳指日期 d 的收盘 → 中证1000 中「日期严格大于 d」的第一个交易日。
    """
    if not ndx or not kl:
        return None
    z_day = [r['day'] for r in kl]
    z_c = [r['close'] for r in kl]
    z_o = [r['open'] for r in kl]
    z_l = [r['low'] for r in kl]

    def nxt(d):
        for i, x in enumerate(z_day):
            if x > d:
                return i
        return None

    pairs = []
    for i in range(1, len(ndx)):
        chg = (ndx[i][1] / ndx[i - 1][1] - 1) * 100
        j = nxt(ndx[i][0])
        if j is None or j == 0:
            continue
        r20 = (z_c[j - 1] / z_c[j - 21] - 1) * 100 if j >= 21 else None
        pairs.append(dict(date=ndx[i][0], ndx=chg, zday=z_day[j],
                          close=(z_c[j] / z_c[j - 1] - 1) * 100,
                          open=(z_o[j] / z_c[j - 1] - 1) * 100,
                          low=(z_l[j] / z_c[j - 1] - 1) * 100, r20=r20))

    def stat(cond, label):
        h = [p for p in pairs if cond(p)]
        if not h:
            return dict(label=label, n=0)
        up = sum(1 for p in h if p['close'] > 0)
        return dict(label=label, n=len(h), win=up / len(h) * 100,
                    open=sum(p['open'] for p in h) / len(h),
                    low=sum(p['low'] for p in h) / len(h),
                    close=sum(p['close'] for p in h) / len(h))

    return dict(
        total=len(pairs),
        g2=stat(lambda p: p['ndx'] <= -2.0, '纳指跌超2%'),
        g2_5=stat(lambda p: p['ndx'] <= -2.0 and p['r20'] is not None and p['r20'] <= -5,
                  '纳指跌超2% + 前20日跌超5%'),
        g2_10=stat(lambda p: p['ndx'] <= -2.0 and p['r20'] is not None and p['r20'] <= -10,
                   '纳指跌超2% + 前20日跌超10%'),
        latest_ndx=pairs[-1]['ndx'] if pairs else None,
    )


def third_wed(y, m):
    """MO 到期日：到期月第三个星期三。"""
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(2 - d.weekday()) % 7 + 14)


def third_fri(y, m):
    """IM 到期日：到期月第三个星期五。"""
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(4 - d.weekday()) % 7 + 14)


def norm_cdf(x):
    import math
    return 0.5 * (1 + math.erf(x / (2 ** 0.5)))


def black76_call(F, K, T, r, v):
    """Black-76：期货期权定价。MO 远期应取同月 IM 期货价。"""
    import math
    if T <= 0:
        return max(0.0, F - K)
    d1 = (math.log(F / K) + (v * v / 2) * T) / (v * math.sqrt(T))
    d2 = d1 - v * math.sqrt(T)
    return math.exp(-r * T) * (F * norm_cdf(d1) - K * norm_cdf(d2))


def implied_vol(F, K, T, r, price):
    lo, hi = 0.0001, 5.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if black76_call(F, K, T, r, mid) < price:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def realized_vol(closes, p):
    import math
    if len(closes) < p + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(len(closes) - p, len(closes))]
    m = sum(rets) / len(rets)
    var = sum((x - m) ** 2 for x in rets) / (len(rets) - 1)
    return (var ** 0.5) * math.sqrt(252)
