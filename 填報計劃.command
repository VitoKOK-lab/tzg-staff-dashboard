#!/bin/bash
# 填報行銷企劃 / 銷售客服月度評分
# 雙擊此檔案即可執行

cd "$(dirname "$0")"

echo "=============================="
echo "  TZG 員工績效 — 填報工具"
echo "=============================="
echo ""
echo "請選擇填報項目："
echo "  1) 行銷企劃 — 月度目標 & 週任務"
echo "  2) 銷售客服 — 月度評分"
echo "  3) 離開"
echo ""
read -p "請輸入 1 / 2 / 3：" CHOICE

# ──────────────────────────────────────────
# 取得當前年月
# ──────────────────────────────────────────
PERIOD=$(date '+%Y-%m')
read -p "填報月份（直接 Enter 使用 $PERIOD）：" INPUT_PERIOD
[ -n "$INPUT_PERIOD" ] && PERIOD="$INPUT_PERIOD"

PLANS_FILE="data/marketing_plans.json"
CS_FILE="data/cs_scores.json"

# ──────────────────────────────────────────
case "$CHOICE" in

# ====== 行銷企劃 ======
1)
  echo ""
  echo "── 行銷企劃 $PERIOD ──"
  echo ""
  python3 - <<PYEOF
import json, sys, os

PERIOD = "$PERIOD"
PATH = "$PLANS_FILE"

with open(PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

if PERIOD not in data:
    data[PERIOD] = {
        "monthly": {"goals": [], "completed": [], "notes": ""},
        "weeks": {
            "W1": {"label": "", "tasks": [], "done": [], "review": ""},
            "W2": {"label": "", "tasks": [], "done": [], "review": ""},
            "W3": {"label": "", "tasks": [], "done": [], "review": ""},
            "W4": {"label": "", "tasks": [], "done": [], "review": ""}
        }
    }

mo = data[PERIOD]["monthly"]
wks = data[PERIOD]["weeks"]

print("【月度目標】")
for i, (g, c) in enumerate(zip(mo["goals"], mo["completed"])):
    status = "✅" if c else "⬜"
    print(f"  {i+1}. {status} {g}")

print("")
ans = input("是否更新月度目標完成狀態？(y/n) ").strip().lower()
if ans == 'y':
    for i, g in enumerate(mo["goals"]):
        done = input(f"  目標 {i+1}「{g}」已完成？(y/n) ").strip().lower()
        mo["completed"][i] = done == 'y'

notes = input(f"主管備註（目前：{mo['notes'] or '（空）'}，直接 Enter 略過）：").strip()
if notes:
    mo["notes"] = notes

print("")
for wk, wdata in wks.items():
    print(f"【{wk} {wdata.get('label','')}】")
    for i, (t, d) in enumerate(zip(wdata["tasks"], wdata["done"])):
        status = "✅" if d else "⬜"
        print(f"  {i+1}. {status} {t}")

    ans2 = input(f"  是否更新 {wk} 任務狀態？(y/n) ").strip().lower()
    if ans2 == 'y':
        for i, t in enumerate(wdata["tasks"]):
            done = input(f"    任務{i+1}「{t}」已完成？(y/n) ").strip().lower()
            wdata["done"][i] = done == 'y'
    rev = input(f"  {wk} 週回顧（目前：{wdata.get('review','') or '（空）'}，Enter 略過）：").strip()
    if rev:
        wdata["review"] = rev
    print("")

with open(PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("✅ 行銷企劃資料已儲存！")
PYEOF
  ;;

# ====== 銷售客服評分 ======
2)
  echo ""
  echo "── 銷售客服評分 $PERIOD ──"
  echo ""
  python3 - <<PYEOF
import json, sys

PERIOD = "$PERIOD"
PATH = "$CS_FILE"

with open(PATH, 'r', encoding='utf-8') as f:
    data = json.load(f)

if PERIOD not in data:
    data[PERIOD] = {
        "members": [],
        "scoring_rules": {
            "response_score_weight": 0.7,
            "complaint_deduction_each": 10,
            "max_score": 100
        },
        "manager_notes": ""
    }

members = data[PERIOD]["members"]
rules = data[PERIOD]["scoring_rules"]
deduction_each = rules.get("complaint_deduction_each", 10)

print(f"目前共 {len(members)} 位客服成員")
print("選項：(a) 新增成員  (e) 編輯現有成員  (Enter) 略過")
print("")

for idx, m in enumerate(members):
    print(f"  {idx+1}. {m['name']}  回覆分:{m['response_score']}  客訴:{m['complaints']}  最終:{m['final_score']}")

print("")
action = input("請選擇 a / e / Enter：").strip().lower()

if action == 'a':
    name = input("新成員姓名：").strip()
    if name:
        rs = int(input(f"  {name} 回覆速度評分（0-100）：") or "80")
        rs_note = input(f"  回覆速度備註（如「平均 X 分鐘」）：").strip()
        comps = int(input(f"  本月客訴次數：") or "0")
        comp_details = []
        for ci in range(comps):
            d = input(f"    客訴 {ci+1} 說明：").strip()
            if d:
                comp_details.append(d)
        bonus_note = input(f"  加分備註（選填）：").strip()
        deduction = comps * deduction_each
        final = max(0, rs - deduction)
        members.append({
            "name": name,
            "response_score": rs,
            "response_note": rs_note,
            "complaints": comps,
            "complaint_details": comp_details,
            "deduction": deduction,
            "bonus_note": bonus_note,
            "final_score": final
        })
        print(f"✅ {name} 最終得分：{final}")

elif action == 'e' and members:
    idx_str = input(f"請輸入要編輯的成員編號（1-{len(members)}）：").strip()
    try:
        idx = int(idx_str) - 1
        m = members[idx]
        print(f"編輯 {m['name']}（目前回覆分:{m['response_score']} 客訴:{m['complaints']}）")
        rs = input(f"  新回覆評分（Enter 保留 {m['response_score']}）：").strip()
        if rs:
            m['response_score'] = int(rs)
        rs_note = input(f"  回覆備註（Enter 保留）：").strip()
        if rs_note:
            m['response_note'] = rs_note
        comps = input(f"  客訴次數（Enter 保留 {m['complaints']}）：").strip()
        if comps:
            m['complaints'] = int(comps)
        bonus_note = input(f"  加分備註（Enter 保留）：").strip()
        if bonus_note:
            m['bonus_note'] = bonus_note
        m['deduction'] = m['complaints'] * deduction_each
        m['final_score'] = max(0, m['response_score'] - m['deduction'])
        print(f"✅ {m['name']} 更新後最終得分：{m['final_score']}")
    except (ValueError, IndexError):
        print("⚠️  無效編號")

mnotes = input(f"\n主管備註（目前：{data[PERIOD].get('manager_notes','') or '（空）'}，Enter 略過）：").strip()
if mnotes:
    data[PERIOD]["manager_notes"] = mnotes

with open(PATH, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)

print("\n✅ 客服評分資料已儲存！")
PYEOF
  ;;

3|"")
  echo "已離開。"
  exit 0
  ;;
*)
  echo "⚠️  無效選項"
  ;;
esac

echo ""
read -p "是否立即產生報表並推送？(y/n) " PUSH
if [ "$PUSH" = "y" ]; then
  bash "產生報表.command"
else
  echo "完成。你可以之後雙擊「產生報表.command」更新頁面。"
fi

read -p "按 Enter 關閉..."
