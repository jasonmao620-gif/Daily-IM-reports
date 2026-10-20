#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报告生成 —— 同一份数据产出两个形态：
  1) HTML 全版（带表格/颜色）写入 docs/，由 GitHub Pages 提供公网链接
  2) 微信摘要（markdown，3-6 行结论 + 链接），因为微信通道不支持复杂表格
"""
import datetime as dt

CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#1f2328;--sub:#5b6470;--line:#e4e7ec;
--up:#d92b2b;--down:#0f9960;--warn:#b26a00;--warnbg:#fff7e6;--blue:#1f5fbf;--bluebg:#eef4ff;--greybg:#f0f2f5}
*{box-sizing:border-box}
body{margin:0;padding:28px 18px 60px;background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;color:var(--ink);line-height:1.75;font-size:15px}
.wrap{max-width:940px;margin:0 auto}
h1{font-size:26px;margin:0 0 6px}.meta{color:var(--sub);font-size:13px;margin-bottom:22px}
.sec{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px 22px;margin-bottom:18px}
.sec h2{font-size:18px;margin:0 0 14px;padding-bottom:10px;border-bottom:2px solid var(--line)}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:8px 0}
th,td{padding:7px 9px;border-bottom:1px solid var(--line);text-align:right}
th{background:var(--greybg);font-weight:600;color:var(--sub);font-size:12.5px}
td.left,th.left{text-align:left}
.up{color:var(--up);font-weight:600}.down{color:var(--down);font-weight:600}
.note{background:var(--greybg);border-left:3px solid var(--sub);padding:10px 14px;border-radius:0 6px 6px 0;font-size:13.5px;color:var(--sub);margin:12px 0}
.warn{background:var(--warnbg);border-left:3px solid var(--warn);padding:12px 15px;border-radius:0 6px 6px 0;font-size:14px;margin:12px 0}
.key{background:var(--bluebg);border-left:3px solid var(--blue);padding:12px 15px;border-radius:0 6px 6px 0;font-size:14px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px;margin:12px 0}
.stat{background:var(--greybg);border-radius:8px;padding:11px 13px}
.stat .k{font-size:12px;color:var(--sub)}.stat .v{font-size:19px;font-weight:700}.stat .d{font-size:12px;color:var(--sub)}
.foot{font-size:12.5px;color:var(--sub);margin-top:24px;padding:14px 18px;background:var(--card);border:1px solid var(--line);border-radius:10px}
"""

MULT_IM, MULT_MO = 200, 100


def cls(v):
    return 'up' if v > 0 else ('down' if v < 0 else '')


def fmt(v, p=2, suffix=''):
    if v is None:
        return '<span style="color:#999">数据缺失</span>'
    return f'{v:,.{p}f}{suffix}'


def pct(v, p=2):
    if v is None:
        return '<span style="color:#999">数据缺失</span>'
    return f'<span class="{cls(v)}">{v:+.{p}f}%</span>'


def build_html(d):
    """d = 汇总后的数据字典，见 main.py。"""
    c = d['core']
    im = d['im']
    pre = d.get('session') == 'premkt'
    kind = '盘前简报' if pre else '每日复盘'
    P = []
    A = P.append
    A(f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1.0">')
    A(f'<title>IM 中证1000 {kind} · {c["day"]}</title><style>{CSS}</style></head><body><div class="wrap">')
    A(f'<h1>IM 中证1000 {kind}</h1>')
    A(f'<div class="meta">数据日 {c["day"]}（A股收盘） · 生成于 {d["stamp"]} ｜ '
      f'中证1000现货 {fmt(c["close"])} '
      f'<span class="{cls(c["pct"])}">({c["pct"]:+.2f}%)</span></div>')
    if pre:
        A(f'<div class="key"><b>盘前版说明：</b>A 股与 IM 数据为 <b>{c["day"]}</b> 收盘（最近一个交易日）；'
          f'美股、VIX、黄金原油为 <b>最新隔夜完整收盘</b>（美股 4:00–5:00 北京时间已收）。'
          f'这是每天唯一能看到完整外围的时点。今日（{d.get("today","")}）盘中数据尚未产生。</div>')
    if d.get('stale'):
        A(f'<div class="warn" style="font-size:15px">⚠️ {d["stale"]}</div>')

    # 一、行情快照
    A('<div class="sec"><h2>一、行情快照</h2><div class="grid">')
    for k, v, dd in (('收盘', c['close'], f"{c['chg']:+.2f} ({c['pct']:+.2f}%)"),
                     ('RSI6', fmt(c['rsi6']), '极端超卖' if c['rsi6'] and c['rsi6'] < 15 else '超卖区'),
                     ('RSI14', fmt(c['rsi14']), ''),
                     ('MACD DIF', fmt(c['dif']), f'DEA {c["dea"]:.2f}')):
        A(f'<div class="stat"><div class="k">{k}</div><div class="v">{v}</div><div class="d">{dd}</div></div>')
    A('</div>')
    A(f'<div class="note">开 {fmt(c["open"])} ｜ 高 {fmt(c["high"])} ｜ 低 {fmt(c["low"])} ｜ '
      f'振幅 {fmt(c["ampl"])}% ｜ ATR14 {fmt(c["atr14"])} 点</div>')
    A('<table><tr><th class="left">均线</th><th>数值</th><th class="left">乖离</th></tr>')
    for name, v in (('MA5', c['ma5']), ('MA10', c['ma10']), ('MA20', c['ma20']),
                    ('MA60', c['ma60'])):
        dev = (c['close'] / v - 1) * 100 if v else None
        A(f'<tr><td class="left">{name}</td><td>{fmt(v)}</td>'
          f'<td class="left">{pct(dev)}</td></tr>')
    A(f'<tr><td class="left">布林下轨</td><td>{fmt(c["boll_lo"])}</td>'
      f'<td class="left">{pct((c["close"]/c["boll_lo"]-1)*100) if c["boll_lo"] else ""}</td></tr>')
    A('</table></div>')

    # 二、IM 合约
    A('<div class="sec"><h2>二、IM 期货合约</h2>')
    A('<table><tr><th class="left">合约</th><th>收盘</th><th>涨跌</th><th>持仓</th><th>持仓变化</th>'
      '<th>基差</th><th>贴水率</th></tr>')
    for code, r in im.items():
        basis = c['close'] - r['close']
        A(f'<tr><td class="left">{code}</td><td>{fmt(r["close"])}</td>'
          f'<td class="{cls(r["chg"])}">{r["chg"]:+.2f}</td>'
          f'<td>{r["oi"]:,}</td><td class="{cls(r["doi"])}">{r["doi"]:+,}</td>'
          f'<td>{basis:+.2f}</td><td>{basis/c["close"]*100:+.2f}%</td></tr>')
    A('</table>')
    if d.get('oi_note'):
        A(f'<div class="note">{d["oi_note"]}</div>')
    A('</div>')

    # 三、背离
    A('<div class="sec"><h2>三、顶/底背离监测</h2>')
    A(f'<div class="key"><b>当前状态：{d["div_text"]}</b><br>{d["div_detail"]}</div>')
    bt = d.get('div_bt')
    if bt:
        A('<table><tr><th class="left">持有期</th><th>上涨概率</th><th class="left">样本</th></tr>')
        for hz, (w, t) in sorted(bt['wins'].items()):
            if t:
                A(f'<tr><td class="left">T+{hz}</td><td><b>{w/t*100:.1f}%</b></td>'
                  f'<td class="left">{w} / {t}</td></tr>')
        A('</table>')
        if bt['dd_avg'] is not None:
            A(f'<div class="warn">历史底背离信号共 {bt["signals"]} 次。T+10 内最深回撤均值 '
              f'<b>{bt["dd_avg"]:.2f}%</b>、最坏 <b>{bt["dd_worst"]:.2f}%</b>（n={bt["dd_n"]}）。'
              f'只报胜率会误导——方向对不等于活得到终点。</div>')
    A('</div>')

    # 四、隔夜外围
    g = d.get('gidx') or {}
    A('<div class="sec"><h2>四、隔夜外围</h2><div class="grid">')
    for key, label in (('NDX', '纳斯达克'), ('SPX', '标普500'), ('DJIA', '道琼斯'), ('HSI', '恒生')):
        v = g.get(key)
        A(f'<div class="stat"><div class="k">{label}</div>'
          f'<div class="v">{fmt(v["last"]) if v else "—"}</div>'
          f'<div class="d">{pct(v["chg"]) if v else ""}</div></div>')
    A('</div><div class="grid">')
    vix = d.get('vix')
    A(f'<div class="stat"><div class="k">VIX</div><div class="v">{fmt(vix["last"]) if vix else "—"}</div>'
      f'<div class="d">{pct(vix["chg"]) if vix else ""}</div></div>')
    ust = d.get('ust')
    A(f'<div class="stat"><div class="k">美债10Y</div><div class="v">{fmt(ust[1]) if ust else "—"}%</div>'
      f'<div class="d">{ust[0] if ust else ""}（官方滞后1日）</div></div>')
    mb = d.get('margin')
    if mb:
        chg = (mb[-1]['rzrqye'] - mb[-2]['rzrqye']) / 1e8 if len(mb) > 1 else None
        A(f'<div class="stat"><div class="k">两融余额</div><div class="v">{mb[-1]["rzrqye"]/1e8:,.0f} 亿</div>'
          f'<div class="d">{mb[-1]["date"]} ｜ {chg:+.0f} 亿</div></div>')
    A('</div>')
    tr = d.get('transmit')
    if tr and tr.get('g2', {}).get('n'):
        lx = tr.get('last_ndx_chg')
        pick = pick_transmit_group(tr)
        A('<h3 style="font-size:15px;color:var(--blue);margin:18px 0 8px">'
          '纳指变动 → A股次日传导（历史配对）</h3>')
        if lx is not None:
            A(f'<div class="note">最近一夜纳指 <b>{lx:+.2f}%</b>。下表按涨跌幅分档，'
              f'<b>高亮那一行</b>才是与之匹配的历史分组——不要拿别的档位当今天的胜率。</div>')
        A('<table><tr><th class="left">条件</th><th>样本</th><th>次日上涨</th>'
          '<th>开盘</th><th>日内最低</th><th>收盘</th></tr>')
        for k in ('g2', 'g2_10', 'g1down', 'gflat', 'g1up', 'g1up_10'):
            s = tr.get(k) or {}
            if not s.get('n'):
                continue
            hl = (' style="background:#eef4ff;font-weight:700"'
                  if pick and s.get('label') == pick.get('label') else '')
            A(f'<tr{hl}><td class="left">{s["label"]}</td><td>{s["n"]}</td>'
              f'<td><b>{s["win"]:.1f}%</b></td><td>{s["open"]:+.2f}%</td>'
              f'<td>{s["low"]:+.2f}%</td><td>{s["close"]:+.2f}%</td></tr>')
        A('</table>')
        A('<div class="note">配对规则：纳指日期 d 的收盘 → 中证1000 中日期严格大于 d 的第一个交易日。'
          '开盘均值≈收盘均值意味着跌幅在开盘瞬间兑现，低开后追空性价比极低。</div>')
    A('</div>')

    # 五、期权
    mo = d.get('mo')
    if mo:
        A('<div class="sec"><h2>五、MO 期权情绪</h2>')
        A(f'<div class="note">近平值隐含波动率 <b>{fmt(mo["iv"])}%</b>（Black-76，远期取 {mo["fwd"]}）'
          f' ｜ 已实现波动率 近20日 {fmt(mo["rv20"])}% ｜ 近60日 {fmt(mo["rv60"])}%<br>'
          f'{mo["verdict"]}</div>')
        A(f'<div class="note">推荐参考：<b>{mo["code"]}</b> 权利金 {fmt(mo["prem"])} 点 = '
          f'{mo["prem"]*MULT_MO:,.0f} 元/张，3 张合计 {mo["prem"]*MULT_MO*3:,.0f} 元'
          f'（占 70 万账户 {mo["prem"]*MULT_MO*3/700000*100:.2f}%）。'
          f'到期 {mo["exp"]}（第三个星期三），IM 同月到期 {mo["im_exp"]}（第三个星期五）。</div>')
        A('</div>')

    # 六、展望
    A('<div class="sec"><h2>六、展望与操作关注点</h2>')
    for t in d.get('points', []):
        A(f'<div class="key">{t}</div>')
    A('</div>')

    A('<div class="foot"><b>数据截止：</b>' + '；'.join(d.get('stamps', [])) +
      '<br><br><b>免责声明：</b>本报告基于公开数据的量化统计与历史情景推演，<b>不构成投资建议</b>。'
      '历史概率不代表未来表现。股指期货为高杠杆品种，1 手 IM 名义价值约 130 万元，'
      '请严格控制仓位。</div>')
    A('</div></body></html>')
    return '\n'.join(P)


def pick_transmit_group(tr):
    """按「最近一夜」纳指的真实涨跌，挑出与之匹配的历史分组。

    原先固定取 g2_10（纳指跌超2%），当夜纳指上涨时会写出
    「隔夜纳指 +1.11%」紧接「同类情形：纳指跌超2%…」的自相矛盾。

    关键在于用 last_ndx_chg（最近一夜真实变动）而不是 latest_ndx
    （最后一对可回测的变动）——后者永远落后一夜，用它选组必然错位。
    """
    if not tr:
        return None
    lx = tr.get('last_ndx_chg')
    if lx is None:
        lx = tr.get('latest_ndx')
    if lx is None:
        return None
    r20 = tr.get('r20_now')
    deep = r20 is not None and r20 <= -10          # 当日处于深度超跌
    if lx <= -2.0:
        key = 'g2_10' if deep else 'g2'
    elif lx <= -1.0:
        key = 'g1down'
    elif lx >= 1.0:
        key = 'g1up_10' if deep else 'g1up'
    else:
        key = 'gflat'
    s = tr.get(key)
    return s if s and s.get('n') else None


def build_summary(d, url):
    """微信摘要：结论先行，表格压成一行行短句，末尾附完整版链接。"""
    c = d['core']
    im = d['im']
    main = d.get('main_contract')
    pre = d.get('session') == 'premkt'
    L = []
    if d.get('stale'):
        L.append(f'> ⚠️ 数据异常：{d["stale"]}'.replace('<b>', '').replace('</b>', ''))
        L.append('')
    if pre:
        L.append(f'**盘前简报 · A股数据日 {c["day"]}**')
    L.append(f'**中证1000 {c["close"]:,.2f}（{c["pct"]:+.2f}%）**')
    if main and main in im:
        r = im[main]
        L.append(f'IM{main[2:]} {r["close"]:,.2f}（{r["chg"]/r["prev"]*100:+.2f}%）'
                 f'｜持仓 {r["oi"]:,}（{r["doi"]:+,}）｜贴水 {(c["close"]-r["close"])/c["close"]*100:.2f}%')
    L.append(f'RSI6 {c["rsi6"]:.1f} ｜ RSI14 {c["rsi14"]:.1f} ｜ DIF {c["dif"]:.1f}')
    L.append('')
    L.append(f'**背离：** {d["div_short"]}')
    vix = d.get('vix')
    g = d.get('gidx') or {}
    ndx = g.get('NDX')
    if ndx:
        L.append(f'**隔夜：** 纳指 {ndx["last"]:,.0f}（{ndx["chg"]:+.2f}%）' +
                 (f'｜VIX {vix["last"]:.1f}（{vix["chg"]:+.1f}%）' if vix else ''))
    tr = d.get('transmit')
    s = pick_transmit_group(tr)
    if s:
        lx = tr.get('last_ndx_chg')
        L.append(f'**同类情形：** 当夜纳指 {lx:+.2f}%，参照历史同档「{s["label"]}」'
                 f'（n={s["n"]}）：次日上涨 {s["win"]:.0f}%，开盘 {s["open"]:+.2f}%、'
                 f'收盘 {s["close"]:+.2f}%')
    L.append('')
    L.append('**关键价位**')
    for name, v in d.get('levels', [])[:4]:
        L.append(f'- {name}：{v:,.0f}')
    L.append('')
    for i, t in enumerate(d.get('points_short', [])[:3], 1):
        L.append(f'{i}. {t}')
    L.append('')
    if url:
        L.append(f'[📄 完整报告（含全部表格）]({url})')
    L.append('')
    L.append('> 公开数据量化推演，不构成投资建议。')
    return '\n'.join(L)
