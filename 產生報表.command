#!/bin/bash
# 產生員工績效報表並推送至 GitHub Pages
# 雙擊此檔案即可執行

cd "$(dirname "$0")"

echo "=============================="
echo "  TZG 員工績效報表 — 產生中"
echo "=============================="
echo ""

# 確認 Python 環境
if ! command -v python3 &> /dev/null; then
  echo "❌ 找不到 python3，請先安裝 Python 3"
  read -p "按 Enter 關閉..."
  exit 1
fi

# 安裝依賴（若尚未安裝）
echo "🔧 確認依賴套件..."
pip3 install -q -r requirements.txt 2>/dev/null || pip install -q -r requirements.txt 2>/dev/null

echo ""
echo "📊 計算 KPI 並產生 HTML..."
python3 generate_staff.py

if [ $? -ne 0 ]; then
  echo ""
  echo "❌ 產生失敗，請確認資料來源是否存在"
  echo "   預期路徑：../tzg-dashboard/data/"
  echo "   預期路徑：../meta-dashboard/data/videos.json"
  read -p "按 Enter 關閉..."
  exit 1
fi

echo ""
echo "✅ 報表已產生：output/staff_latest.html"
echo ""

# Git 推送
echo "🚀 推送至 GitHub Pages..."
git add output/staff_latest.html
git add data/
git commit -m "chore: update staff dashboard $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "（無變更需要 commit）"
git push origin main

if [ $? -eq 0 ]; then
  echo ""
  echo "✅ 已推送！約 1 分鐘後生效"
  echo "   https://vitokok-lab.github.io/tzg-staff-dashboard/output/staff_latest.html"
else
  echo ""
  echo "⚠️  推送失敗，請確認網路連線與 GitHub 設定"
fi

echo ""
read -p "按 Enter 關閉..."
