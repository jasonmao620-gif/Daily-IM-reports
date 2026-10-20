#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自选股追踪 —— 云端主程序（每天北京 8:30 盘前推送）。

流程与主报告一致：取数 → 指标/回测 → 生成 HTML(写入 docs/) → 暂存摘要 → 推送微信。
拆成两步（--stage generate / push）是为了让工作流先把 HTML 推到仓库、
等 GitHub Pages 部署出 200 之后再推送，否则微信里点链接是 404。

用法：
    python3 watch_main.py --stage generate    # 只出报告，暂存摘要
    python3 watch_main.py --stage push        # Pages 就绪后推送微信
    python3 watch_main.py --dry-run           # 本地调试，出报告不推送
"""
import os
import sys
import json
import argparse
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, 'src'))
import watch          # noqa: E402
import watch_report   # noqa: E402
import push           # noqa: E402

DOCS = os.path.join(HERE, 'docs')
CACHE = os.path.join(HERE, '.cache')
PAGES_BASE = os.environ.get('PAGES_BASE', '').rstrip('/')


def _now_cn():
    """GitHub Actions 的机器时钟是 UTC，必须显式换算到北京时间。"""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
    except Exception:
        return dt.datetime.utcnow() + dt.timedelta(hours=8)


NOW = _now_cn()
TODAY = NOW.date()


def log(msg):
    print(f'[{NOW:%H:%M:%S}] {msg}', flush=True)


def prev_trading_day(ref):
    d = ref - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def check_stale(data_day):
    """盘前 8:30 跑，个股日线最后一根本来就应该是上一交易日。

    只有落后超过 4 天（超出正常周末+短假）才判定为取数异常。
    返回 (stale_html or '')
    """
    last = dt.date.fromisoformat(data_day)
    exp = prev_trading_day(TODAY)
    if last >= exp:
        return ''
    gap = (exp - last).days
    if gap <= 4:          # 节假日休市，属正常
        return ''
    return (f'个股日线最新只到 <b>{data_day}</b>，距上一交易日（{exp:%Y-%m-%d}）'
            f'已隔 {gap} 天，<b>大概率取数失败</b>，本报告结论可能已过期。')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', choices=['generate', 'push', 'all'], default='all')
    ap.add_argument('--dry-run', action='store_true', help='出报告但不推送')
    args = ap.parse_args()

    cache_fp = os.path.join(CACHE, 'msg_watch.json')

    # ---------- 推送阶段：直接读上一步暂存的摘要 ----------
    if args.stage == 'push':
        try:
            m = json.load(open(cache_fp, encoding='utf-8'))
        except Exception as e:
            log(f'读取暂存摘要失败: {e}')
            return 1
        ok, msg = push.send(m['title'], m['summary'])
        log(f'推送结果: {"成功" if ok else "失败"} | {msg}')
        return 0 if ok else 1

    # ---------- 取数 ----------
    log('开始取数：6 只自选股 + A50 + 两融')
    stocks, failed = watch.collect()
    if not stocks:
        log('全部自选股取数失败，终止（避免推送一份空报告）')
        return 1
    log(f'自选股成功 {len(stocks)} 只' + (f'，失败：{"、".join(failed)}' if failed else ''))

    a50 = watch.a50()
    log(f'A50 夜盘：{a50["last"]:,.1f}（{a50["pct"]:+.2f}%）' if a50 else 'A50 取数失败')

    mg = watch.margin(61)
    log(f'两融：{len(mg)} 个交易日，最新 {mg[-1]["total"]:,.1f} 亿（{mg[-1]["day"]}）'
        if mg else '两融取数失败')

    # 数据日取出现次数最多的日线日期（个别股票停牌会落后一天）
    days = [s['day'] for s in stocks]
    data_day = max(set(days), key=days.count)
    log(f'数据日：{data_day}')

    stale = check_stale(data_day)
    if stale:
        log('⚠️ 数据新鲜度异常，报告中会显式标注')

    d = dict(stocks=stocks, a50=a50, margin=mg, data_day=data_day,
             stamp=f'{NOW:%Y-%m-%d %H:%M}', stale=stale,
             fail_note=f'（{"、".join(failed)} 取数失败，未纳入）' if failed else '')

    d['focus'] = watch_report.build_focus(d)
    d['method'] = watch_report.build_method()
    d['disclaimer'] = ('本报告由脚本自动生成，数据来自腾讯行情、新浪财经、东方财富与交易所公开披露，'
                       '已尽力校验但不保证完全无误。历史回测为单因子统计，'
                       '不构成任何投资建议或买卖依据，据此操作风险自负。')

    # ---------- 出报告 ----------
    os.makedirs(DOCS, exist_ok=True)
    fname = f'watch-{data_day.replace("-", "")}.html'
    d['url'] = f'{PAGES_BASE}/{fname}' if PAGES_BASE else ''
    html = watch_report.build_html(d)
    path = os.path.join(DOCS, fname)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)
    log(f'报告已写入 {path}（{len(html):,} 字节）')

    summary = watch_report.build_summary(d)
    print('\n' + '=' * 60 + '\n微信摘要预览：\n' + '=' * 60)
    print(summary)
    print('=' * 60)

    title = f'自选股盘前 {data_day}｜{len(stocks)} 只'
    if a50:
        title += f'｜A50 {a50["pct"]:+.2f}%'

    os.makedirs(CACHE, exist_ok=True)
    if args.stage == 'generate':
        with open(cache_fp, 'w', encoding='utf-8') as f:
            json.dump(dict(title=title, summary=summary, url=d['url'], file=fname),
                      f, ensure_ascii=False)
        with open(os.path.join(CACHE, 'url_watch.txt'), 'w', encoding='utf-8') as f:
            f.write(d['url'])
        log('摘要已暂存 → 待 Pages 部署后执行 --stage push')
        return 0

    if args.dry_run:
        log('--dry-run：已跳过推送')
        return 0

    ok, msg = push.send(title, summary)
    log(f'推送结果: {"成功" if ok else "失败"} | {msg}')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
