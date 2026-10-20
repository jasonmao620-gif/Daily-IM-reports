#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""IM 中证1000 每日复盘 —— 云端主程序。

流程：取数 → 指标/概率 → 生成 HTML(写入 docs/) → 生成微信摘要 → 推送到个人微信。
任何单一数据源失败只降级为「数据缺失」，绝不中断整条流水线。

两种运行时段（--session）：
    premkt  盘前版，早 7:00 跑。A股数据=上一交易日收盘（这是主动选择的，不是数据滞后）；
            美股/VX/商品=最新隔夜完整收盘（美股 4:00-5:00 北京时间已收）。
    close   复盘版，晚上跑。A股数据=当日收盘。

用法：
    python3 main.py --session premkt --stage generate   # 云端：只出报告
    python3 main.py --session premkt --stage push       # 云端：Pages 就绪后推送
    python3 main.py --dry-run                           # 本地调试：出报告不推送
"""
import os, re, sys, json, argparse, datetime as dt

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'src'))
import fetch, indicators as ind, report, push

def _now_cn():
    """北京时间。GitHub Actions 的机器时钟是 UTC，早 7 点北京时间=前一天 23:00 UTC，
    直接 dt.date.today() 会把日期算成前一天，报告标题和文件名都会错。"""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    except Exception:
        return dt.datetime.utcnow() + dt.timedelta(hours=8)


NOW_CN = _now_cn()
TODAY = NOW_CN.date()
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs')
PAGES_BASE = os.environ.get('PAGES_BASE', '').rstrip('/')   # 如 https://user.github.io/repo


def pick_main(im):
    """主力合约 = 持仓量最大者（调用前已剔除到期合约）。"""
    return max(im, key=lambda k: im[k]['oi']) if im else None


def expired(code):
    """IM 到期日 = 到期月第三个星期五。"""
    try:
        y, m = 2000 + int(code[2:4]), int(code[4:6])
    except Exception:
        return False
    return ind.third_fri(y, m) <= TODAY


def prev_trading_day(ref):
    """ref 之前最近的工作日（不处理法定节假日；节假日在下方用 gap 容忍）。"""
    d = ref - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def check_fresh(last_day_str, session):
    """判断数据是否新鲜。返回 (fresh, stale_html, expected_day_str)。

    盘前版与复盘版对「新鲜」的定义不同：
      - 复盘版：日线最后一根必须是今天，否则就是数据滞后 → 严重警告
      - 盘前版：日线最后一根本来就应该是上一交易日；只有落后超过 4 天
                 （超出正常周末+短假跨度）才判定为真的数据异常
    """
    last = dt.date.fromisoformat(last_day_str)
    if session == 'close':
        if last == TODAY:
            return True, '', f'{TODAY:%Y-%m-%d}'
        msg = (f'现货日线最新只到 <b>{last_day_str}</b>，今日（{TODAY:%Y-%m-%d}）数据尚未更新。'
               f'本报告全部现货指标基于 {last_day_str} 收盘，<b>不是当日复盘</b>。')
        return False, msg, f'{TODAY:%Y-%m-%d}'

    exp = prev_trading_day(TODAY)
    # 数据日 >= 期望日 都算新鲜：正常早7点跑会相等；
    # 手动在 15:05 之后测试时数据日会是"今天"，比期望更新，同样没问题。
    # （盘中运行时未完成的当日 K 线已在取数阶段被剔除，不会走到 last == TODAY 的情形）
    if last >= exp:
        return True, '', f'{last:%Y-%m-%d}'
    gap = (exp - last).days
    if gap <= 4:
        # 节假日休市，属正常，不当成数据故障
        return True, '', f'{last:%Y-%m-%d}'
    msg = (f'现货日线最新只到 <b>{last_day_str}</b>，距上一交易日（{exp:%Y-%m-%d}）已隔 {gap} 天，'
           f'<b>大概率取数失败</b>，本报告结论可能已过期。')
    return False, msg, f'{last:%Y-%m-%d}'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true', help='出报告但不推送')
    ap.add_argument('--no-push', action='store_true', help='同 --dry-run')
    ap.add_argument('--stage', choices=['generate', 'push', 'all'], default='all',
                    help='generate=只出报告并存摘要；push=只推送已存摘要；all=全部')
    ap.add_argument('--session', choices=['premkt', 'close'], default=None,
                    help='premkt=盘前版（早7点）；close=复盘版（晚间）。'
                         '不传则读环境变量 SESSION，再否则按北京时间 12 点前后自动判断')
    args = ap.parse_args()
    if not args.session:
        args.session = os.environ.get('SESSION') or ('premkt' if NOW_CN.hour < 12 else 'close')
    session = args.session

    stamps = []
    log = lambda m: print(f'[{NOW_CN:%H:%M:%S}] {m}', flush=True)
    log(f'运行时段：{"盘前版" if session == "premkt" else "复盘版"}　北京时间 {NOW_CN:%Y-%m-%d %H:%M}')

    # ---------- 1. 取数 ----------
    # 盘中标记：北京时间 15:05 前，日线最后一根（若日期是今天）属于未完成的盘中 K 线
    _mins = NOW_CN.hour * 60 + NOW_CN.minute
    intraday = _mins < 15 * 60 + 5
    log('取数：现货日线')
    kl = fetch.spot_kline(800)
    if not kl:
        print('FATAL: 现货日线取不到，无法生成报告')
        return 2
    snap = fetch.spot_today()
    kl, merged = fetch.merge_today(kl, snap, TODAY)
    if merged:
        log(f'  已用东财实时价补入当日 K 线 {TODAY:%Y-%m-%d}')

    # 盘中保护：定时任务 7:00 跑不会触发这条，但手动 Run workflow 极易在盘中撞上。
    # 那时日线最后一根是**未完成**的 K 线，直接当收盘价用，会把「10:22 的即时价」
    # 标成「A股收盘」——这正是 2026-10-20 首次云端测试暴露的问题。
    if intraday and kl[-1]['day'] == f'{TODAY:%Y-%m-%d}':
        dropped = kl[-1]['day']
        kl = kl[:-1]
        if len(kl) < 120:
            print('FATAL: 剔除未完成 K 线后剩余数据不足，终止')
            return 2
        log(f'  剔除未完成的当日 K 线 {dropped}（北京时间 {NOW_CN:%H:%M} 尚未收盘）'
            f' → 改用 {kl[-1]["day"]}')
    stamps.append(f'现货日线 {kl[-1]["day"]}')

    log('取数：纳指日线')
    ndx = fetch.ndx_kline(800)

    log('取数：IM 合约')
    im_raw = fetch.im_all(TODAY)
    im = {}
    for code, bars in im_raw.items():
        if expired(code):
            continue
        # 与现货同理：盘中运行时剔除未完成的当日 K 线，否则持仓/涨跌都是盘中的瞬时值
        if intraday and bars and bars[-1].get('day') == f'{TODAY:%Y-%m-%d}':
            bars = bars[:-1]
        if len(bars) >= 2:
            im[code] = dict(close=bars[-1]['close'], open=bars[-1]['open'],
                            high=bars[-1]['high'], low=bars[-1]['low'],
                            oi=bars[-1]['oi'], vol=bars[-1]['vol'],
                            prev=bars[-2]['close'], chg=bars[-1]['close'] - bars[-2]['close'],
                            doi=bars[-1]['oi'] - bars[-2]['oi'], day=bars[-1]['day'])
    mainc = pick_main(im)
    log(f'  挂牌 {sorted(im)} → 主力 {mainc}')
    if mainc:
        last_day = im[mainc]['day']
        stamps.append(f'IM{mainc[2:]} 日线 {last_day}')
        if last_day != kl[-1]['day']:
            log(f'  注意：IM 日线 {last_day} 与现货日线 {kl[-1]["day"]} 不同步'
                f'（期货结算价发布晚于指数，7:00 跑时两者应一致）')

    log('取数：中金所前20持仓')
    top20 = None
    for back in range(0, 6):                      # 向前找最近有数据的交易日
        d = TODAY - dt.timedelta(days=back)
        top20 = fetch.cffex_top20(d)
        if top20:
            stamps.append(f'前20持仓 {d:%Y-%m-%d}')
            break

    log('取数：外围（指数/VIX/美债/金油/两融）')
    g = fetch.global_indices()
    vix = fetch.vix()
    ust_raw = fetch.ust10y()
    ust = next(((d_, v) for d_, v in reversed(ust_raw) if v is not None), None) if ust_raw else None
    go = fetch.gold_oil()
    mb = fetch.margin_balance(6)
    if mb:
        stamps.append(f'两融 {mb[-1]["date"]}')
    if ust:
        stamps.append(f'美债10Y {ust[0]}')

    log('取数：MO 期权')
    mo_raw = fetch.mo_quotes()

    # ---------- 2. 指标 ----------
    c = ind.core(kl)
    sigs, div_state = ind.divergence(c)
    bt = ind.backtest_divergence(c)
    tr = ind.overnight_transmit(ndx, kl)
    if tr is not None and len(kl) >= 21:
        # 当日自身的 20 日涨跌幅：用于在「跌超2%」与「跌超2%+前20日跌超10%」之间选对分组
        tr['r20_now'] = (kl[-1]['close'] / kl[-21]['close'] - 1) * 100

    div_text = {'formed': '底背离成立（待确认）', 'unconfirmed': '底背离成立但未确认',
                'none': '无底背离信号'}[div_state]
    if div_state == 'none':
        div_detail = '近 10 个交易日内未出现「收盘创 60 日新低而 DIF 未同步新低」的形态。'
        div_short = '无底背离信号'
    else:
        div_detail = ('价格创 60 日新低而 DIF 未同步创新低，符合严格定义；'
                      '但确认信号是 <b>DIF 拐头向上</b>，目前尚未出现，'
                      '在此之前反弹只能按超跌修复对待。')
        div_short = '底背离成立，但 DIF 未拐头 → 未确认'

    # ---------- 3. 期权 ----------
    mo = None
    if mo_raw and mainc:
        try:
            mo_code_m = mainc[2:]                 # 如 2612
            fwd = im[mainc]['close']
            cs = {}
            for r in mo_raw:
                m = re.match(r'MO(\d{4})-([CP])-(\d+)', r['inst'])
                if not m:
                    continue
                if m.group(1) == mo_code_m and m.group(2) == 'C':
                    cs[int(m.group(3))] = r
            if cs:
                # 选第一个略高于现货的行权价（虚值看涨）
                strikes = sorted(cs)
                k_atm = min(strikes, key=lambda k: abs(k - c['close']))
                cand = [k for k in strikes if k >= c['close']] or [k_atm]
                K = cand[0]
                y, mth = 2000 + int(mo_code_m[:2]), int(mo_code_m[2:])
                exp = ind.third_wed(y, mth)
                T = max((exp - TODAY).days / 365, 1 / 365)
                iv = ind.implied_vol(fwd, K, T, 0.02, cs[K]['last'])
                rv20 = ind.realized_vol(c['closes'], 20)
                rv60 = ind.realized_vol(c['closes'], 60)
                if iv and rv20:
                    diff = (iv - rv20) * 100
                    verdict = ('期权定价合理，未出现恐慌溢价' if abs(diff) < 5 else
                               ('期权偏贵，隐含波动率显著高于已实现' if diff > 0 else
                                '期权偏便宜，隐含波动率低于已实现'))
                    mo = dict(iv=iv * 100, rv20=(rv20 or 0) * 100, rv60=(rv60 or 0) * 100,
                              code=f'MO{mo_code_m}-C-{K}', prem=cs[K]['last'],
                              fwd=mainc, exp=f'{exp:%Y-%m-%d}',
                              im_exp=f'{ind.third_fri(y, mth):%Y-%m-%d}', verdict=verdict)
        except Exception as e:
            log(f'  期权解析失败（跳过）: {e}')

    # ---------- 4. 关键价位与结论 ----------
    levels = []
    if c['boll_lo']:
        levels.append(('布林下轨', c['boll_lo']))
    levels.append(('近5日低点', min(c['lows'][-5:])))
    if c['ma5']:
        levels.append(('MA5（压力）', c['ma5']))
    levels.append(('近5日高点', max(c['highs'][-5:])))

    head = mainc[2:] if mainc else '—'
    oi_note = ''
    if mainc and im[mainc]['doi'] != 0:
        up = im[mainc]['chg'] > 0
        doi = im[mainc]['doi']
        if up and doi < 0:
            oi_note = (f'<b>{mainc} 减仓上涨</b>（持仓 {doi:+,}，价格 {im[mainc]["chg"]:+.2f}）——'
                       '下跌趋势中的减仓上涨通常意味着<b>空头主动离场</b>，'
                       '与「增仓下跌」（新空进场）性质相反。')
        elif up and doi > 0:
            oi_note = f'{mainc} 增仓上涨（持仓 {doi:+,}），新多进场。'
        elif not up and doi > 0:
            oi_note = (f'<b>{mainc} 增仓下跌</b>（持仓 {doi:+,}）——有新资金持续做空，'
                       '属典型空头打压，尚未见到下跌末端信号。')
        else:
            oi_note = f'{mainc} 减仓下跌（持仓 {doi:+,}），多头止损离场为主。'

    pts = []
    if div_state != 'none':
        pts.append('<b>本周观察重点是 DIF 是否拐头，不是涨跌幅。</b>底背离已成立，'
                   '但确认信号是 DIF 拐头向上。在此之前任何反弹都按超跌修复处理，不加仓。')
    if tr and tr.get('g2', {}).get('n'):
        s = tr['g2']
        pts.append(f'<b>不在低开瞬间追空。</b>历史上纳指跌超 2% 的 {s["n"]} 次里，'
                   f'次日开盘均值 {s["open"]:+.2f}%、收盘均值 {s["close"]:+.2f}%——'
                   '跌幅基本在开盘那一刻兑现完。')
    pts.append('<b>仓位纪律：70 万账户，IM 最多 1 手，绝不 2 手。</b>'
               '1 手名义约 130 万 = 账户 1.88 倍；若担心被波动震出局，'
               '优先用 MO 买权替代期货多头，最大亏损锁定为权利金。')

    # ---------- 数据新鲜度防呆 ----------
    # 最危险的失效模式：报告挂着今天的日期，装的是过期的数据。
    # 盘前版与复盘版的「新鲜」标准不同，见 check_fresh 注释。
    fresh, stale, expected_day = check_fresh(kl[-1]['day'], session)
    data_day = kl[-1]['day']
    if not fresh:
        log(f'!! 数据异常：日线最新 {data_day}，应为 {expected_day}')
    else:
        log(f'数据校验通过：日线最新 {data_day}（{"盘前应为上一交易日" if session=="premkt" else "复盘应为当日"}）')
    stamps.append(f'报告生成 {NOW_CN:%Y-%m-%d %H:%M}（北京时间）')

    pts_short = ['DIF 未拐头前，反弹只算超跌修复，不加仓',
                 '低开瞬间不追空，跌幅多在开盘兑现完',
                 '70 万账户 IM 最多 1 手；怕被震出局就用 MO 买权']

    d = dict(core=c, im=im, main_contract=mainc, gidx=g, vix=vix, ust=ust,
             gold_oil=go, margin=mb, transmit=tr, div_text=div_text,
             div_detail=div_detail, div_short=div_short, div_bt=bt, mo=mo,
             levels=levels, oi_note=oi_note, points=pts, points_short=pts_short,
             stamp=f'{NOW_CN:%Y-%m-%d %H:%M}', stamps=stamps,
             stale=stale, fresh=fresh, session=session, data_day=data_day,
             today=f'{TODAY:%Y-%m-%d}')

    # ---------- 5. 出报告 ----------
    os.makedirs(DOCS, exist_ok=True)
    fname = f'daily-{kl[-1]["day"].replace("-", "")}.html'
    html = report.build_html(d)
    path = os.path.join(DOCS, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f'报告已写入 {path}（{len(html):,} 字节）')

    # 更新索引页，方便翻历史
    # 两类报告共用一个索引：daily-* 是 IM 期货盘前报，watch-* 是自选股报。
    # 自选股流水线不写 index（否则两条 workflow 会互相覆盖），只在主报告里统一重建。
    try:
        def _li(prefix):
            xs = sorted([x for x in os.listdir(DOCS) if x.startswith(prefix)], reverse=True)
            return '\n'.join(f'<li><a href="{x}">{x[len(prefix):len(prefix)+4]}-'
                             f'{x[len(prefix)+4:len(prefix)+6]}-{x[len(prefix)+6:len(prefix)+8]}</a></li>'
                             for x in xs[:40])

        li_d, li_w = _li('daily-'), _li('watch-')
        with open(os.path.join(DOCS, 'index.html'), 'w', encoding='utf-8') as f:
            f.write(f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">'
                    f'<meta name="viewport" content="width=device-width,initial-scale=1">'
                    f'<title>每日简报索引</title></head>'
                    f'<body style="font-family:-apple-system,BlinkMacSystemFont,\'PingFang SC\','
                    f'sans-serif;padding:30px;max-width:640px;margin:auto;line-height:1.8">'
                    f'<h2>IM 中证1000 盘前简报</h2><ul>{li_d}</ul>'
                    f'<h2>自选股追踪</h2><ul>{li_w}</ul></body></html>')
    except Exception as e:
        log(f'  索引页更新失败: {e}')

    # ---------- 6. 推送 ----------
    url = f'{PAGES_BASE}/{fname}' if PAGES_BASE else ''
    summary = report.build_summary(d, url)
    print('\n' + '=' * 60 + '\n微信摘要预览：\n' + '=' * 60)
    print(summary)
    print('=' * 60)

    title = (f'IM{"盘前" if session=="premkt" else "复盘"} {c["day"]}｜'
             f'{c["close"]:,.0f} ({c["pct"]:+.2f}%)')
    cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.cache')
    cache_fp = os.path.join(cache_dir, 'msg.json')

    if args.stage == 'generate':
        # 只出报告并存摘要。推送要等 Pages 部署完成后再单独执行，
        # 否则微信里的链接点开是 404。
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_fp, 'w', encoding='utf-8') as f:
            json.dump(dict(title=title, summary=summary, url=url, file=fname), f, ensure_ascii=False)
        # 供工作流轮询 Pages 用：文件名按「数据日期」命名，不一定等于 UTC 当天，
        # 所以不能让 shell 用 date 自己拼。
        with open(os.path.join(cache_dir, 'url.txt'), 'w', encoding='utf-8') as f:
            f.write(url or '')
        log(f'摘要已暂存 → 待 Pages 部署后执行 --stage push')
        return 0

    if args.stage == 'push':
        try:
            m = json.load(open(cache_fp, encoding='utf-8'))
        except Exception as e:
            log(f'读取暂存摘要失败: {e}')
            return 1
        ok, msg = push.send(m['title'], m['summary'])
        log(f'推送结果: {"成功" if ok else "失败"} | {msg}')
        return 0 if ok else 1

    if args.dry_run or args.no_push:
        log('--dry-run：已跳过推送')
        return 0
    ok, msg = push.send(title, summary)
    log(f'推送结果: {"成功" if ok else "失败"} | {msg}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
