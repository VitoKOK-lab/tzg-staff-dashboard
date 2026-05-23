#!/usr/bin/env python3
"""TZG 部門 KPI 儀表板產生器 — 飛輪版"""
import json, sys
from pathlib import Path
from datetime import datetime, date

BASE          = Path(__file__).parent
DATA_DIR      = BASE / 'data'
OUTPUT        = BASE / 'output' / 'staff_latest.html'
TZG_DATA      = BASE.parent / 'tzg-dashboard' / 'data'
VIDEO_FILE    = BASE.parent / 'meta-dashboard' / 'data' / 'videos.json'
FOLLOWER_FILE = BASE.parent / 'meta-dashboard' / 'data' / 'follower_history.json'
STAFF_CFG     = BASE / 'staff_config.json'
MKT_PLANS     = DATA_DIR / 'marketing_plans.json'
CS_SCORES     = DATA_DIR / 'cs_scores.json'

def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except:
        return default if default is not None else {}

def get_period_label():
    today = date.today()
    return today.strftime('%Y-%m'), today.strftime('%Y 年 %m 月')

def num_fmt(n):
    if n >= 10000: return f'{n/10000:.1f}萬'
    if n >= 1000:  return f'{n/1000:.1f}K'
    return str(int(n))

def pct_color(p, good=80):
    return '#0ABAB5' if p >= good else '#B8892A' if p >= good * .65 else '#C94070'

# ── 訂單資料（一次載入，共用）────────────────────────────
def compute_orders(period_key):
    """pandas 一次載入全部訂單 → 業績、新客、推薦碼追蹤訂單"""
    cfg    = load_json(STAFF_CFG)
    target = cfg.get('company_targets', {}).get('monthly_revenue', 0)
    try:
        import pandas as pd
    except ImportError:
        return {'revenue':0,'orders':0,'target':int(target),'rev_rate':0,
                'new_customers':0,'new_cust_target':0,
                'utm_orders':0,'utm_revenue':0}

    dfs = []
    need_cols = {'訂單號碼','訂單日期','訂單合計','訂單狀態','顧客 ID','推薦代碼'}

    for f in sorted(TZG_DATA.glob('*.csv')):
        try:
            df = pd.read_csv(f, encoding='utf-8-sig', low_memory=False,
                             usecols=lambda c: c in need_cols)
            dfs.append(df)
        except: pass

    for f in sorted(TZG_DATA.glob('*.xls')) + sorted(TZG_DATA.glob('*.xlsx')):
        try:
            df = pd.read_excel(f, usecols=lambda c: c in need_cols)
            dfs.append(df)
        except: pass

    if not dfs:
        return {'revenue':0,'orders':0,'target':int(target),'rev_rate':0,
                'new_customers':0,'new_cust_target':0,
                'utm_orders':0,'utm_revenue':0}

    df = pd.concat(dfs, ignore_index=True).drop_duplicates(subset='訂單號碼')
    df['訂單日期']  = pd.to_datetime(df['訂單日期'], errors='coerce')
    df['訂單合計']  = pd.to_numeric(df['訂單合計'], errors='coerce').fillna(0)
    df['_period']   = df['訂單日期'].dt.to_period('M').astype(str)
    df_p = df[df['_period'] == period_key]

    # ── 業績 ──
    revenue = int(df_p['訂單合計'].sum())
    orders  = len(df_p)
    rev_rate = round(revenue / target * 100) if target else 0

    # ── 新客（本期首購）──
    df_sorted = df.sort_values('訂單日期')
    first_buy  = df_sorted.drop_duplicates(subset='顧客 ID', keep='first')
    new_cust   = int((first_buy['_period'] == period_key).sum())
    new_cust_t = cfg.get('company_targets', {}).get('monthly_new_customers', 0)

    # ── 推薦碼追蹤訂單（UTM / 訂製 / 代理）──
    has_code   = df_p['推薦代碼'].notna() & \
                 ~df_p['推薦代碼'].astype(str).str.strip().isin(['','nan','None'])
    utm_df     = df_p[has_code]
    utm_orders  = len(utm_df)
    utm_revenue = int(utm_df['訂單合計'].sum())

    return {
        'revenue': revenue, 'orders': orders,
        'target': int(target), 'rev_rate': rev_rate,
        'new_customers': new_cust, 'new_cust_target': new_cust_t,
        'utm_orders': utm_orders, 'utm_revenue': utm_revenue,
    }

# ── 影音內容 ─────────────────────────────────────────────
def compute_content(period_key):
    raw = load_json(VIDEO_FILE, {}).get('videos', {})
    videos = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    videos = [v for v in videos if isinstance(v, dict)]

    year, month = period_key.split('-')
    prefix = f'{year}-{month}'
    period_vids = [v for v in videos if str(v.get('created_date','')).startswith(prefix)]

    def avg(lst): return sum(lst)/len(lst) if lst else 0

    plays    = [v.get('plays',0)  for v in period_vids]
    reach    = [v.get('reach',0)  for v in period_vids]
    likes    = [v.get('likes',0)  for v in period_vids]
    comments = [v.get('comments',0) for v in period_vids]
    shares   = [v.get('shares',0) for v in period_vids]
    cr_list  = [v.get('completion_rate') or 0 for v in period_vids if v.get('completion_rate')]
    total_reach    = sum(reach)
    total_interact = sum(likes)+sum(comments)+sum(shares)
    interact_rate  = total_interact/total_reach*100 if total_reach else 0

    # 粉絲成長（follower_history.json）
    fh   = load_json(FOLLOWER_FILE, {})
    hist = [h for h in fh.get('history', []) if str(h.get('date','')).startswith(prefix)]
    fb_growth = sum(max(h.get('fb_net',0) or 0, 0) for h in hist)
    ig_growth = sum(max(h.get('ig_net',0) or 0, 0) for h in hist)

    # 最新粉絲總數
    all_hist = fh.get('history', [])
    latest_fb = next((h['fb_total'] for h in reversed(all_hist) if h.get('fb_total')), 0)
    latest_ig = next((h['ig_total'] for h in reversed(all_hist) if h.get('ig_total')), 0)

    cfg     = load_json(STAFF_CFG)
    targets = cfg.get('departments',{}).get('content',{}).get('kpi_targets',{})
    high_play_threshold = targets.get('high_play_threshold', 30000)
    high_plays = sum(1 for p in plays if p >= high_play_threshold)

    recent = sorted(period_vids, key=lambda v: v.get('plays',0), reverse=True)[:6]

    return {
        'count': len(period_vids),
        'target_count': targets.get('monthly_video_count', 12),
        'avg_plays': int(avg(plays)),
        'target_plays': targets.get('avg_plays', 14000),
        'avg_cr': round(avg(cr_list)*100, 1),
        'target_cr': round(targets.get('avg_completion_rate',0.154)*100,1),
        'total_reach': total_reach,
        'interact_rate': round(interact_rate, 1),
        'fb_growth': fb_growth,
        'ig_growth': ig_growth,
        'total_follower_growth': fb_growth + ig_growth,
        'latest_fb': latest_fb,
        'latest_ig': latest_ig,
        'high_plays': high_plays,
        'high_play_threshold': high_play_threshold,
        'recent': recent,
    }

# ── 行銷企劃 ─────────────────────────────────────────────
def compute_marketing(period_key, orders):
    plans = load_json(MKT_PLANS, {})
    p     = plans.get(period_key, {})
    mo    = p.get('monthly', {})
    goals, completed = mo.get('goals',[]), mo.get('completed',[])
    m_done  = sum(1 for c in completed if c)
    m_total = len(goals)

    week_stats, total_tasks, total_done = [], 0, 0
    for wk, wd in p.get('weeks',{}).items():
        tasks, done = wd.get('tasks',[]), wd.get('done',[])
        n_done, n_total = sum(1 for d in done if d), len(tasks)
        total_tasks += n_total; total_done += n_done
        week_stats.append({'label':wd.get('label',wk),'key':wk,'tasks':tasks,'done':done,
                           'n_done':n_done,'n_total':n_total,
                           'rate':round(n_done/n_total*100) if n_total else 0,
                           'review':wd.get('review','')})

    cfg     = load_json(STAFF_CFG)
    targets = cfg.get('departments',{}).get('marketing',{}).get('kpi_targets',{})
    ct      = cfg.get('company_targets',{})
    line_members   = ct.get('line_members_total', 20000)
    line_purchased = ct.get('line_members_purchased', 7000)

    return {
        'goals': goals, 'completed': completed,
        'm_done': m_done, 'm_total': m_total,
        'm_rate': round(m_done/m_total*100) if m_total else 0,
        'target_rate': round(targets.get('completion_rate_target',0.8)*100),
        'weeks': week_stats,
        'overall_done': total_done, 'overall_total': total_tasks,
        'overall_rate': round(total_done/total_tasks*100) if total_tasks else 0,
        'notes': mo.get('notes',''),
        'new_customers': orders['new_customers'],
        'new_cust_target': orders['new_cust_target'],
        'line_members': line_members,
        'line_purchased': line_purchased,
        'line_pipeline': line_members - line_purchased,
    }

# ── 銷售客服 ─────────────────────────────────────────────
def compute_sales_cs(period_key, orders):
    scores_all = load_json(CS_SCORES, {})
    period  = scores_all.get(period_key, {})
    members = period.get('members', [])
    rules   = period.get('scoring_rules', {})
    cfg     = load_json(STAFF_CFG)
    targets = cfg.get('departments',{}).get('sales_cs',{}).get('kpi_targets',{})
    ded_each = rules.get('complaint_deduction_each', 10)
    tiers   = cfg.get('bonus_reference',{}).get('tiers',[])

    def get_tier(score):
        for t in sorted(tiers, key=lambda x: x['min_score'], reverse=True):
            if score >= t['min_score']: return t
        return tiers[-1] if tiers else {}

    for m in members:
        if 'final_score' not in m:
            m['final_score'] = max(0, m.get('response_score',0) -
                                   m.get('deduction', m.get('complaints',0)*ded_each))
        m['tier'] = get_tier(m.get('final_score',0))

    members_sorted = sorted(members, key=lambda x: x.get('final_score',0), reverse=True)
    avg_score = sum(m.get('final_score',0) for m in members)/len(members) if members else 0

    return {
        'members': members_sorted,
        'avg_score': round(avg_score, 1),
        'target_score': targets.get('response_score_target', 85),
        'total_complaints': sum(m.get('complaints',0) for m in members),
        'max_complaints': targets.get('max_complaints_per_month', 2),
        'manager_notes': period.get('manager_notes',''),
        'utm_orders':  orders['utm_orders'],
        'utm_revenue': orders['utm_revenue'],
    }

# ── HTML 工具 ────────────────────────────────────────────
def ring_svg(pct, color, size=72):
    r = 28; circ = 2*3.14159*r; dash = circ*min(pct/100,1)
    return (f'<svg width="{size}" height="{size}" viewBox="0 0 64 64">'
            f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="#f0ece4" stroke-width="6"/>'
            f'<circle cx="32" cy="32" r="{r}" fill="none" stroke="{color}" stroke-width="6"'
            f' stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="{circ/4:.1f}"'
            f' stroke-linecap="round"/>'
            f'<text x="32" y="37" text-anchor="middle" font-size="13" font-weight="700"'
            f' fill="{color}">{pct}%</text></svg>')

def bar_html(pct, color):
    w = min(pct,100)
    return (f'<div style="background:#f0ece4;border-radius:99px;height:5px;overflow:hidden;margin-top:6px">'
            f'<div style="width:{w}%;height:100%;background:{color};border-radius:99px"></div></div>')

# ── 總覽 ─────────────────────────────────────────────────
def render_overview(mkt, content, cs, orders, period_label):
    # 業績卡
    rc = pct_color(orders['rev_rate'])
    rev_diff = orders['revenue'] - orders['target']
    diff_str = (f'+{rev_diff/10000:.1f}萬' if rev_diff>=0 else f'{rev_diff/10000:.1f}萬')
    diff_col = '#0ABAB5' if rev_diff>=0 else '#C94070'

    rev_card = f'''<div class="card" style="margin-bottom:20px">
  <div class="card-label">本月公司業績</div>
  <div style="display:flex;align-items:flex-end;gap:10px;margin:10px 0 6px">
    <div style="font-family:var(--serif);font-size:38px;font-weight:600;color:{rc};line-height:1">
      {orders['revenue']/10000:.1f}<span style="font-size:14px;font-weight:400;margin-left:2px">萬</span></div>
    <div style="font-size:12px;color:var(--dim);padding-bottom:6px">/ 目標 {orders['target']/10000:.0f}萬</div>
    <div style="font-size:14px;font-weight:700;color:{diff_col};padding-bottom:5px;margin-left:auto">{diff_str}</div>
    <div style="font-size:22px;font-weight:700;color:{rc};padding-bottom:4px">{orders['rev_rate']}%</div>
  </div>
  {bar_html(orders['rev_rate'], rc)}
  <div style="font-size:10px;color:var(--dim);margin-top:5px">本月訂單 {orders['orders']} 筆</div>
</div>'''

    # 飛輪三節點
    fg = content['total_follower_growth']
    nc = orders['new_customers']
    ur = orders['utm_revenue']
    fg_c = pct_color(min(fg/300*100,100))
    nc_c = pct_color(min(nc/400*100,100) if orders['new_cust_target']==0 else min(nc/orders['new_cust_target']*100,200))
    ur_c = '#B8892A'

    flywheel = f'''<div class="card-label" style="margin-bottom:12px">行銷飛輪 — 本月關鍵交接點</div>
<div style="display:flex;gap:10px;align-items:stretch;margin-bottom:24px;flex-wrap:wrap">
  <div class="fly-node c-cnt">
    <div class="fly-dept">影音內容</div>
    <div class="fly-num" style="color:{fg_c}">{num_fmt(fg)}</div>
    <div class="fly-label">本月新粉絲<br><span style="font-size:9px;color:var(--dim)">FB +{content['fb_growth']} · IG +{content['ig_growth']}</span></div>
  </div>
  <div class="fly-arrow">→</div>
  <div class="fly-node c-mkt">
    <div class="fly-dept">行銷企劃</div>
    <div class="fly-num" style="color:{nc_c}">{nc}</div>
    <div class="fly-label">本月新客首購<br><span style="font-size:9px;color:var(--dim)">LINE未購池 {num_fmt(mkt['line_pipeline'])} 人</span></div>
  </div>
  <div class="fly-arrow">→</div>
  <div class="fly-node c-cs">
    <div class="fly-dept">銷售客服</div>
    <div class="fly-num" style="color:{ur_c}">{ur/10000:.1f}<span style="font-size:14px;font-weight:400">萬</span></div>
    <div class="fly-label">推薦/訂製附加金額<br><span style="font-size:9px;color:var(--dim)">{orders['utm_orders']} 件可追蹤訂單</span></div>
  </div>
</div>'''

    # 部門燈號
    mkt_s = mkt['overall_rate'] if mkt['overall_total'] > 0 else None
    cs_s  = cs['avg_score'] if cs['members'] else None
    cnt_s = min(100, round(
        min(content['count']/max(content['target_count'],1),1)*40 +
        min(content['avg_plays']/max(content['target_plays'],1),1)*30 +
        min(content['avg_cr']/max(content['target_cr'],1),1)*30))

    def dept_light(label, score, color, subtitle):
        if score is None:
            return f'<div class="dept-light"><div class="dl-dot" style="background:#ddd"></div><div class="dl-name">{label}</div><div class="dl-sub">尚未填報</div></div>'
        c = pct_color(score)
        return f'<div class="dept-light"><div class="dl-dot" style="background:{c}"></div><div class="dl-name">{label}</div><div class="dl-score" style="color:{c}">{score}<span style="font-size:10px;font-weight:400"> {subtitle}</span></div></div>'

    lights = f'''<div class="card-label" style="margin-bottom:10px">部門狀態</div>
<div class="dept-lights">
  {dept_light("影音內容", cnt_s, "#0ABAB5", "綜合指標")}
  {dept_light("行銷企劃", mkt_s, "#C94070", "計劃完成率%")}
  {dept_light("銷售客服", cs_s, "#B8892A", "平均服務分")}
</div>'''

    return rev_card + flywheel + lights

# ── 影音內容 ─────────────────────────────────────────────
def render_content(c):
    fg = c['total_follower_growth']
    fg_c = pct_color(min(fg/200*100,100))

    vid_rows = ''
    for i, v in enumerate(c['recent'], 1):
        title = (v.get('title') or '')[:44] + ('…' if len(v.get('title',''))>44 else '')
        cr_v  = round((v.get('completion_rate') or 0)*100, 1)
        vtype = v.get('type','')
        type_lbl = '流量' if vtype=='traffic' else '帶貨' if vtype=='commerce' else '—'
        type_cls = 'type-t' if vtype=='traffic' else 'type-c'
        vid_rows += f'''<div class="vid-row">
  <div class="vid-rank">{i}</div>
  <div class="vid-info">
    <div class="vid-title">{title}</div>
    <div class="vid-meta">完播 {cr_v}% · 觸及 {num_fmt(v.get("reach",0))} · 讚 {num_fmt(v.get("likes",0))}</div>
  </div>
  <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px">
    <div class="vid-plays">{num_fmt(v.get("plays",0))}</div>
    <div class="vid-type {type_cls}">{type_lbl}</div>
  </div>
</div>'''

    kc = pct_color(min(c['count']/max(c['target_count'],1)*100,100))
    pc = pct_color(min(c['avg_plays']/max(c['target_plays'],1)*100,100))
    cc = pct_color(min(c['avg_cr']/max(c['target_cr'],1)*100,100))

    return f'''
<div class="hero-card" style="border-top:3px solid #0ABAB5">
  <div class="hero-label">本月新粉絲（FB + IG）</div>
  <div class="hero-num" style="color:{fg_c}">{num_fmt(fg)}</div>
  <div style="display:flex;gap:20px;margin-top:8px">
    <div class="hero-sub">FB <span style="color:#0ABAB5;font-weight:700">+{c['fb_growth']}</span></div>
    <div class="hero-sub">IG <span style="color:#C94070;font-weight:700">+{c['ig_growth']}</span></div>
    <div class="hero-sub" style="margin-left:auto">FB總計 {num_fmt(c['latest_fb'])} · IG總計 {num_fmt(c['latest_ig'])}</div>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{kc}">{c['count']}<span class="kpi-target">/{c['target_count']}</span></div>
    <div class="kpi-label">發片數 / 目標</div>{bar_html(min(c['count']/max(c['target_count'],1)*100,100),kc)}
  </div>
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{cc}">{c['avg_cr']}%<span class="kpi-target"> 目標{c['target_cr']}%</span></div>
    <div class="kpi-label">平均完播率</div>{bar_html(min(c['avg_cr']/max(c['target_cr'],1)*100,100),cc)}
  </div>
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{pc}">{num_fmt(c['avg_plays'])}</div>
    <div class="kpi-label">平均播放 <span style="font-size:10px;color:var(--dim)">目標 {num_fmt(c['target_plays'])}</span></div>{bar_html(min(c['avg_plays']/max(c['target_plays'],1)*100,100),pc)}
  </div>
  <div class="kpi-cell">
    <div class="kpi-big" style="color:#B8892A">{c['high_plays']}</div>
    <div class="kpi-label">爆款影片 <span style="font-size:10px;color:var(--dim)">≥{num_fmt(c['high_play_threshold'])}次</span></div>
  </div>
</div>

<div class="sec-title">本期熱門影片</div>
<div class="vid-list">{vid_rows if vid_rows else '<div style="color:var(--dim);font-size:13px">本期尚無影片</div>'}</div>
'''

# ── 行銷企劃 ─────────────────────────────────────────────
def render_marketing(m):
    if m['m_total'] == 0 and not m['weeks']:
        nc = m['new_customers']; nc_c = pct_color(min(nc/400*100,100))
        return f'''
<div class="hero-card" style="border-top:3px solid #C94070">
  <div class="hero-label">本月新客首購</div>
  <div class="hero-num" style="color:{nc_c}">{nc}<span style="font-size:18px;font-weight:400"> 人</span></div>
  <div class="hero-sub" style="margin-top:6px">LINE未購會員池 <strong>{num_fmt(m['line_pipeline'])}</strong> 人可觸及</div>
</div>
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:40px 24px;text-align:center;color:var(--dim)">
  <div style="font-size:32px;margin-bottom:14px">📋</div>
  <div style="font-size:15px;font-weight:600;color:var(--sub);margin-bottom:6px">本月計劃尚未填報</div>
  <div style="font-size:12px;line-height:1.8">雙擊「填報計劃.command」填入月度目標與週任務</div>
</div>'''

    nc = m['new_customers']; nc_c = pct_color(min(nc/400*100,100))
    mr_c = pct_color(m['m_rate'])

    goal_html = ''
    for g, done in zip(m['goals'], m['completed']):
        ic = '✓' if done else ''; cls = 'cb-done' if done else 'cb-pend'
        txt = f'<span style="text-decoration:line-through;color:var(--dim)">{g}</span>' if done else g
        goal_html += f'<div class="goal-row"><div class="goal-cb {cls}">{ic}</div>{txt}</div>'

    week_html = ''
    for w in m['weeks']:
        rate = w['rate']
        bc = '#d6f3f1' if rate>=80 else '#f3ebd4' if rate>=50 else '#fce4ec'
        tc = '#0ABAB5' if rate>=80 else '#B8892A' if rate>=50 else '#C94070'
        tasks_html = ''
        for task, done in zip(w['tasks'], w['done']):
            dot = 'dot-done' if done else 'dot-pend'
            txt = f'<span style="color:var(--dim);text-decoration:line-through">{task}</span>' if done else task
            tasks_html += f'<div class="wk-task"><div class="wk-dot {dot}"></div><span class="wk-txt">{txt}</span></div>'
        rev_html = f'<div class="wk-review">{w["review"]}</div>' if w.get('review') else ''
        week_html += f'''<div class="week-card">
  <div class="wk-hdr"><span class="wk-title">{w["label"]}</span>
    <span class="wk-badge" style="background:{bc};color:{tc}">{w["n_done"]}/{w["n_total"]} · {rate}%</span></div>
  {tasks_html}{rev_html}</div>'''

    return f'''
<div class="hero-card" style="border-top:3px solid #C94070">
  <div class="hero-label">本月新客首購</div>
  <div class="hero-num" style="color:{nc_c}">{nc}<span style="font-size:18px;font-weight:400"> 人</span></div>
  <div class="hero-sub" style="margin-top:6px">LINE未購會員池 <strong>{num_fmt(m['line_pipeline'])}</strong> 人 · 歷史覆購率 7%</div>
</div>

<div class="kpi-row">
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{mr_c}">{m['m_rate']}%</div>
    <div class="kpi-label">月度目標完成率<span style="font-size:10px;color:var(--dim)"> 目標{m['target_rate']}%</span></div>
    {bar_html(m['m_rate'], mr_c)}
  </div>
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{pct_color(m['overall_rate'])}">{m['overall_rate']}%</div>
    <div class="kpi-label">週任務完成率 <span style="font-size:10px;color:var(--dim)">{m['overall_done']}/{m['overall_total']}</span></div>
    {bar_html(m['overall_rate'], pct_color(m['overall_rate']))}
  </div>
</div>

<div class="sec-title">月度目標</div>
<div class="goal-list">{goal_html}</div>

<div class="sec-title">週任務</div>
<div class="week-grid">{week_html}</div>
'''

# ── 銷售客服 ─────────────────────────────────────────────
def render_sales_cs(cs):
    ur_c = '#B8892A'
    member_cards = ''
    for i, m in enumerate(cs['members'], 1):
        score = m.get('final_score', 0)
        sc    = pct_color(score)
        tier  = m.get('tier', {})
        tl    = tier.get('label','—')
        t_cls = 'bonus-ok' if score>=90 else 'bonus-warn' if score>=75 else 'bonus-fail'
        complaints_html = ''
        for d in m.get('complaint_details',[]):
            complaints_html += f'<div class="complaint-item">⚠ {d}</div>'
        bonus_note = f'<div style="font-size:10.5px;color:var(--tiff);margin-top:6px">★ {m["bonus_note"]}</div>' if m.get('bonus_note') else ''
        member_cards += f'''<div class="cs-card">
  <div class="cs-rank">#{i}</div>
  <div class="cs-name">{m['name']}</div>
  <div class="cs-score" style="color:{sc}">{score}</div>
  <div style="font-size:10px;color:var(--dim);margin-bottom:8px">最終得分</div>
  {bar_html(score, sc)}
  <div class="cs-detail" style="margin-top:10px">回覆分 {m.get("response_score","—")} · 客訴 {m.get("complaints",0)} 件 · 扣 {m.get("deduction",0)}</div>
  {f'<div style="font-size:10.5px;color:var(--sub);margin-top:3px">{m.get("response_note","")}</div>' if m.get("response_note") else ''}
  {complaints_html}{bonus_note}
  <div class="cs-tier {t_cls}">{tl} · {tier.get("note","")}</div>
</div>'''

    avg_c = pct_color(cs['avg_score'])
    comp_c = '#0ABAB5' if cs['total_complaints']<=cs['max_complaints'] else '#C94070'
    notes_html = f'<div class="sec-title">主管備注</div><div class="notes-box">{cs["manager_notes"]}</div>' if cs.get('manager_notes') else ''

    return f'''
<div class="hero-card" style="border-top:3px solid #B8892A">
  <div class="hero-label">本月推薦/訂製附加金額</div>
  <div style="display:flex;align-items:flex-end;gap:16px">
    <div class="hero-num" style="color:#B8892A">{cs['utm_revenue']/10000:.1f}<span style="font-size:18px;font-weight:400">萬</span></div>
    <div style="padding-bottom:8px">
      <div style="font-size:12px;color:var(--dim)">{cs['utm_orders']} 件可追蹤訂單</div>
      <div style="font-size:11px;color:var(--dim);margin-top:2px">含訂製加工・代理推薦・活動連結</div>
    </div>
  </div>
</div>

<div class="kpi-row">
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{avg_c}">{cs['avg_score']}</div>
    <div class="kpi-label">平均服務分 <span style="font-size:10px;color:var(--dim)">目標 {cs['target_score']}</span></div>
    {bar_html(cs['avg_score'], avg_c)}
  </div>
  <div class="kpi-cell">
    <div class="kpi-big" style="color:{comp_c}">{cs['total_complaints']}</div>
    <div class="kpi-label">本月客訴總數 <span style="font-size:10px;color:var(--dim)">上限 {cs['max_complaints']} 件</span></div>
  </div>
</div>

<div class="sec-title">客服人員評分（全員公開）</div>
<div class="cs-grid">{member_cards if member_cards else '<div style="color:var(--dim);font-size:13px;padding:16px 0">尚無評分，執行「填報計劃.command」填入</div>'}</div>
{notes_html}'''

# ── 主 render ────────────────────────────────────────────
def render(mkt, content, cs, orders, period_key, period_label):
    now_str = datetime.now().strftime('%Y/%m/%d %H:%M')
    ov = render_overview(mkt, content, cs, orders, period_label)
    ct = render_content(content)
    mk = render_marketing(mkt)
    sc = render_sales_cs(cs)

    return f'''<!DOCTYPE html>
<html lang="zh-TW"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>TZG KPI · {period_label}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600&family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{--gold:#B8892A;--pink:#C94070;--tiff:#0ABAB5;
  --text:#1a1a1a;--sub:#555;--dim:#999;--bg:#fff;--bg1:#fafaf7;--bg2:#f5f3ef;--bdr:rgba(0,0,0,.08);
  --serif:'Cormorant Garamond',serif;--sans:'Montserrat','PingFang TC',sans-serif}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:var(--sans);background:var(--bg1);color:var(--text);-webkit-font-smoothing:antialiased}}
.hdr{{background:var(--bg);border-bottom:1px solid var(--bdr);padding:12px 20px;display:flex;align-items:center;gap:12px;position:sticky;top:0;z-index:50}}
.hdr-brand{{font-family:var(--serif);font-size:17px;font-weight:600;letter-spacing:.2em;color:var(--gold)}}
.hdr-title{{font-size:11px;font-weight:600;color:var(--sub);flex:1}}
.hdr-date{{font-size:10px;color:var(--dim)}}
.dept-tabs{{display:flex;background:var(--bg);border-bottom:1px solid var(--bdr);padding:0 20px;gap:2px}}
.dtab{{padding:10px 16px;font-size:12px;font-weight:600;color:var(--dim);cursor:pointer;border-bottom:2px solid transparent;transition:color .14s,border-color .14s;white-space:nowrap;user-select:none}}
.dtab:hover{{color:var(--pink)}}.dtab.on{{color:var(--pink);border-bottom-color:var(--pink)}}
.content{{padding:20px;max-width:900px;margin:0 auto}}
.dept-sec{{display:none}}.dept-sec.on{{display:block}}
.card{{background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:18px 20px}}
.card-label{{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}}
.hero-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:20px 22px;margin-bottom:16px}}
.hero-label{{font-size:11px;font-weight:700;letter-spacing:.08em;color:var(--dim);margin-bottom:6px}}
.hero-num{{font-family:var(--serif);font-size:44px;font-weight:600;line-height:1}}
.hero-sub{{font-size:12px;color:var(--dim)}}
.kpi-row{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:20px}}
.kpi-cell{{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:14px 16px}}
.kpi-big{{font-family:var(--serif);font-size:28px;font-weight:600;line-height:1.1}}
.kpi-target{{font-size:13px;font-weight:400;color:var(--dim)}}
.kpi-label{{font-size:10px;color:var(--sub);margin-top:4px;margin-bottom:2px}}
.sec-title{{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);margin:20px 0 10px}}
/* Flywheel */
.fly-node{{flex:1;min-width:130px;background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:16px;text-align:center}}
.fly-dept{{font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);margin-bottom:6px}}
.fly-num{{font-family:var(--serif);font-size:32px;font-weight:600;line-height:1;margin-bottom:4px}}
.fly-label{{font-size:11px;color:var(--sub);line-height:1.5}}
.fly-arrow{{font-size:20px;color:var(--dim);align-self:center;flex-shrink:0}}
.c-cnt{{border-top:2px solid var(--tiff)}}.c-mkt{{border-top:2px solid var(--pink)}}.c-cs{{border-top:2px solid var(--gold)}}
/* Dept lights */
.dept-lights{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:4px}}
.dept-light{{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:14px 16px;flex:1;min-width:140px;display:flex;align-items:center;gap:10px}}
.dl-dot{{width:10px;height:10px;border-radius:50%;flex-shrink:0}}
.dl-name{{font-size:11px;font-weight:600;color:var(--sub);flex:1}}
.dl-score{{font-family:var(--serif);font-size:22px;font-weight:600}}
.dl-sub{{font-size:10px;color:var(--dim)}}
/* Content */
.vid-list{{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}}
.vid-row{{display:flex;gap:10px;align-items:center;background:var(--bg);border:1px solid var(--bdr);border-radius:10px;padding:10px 14px}}
.vid-rank{{font-family:var(--serif);font-size:16px;font-weight:600;color:var(--dim);width:20px;flex-shrink:0}}
.vid-info{{flex:1;min-width:0}}
.vid-title{{font-size:12px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.vid-meta{{font-size:10px;color:var(--dim);margin-top:2px}}
.vid-plays{{font-family:var(--serif);font-size:18px;font-weight:600;color:var(--gold);white-space:nowrap}}
.vid-type{{font-size:9px;font-weight:700;padding:2px 6px;border-radius:4px;margin-top:3px}}
.type-t{{background:#d6f3f1;color:var(--tiff)}}.type-c{{background:#fce4ec;color:var(--pink)}}
/* Marketing */
.goal-list{{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}}
.goal-row{{display:flex;align-items:flex-start;gap:10px;font-size:13px;color:var(--text)}}
.goal-cb{{width:18px;height:18px;border-radius:4px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;flex-shrink:0;margin-top:1px}}
.cb-done{{background:#d6f3f1;color:var(--tiff)}}.cb-pend{{background:var(--bg2);border:1.5px solid var(--bdr)}}
.week-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-bottom:20px}}
.week-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:14px}}
.wk-hdr{{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px}}
.wk-title{{font-size:12px;font-weight:700;color:var(--text)}}
.wk-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:99px}}
.wk-task{{display:flex;align-items:flex-start;gap:8px;margin-bottom:5px;font-size:11.5px}}
.wk-dot{{width:7px;height:7px;border-radius:50%;margin-top:3px;flex-shrink:0}}
.dot-done{{background:var(--tiff)}}.dot-pend{{background:#ddd}}
.wk-txt{{color:var(--sub)}}
.wk-review{{margin-top:8px;font-size:10.5px;color:var(--dim);padding-top:8px;border-top:1px solid var(--bg2)}}
/* CS */
.cs-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px;margin-bottom:20px}}
.cs-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:18px;position:relative}}
.cs-rank{{position:absolute;top:14px;right:14px;font-family:var(--serif);font-size:20px;color:var(--bdr)}}
.cs-name{{font-size:14px;font-weight:700;color:var(--text);margin-bottom:8px}}
.cs-score{{font-family:var(--serif);font-size:40px;font-weight:600;line-height:1}}
.cs-detail{{font-size:11px;color:var(--sub);margin-top:6px;line-height:1.6}}
.complaint-item{{margin-top:6px;padding:6px 8px;background:#fce4ec;border-radius:7px;font-size:10.5px;color:var(--pink)}}
.cs-tier{{margin-top:10px;font-size:10.5px;font-weight:700;padding:5px 10px;border-radius:7px}}
.bonus-ok{{background:#d6f3f1;color:var(--tiff)}}.bonus-warn{{background:#f3ebd4;color:var(--gold)}}.bonus-fail{{background:#fce4ec;color:var(--pink)}}
.notes-box{{background:var(--bg2);border-radius:10px;padding:12px;font-size:13px;color:var(--sub);margin-bottom:20px}}
@media(max-width:600px){{
  .kpi-row{{grid-template-columns:1fr 1fr}}
  .fly-arrow{{display:none}}
  .fly-node{{min-width:100%}}
  .dept-lights{{flex-direction:column}}
}}
</style></head><body>

<div class="hdr">
  <div class="hdr-brand">TZG</div>
  <div class="hdr-title">部門 KPI · {period_label}</div>
  <div class="hdr-date">更新 {now_str}</div>
</div>

<div class="dept-tabs">
  <div class="dtab on"  onclick="show('overview')">總覽</div>
  <div class="dtab"     onclick="show('content')">影音內容</div>
  <div class="dtab"     onclick="show('marketing')">行銷企劃</div>
  <div class="dtab"     onclick="show('cs')">銷售客服</div>
</div>

<div class="content">
  <div class="dept-sec on" id="s-overview">{ov}</div>
  <div class="dept-sec"    id="s-content">{ct}</div>
  <div class="dept-sec"    id="s-marketing">{mk}</div>
  <div class="dept-sec"    id="s-cs">{sc}</div>
</div>

<script>
function show(id){{
  document.querySelectorAll('.dtab').forEach((t,i)=>{{
    const ids=['overview','content','marketing','cs'];
    t.classList.toggle('on',ids[i]===id);
  }});
  document.querySelectorAll('.dept-sec').forEach(s=>{{
    s.classList.toggle('on',s.id==='s-'+id);
  }});
}}
</script></body></html>'''

# ── 主程式 ──────────────────────────────────────────────
def main():
    period_key, period_label = get_period_label()
    if len(sys.argv) > 1:
        period_key = sys.argv[1]
        period_label = period_key[:4] + ' 年 ' + period_key[5:] + ' 月'

    print(f'[TZG KPI] 產生 {period_label}...')
    orders  = compute_orders(period_key)
    content = compute_content(period_key)
    mkt     = compute_marketing(period_key, orders)
    cs      = compute_sales_cs(period_key, orders)

    html = render(mkt, content, cs, orders, period_key, period_label)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding='utf-8')

    print(f'[✓] {OUTPUT}')
    print(f'  業績達成：{orders["rev_rate"]}%（{orders["revenue"]:,} / 目標 {orders["target"]:,}）')
    print(f'  新粉絲：+{content["total_follower_growth"]}（FB +{content["fb_growth"]} · IG +{content["ig_growth"]}）')
    print(f'  新客：{orders["new_customers"]} 人')
    print(f'  推薦/訂製：{orders["utm_orders"]} 件 · {orders["utm_revenue"]:,} 元')
    print(f'  客服平均分：{cs["avg_score"]}')

if __name__ == '__main__':
    main()
