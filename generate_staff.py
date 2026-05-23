#!/usr/bin/env python3
"""
TZG 員工部門績效儀表板產生器
讀取現有資料（唯讀），輸出 output/staff_latest.html
"""
import json
import sys
from pathlib import Path
from datetime import datetime, date
import glob

# ── 路徑設定 ────────────────────────────────────────────
BASE      = Path(__file__).parent
DATA_DIR  = BASE / 'data'
OUTPUT    = BASE / 'output' / 'staff_latest.html'

# 現有系統（唯讀）
TZG_DATA  = BASE.parent / 'tzg-dashboard' / 'data'
VIDEO_FILE = BASE.parent / 'meta-dashboard' / 'data' / 'videos.json'

STAFF_CFG = BASE / 'staff_config.json'
MKT_PLANS = DATA_DIR / 'marketing_plans.json'
CS_SCORES = DATA_DIR / 'cs_scores.json'

# ── 資料載入 ────────────────────────────────────────────
def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[WARN] 無法讀取 {path}: {e}')
        return default or {}

def load_orders():
    """讀取所有訂單 CSV/XLSX，合併成 list of dicts"""
    import csv
    rows = []
    csvs = sorted(TZG_DATA.glob('TZG_*.csv'))
    for f in csvs:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                reader = csv.DictReader(fh)
                for r in reader:
                    r['_src'] = f.name
                    rows.append(r)
        except Exception as e:
            print(f'[WARN] CSV 讀取失敗 {f.name}: {e}')
    # XLSX
    try:
        import openpyxl
        for f in sorted(TZG_DATA.glob('*.xlsx')):
            try:
                wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
                ws = wb.active
                headers = None
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i == 0:
                        headers = [str(c).strip() if c else f'col{i}' for i, c in enumerate(row)]
                        continue
                    if headers and any(row):
                        d = dict(zip(headers, row))
                        d['_src'] = f.name
                        rows.append(d)
            except Exception as e:
                print(f'[WARN] XLSX 讀取失敗 {f.name}: {e}')
    except ImportError:
        print('[WARN] openpyxl 未安裝，略過 XLSX')
    return rows

def get_period_label():
    today = date.today()
    return today.strftime('%Y-%m'), today.strftime('%Y 年 %m 月')

# ── 部門計算：影音內容 ───────────────────────────────────
def compute_content(period_key):
    raw = load_json(VIDEO_FILE, {}).get('videos', {})
    # videos field may be a dict {id: {...}} or a list
    if isinstance(raw, dict):
        videos = list(raw.values())
    elif isinstance(raw, list):
        videos = raw
    else:
        videos = []

    if not videos:
        # archive.json fallback
        arc = load_json(BASE.parent / 'meta-dashboard' / 'data' / 'archive.json', {})
        arc_raw = arc.get('videos', {})
        videos = list(arc_raw.values()) if isinstance(arc_raw, dict) else (arc_raw if isinstance(arc_raw, list) else [])

    year, month = period_key.split('-')
    prefix = f'{year}-{month}'

    period_vids = [v for v in videos if isinstance(v, dict) and str(v.get('created_date', '')).startswith(prefix)]
    all_vids    = [v for v in videos if isinstance(v, dict)]

    def safe_avg(lst):
        return sum(lst) / len(lst) if lst else 0

    count   = len(period_vids)
    plays   = [v.get('plays', 0) for v in period_vids]
    reach   = [v.get('reach', 0) for v in period_vids]
    likes   = [v.get('likes', 0) for v in period_vids]
    comments = [v.get('comments', 0) for v in period_vids]
    shares  = [v.get('shares', 0) for v in period_vids]
    followers = [v.get('new_followers', 0) for v in period_vids]
    cr_list = [v.get('completion_rate', 0) for v in period_vids if v.get('completion_rate')]

    total_reach = sum(reach)
    total_interact = sum(likes) + sum(comments) + sum(shares)
    interact_rate = total_interact / total_reach * 100 if total_reach else 0

    traffic_n  = sum(1 for v in period_vids if v.get('type') == 'traffic')
    commerce_n = sum(1 for v in period_vids if v.get('type') == 'commerce')

    # 近期影片列表（最多8支）
    recent = sorted(period_vids, key=lambda v: v.get('plays', 0), reverse=True)[:8]

    cfg = load_json(STAFF_CFG)
    targets = cfg.get('departments', {}).get('content', {}).get('kpi_targets', {})

    return {
        'count': count,
        'target_count': targets.get('monthly_video_count', 12),
        'avg_plays': int(safe_avg(plays)),
        'target_plays': targets.get('avg_plays', 3000),
        'avg_cr': round(safe_avg(cr_list) * 100, 1),
        'target_cr': round(targets.get('avg_completion_rate', 0.15) * 100, 1),
        'total_reach': sum(reach),
        'interact_rate': round(interact_rate, 2),
        'new_followers': sum(followers),
        'target_followers': targets.get('monthly_new_followers', 500),
        'traffic_n': traffic_n,
        'commerce_n': commerce_n,
        'recent': recent,
    }

# ── 公司業績：讀訂單月營收 ───────────────────────────────
def compute_revenue(period_key):
    """從訂單 CSV/XLS 算出本月營收，並與 staff_config 目標比較。
    使用 pandas（與 generate_daily.py 相同邏輯），去重後計算。"""
    cfg = load_json(STAFF_CFG)
    target = cfg.get('company_targets', {}).get('monthly_revenue', 0)

    try:
        import pandas as pd
    except ImportError:
        print('[WARN] pandas 未安裝，跳過營收計算')
        return {'revenue': 0, 'orders': 0, 'target': int(target), 'rate': 0}

    year, month = period_key.split('-')
    prefix = f'{year}-{month}'
    dfs = []

    # CSV files
    for f in sorted(TZG_DATA.glob('*.csv')):
        try:
            df = pd.read_csv(f, encoding='utf-8-sig', low_memory=False,
                             usecols=lambda c: c in ('訂單號碼', '訂單日期', '訂單合計', '訂單狀態'))
            dfs.append(df)
        except Exception:
            pass

    # XLS / XLSX files (Shopline format, xlrd or openpyxl)
    for f in sorted(TZG_DATA.glob('*.xls')) + sorted(TZG_DATA.glob('*.xlsx')):
        try:
            df = pd.read_excel(f, usecols=lambda c: c in ('訂單號碼', '訂單日期', '訂單合計', '訂單狀態'))
            dfs.append(df)
        except Exception:
            pass

    if not dfs:
        return {'revenue': 0, 'orders': 0, 'target': int(target), 'rate': 0}

    df = pd.concat(dfs, ignore_index=True)

    # 去重（同一訂單在多個檔案中重複出現）
    df = df.drop_duplicates(subset='訂單號碼')

    # 過濾本期
    df['訂單日期'] = pd.to_datetime(df['訂單日期'], errors='coerce')
    mask = df['訂單日期'].dt.to_period('M').astype(str) == period_key
    df_period = df[mask].copy()

    df_period['訂單合計'] = pd.to_numeric(df_period['訂單合計'], errors='coerce').fillna(0)
    total = float(df_period['訂單合計'].sum())
    orders = int(len(df_period))

    rate = round(total / target * 100) if target else 0
    return {
        'revenue': int(total),
        'orders': orders,
        'target': int(target),
        'rate': rate,
    }

# ── 部門計算：行銷企劃 ───────────────────────────────────
def compute_marketing(period_key):
    plans = load_json(MKT_PLANS, {})
    p = plans.get(period_key, {})

    monthly = p.get('monthly', {})
    goals     = monthly.get('goals', [])
    completed = monthly.get('completed', [])
    monthly_done = sum(1 for c in completed if c)
    monthly_total = len(goals)
    monthly_rate  = monthly_done / monthly_total * 100 if monthly_total else 0

    weeks = p.get('weeks', {})
    week_stats = []
    total_tasks = 0
    total_done  = 0
    for wk, wd in weeks.items():
        tasks = wd.get('tasks', [])
        done  = wd.get('done', [])
        n_done = sum(1 for d in done if d)
        n_total = len(tasks)
        total_tasks += n_total
        total_done  += n_done
        week_stats.append({
            'label': wd.get('label', wk),
            'key': wk,
            'tasks': tasks,
            'done': done,
            'n_done': n_done,
            'n_total': n_total,
            'rate': round(n_done / n_total * 100) if n_total else 0,
            'review': wd.get('review', ''),
        })

    cfg = load_json(STAFF_CFG)
    targets = cfg.get('departments', {}).get('marketing', {}).get('kpi_targets', {})

    return {
        'goals': goals,
        'completed': completed,
        'monthly_done': monthly_done,
        'monthly_total': monthly_total,
        'monthly_rate': round(monthly_rate),
        'target_rate': round(targets.get('completion_rate_target', 0.8) * 100),
        'weeks': week_stats,
        'overall_done': total_done,
        'overall_total': total_tasks,
        'overall_rate': round(total_done / total_tasks * 100) if total_tasks else 0,
        'notes': monthly.get('notes', ''),
    }

# ── 部門計算：銷售客服 ───────────────────────────────────
def compute_sales_cs(period_key):
    scores_all = load_json(CS_SCORES, {})
    period = scores_all.get(period_key, {})
    members = period.get('members', [])
    rules   = period.get('scoring_rules', {})

    cfg = load_json(STAFF_CFG)
    targets = cfg.get('departments', {}).get('sales_cs', {}).get('kpi_targets', {})

    for m in members:
        # 確保 final_score 計算
        if 'final_score' not in m:
            base = m.get('response_score', 0)
            deduct = m.get('deduction', m.get('complaints', 0) * rules.get('complaint_deduction_each', 10))
            m['final_score'] = max(0, base - deduct)
        m['deduction'] = m.get('deduction', m.get('complaints', 0) * 10)

    members_sorted = sorted(members, key=lambda x: x.get('final_score', 0), reverse=True)

    avg_score = sum(m.get('final_score', 0) for m in members) / len(members) if members else 0
    total_complaints = sum(m.get('complaints', 0) for m in members)

    cfg_bonus = cfg.get('bonus_reference', {})
    tiers = cfg_bonus.get('tiers', [])

    def get_tier(score):
        for t in sorted(tiers, key=lambda x: x['min_score'], reverse=True):
            if score >= t['min_score']:
                return t
        return tiers[-1] if tiers else {}

    for m in members_sorted:
        m['tier'] = get_tier(m.get('final_score', 0))

    return {
        'members': members_sorted,
        'avg_score': round(avg_score, 1),
        'target_score': targets.get('response_score_target', 85),
        'total_complaints': total_complaints,
        'max_complaints': targets.get('max_complaints_per_month', 2),
        'manager_notes': period.get('manager_notes', ''),
    }

# ── HTML 產生 ────────────────────────────────────────────
def pct_color(pct, good=80):
    if pct >= good:       return '#0ABAB5'
    if pct >= good * 0.7: return '#B8892A'
    return '#C94070'

def ring_svg(pct, color, size=80):
    r = 30
    circ = 2 * 3.14159 * r
    dash = circ * min(pct / 100, 1)
    return f'''<svg width="{size}" height="{size}" viewBox="0 0 72 72">
  <circle cx="36" cy="36" r="{r}" fill="none" stroke="#f0ece4" stroke-width="7"/>
  <circle cx="36" cy="36" r="{r}" fill="none" stroke="{color}" stroke-width="7"
    stroke-dasharray="{dash:.1f} {circ:.1f}" stroke-dashoffset="{circ/4:.1f}"
    stroke-linecap="round"/>
  <text x="36" y="40" text-anchor="middle" font-size="14" font-weight="700" fill="{color}">{pct}%</text>
</svg>'''

def num_fmt(n):
    if n >= 10000: return f'{n/10000:.1f}萬'
    if n >= 1000:  return f'{n/1000:.1f}K'
    return str(n)

def render(mkt, content, cs, revenue, period_key, period_label):
    cfg = load_json(STAFF_CFG)
    depts = cfg.get('departments', {})

    # ── 各部門整體分數 ──
    mkt_score = mkt['overall_rate']
    content_score = min(100, round(
        (min(content['count'] / max(content['target_count'], 1), 1) * 40) +
        (min(content['avg_plays'] / max(content['target_plays'], 1), 1) * 30) +
        (min(content['avg_cr'] / max(content['target_cr'], 1), 1) * 30)
    ))
    cs_score = round(sum(m.get('final_score', 0) for m in cs['members']) / len(cs['members'])) if cs['members'] else 0

    now_str = datetime.now().strftime('%Y/%m/%d %H:%M')

    html = f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>TZG 部門績效 {period_label}</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@300;400;600&family=Montserrat:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{{
  --gold:#B8892A; --gold2:#C9A961; --goldsoft:#f3ebd4;
  --pink:#C94070; --pinksoft:#fce4ec;
  --tiff:#0ABAB5; --tiff2:#4DD0CB; --tiffsoft:#d6f3f1;
  --text:#1a1a1a; --sub:#555; --dim:#999;
  --bg:#fff; --bg1:#fafaf7; --bg2:#f5f3ef; --bdr:rgba(0,0,0,.08);
  --serif:'Cormorant Garamond',serif;
  --sans:'Montserrat','PingFang TC',sans-serif;
}}
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
html,body{{height:100%;font-family:var(--sans);background:var(--bg1);color:var(--text);-webkit-font-smoothing:antialiased}}

/* ── HEADER ── */
.hdr{{background:var(--bg);border-bottom:1px solid var(--bdr);padding:14px 24px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:50}}
.hdr-brand{{font-family:var(--serif);font-size:18px;font-weight:600;letter-spacing:.2em;color:var(--gold);flex-shrink:0}}
.hdr-title{{font-size:12px;font-weight:600;color:var(--sub);flex:1}}
.hdr-date{{font-size:10px;color:var(--dim)}}

/* ── DEPT TABS ── */
.dept-tabs{{display:flex;background:var(--bg);border-bottom:1px solid var(--bdr);padding:0 24px;gap:2px}}
.dtab{{padding:11px 18px;font-size:12px;font-weight:600;color:var(--dim);cursor:pointer;border-bottom:2px solid transparent;transition:color .14s,border-color .14s;white-space:nowrap;user-select:none}}
.dtab:hover{{color:var(--pink)}}
.dtab.on{{color:var(--pink);border-bottom-color:var(--pink)}}

/* ── PERIOD TABS ── */
.period-bar{{display:flex;align-items:center;gap:8px;padding:14px 24px 0}}
.period-label{{font-size:11px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim)}}
.ptab{{padding:4px 12px;font-size:11px;font-weight:600;border-radius:20px;cursor:pointer;border:1px solid var(--bdr);color:var(--dim);background:none;transition:all .13s}}
.ptab.on{{background:var(--pink);color:#fff;border-color:var(--pink)}}

/* ── CONTENT ── */
.content{{padding:20px 24px 60px;max-width:1100px;margin:0 auto}}
.dept-section{{display:none}}.dept-section.on{{display:block}}

/* ── OVERVIEW CARDS ── */
.overview-row{{display:flex;gap:16px;margin-bottom:28px;flex-wrap:wrap}}
.ov-card{{flex:1;min-width:160px;background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:20px;text-align:center}}
.ov-num{{font-family:var(--serif);font-size:36px;font-weight:600;line-height:1}}
.ov-label{{font-size:11px;color:var(--dim);margin-top:5px;letter-spacing:.05em}}
.ov-sub{{font-size:10px;color:var(--dim);margin-top:3px}}

/* ── SECTION TITLE ── */
.sec-title{{font-size:10px;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:var(--dim);margin:24px 0 12px}}

/* ── KPI GRID ── */
.kpi-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:24px}}
.kpi-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:16px;position:relative;overflow:hidden}}
.kpi-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px}}
.kpi-gold::before{{background:var(--gold)}}
.kpi-pink::before{{background:var(--pink)}}
.kpi-tiff::before{{background:var(--tiff)}}
.kpi-val{{font-family:var(--serif);font-size:28px;font-weight:600;color:var(--text);line-height:1}}
.kpi-label{{font-size:10.5px;color:var(--dim);margin-top:4px}}
.kpi-target{{font-size:10px;color:var(--dim);margin-top:2px}}
.kpi-bar-wrap{{margin-top:8px;height:4px;background:var(--bg2);border-radius:2px;overflow:hidden}}
.kpi-bar{{height:100%;border-radius:2px;transition:width .4s}}

/* ── RING ROW ── */
.ring-row{{display:flex;gap:20px;flex-wrap:wrap;align-items:center;margin-bottom:24px}}
.ring-item{{text-align:center}}
.ring-item-label{{font-size:11px;color:var(--sub);margin-top:6px;font-weight:600}}
.ring-item-sub{{font-size:10px;color:var(--dim)}}

/* ── GOAL LIST ── */
.goal-list{{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}}
.goal-item{{display:flex;align-items:center;gap:10px;background:var(--bg);border:1px solid var(--bdr);border-radius:10px;padding:12px 14px}}
.goal-cb{{width:18px;height:18px;border-radius:5px;border:2px solid var(--bdr);flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:11px}}
.goal-cb.done{{background:var(--tiff);border-color:var(--tiff);color:#fff}}
.goal-cb.pend{{background:var(--bg2);color:transparent}}
.goal-text{{font-size:13px;color:var(--text);flex:1}}
.goal-text.done{{color:var(--dim);text-decoration:line-through}}

/* ── WEEK CARD ── */
.week-cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:12px;margin-bottom:24px}}
.week-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:12px;padding:16px}}
.wk-hdr{{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px}}
.wk-title{{font-size:12px;font-weight:700;color:var(--sub)}}
.wk-badge{{font-size:10px;font-weight:700;padding:2px 8px;border-radius:10px}}
.wk-task{{display:flex;align-items:center;gap:7px;padding:5px 0;border-bottom:1px solid var(--bg2)}}
.wk-task:last-child{{border:none}}
.wk-dot{{width:8px;height:8px;border-radius:50%;flex-shrink:0}}
.wk-dot.done{{background:var(--tiff)}}
.wk-dot.pend{{background:var(--bdr)}}
.wk-task-text{{font-size:11.5px;color:var(--sub)}}
.wk-task-text.done{{color:var(--dim);text-decoration:line-through}}

/* ── VIDEO LIST ── */
.vid-list{{display:flex;flex-direction:column;gap:8px;margin-bottom:20px}}
.vid-item{{display:flex;gap:12px;align-items:center;background:var(--bg);border:1px solid var(--bdr);border-radius:10px;padding:12px 14px}}
.vid-rank{{font-family:var(--serif);font-size:18px;font-weight:600;color:var(--dim);width:24px;flex-shrink:0}}
.vid-info{{flex:1;min-width:0}}
.vid-title{{font-size:12px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.vid-meta{{font-size:10px;color:var(--dim);margin-top:3px}}
.vid-plays{{font-family:var(--serif);font-size:18px;font-weight:600;color:var(--gold);white-space:nowrap}}
.vid-type{{font-size:9px;font-weight:700;padding:2px 7px;border-radius:4px;flex-shrink:0}}
.type-traffic{{background:var(--tiffsoft);color:var(--tiff)}}
.type-commerce{{background:var(--pinksoft);color:var(--pink)}}

/* ── CS MEMBER CARDS ── */
.cs-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px;margin-bottom:24px}}
.cs-card{{background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:20px;position:relative}}
.cs-rank-badge{{position:absolute;top:14px;right:14px;font-family:var(--serif);font-size:22px;font-weight:600;color:var(--bdr)}}
.cs-name{{font-size:15px;font-weight:700;color:var(--text);margin-bottom:14px}}
.cs-score-row{{display:flex;align-items:baseline;gap:6px;margin-bottom:10px}}
.cs-score-big{{font-family:var(--serif);font-size:42px;font-weight:600;line-height:1}}
.cs-score-label{{font-size:11px;color:var(--dim)}}
.cs-bar-wrap{{height:5px;background:var(--bg2);border-radius:3px;margin-bottom:12px;overflow:hidden}}
.cs-bar{{height:100%;border-radius:3px}}
.cs-detail{{font-size:11px;color:var(--sub);line-height:1.7}}
.cs-complaint{{margin-top:8px;padding:8px 10px;background:var(--pinksoft);border-radius:8px;font-size:11px;color:var(--pink)}}
.cs-bonus{{margin-top:8px;padding:8px 10px;border-radius:8px;font-size:11px;font-weight:700}}
.cs-bonus-ok{{background:var(--tiffsoft);color:var(--tiff)}}
.cs-bonus-warn{{background:var(--goldsoft);color:var(--gold)}}
.cs-bonus-fail{{background:var(--pinksoft);color:var(--pink)}}

/* ── SUMMARY SCORE ── */
.summary-bar{{display:flex;gap:14px;margin-bottom:28px;flex-wrap:wrap}}
.sum-card{{flex:1;min-width:140px;background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:18px;text-align:center;border-top:3px solid transparent}}
.sum-card.c-mkt{{border-top-color:var(--pink)}}
.sum-card.c-cnt{{border-top-color:var(--tiff)}}
.sum-card.c-cs{{border-top-color:var(--gold)}}
.sum-score{{font-family:var(--serif);font-size:40px;font-weight:600;line-height:1}}
.sum-name{{font-size:11px;color:var(--dim);margin-top:5px}}
.sum-tier{{font-size:10px;font-weight:700;margin-top:4px}}

/* ── BONUS TABLE ── */
.bonus-section{{background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:20px;margin-bottom:24px}}
.bonus-title{{font-size:13px;font-weight:700;color:var(--text);margin-bottom:14px;display:flex;align-items:center;gap:8px}}
.bonus-title::before{{content:'';display:inline-block;width:12px;height:12px;border-radius:3px;background:var(--goldsoft);border:1px solid var(--gold)}}
.bonus-note{{font-size:11px;color:var(--dim);margin-top:12px;padding-top:12px;border-top:1px solid var(--bdr)}}
table.bonus-tbl{{width:100%;border-collapse:collapse}}
table.bonus-tbl th{{font-size:10px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--dim);padding:0 8px 10px;text-align:left}}
table.bonus-tbl td{{font-size:12px;padding:10px 8px;border-top:1px solid var(--bg2);vertical-align:middle}}

@media(max-width:600px){{
  .hdr{{padding:12px 16px}}
  .content{{padding:14px 16px 60px}}
  .kpi-grid{{grid-template-columns:1fr 1fr}}
  .overview-row{{flex-direction:column}}
}}
</style>
</head>
<body>

<div class="hdr">
  <div class="hdr-brand">TZG</div>
  <div class="hdr-title">部門績效儀表板 · {period_label}</div>
  <div class="hdr-date">更新：{now_str}</div>
</div>

<div class="dept-tabs">
  <div class="dtab on" onclick="showDept('overview')">總覽</div>
  <div class="dtab" onclick="showDept('marketing')">行銷企劃</div>
  <div class="dtab" onclick="showDept('content')">影音內容</div>
  <div class="dtab" onclick="showDept('sales_cs')">銷售客服</div>
</div>

<div class="content">

<!-- ── 總覽 ── -->
<div class="dept-section on" id="sec-overview">

  <div class="sec-title" style="margin-top:20px">本月公司業績</div>
  {render_revenue_card(revenue)}

  <div class="sec-title">本月部門綜合分數</div>
  <div class="summary-bar">
    <div class="sum-card c-mkt">
      <div class="sum-score" style="color:{pct_color(mkt_score)}">{mkt_score if mkt['monthly_total'] > 0 else '—'}</div>
      <div class="sum-name">行銷企劃</div>
      <div class="sum-tier" style="color:{pct_color(mkt_score)}">{'任務完成率' if mkt['monthly_total'] > 0 else '尚未填報'}</div>
    </div>
    <div class="sum-card c-cnt">
      <div class="sum-score" style="color:{pct_color(content_score)}">{content_score}</div>
      <div class="sum-name">影音內容</div>
      <div class="sum-tier" style="color:{pct_color(content_score)}">綜合指標</div>
    </div>
    <div class="sum-card c-cs">
      <div class="sum-score" style="color:{pct_color(cs_score)}">{cs_score if cs['members'] else '—'}</div>
      <div class="sum-name">銷售客服</div>
      <div class="sum-tier" style="color:{pct_color(cs_score)}">{'平均服務分' if cs['members'] else '尚未填報'}</div>
    </div>
  </div>

  <div class="sec-title">獎金參考試算</div>
  {render_bonus_table(mkt_score, content_score, cs_score, load_json(STAFF_CFG))}

</div>

<!-- ── 行銷企劃 ── -->
<div class="dept-section" id="sec-marketing">
  {render_marketing(mkt)}
</div>

<!-- ── 影音內容 ── -->
<div class="dept-section" id="sec-content">
  {render_content(content)}
</div>

<!-- ── 銷售客服 ── -->
<div class="dept-section" id="sec-sales_cs">
  {render_sales_cs(cs)}
</div>

</div><!-- /content -->

<script>
function showDept(id) {{
  document.querySelectorAll('.dtab').forEach((t,i) => {{
    const ids = ['overview','marketing','content','sales_cs'];
    t.classList.toggle('on', ids[i] === id);
  }});
  document.querySelectorAll('.dept-section').forEach(s => {{
    s.classList.toggle('on', s.id === 'sec-' + id);
  }});
}}
</script>
</body>
</html>'''
    return html

# ── 子區塊渲染 ──────────────────────────────────────────

def render_revenue_card(rev):
    r = rev['rate']
    actual = rev['revenue']
    target = rev['target']
    color = pct_color(r, good=80)
    if not target:
        return '<div style="color:var(--dim);font-size:13px;padding:10px 0 4px">尚未設定業績目標（請在 staff_config.json 中填入 company_targets.monthly_revenue）</div>'
    bar_w = min(r, 100)
    bar_color = color
    diff = actual - target
    diff_str = (f'+{diff/10000:.1f}萬' if diff >= 0 else f'-{abs(diff)/10000:.1f}萬')
    diff_color = '#0ABAB5' if diff >= 0 else '#C94070'
    return f'''<div style="background:var(--bg);border:1px solid var(--bdr);border-radius:14px;padding:20px 24px;margin-bottom:8px">
  <div style="display:flex;align-items:flex-end;gap:12px;margin-bottom:12px">
    <div style="font-family:var(--serif);font-size:32px;font-weight:600;color:{color};line-height:1">{actual/10000:.1f}<span style="font-size:14px;font-weight:400;margin-left:2px">萬</span></div>
    <div style="font-size:12px;color:var(--dim);padding-bottom:4px">/ 目標 {target/10000:.0f}萬</div>
    <div style="font-size:13px;font-weight:700;color:{diff_color};padding-bottom:4px;margin-left:auto">{diff_str}</div>
    <div style="font-size:22px;font-weight:700;color:{color};padding-bottom:2px">{r}%</div>
  </div>
  <div style="background:var(--bg2);border-radius:99px;height:6px;overflow:hidden">
    <div style="width:{bar_w}%;height:100%;background:{bar_color};border-radius:99px;transition:width .6s"></div>
  </div>
  <div style="margin-top:8px;font-size:11px;color:var(--dim)">本月訂單數 {rev["orders"]} 筆</div>
</div>'''

def render_bonus_table(mkt_score, content_score, cs_score, cfg):
    tiers = cfg.get('bonus_reference', {}).get('tiers', [])
    def tier_label(score):
        for t in sorted(tiers, key=lambda x: x['min_score'], reverse=True):
            if score >= t['min_score']:
                return t.get('label','—'), t.get('note','')
        return '—', ''

    rows = []
    for name, score, color in [('行銷企劃', mkt_score, 'var(--pink)'),
                                 ('影音內容', content_score, 'var(--tiff)'),
                                 ('銷售客服', cs_score, 'var(--gold)')]:
        lbl, note = tier_label(score)
        rows.append(f'''<tr>
          <td style="font-weight:700">{name}</td>
          <td><span style="font-family:var(--serif);font-size:22px;font-weight:600;color:{color}">{score}</span></td>
          <td><span style="font-weight:700;color:{color}">{lbl}</span></td>
          <td style="color:var(--dim)">{note}</td>
          <td style="color:var(--dim)">主管核定後填入</td>
        </tr>''')

    return f'''<div class="bonus-section">
  <div class="bonus-title">季/年終獎金參考（主管核定用）</div>
  <table class="bonus-tbl">
    <tr>
      <th>部門</th><th>本月分數</th><th>等級</th><th>建議</th><th>實際金額</th>
    </tr>
    {''.join(rows)}
  </table>
  <div class="bonus-note">⚠️ 以上為系統依 KPI 達成率自動試算，最終獎金金額由主管審閱後手動核定。</div>
</div>'''

def render_marketing(mkt):
    # Empty state — no plans entered yet
    if mkt['monthly_total'] == 0 and not mkt['weeks']:
        return '''
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:60px 24px;text-align:center;color:var(--dim)">
  <div style="font-size:36px;margin-bottom:16px">📋</div>
  <div style="font-size:16px;font-weight:600;color:var(--sub);margin-bottom:8px">尚未填報本月計劃</div>
  <div style="font-size:13px;line-height:1.7">雙擊「填報計劃.command」<br>即可填入本月目標與週任務</div>
</div>'''

    goal_items = ''
    for g, c in zip(mkt['goals'], mkt['completed']):
        cls = 'done' if c else 'pend'
        txt_cls = 'done' if c else ''
        icon = '✓' if c else ''
        goal_items += f'<div class="goal-item"><div class="goal-cb {cls}">{icon}</div><div class="goal-text {txt_cls}">{g}</div></div>'

    week_cards = ''
    for w in mkt['weeks']:
        rate = w['rate']
        bg = '#d6f3f1' if rate >= 80 else '#f3ebd4' if rate >= 50 else '#fce4ec'
        tc = '#0ABAB5' if rate >= 80 else '#B8892A' if rate >= 50 else '#C94070'
        tasks_html = ''
        for task, done in zip(w['tasks'], w['done']):
            dot_cls = 'done' if done else 'pend'
            txt_cls = 'done' if done else ''
            tasks_html += f'<div class="wk-task"><div class="wk-dot {dot_cls}"></div><div class="wk-task-text {txt_cls}">{task}</div></div>'
        review = f'<div style="margin-top:8px;font-size:10.5px;color:var(--dim);padding-top:8px;border-top:1px solid var(--bg2)">{w["review"]}</div>' if w.get('review') else ''
        week_cards += f'''<div class="week-card">
  <div class="wk-hdr">
    <div class="wk-title">{w["label"]}</div>
    <div class="wk-badge" style="background:{bg};color:{tc}">{w["n_done"]}/{w["n_total"]} · {rate}%</div>
  </div>
  {tasks_html}{review}
</div>'''

    cr = mkt['overall_rate']
    color = pct_color(cr)
    return f'''
<div class="overview-row" style="margin-top:20px">
  <div class="ov-card">
    <div class="ov-num" style="color:{pct_color(mkt['monthly_rate'])}">{mkt['monthly_rate']}%</div>
    <div class="ov-label">月度目標完成率</div>
    <div class="ov-sub">{mkt['monthly_done']}/{mkt['monthly_total']} 項完成</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:{pct_color(cr)}">{cr}%</div>
    <div class="ov-label">週任務完成率</div>
    <div class="ov-sub">{mkt['overall_done']}/{mkt['overall_total']} 任務</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:var(--gold)">{mkt['target_rate']}%</div>
    <div class="ov-label">目標達成率</div>
    <div class="ov-sub">本月目標</div>
  </div>
</div>

<div class="sec-title">月度目標</div>
<div class="goal-list">{goal_items}</div>

<div class="sec-title">週任務進度</div>
<div class="week-cards">{week_cards}</div>
'''

def render_content(c):
    cr_color = pct_color(c['avg_cr'] / c['target_cr'] * 100 if c['target_cr'] else 0)
    plays_color = pct_color(c['avg_plays'] / c['target_plays'] * 100 if c['target_plays'] else 0)
    cnt_pct = min(100, round(c['count'] / c['target_count'] * 100)) if c['target_count'] else 0
    fol_pct = min(100, round(c['new_followers'] / c['target_followers'] * 100)) if c['target_followers'] else 0

    vid_rows = ''
    for i, v in enumerate(c['recent'], 1):
        title = (v.get('title') or '')[:50] + ('…' if len(v.get('title','')) > 50 else '')
        vtype = v.get('type','')
        type_cls = 'type-traffic' if vtype == 'traffic' else 'type-commerce'
        type_lbl = '流量' if vtype == 'traffic' else '帶貨' if vtype == 'commerce' else vtype
        cr_val = round((v.get('completion_rate') or 0) * 100, 1)
        vid_rows += f'''<div class="vid-item">
  <div class="vid-rank">{i}</div>
  <div class="vid-info">
    <div class="vid-title">{title}</div>
    <div class="vid-meta">完播 {cr_val}%・觸及 {num_fmt(v.get("reach",0))}・讚 {num_fmt(v.get("likes",0))}</div>
  </div>
  <div class="vid-type {type_cls}">{type_lbl}</div>
  <div class="vid-plays">{num_fmt(v.get("plays",0))}</div>
</div>'''

    traffic_pct = round(c['traffic_n'] / (c['traffic_n'] + c['commerce_n']) * 100) if (c['traffic_n'] + c['commerce_n']) else 0

    return f'''
<div class="overview-row" style="margin-top:20px">
  <div class="ov-card">
    <div class="ov-num" style="color:{pct_color(cnt_pct)}">{c['count']}</div>
    <div class="ov-label">本月發片數</div>
    <div class="ov-sub">目標 {c['target_count']} 支</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:{plays_color}">{num_fmt(c['avg_plays'])}</div>
    <div class="ov-label">平均播放</div>
    <div class="ov-sub">目標 {num_fmt(c['target_plays'])}</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:{cr_color}">{c['avg_cr']}%</div>
    <div class="ov-label">平均完播率</div>
    <div class="ov-sub">目標 {c['target_cr']}%</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:{pct_color(fol_pct)}">{num_fmt(c['new_followers'])}</div>
    <div class="ov-label">新增粉絲</div>
    <div class="ov-sub">目標 {num_fmt(c['target_followers'])}</div>
  </div>
</div>

<div class="kpi-grid">
  <div class="kpi-card kpi-tiff">
    <div class="kpi-val">{num_fmt(c['total_reach'])}</div>
    <div class="kpi-label">總觸及人數</div>
  </div>
  <div class="kpi-card kpi-pink">
    <div class="kpi-val">{c['interact_rate']}%</div>
    <div class="kpi-label">互動率</div>
    <div class="kpi-target">（讚+留言+分享）/ 觸及</div>
  </div>
  <div class="kpi-card kpi-gold">
    <div class="kpi-val">{c['traffic_n']}</div>
    <div class="kpi-label">流量型影片</div>
    <div class="kpi-target">佔比 {traffic_pct}%</div>
  </div>
  <div class="kpi-card kpi-pink">
    <div class="kpi-val">{c['commerce_n']}</div>
    <div class="kpi-label">帶貨型影片</div>
    <div class="kpi-target">佔比 {100-traffic_pct}%</div>
  </div>
</div>

<div class="sec-title">本月高播放影片 Top {len(c["recent"])}</div>
<div class="vid-list">{vid_rows if vid_rows else '<div style="color:var(--dim);font-size:13px;padding:20px 0">本期尚無影片資料</div>'}</div>
'''

def render_sales_cs(cs):
    member_cards = ''
    for i, m in enumerate(cs['members'], 1):
        score = m.get('final_score', 0)
        score_color = pct_color(score)
        complaints = m.get('complaints', 0)
        comp_html = ''
        if complaints > 0:
            details = m.get('complaint_details', [])
            detail_str = '<br>'.join(details) if details else f'共 {complaints} 件'
            comp_html = f'<div class="cs-complaint">⚠️ 客訴 {complaints} 件（扣 {m.get("deduction",0)} 分）<br><span style="opacity:.7">{detail_str}</span></div>'

        tier = m.get('tier', {})
        tier_lbl = tier.get('label', '—')
        tier_note = tier.get('note', '')
        bonus_cls = 'cs-bonus-ok' if score >= 75 else ('cs-bonus-warn' if score >= 60 else 'cs-bonus-fail')
        bonus_html = f'<div class="cs-bonus {bonus_cls}">{tier_lbl}｜{tier_note}</div>'

        bonus_note = m.get('bonus_note', '')
        bonus_note_html = f'<div style="margin-top:6px;font-size:10.5px;color:var(--tiff)">💡 {bonus_note}</div>' if bonus_note else ''

        bar_w = min(100, score)
        member_cards += f'''<div class="cs-card">
  <div class="cs-rank-badge">#{i}</div>
  <div class="cs-name">{m["name"]}</div>
  <div class="cs-score-row">
    <div class="cs-score-big" style="color:{score_color}">{score}</div>
    <div class="cs-score-label">/ 100 分</div>
  </div>
  <div class="cs-bar-wrap"><div class="cs-bar" style="width:{bar_w}%;background:{score_color}"></div></div>
  <div class="cs-detail">
    回覆評分：{m.get("response_score","—")}<br>
    {m.get("response_note","")}
  </div>
  {comp_html}{bonus_html}{bonus_note_html}
</div>'''

    avg_color = pct_color(cs['avg_score'])
    complaint_color = 'var(--tiff)' if cs['total_complaints'] <= cs['max_complaints'] else 'var(--pink)'

    notes_html = f'<div class="sec-title">主管備注</div><div style="background:var(--bg);border:1px solid var(--bdr);border-radius:10px;padding:14px;font-size:13px;color:var(--sub)">{cs["manager_notes"]}</div>' if cs.get('manager_notes') else ''

    return f'''
<div class="overview-row" style="margin-top:20px">
  <div class="ov-card">
    <div class="ov-num" style="color:{avg_color}">{cs['avg_score']}</div>
    <div class="ov-label">平均服務分</div>
    <div class="ov-sub">目標 {cs['target_score']} 分</div>
  </div>
  <div class="ov-card">
    <div class="ov-num" style="color:{complaint_color}">{cs['total_complaints']}</div>
    <div class="ov-label">本月客訴總數</div>
    <div class="ov-sub">上限 {cs['max_complaints']} 件</div>
  </div>
  <div class="ov-card">
    <div class="ov-num">{len(cs['members'])}</div>
    <div class="ov-label">評分人員數</div>
  </div>
</div>

<div class="sec-title">客服人員評分排行（全員公開）</div>
<div class="cs-grid">{member_cards if member_cards else '<div style="color:var(--dim);font-size:13px;padding:20px 0">尚無評分資料，請執行「填報計劃.command」填入。</div>'}</div>
{notes_html}
'''

# ── 主程式 ──────────────────────────────────────────────
def main():
    period_key, period_label = get_period_label()
    if len(sys.argv) > 1:
        period_key = sys.argv[1]
        period_label = period_key.replace('-', ' 年 ') + ' 月'

    print(f'[TZG Staff] 產生 {period_label} 部門績效...')

    mkt     = compute_marketing(period_key)
    content = compute_content(period_key)
    cs      = compute_sales_cs(period_key)
    revenue = compute_revenue(period_key)

    html = render(mkt, content, cs, revenue, period_key, period_label)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding='utf-8')
    print(f'[✓] 輸出：{OUTPUT}')
    print(f'  行銷企劃完成率：{mkt["overall_rate"]}%')
    print(f'  影音內容發片數：{content["count"]}')
    print(f'  客服平均分：{cs["avg_score"]}')
    print(f'  本月營收：{revenue["revenue"]:,} / 目標 {revenue["target"]:,} ({revenue["rate"]}%)')

if __name__ == '__main__':
    main()
