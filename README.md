# 每日情報

每天自動蒐集、過濾並整理 AI、科技、財經、社群趨勢與商業案例，以雜誌式網頁呈現。

- 網站：<https://jennywwww289.github.io/daily-brief/>
- 內容來自 `archive/YYYY-MM-DD.md`，由 `src/build_site.py` 轉成靜態網站，經 GitHub Pages 部署。
- 資訊以來源分級（T1 一手、T2 專業媒體、T3 獨立分析、T4 社群），社群貼文只當訊號，不當事實。
- 內容為程式自動整理，可能有誤，請以原始來源為準。

## 本機預覽

```bash
python3 -m venv .venv && .venv/bin/pip install markdown
.venv/bin/python -m src.build_site
python3 -m http.server 8001 --directory dist
```
