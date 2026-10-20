#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股追踪报告 —— 渲染层（HTML + 微信摘要）。

原则：
  1. 所有数字来自 Python 计算，模板里不写死任何行情数值。
  2. 红涨绿跌，符合 A 股习惯。
  3. 回测结论必须带样本量，并强制与自身基准对比 —— 胜率低于基准时
     必须明说「该读数未带来上涨概率提升」，不允许含糊。
"""
import datetime as dt

UP, DOWN, FLAT = '#d9342b', '#12a05c', '#6b7280'


def _c(v):
    if v is None:
        return FLAT
    return UP if v > 0 else (DOWN if v < 0 else FLAT)


def _s(v, fmt='{:+.2f}'):
    if v is None:
        return '—'
    return fmt.format(v)


def _color_span(v, fmt='{:+.2f}'):
    return f'<span style="color:{_c(v)}">{_s(v, fmt)}</span>'


def _f(v, n=2):
    if v is None:
        return '—'
    return f'{v:,.{n}f}'


# ------------------------------------------------------------------ 两融 SVG
def svg_margin(mg, w=680, h=210):
    """两融余额 60 日折线。标出区间高/低与最新值。"""
    if not mg or len(mg) < 5:
        return '<p class="muted">两融数据缺失</p>'
    vals = [x['total'] for x in mg]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.15 or 1
    lo, hi = lo - pad, hi + pad
    L, R, T, B = 54, 14, 16, 30
    iw, ih = w - L - R, h - T - B

    def px(i):
        return L + iw * i / (len(vals) - 1)

    def py(v):
        return T + ih * (1 - (v - lo) / (hi - lo))

    pts = ' '.join(f'{px(i):.1f},{py(v):.1f}' for i, v in enumerate(vals))
    area = f'{L},{T + ih} ' + pts + f' {L + iw},{T + ih}'

    # 区间最高 / 最低点在序列中的位置
    i_hi, i_lo = vals.index(max(vals)), vals.index(min(vals))
    grid = []
    for k in range(4):
        gy = T + ih * k / 3
        gv = hi - (hi - lo) * k / 3
        grid.append(f'<line x1="{L}" y1="{gy:.1f}" x2="{L + iw}" y2="{gy:.1f}" '
                    f'stroke="#e5e7eb" stroke-width="1"/>'
                    f'<text x="{L - 6}" y="{gy + 4:.1f}" text-anchor="end" '
                    f'font-size="10" fill="#9ca3af">{gv:,.0f}</text>')

    dots = (f'<circle cx="{px(i_hi):.1f}" cy="{py(max(vals)):.1f}" r="3.2" fill="{UP}"/>'
            f'<text x="{px(i_hi):.1f}" y="{py(max(vals)) - 8:.1f}" text-anchor="middle" '
            f'font-size="10" fill="{UP}">高 {max(vals):,.0f}</text>'
            f'<circle cx="{px(i_lo):.1f}" cy="{py(min(vals)):.1f}" r="3.2" fill="{DOWN}"/>'
            f'<text x="{px(i_lo):.1f}" y="{py(min(vals)) + 16:.1f}" text-anchor="middle" '
            f'font-size="10" fill="{DOWN}">低 {min(vals):,.0f}</text>'
            f'<circle cx="{px(len(vals) - 1):.1f}" cy="{py(vals[-1]):.1f}" r="3.6" fill="#1f2937"/>'
            f'<text x="{px(len(vals) - 1) - 6:.1f}" y="{py(vals[-1]) - 9:.1f}" text-anchor="end" '
            f'font-size="11" font-weight="600" fill="#1f2937">{vals[-1]:,.0f}</text>')

    xlab = (f'<text x="{L}" y="{h - 8}" font-size="10" fill="#9ca3af">{mg[0]["day"][5:]}</text>'
            f'<text x="{L + iw}" y="{h - 8}" text-anchor="end" font-size="10" '
            f'fill="#9ca3af">{mg[-1]["day"][5:]}</text>')

    return (f'<svg viewBox="0 0 {w} {h}" width="100%" style="max-width:{w}px" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'{"".join(grid)}'
            f'<polygon points="{area}" fill="#dbeafe" opacity="0.55"/>'
            f'<polyline points="{pts}" fill="none" stroke="#2563eb" stroke-width="1.8"/>'
            f'{dots}{xlab}</svg>')


# ------------------------------------------------------------------ 总表
def table_main(stocks):
    if not stocks:
        return '<p class="muted">全部自选股取数失败。</p>'
    head = ('<tr><th>标的</th><th>收盘</th><th>涨跌</th><th>换手%</th>'
            '<th>换手/20日</th><th>MA20</th><th>MA34</th><th>20周线</th>'
            '<th>RSI6</th><th>RSI12</th><th>状态</th><th>T+10 胜率</th></tr>')
    rows = []
    for s in stocks:
        m = s['ma']
        bt = s['bt'].get('near', {}) if s['bt'] else {}
        zw = s['bt'].get('zone', {}) if s['bt'] else {}
        n = bt.get('n') or 0
        win = bt.get('win')
        # 与自身基准对比后再着色，避免把低胜率也标成"好"
        bwin = (s['bt'].get('base', {}) or {}).get('win')
        rc = FLAT
        if win is not None and bwin:
            rc = UP if win > bwin + 2 else (DOWN if win < bwin - 2 else FLAT)
        ratio = s['t_ratio']
        rcol = UP if (ratio or 0) >= 1.3 else (DOWN if (ratio or 0) <= 0.7 else FLAT)
        rows.append(
            f'<tr><td class="nm"><a href="#{s["plain"]}">{s["name"]}</a>'
            f'<span class="code">{s["plain"]}</span></td>'
            f'<td class="num">{s["close"]:.2f}</td>'
            f'<td class="num" style="color:{_c(s["pct"])}">{_s(s["pct"])}%</td>'
            f'<td class="num">{_f(s["turnover"])}</td>'
            f'<td class="num" style="color:{rcol};font-weight:600">{_f(ratio)}×</td>'
            f'<td class="num">{_f(m.get(20))}</td>'
            f'<td class="num">{_f(m.get(34))}</td>'
            f'<td class="num">{_f(m.get("w20"))}</td>'
            f'<td class="num">{_f(s["r6"], 1)}</td>'
            f'<td class="num">{_f(s["r12"], 1)}</td>'
            f'<td class="num">{_zone(s["r6"]) if s["r6"] else "—"}</td>'
            f'<td class="num" style="color:{rc}">{_f(win, 1)}%<span class="muted">'
            f' (n={n})</span></td></tr>')
    return f'<table class="tbl"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table>'


def _zone(v):
    if v < 20:
        return '超卖'
    if v < 40:
        return '偏弱'
    if v < 60:
        return '中性'
    if v < 80:
        return '偏强'
    return '超买'


# ------------------------------------------------------------------ 回测表
def table_bt(s):
    bt = s['bt'] or {}
    base = bt.get('base') or {}
    bw = base.get('win')
    rows = []
    spec = [('A 就近匹配', bt.get('near') or {}, f'±{bt.get("near", {}).get("band")} 以内'),
            ('B 同档位', bt.get('zone') or {}, bt.get('zone', {}).get('zone') or ''),
            ('C 同档位+同向', bt.get('zone_dir') or {}, bt.get('zone', {}).get('zone') or ''),
            ('D 全样本基准', base, '无条件')]
    for name, d, note in spec:
        n = d.get('n') or 0
        if not n:
            rows.append(f'<tr><td>{name}</td><td class="muted" colspan="6">样本不足</td></tr>')
            continue
        win = d.get('win')
        # 与基准比：高 2pp 以上利好，低 2pp 以上利空，其余视为中性
        if name.startswith('D'):
            col = '#1f2937'
        elif bw and win > bw + 2:
            col = UP
        elif bw and win < bw - 2:
            col = DOWN
        else:
            col = FLAT
        rows.append(
            f'<tr><td>{name}<span class="muted"> {note}</span></td>'
            f'<td class="num">{n}</td>'
            f'<td class="num" style="color:{col};font-weight:600">{_f(win, 1)}%</td>'
            f'<td class="num">{_s(d.get("avg"), "{:+.2f}")}%</td>'
            f'<td class="num">{_s(d.get("med"), "{:+.2f}")}%</td>'
            f'<td class="num" style="color:{_c(d.get("dd"))}">{_s(d.get("dd"), "{:+.2f}")}%</td>'
            f'<td class="num">{_f(d.get("win5"), 1)}%</td></tr>')
    return ('<table class="tbl small"><thead><tr><th>口径</th><th>样本</th><th>T+10 胜率</th>'
            '<th>平均收益</th><th>中位收益</th><th>期间最大回撤</th><th>T+5 胜率</th>'
            f'</tr></thead><tbody>{"".join(rows)}</tbody></table>')


def bt_verdict(s):
    """把回测结果翻译成人话。这是报告里唯一真正有价值的判断，必须老实。"""
    bt = s['bt'] or {}
    near = bt.get('near') or {}
    base = bt.get('base') or {}
    win, n, bw = near.get('win'), near.get('n') or 0, base.get('win')
    if not win or not bw:
        return '<li class="muted">回测样本不足，本次不给出概率结论。</li>'

    out = []
    diff = win - bw
    if diff >= 2:
        out.append(f'<li>就近匹配口径胜率 <b>{win:.1f}%</b>，高于自身基准 {bw:.1f}% '
                   f'<b>{diff:+.1f}pp</b>，该读数历史上确实带来过上涨概率的边际提升（n={n}）。</li>')
    elif diff <= -2:
        out.append(f'<li>就近匹配口径胜率 <b>{win:.1f}%</b>，<b>低于</b>自身基准 {bw:.1f}% '
                   f'<b>{diff:+.1f}pp</b> —— 该读数<b>未带来上涨概率提升</b>，'
                   f'不能因为「跌多了」就当成买点（n={n}）。</li>')
    else:
        out.append(f'<li>就近匹配口径胜率 <b>{win:.1f}%</b>，与自身基准 {bw:.1f}% '
                   f'基本持平（<b>{diff:+.1f}pp</b>），该读数本身<b>没有方向性信息</b>（n={n}）。</li>')

    avg, med = near.get('avg'), near.get('med')
    if avg is not None and med is not None and avg > 0 > med:
        out.append('<li>平均为正而中位为负，说明收益<b>右偏</b>：靠少数大涨样本拉高均值，'
                   '典型样本其实是亏的，不要被均值误导。</li>')

    dd = near.get('dd')
    if dd is not None:
        out.append(f'<li>持有 10 个交易日内平均最深回撤 <b>{dd:+.2f}%</b>'
                   f'（最差单次样本 {_s(near.get("worst"), "{:+.2f}")}%）——'
                   f'即便最终收涨，中途的浮亏也要能扛住。</li>')

    zd = bt.get('zone_dir') or {}
    zo = bt.get('zone') or {}
    if zd.get('n') and zo.get('n') and zd['n'] == zo['n']:
        out.append('<li class="muted">「同档位+同向」与「同档位」样本完全相同，'
                   '说明该股在同类区间里 RSI6 与 RSI12 的上下关系高度一致，'
                   '这一条件未起额外筛选作用。</li>')
    elif zd.get('win') and zo.get('win') and zd['win'] < zo['win'] - 3:
        out.append(f'<li style="color:{DOWN}"><b>风险提示</b>：叠加「同向排列」后胜率由 '
                   f'{zo["win"]:.1f}% 降至 {zd["win"]:.1f}%，弱势区里的金叉式排列多为下跌中继。</li>')

    out.append(f'<li class="muted">可信度：{_conf(n)}（n={n}）。</li>')
    return ''.join(out)


def _conf(n):
    if n >= 30:
        return '高'
    if n >= 15:
        return '中'
    if n >= 8:
        return '偏低'
    return '极低，仅供参考'


# ------------------------------------------------------------------ 个股块
def block_stock(s):
    m = s['ma']
    rows = []
    for k, label in ((5, 'MA5'), (20, 'MA20'), (34, 'MA34'), (60, 'MA60')):
        v = m.get(k)
        if not v:
            continue
        now_up = s['now_above'].get(k)
        prev_up = s['prev_above'].get(k)
        if now_up and not prev_up:
            tag = f'<span style="color:{UP}">▲ 今日站上</span>'
        elif (not now_up) and prev_up:
            tag = f'<span style="color:{DOWN}">▼ 今日跌破</span>'
        else:
            tag = '<span class="muted">维持</span>'
        gap = (s['close'] / v - 1) * 100
        rows.append(f'<tr><td>{label}</td><td class="num">{v:.2f}</td>'
                    f'<td class="num" style="color:{_c(gap)}">{_s(gap)}%</td>'
                    f'<td>{tag}</td></tr>')
    w20 = m.get('w20')
    if w20:
        gap = (s['close'] / w20 - 1) * 100
        wtag = (f'<span style="color:{UP}">站上（中期偏多）</span>' if gap > 0
                else f'<span style="color:{DOWN}">失守（中期偏空）</span>')
        rows.append(f'<tr><td>20 周线</td><td class="num">{w20:.2f}</td>'
                    f'<td class="num" style="color:{_c(gap)}">{_s(gap)}%</td>'
                    f'<td>{wtag}</td></tr>')

    nt = s['notices'] or []
    nt_html = ('<ul class="news">' + ''.join(
        f'<li><span class="muted">{x["day"]}</span> {x["title"]}</li>' for x in nt[:5])
        + '</ul>') if nt else '<p class="muted">近 45 日无交易所披露公告（或接口未取到）。</p>'

    ratio = s['t_ratio']
    if ratio is None:
        vol_txt = '换手率数据缺失。'
    elif ratio >= 1.5:
        vol_txt = f'换手率 {s["turnover"]:.2f}%，为 20 日均值的 <b>{ratio:.2f} 倍</b>，属于明显放量。'
    elif ratio >= 1.2:
        vol_txt = f'换手率 {s["turnover"]:.2f}%，为 20 日均值的 <b>{ratio:.2f} 倍</b>，温和放量。'
    elif ratio <= 0.7:
        vol_txt = f'换手率 {s["turnover"]:.2f}%，仅为 20 日均值的 <b>{ratio:.2f} 倍</b>，明显缩量。'
    elif ratio <= 0.9:
        vol_txt = f'换手率 {s["turnover"]:.2f}%，为 20 日均值的 <b>{ratio:.2f} 倍</b>，小幅缩量。'
    else:
        vol_txt = f'换手率 {s["turnover"]:.2f}%，为 20 日均值的 <b>{ratio:.2f} 倍</b>，量能中性。'

    # 量价配合：涨跌方向 × 量能方向
    if s['pct'] > 0 and ratio and ratio >= 1.2:
        vp = '放量上涨，趋势确认度较高'
    elif s['pct'] > 0 and ratio and ratio <= 0.8:
        vp = '缩量上涨，反弹动能不足'
    elif s['pct'] < 0 and ratio and ratio >= 1.2:
        vp = '放量下跌，资金出逃'
    elif s['pct'] < 0 and ratio and ratio <= 0.8:
        vp = '缩量下跌，抛压衰减'
    else:
        vp = '量价关系中性'

    r6d = s['r6'] - s['r6_prev']
    r12d = s['r12'] - s['r12_prev']
    cross = '金叉（RSI6 > RSI12）' if s['r6'] > s['r12'] else '死叉（RSI6 < RSI12）'
    new_cross = '新形成' if ((s['r6'] > s['r12']) != (s['r6_prev'] > s['r12_prev'])) else '延续'

    return f'''
<section class="card" id="{s['plain']}">
  <div class="chead">
    <h3>{s['name']} <span class="code">{s['plain']}</span></h3>
    <div class="tag">{s['sector']}</div>
  </div>
  <div class="kpi">
    <div><span class="muted">收盘</span><b>{s['close']:.2f}</b></div>
    <div><span class="muted">涨跌</span><b style="color:{_c(s['pct'])}">{_s(s['pct'])}%</b></div>
    <div><span class="muted">换手</span><b>{_f(s['turnover'])}%</b></div>
    <div><span class="muted">换手/20日</span><b>{_f(ratio)}×</b></div>
    <div><span class="muted">RSI6</span><b>{_f(s['r6'], 1)} <span class="muted">({_s(r6d, '{:+.1f}')})</span></b></div>
    <div><span class="muted">RSI12</span><b>{_f(s['r12'], 1)} <span class="muted">({_s(r12d, '{:+.1f}')})</span></b></div>
  </div>

  <h4>1. 公告与消息</h4>
  {nt_html}

  <h4>2. RSI 三周期</h4>
  <p>RSI6 <b>{_f(s['r6'], 1)}</b>（{_zone(s['r6'])}）、RSI12 <b>{_f(s['r12'], 1)}</b>、
     RSI24 <b>{_f(s['r24'], 1)}</b>；当前为 <b>{cross}</b>，{new_cross}。</p>

  <h4>3. 历史概率回测（RSI6 ≈ {_f(s['r6'], 1)} 之后 10 个交易日的表现）</h4>
  {table_bt(s)}
  <ul class="verdict">{bt_verdict(s)}</ul>

  <h4>4. 量能</h4>
  <p>{vol_txt} 5 日均换手 {_f(s['t5'])}%，20 日均换手 {_f(s['t20'])}%。判定：<b>{vp}</b>。
     成交额 {_f(s['amount'] / 10000 if s['amount'] else None)} 亿元。</p>

  <h4>5. 均线位置</h4>
  <table class="tbl small"><thead><tr><th>均线</th><th>数值</th><th>股价相对</th><th>变化</th></tr></thead>
  <tbody>{''.join(rows)}</tbody></table>
</section>'''


# ------------------------------------------------------------------ 主渲染
def build_html(d):
    st, mg, a50 = d['stocks'], d['margin'], d['a50']

    a50_html = '<p class="muted">A50 夜盘数据缺失。</p>'
    if a50:
        mood = '平开' if abs(a50['pct']) < 0.3 else ('高开' if a50['pct'] > 0 else '低开')
        a50_html = f'''
<div class="kpi big">
  <div><span class="muted">最新</span><b>{a50['last']:,.1f}</b></div>
  <div><span class="muted">涨跌</span><b style="color:{_c(a50['pct'])}">{_s(a50['pct'])}%</b></div>
  <div><span class="muted">夜盘区间</span><b>{a50['low']:,.0f} ~ {a50['high']:,.0f}</b></div>
  <div><span class="muted">更新时间</span><b>{a50['day']} {a50['time']}</b></div>
</div>
<p>按当前 {_s(a50['pct'])}% 的幅度，指向 A 股今日 <b>{mood}</b>。
   {'夜盘走强，对早盘情绪有正向牵引。' if a50['pct'] > 0.3 else
    ('夜盘走弱，需防低开后承接不足。' if a50['pct'] < -0.3 else '夜盘波动极小，对外盘指引有限，主要看 A 股自身量能。')}</p>'''

    mg_html = '<p class="muted">两融数据缺失。</p>'
    if mg and len(mg) > 2:
        cur, first = mg[-1]['total'], mg[0]['total']
        chg = cur - first
        pct = chg / first * 100 if first else 0
        recent15 = mg[-15:]
        rows = ''.join(
            f'<tr><td>{x["day"]}</td><td class="num">{x["total"]:,.1f}</td>'
            f'<td class="num">{x["rz"]:,.1f}</td>'
            f'<td class="num" style="color:{_c(x["net"])}">{x["net"]:+.1f}</td></tr>'
            for x in reversed(recent15))
        # 连续净买入/净卖出天数
        streak, sgn = 0, 0
        for x in reversed(mg):
            s = 1 if x['net'] > 0 else -1
            if streak == 0:
                sgn, streak = s, 1
            elif s == sgn:
                streak += 1
            else:
                break
        trend = (f'已连续 <b>{streak}</b> 个交易日净{"买入" if sgn > 0 else "卖出"}'
                 if streak >= 2 else '最近一日方向不明')
        mg_html = f'''
<div class="kpi big">
  <div><span class="muted">最新余额</span><b>{cur:,.1f} 亿</b></div>
  <div><span class="muted">区间变化</span><b style="color:{_c(chg)}">{chg:+,.1f} 亿 ({pct:+.2f}%)</b></div>
  <div><span class="muted">数据截止</span><b>{mg[-1]['day']}</b></div>
</div>
{svg_margin(mg)}
<p>近 {len(mg)} 个交易日两融余额自 {first:,.0f} 亿降至 {cur:,.0f} 亿，<b style="color:{_c(chg)}">{pct:+.2f}%</b>；
   融资净买入最近 {streak} 日为{'净流入' if sgn > 0 else '净流出'}，{trend}。
   {'去杠杆仍在延续，杠杆资金尚未回稳。' if chg < 0 and sgn < 0 else
    ('杠杆资金已出现回补迹象。' if sgn > 0 else '余额仍在收缩，但净流出速度放缓。')}
   <span class="muted">（两融为 T+1 披露）</span></p>
<details><summary>近 15 日明细</summary>
<table class="tbl small"><thead><tr><th>日期</th><th>两融余额(亿)</th><th>融资余额(亿)</th>
<th>融资净买入(亿)</th></tr></thead><tbody>{rows}</tbody></table></details>'''

    stale = ''
    if d.get('stale'):
        stale = f'<div class="warn">{d["stale"]}</div>'

    body = f'''<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>自选股追踪 · {d["data_day"]}</title>
<style>
*{{box-sizing:border-box}}
body{{margin:0;padding:24px 16px 60px;background:#f6f7f9;color:#1f2937;
     font:15px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:820px;margin:0 auto}}
h1{{font-size:23px;margin:0 0 6px}}
h2{{font-size:17px;margin:30px 0 10px;padding-left:9px;border-left:4px solid #2563eb}}
h3{{font-size:17px;margin:0}}
h4{{font-size:14px;margin:18px 0 7px;color:#374151}}
.sub{{color:#6b7280;font-size:13px;margin-bottom:18px}}
.card{{background:#fff;border-radius:11px;padding:18px 20px;margin:13px 0;
      box-shadow:0 1px 3px rgba(16,24,40,.06)}}
.chead{{display:flex;justify-content:space-between;align-items:center;gap:10px;
       flex-wrap:wrap;border-bottom:1px solid #eef0f3;padding-bottom:10px}}
.tag{{font-size:12px;color:#4b5563;background:#f3f4f6;padding:3px 9px;border-radius:20px}}
.code{{font-size:12px;color:#9ca3af;font-weight:400;margin-left:4px}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(104px,1fr));gap:10px;margin:13px 0}}
.kpi>div{{background:#fafbfc;border:1px solid #eef0f3;border-radius:8px;padding:8px 11px}}
.kpi span{{display:block;font-size:11px;margin-bottom:2px}}
.kpi b{{font-size:15px}}
.kpi.big b{{font-size:17px}}
.tbl{{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px}}
.tbl.small{{font-size:12.5px}}
.tbl th{{background:#f3f4f6;text-align:left;padding:8px 9px;font-weight:600;
        color:#374151;white-space:nowrap;border-bottom:1px solid #e5e7eb}}
.tbl td{{padding:7px 9px;border-bottom:1px solid #f1f3f5}}
.tbl .num{{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}}
.tbl tbody tr:hover{{background:#fafbfc}}
.nm{{font-weight:600;white-space:nowrap}}
.news{{margin:6px 0;padding-left:20px}}
.news li{{margin:4px 0}}
.verdict{{margin:6px 0;padding-left:20px;font-size:13.5px}}
.verdict li{{margin:6px 0}}
.muted{{color:#9ca3af}}
.warn{{background:#fef3c7;border-left:4px solid #f59e0b;padding:11px 14px;
      border-radius:6px;margin:14px 0;font-size:13.5px}}
.note{{background:#eff6ff;border-left:4px solid #2563eb;padding:11px 14px;
      border-radius:6px;margin:14px 0;font-size:13.5px}}
details summary{{cursor:pointer;color:#2563eb;font-size:13px;margin:8px 0}}
a{{color:#2563eb;text-decoration:none}}
footer{{color:#9ca3af;font-size:12px;margin-top:34px;line-height:1.8;text-align:center}}
</style></head><body><div class="wrap">
<h1>自选股追踪 · 盘前报</h1>
<div class="sub">数据日 {d["data_day"]}（前一交易日收盘）｜生成 {d["stamp"]}｜
覆盖 {len(st)} 只自选股{d["fail_note"]}</div>
{stale}

<h2>一、A50 期货夜盘</h2>
<div class="card">{a50_html}</div>

<h2>二、两融余额趋势</h2>
<div class="card">{mg_html}</div>

<h2>三、自选股速览</h2>
<div class="card">{table_main(st)}
<p class="muted" style="font-size:12.5px">T+10 胜率旁括号内为去重后样本量；
红色表示高于该股自身全样本基准，绿色表示低于基准。</p></div>

<h2>四、个股详解</h2>
{''.join(block_stock(s) for s in st)}

<h2>五、今日关注</h2>
<div class="card">{d["focus"]}</div>

<h2>六、回测方法论与局限</h2>
<div class="card">{d["method"]}</div>

<footer>{d["disclaimer"]}</footer>
</div></body></html>'''
    return body


# ------------------------------------------------------------------ 摘要
def build_summary(d):
    st = d['stocks']
    url = d.get('url') or ''
    L = [f'**数据日 {d["data_day"]}**（前一交易日收盘）', '']
    if d.get('stale'):
        L += ['⚠️ ' + d['stale'].replace('<b>', '').replace('</b>', ''), '']

    a50 = d['a50']
    if a50:
        L.append(f'A50 夜盘 {a50["last"]:,.0f}（{a50["pct"]:+.2f}%），'
                 f'指向{"高开" if a50["pct"] > 0.3 else ("低开" if a50["pct"] < -0.3 else "平开")}。')
    mg = d['margin']
    if mg and len(mg) > 1:
        L.append(f'两融 {mg[-1]["total"]:,.0f} 亿，较 {len(mg)} 日前 '
                 f'{mg[-1]["total"] - mg[0]["total"]:+,.0f} 亿。')
    L.append('')

    # 只报最值得看的：相对基准偏离最大的两只
    ranked = []
    for s in st:
        bt = s['bt'] or {}
        n = (bt.get('near') or {}).get('win')
        b = (bt.get('base') or {}).get('win')
        if n and b:
            ranked.append((n - b, s, n, b))
    ranked.sort(key=lambda x: x[0])

    L.append('**自选股**（收盘/涨跌/RSI6/T+10胜率）')
    for s in st:
        nbt = (s['bt'] or {}).get('near') or {}
        win, nn = nbt.get('win'), nbt.get('n') or 0
        line = (f'- {s["name"]} {s["close"]:.2f}（{s["pct"]:+.2f}%）'
                f'　RSI6 {s["r6"]:.0f}')
        if win:
            line += f'　胜率 {win:.0f}%（n={nn}）'
        L.append(line)

    if ranked:
        L += ['', '**关键结论**']
        low = ranked[0]
        if low[0] <= -2:
            L.append(f'- {low[1]["name"]} RSI6 {low[1]["r6"]:.0f} 看似超卖，'
                     f'但同类读数 T+10 胜率仅 {low[2]:.0f}%（n={low[1]["bt"]["near"]["n"]}），'
                     f'低于自身基准 {low[3]:.0f}%，「跌多了」不构成买点')
        high = ranked[-1]
        if high[0] >= 2:
            L.append(f'- {high[1]["name"]} 同类读数胜率 {high[2]:.0f}%'
                     f'（n={high[1]["bt"]["near"]["n"]}），高于基准 {high[3]:.0f}%'
                     f'，信度{watch_conf(high[1]["bt"]["near"]["n"])}')

    if url:
        L += ['', f'[查看完整报告]({url})']
    L += ['', '_回测为单因子历史统计，未控制市场环境，不构成投资建议。_']
    return '\n'.join(L)


# ------------------------------------------------------------------ 关注点
def build_focus(d):
    st = d['stocks']
    items = []
    if not st:
        return '<p class="muted">无可用数据。</p>'

    # 1. 量能异常
    big = max((s for s in st if s['t_ratio']), key=lambda s: s['t_ratio'], default=None)
    if big and big['t_ratio'] >= 1.5:
        items.append(f'<li><b>{big["name"]}</b> 换手率达 20 日均值 <b>{big["t_ratio"]:.2f} 倍</b>，'
                     f'为自选股中最高，{"放量上涨需确认能否延续" if big["pct"] > 0 else "放量下跌要留意资金出逃"}。</li>')
    small = min((s for s in st if s['t_ratio']), key=lambda s: s['t_ratio'], default=None)
    if small and small['t_ratio'] <= 0.7:
        items.append(f'<li><b>{small["name"]}</b> 换手率仅 <b>{small["t_ratio"]:.2f} 倍</b>，'
                     f'缩量{"下跌说明抛压衰减，但反弹也缺量" if small["pct"] < 0 else "上涨，反弹动能不足"}。</li>')

    # 2. 均线得失
    for s in st:
        for k, label in ((20, 'MA20'), (60, 'MA60')):
            v = s['ma'].get(k)
            if not v:
                continue
            if s['now_above'].get(k) and not s['prev_above'].get(k):
                items.append(f'<li><b>{s["name"]}</b> 今日站上 {label}（{v:.2f}），'
                             f'是近期首次收复，可作为多头第一步确认。</li>')
            elif (not s['now_above'].get(k)) and s['prev_above'].get(k):
                items.append(f'<li><b>{s["name"]}</b> 今日跌破 {label}（{v:.2f}），'
                             f'短线转弱，反弹到该位置会有压力。</li>')

    # 3. 20 周线（主要参考）
    lost = [s for s in st if s['ma'].get('w20') and s['close'] < s['ma']['w20']]
    if lost:
        names = '、'.join(s['name'] for s in lost)
        items.append(f'<li><b>{names}</b> 仍在 20 周线下方运行，中期趋势未修复；'
                     f'20 周线是这套体系里的主参考，未收复前不宜重仓。</li>')

    # 4. 回测证伪
    falsified = []
    for s in st:
        bt = s['bt'] or {}
        n = (bt.get('near') or {}).get('win')
        b = (bt.get('base') or {}).get('win')
        if n and b and n < b - 2 and s['r6'] < 40:
            falsified.append((n - b, s, n, b))
    if falsified:
        falsified.sort()
        _, s, n, b = falsified[0]
        items.append(f'<li><b>反直觉</b>：{s["name"]} RSI6 已降至 {s["r6"]:.0f}，'
                     f'但历史同类读数 T+10 胜率 <b>{n:.0f}%</b>，低于自身基准 {b:.0f}%。'
                     f'超卖是<b>风险计量的输入</b>，不是买入信号。</li>')

    if not items:
        items.append('<li>自选股整体无显著异动，量能与均线均处于常态区间。</li>')
    return '<ul class="verdict">' + ''.join(items) + '</ul>'


def watch_conf(n):
    """可信度分级（摘要里也要标，避免把 n=8 的胜率当成结论）。"""
    if not n:
        return '极低'
    if n >= 30:
        return '高'
    if n >= 15:
        return '中'
    if n >= 8:
        return '偏低'
    return '极低'


def build_method():
    return '''
<p><b>RSI 口径</b>：通达信 SMA 平滑，RSI(N) = SMA(MAX(C−REF(C,1),0),N,1) /
SMA(ABS(C−REF(C,1)),N,1)×100，取近 640 个交易日前复权日线。<b>K 线为前复权</b>，
除权会造成价格跳空但不影响 RSI 与均线的连续性。</p>
<p><b>回测口径</b>：信号日收盘买入，持有 10 个交易日（T+10）以收盘价计算收益；
同时给出 T+5 胜率与持有期内以最低价计的最大回撤。样本按时间顺序贪心去重，
相邻信号至少间隔 5 个交易日，避免同一波行情被重复计数。四个口径分别为
就近匹配（RSI6 落点 ±N，N 从 3 逐级放宽到 12，取首个样本 ≥12 的档位）、
同档位、同档位+同向排列、全样本基准。</p>
<p><b>可信度分级</b>：n≥30 高、15–29 中、8–14 偏低、&lt;8 极低。</p>
<p><b>已知局限</b>：① 单因子回测未控制市场环境与板块 beta，牛市里任何超卖读数都好用；
② 未剔除个股自身趋势差异，长期下跌通道中的超卖会反复出现；③ 极端读数样本天然稀少；
④ 未计交易成本与滑点；⑤ 历史分布不代表未来。因此回测结论应作为
<b>风险偏好的调节系数</b>，而不是独立的买卖触发器 —— 它最有价值的用法是
<b>证伪</b>「跌多了就该涨」「金叉就该买」这类直觉。</p>
<p><b>量能口径</b>：以换手率倍数（当前换手 / 20 日均换手）为主指标，消除市值与
股价差异，比成交额之比更可比；成交额仅作补充。</p>
<p><b>两融口径</b>：交易所 T+1 披露，报告中的最新余额为上一交易日数据。</p>
'''
