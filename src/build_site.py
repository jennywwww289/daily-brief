#!/usr/bin/env python3
"""archive/*.md -> dist/ 靜態網站（雜誌式版型）。

用法：  python -m src.build_site [--out dist]

每個 archive/YYYY-MM-DD.md 開頭可有 front matter（--- 包起來的 key: value）：
    title / summary / sample（sample: true 表示範例頁，會在網站上標示）
內文以「## 區塊標題」分段。區塊內若有一行 <!--EXCLUDED-->，
其後的內容會被收進「被排除的雜訊」摺疊區。
"""
import argparse
import html
import json
import re
import shutil
from datetime import date
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "archive"
SITE = ROOT / "site"
EXCLUDED_MARK = "<!--EXCLUDED-->"
WEEKDAYS = ["週一", "週二", "週三", "週四", "週五", "週六", "週日"]
TIER_NAMES = {"1": "一手", "2": "專業媒體", "3": "獨立分析", "4": "社群"}
TAGS = {"事實": "fact", "推測": "guess", "不確定": "unsure"}

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600"
         "&family=Noto+Serif+TC:wght@400;600;900&family=Playfair+Display:wght@700;900"
         "&family=Source+Serif+4:ital,wght@0,400;0,600;1,400&display=swap")

PAGE = """<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="color-scheme" content="light dark">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="{fonts}">
<link rel="stylesheet" href="{root}style.css">
</head>
<body>
<a class="skip" href="#main">跳到內容</a>
<header class="bar">
<a class="brand" href="{root}index.html">每日情報<span>THE DAILY BRIEF</span></a>
<nav aria-label="主選單">
<a href="{root}index.html">今日</a>
<a href="{root}archive/index.html">歷史</a>
<a href="{root}search/index.html">搜尋</a>
</nav>
</header>
<main id="main">
{body}
</main>
<footer class="colophon">
<p>本站內容由程式自動蒐集與整理，可能有誤或遺漏。每則都附來源與等級，請以原始來源為準。社群貼文只代表發文者個人說法，不是事實。</p>
</footer>
{script}
</body>
</html>
"""


def md_to_html(text: str) -> str:
    out = markdown.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
    out = re.sub(r'<a href="(https?://[^"]+)"',
                 r'<a href="\1" target="_blank" rel="noopener noreferrer"', out)
    # 「T2」→ 來源等級標籤；【推測】→ 資訊類型標籤；（連結未驗證）→ 警示
    out = re.sub(r"(?<![A-Za-z0-9])T([1-4])(?![0-9A-Za-z])",
                 lambda m: f'<span class="tier t{m.group(1)}">T{m.group(1)} · {TIER_NAMES[m.group(1)]}</span>',
                 out)
    out = re.sub(r"【(事實|推測|不確定)】",
                 lambda m: f'<span class="tag {TAGS[m.group(1)]}">{m.group(1)}</span>', out)
    out = out.replace("（連結未驗證）", '<span class="unverified">（連結未驗證）</span>')
    return out


def parse_day(path: Path) -> dict:
    text = path.read_text("utf-8")
    meta, body = {}, text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            for line in parts[1].strip().splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = parts[2]
    chunks = re.split(r"^## +", body.strip(), flags=re.M)
    preamble, sections = chunks[0].strip(), []
    for i, chunk in enumerate(chunks[1:], 1):
        title, _, content = chunk.partition("\n")
        title = title.strip()
        slug = re.sub(r"[^\w一-鿿]+", "-", title).strip("-") or f"s{i}"
        sections.append({"num": f"{i:02d}", "title": title, "slug": f"{i:02d}-{slug}",
                         "content": content.strip()})
    return {"date": path.stem, "meta": meta, "preamble": preamble, "sections": sections}


def render_section(sec: dict) -> str:
    content = sec["content"]
    excluded_html = ""
    if EXCLUDED_MARK in content:
        content, _, excluded = content.partition(EXCLUDED_MARK)
        excluded = excluded.strip()
        if excluded:
            excluded_html = ("<details class=\"excluded\"><summary>這個區塊被排除的雜訊</summary>"
                             + md_to_html(excluded) + "</details>")
    return (f'<section id="{sec["slug"]}">'
            f'<header class="sec-head"><span class="sec-num">{sec["num"]}</span>'
            f'<h2>{html.escape(sec["title"])}</h2></header>'
            f'{md_to_html(content)}{excluded_html}</section>')


def dateline(day: dict, edition: int) -> str:
    try:
        y, m, d = (int(x) for x in day["date"].split("-"))
        wd = WEEKDAYS[date(y, m, d).weekday()]
    except ValueError:
        wd = ""
    return f'<time datetime="{day["date"]}">{day["date"]}</time> · {wd} · 第 {edition} 期'


ACTIVE_JS = """<script>
(function () {
  var links = [].slice.call(document.querySelectorAll('.rail a'));
  if (!links.length || !('IntersectionObserver' in window)) return;
  var map = {};
  links.forEach(function (a) { map[a.getAttribute('href').slice(1)] = a; });
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      links.forEach(function (l) { l.removeAttribute('aria-current'); });
      var a = map[e.target.id]; if (a) a.setAttribute('aria-current', 'true');
    });
  }, { rootMargin: '-15% 0px -75% 0px' });
  [].forEach.call(document.querySelectorAll('.issue section[id]'), function (s) { io.observe(s); });
})();
</script>"""


def render_day(day: dict, prev_d, next_d, prefix: str, edition: int) -> str:
    """prefix：從目前頁面走到「日期資料夾」的相對前綴（首頁為 ''，日頁為 '../'）。"""
    meta = day["meta"]
    title = meta.get("title") or f"{day['date']} 每日情報"
    rail = "".join(
        f'<li><a href="#{s["slug"]}"><span class="num">{s["num"]}</span>{html.escape(s["title"])}</a></li>'
        for s in day["sections"])
    head = [f'<header class="masthead"><p class="kicker">每日情報 · THE DAILY BRIEF</p>',
            f'<h1>{html.escape(title)}</h1>',
            f'<p class="dateline">{dateline(day, edition)}</p>']
    if meta.get("summary"):
        head.append(f'<p class="deck">{html.escape(meta["summary"])}</p>')
    head.append("</header>")
    parts = ["".join(head)]
    if meta.get("sample", "").lower() == "true":
        parts.append('<p class="sample">這是版面範例頁，內容為示意，不是真實資訊。</p>')
    if day["sections"]:   # 窄螢幕用：目錄放在刊頭下面（寬螢幕改由左側欄顯示）
        parts.append('<nav class="toc-inline" aria-label="本期目錄">'
                     f'<p class="rail-title">本期目錄</p><ol>{rail}</ol></nav>')
    if day["preamble"]:
        parts.append(md_to_html(day["preamble"]))
    parts.extend(render_section(s) for s in day["sections"])
    pager = []
    if prev_d:
        pager.append(f'<a href="{prefix}{prev_d}/index.html"><small>上一期</small>{prev_d}</a>')
    if next_d:
        pager.append(f'<a class="next" href="{prefix}{next_d}/index.html"><small>下一期</small>{next_d}</a>')
    if pager:
        parts.append('<nav class="pager" aria-label="期數切換">' + "".join(pager) + "</nav>")
    return (f'<div class="layout"><aside class="rail"><nav aria-label="本期目錄">'
            f'<p class="rail-title">本期目錄</p><ol>{rail}</ol></nav></aside>'
            f'<article class="issue">{"".join(parts)}</article></div>')


def plain(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[#>*_`|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


SEARCH_JS = """<script>
(async function () {
  const box = document.getElementById('q'), out = document.getElementById('results');
  let data = [];
  try { data = await (await fetch('../search.json')).json(); }
  catch (e) { out.textContent = '搜尋索引載入失敗。'; return; }
  function esc(s) { return s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
  function run() {
    const terms = box.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    if (!terms.length) { out.innerHTML = '<p class="hint">輸入關鍵字，多個詞用空白分開。</p>'; return; }
    const hits = data.filter(r => terms.every(t => (r.s + ' ' + r.t).toLowerCase().includes(t))).slice(0, 60);
    if (!hits.length) { out.innerHTML = '<p class="hint">沒有符合的結果。</p>'; return; }
    out.innerHTML = hits.map(r => {
      const i = Math.max(0, r.t.toLowerCase().indexOf(terms[0]));
      const snip = esc(r.t.slice(Math.max(0, i - 40), i + 120));
      return '<p class="hit"><a href="../' + r.u + '"><span class="when">' + esc(r.d) + '</span> ' + esc(r.s) + '</a><br><span>' + snip + '…</span></p>';
    }).join('');
  }
  box.addEventListener('input', run); run();
})();
</script>"""


def simple_page(kicker: str, heading: str, inner: str) -> str:
    return (f'<div class="plain"><header class="masthead"><p class="kicker">{kicker}</p>'
            f'<h1>{heading}</h1></header>{inner}</div>')


def build(out: Path) -> None:
    files = sorted(ARCHIVE.glob("????-??-??.md"), reverse=True)
    days = [parse_day(p) for p in files]
    dates = [d["date"] for d in days]
    total = len(days)

    if out.exists():
        shutil.rmtree(out)
    (out / "archive").mkdir(parents=True)
    (out / "search").mkdir()
    shutil.copy(SITE / "style.css", out / "style.css")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", "utf-8")

    for i, day in enumerate(days):
        newer = dates[i - 1] if i > 0 else None
        older = dates[i + 1] if i + 1 < total else None
        d_dir = out / day["date"]
        d_dir.mkdir()
        body = render_day(day, older, newer, "../", total - i)
        (d_dir / "index.html").write_text(PAGE.format(
            title=f"{day['date']} 每日情報", root="../", fonts=FONTS, body=body, script=ACTIVE_JS), "utf-8")

    if days:
        body = render_day(days[0], dates[1] if total > 1 else None, None, "", total)
        script = ACTIVE_JS
    else:
        body = simple_page("每日情報 · THE DAILY BRIEF", "尚無資料", "<p>第一期日報產生後會顯示在這裡。</p>")
        script = ""
    (out / "index.html").write_text(PAGE.format(
        title="每日情報", root="", fonts=FONTS, body=body, script=script), "utf-8")

    rows = "".join(
        f'<li><a href="../{d["date"]}/index.html"><span class="no">第 {total - i} 期</span>'
        f'<span class="when">{d["date"]}</span>'
        f'<span class="what">{html.escape(d["meta"].get("title", ""))}</span></a></li>'
        for i, d in enumerate(days))
    arch = simple_page("ARCHIVE", "歷史", f'<ul class="issues">{rows or "<li>尚無資料</li>"}</ul>')
    (out / "archive" / "index.html").write_text(PAGE.format(
        title="歷史｜每日情報", root="../", fonts=FONTS, body=arch, script=""), "utf-8")

    search = simple_page("SEARCH", "搜尋",
                         '<input id="q" type="search" placeholder="輸入關鍵字" autofocus>'
                         '<div id="results"></div>')
    (out / "search" / "index.html").write_text(PAGE.format(
        title="搜尋｜每日情報", root="../", fonts=FONTS, body=search, script=SEARCH_JS), "utf-8")

    index = []
    for day in days:
        for sec in day["sections"]:
            body = sec["content"].partition(EXCLUDED_MARK)[0]
            index.append({"d": day["date"], "s": sec["title"], "t": plain(body)[:1500],
                          "u": f'{day["date"]}/index.html#{sec["slug"]}'})
    (out / "search.json").write_text(json.dumps(index, ensure_ascii=False), "utf-8")
    print(f"built {total} day(s) -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "dist"))
    build(Path(ap.parse_args().out))
