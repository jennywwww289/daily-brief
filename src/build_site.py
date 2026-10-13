#!/usr/bin/env python3
"""archive/*.md -> dist/ 靜態網站。

用法：  python -m src.build_site [--out dist]

每個 archive/YYYY-MM-DD.md 開頭可有 front matter（--- 包起來的 key: value）：
    title / summary / sample（sample: true 表示範例頁，會在網站上標示）
內文以「## 區塊標題」分段，區塊內以「### 標題」分則。區塊內若有一行 <!--EXCLUDED-->，
其後的內容會被收進「被排除的雜訊」摺疊區。

版面結構（由這支腳本在 Markdown 轉出 HTML 之後加上）：
- 「**標籤：** 內容」的段落 → 標籤欄＋內容欄（dl.fields）
- 「來源：連結 · T2」→ 來源清單（div.sources）
- 「30 秒速覽」→ 首頁色塊，每行依「（見「區塊」）」連到該區塊
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
DOUBT_LABEL = "我不確定的地方"

FONTS = ("https://fonts.googleapis.com/css2?"
         "family=Noto+Serif+TC:wght@600;700;900"
         "&family=Noto+Sans+TC:wght@400;500;700;800&display=swap")

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
<a class="brand" href="{root}index.html">每日情報</a>
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

LEGEND = (
    '<aside class="about"><p class="about-title">怎麼讀這份情報</p>'
    '<dl class="legend">'
    '<div><dt><span class="tag fact">事實</span></dt><dd>有一手或專業媒體來源</dd></div>'
    '<div><dt><span class="tag guess">推測</span></dt><dd>我的推論，不是來源說的</dd></div>'
    '<div><dt><span class="tag unsure">不確定</span></dt><dd>資訊不足，只當待查線索</dd></div>'
    '</dl>'
    '<p class="tiers">來源等級'
    '<span class="tier t1"><b>T1</b>一手</span>'
    '<span class="tier t2"><b>T2</b>專業媒體</span>'
    '<span class="tier t3"><b>T3</b>獨立分析</span>'
    '<span class="tier t4"><b>T4</b>社群</span>'
    'T3 只當觀點，T4 只當訊號，都不當事實。</p>'
    '__BODY__</aside>'
)


def md_to_html(text: str) -> str:
    out = markdown.markdown(text, extensions=["extra", "sane_lists", "nl2br"])
    out = re.sub(r'<a href="(https?://[^"]+)"',
                 r'<a href="\1" target="_blank" rel="noopener noreferrer"', out)
    # 「T2」→ 來源等級標籤；【推測】→ 資訊類型標籤；（連結未驗證）→ 警示
    out = re.sub(r"(?<![A-Za-z0-9])T([1-4])(?![0-9A-Za-z])",
                 lambda m: (f'<span class="tier t{m.group(1)}"><b>T{m.group(1)}</b>'
                            f'{TIER_NAMES[m.group(1)]}</span>'),
                 out)
    out = re.sub(r"【(事實|推測|不確定)】",
                 lambda m: f'<span class="tag {TAGS[m.group(1)]}">{m.group(1)}</span>', out)
    out = out.replace("（連結未驗證）", '<span class="unverified">（連結未驗證）</span>')
    return out


# ---- 版面結構 -------------------------------------------------------------

LABEL_RE = re.compile(r"^<strong>([^<]{1,24}?)[：:]</strong>\s*(.*)$", re.S)
TAG_RE = re.compile(r'class="tag (fact|guess|unsure)"')
SRC_RE = re.compile(r'(<a [^>]+>.*?</a>)\s*·\s*(<span class="tier t[1-4]">.*?</span>)', re.S)


def fieldify(body: str) -> str:
    """整段都是「**標籤：** 內容」的段落 → 標籤欄＋內容欄。"""
    def repl(m):
        fields = []    # [label, value, [bullets]]
        for piece in m.group(1).split("<br />\n"):
            piece = piece.strip()
            mm = LABEL_RE.match(piece)
            if mm:
                fields.append([mm.group(1), mm.group(2).strip(), []])
            elif fields and piece.startswith("- "):
                # 原稿的「- 項目」直接接在標籤行後面（沒有空行），Markdown 不會當清單
                fields[-1][2].append(piece[2:].strip())
            else:
                return m.group(0)
        rows = []
        for label, value, bullets in fields:
            cls = "field"
            if label == DOUBT_LABEL:
                cls += " doubt"
            else:
                t = TAG_RE.search(value)
                if t and t.group(1) != "fact":
                    cls += f" is-{t.group(1)}"
            if bullets:
                value += "<ul>" + "".join(f"<li>{b}</li>" for b in bullets) + "</ul>"
            rows.append(f'<div class="{cls}"><dt>{label}</dt><dd>{value}</dd></div>')
        return '<dl class="fields">' + "".join(rows) + "</dl>"

    out = re.sub(r"<p>(.*?)</p>", repl, body, flags=re.S)
    # 「各方立場：」這類標籤後面接條列時，把條列收進同一格
    return re.sub(r"<dd></dd></div></dl>\s*<ul>(.*?)</ul>",
                  r"<dd><ul>\1</ul></dd></div></dl>", out, flags=re.S)


def sourceify(body: str) -> str:
    """「來源：連結 · T2、連結 · T1」→ 每個來源一行，等級在前。"""
    def repl(m):
        text = m.group(1)
        if not text.startswith("來源："):
            return m.group(0)
        rest = text[len("來源："):]
        pairs = SRC_RE.findall(rest)
        leftover = re.sub(r"[、\s]", "", SRC_RE.sub("", rest))
        if not pairs or leftover:        # 格式不符就原樣保留，不冒險吃掉內容
            return m.group(0)
        lis = "".join(f"<li>{tier}{link}</li>" for link, tier in pairs)
        return f'<div class="sources"><span class="k">來源</span><ul>{lis}</ul></div>'

    return re.sub(r"<p>(.*?)</p>", repl, body, flags=re.S)


def split_items(body: str):
    """依 <h3> 分則；每則在來源清單結束處收尾，之後的段落當作區塊附註。"""
    pieces = re.split(r"(?=<h3>)", body)
    pre, items, notes = pieces[0], [], []
    for chunk in pieces[1:]:
        start = chunk.find('<div class="sources">')
        end = chunk.find("</ul></div>", start) if start != -1 else -1
        if end != -1:
            end += len("</ul></div>")
            items.append(chunk[:end])
            tail = chunk[end:].strip()
            if tail:
                notes.append(tail)
        else:
            items.append(chunk)
    return pre, items, notes


def is_glance(sec: dict) -> bool:
    return re.match(r"30\s*秒", sec["title"]) is not None


def glance_html(content: str, slugmap: dict) -> str:
    body = md_to_html(content)

    def li_repl(m):
        inner = m.group(1)
        mm = re.search(r"（見((?:「[^」]+」)+)）\s*$", inner)
        if not mm or "<a " in inner:
            return m.group(0)
        names = re.findall(r"「([^」]+)」", mm.group(1))
        if names[0] not in slugmap:
            return m.group(0)
        text = inner[:mm.start()].rstrip()
        return (f'<li><a href="#{slugmap[names[0]]}"><span class="where">{"／".join(names)}</span>'
                f'<span class="what">{text}</span></a></li>')

    body = re.sub(r"<li>(.*?)</li>", li_repl, body, flags=re.S)
    return body.replace("<ol>", '<ol class="glance-list">', 1)


def render_section(sec: dict, slugmap: dict) -> str:
    content, excluded_html = sec["content"], ""
    if EXCLUDED_MARK in content:
        content, _, excluded = content.partition(EXCLUDED_MARK)
        excluded = excluded.strip()
        if excluded:
            n = len(re.findall(r"^\s*[-*+] ", excluded, flags=re.M))
            label = f"被排除的雜訊（{n} 則）" if n else "被排除的雜訊"
            excluded_html = (f'<details class="excluded"><summary>{label}</summary>'
                             + md_to_html(excluded) + "</details>")
    title = html.escape(sec["title"])
    if is_glance(sec):
        return (f'<section id="{sec["slug"]}" class="glance">'
                f'<h2><span class="glance-icon" aria-hidden="true">⚡</span>{title}</h2>'
                f'<p class="glance-sub">先看這幾則；點任何一則會跳到該區塊的細節。</p>'
                f'{glance_html(content.strip(), slugmap)}{excluded_html}</section>')

    pre, items, notes = split_items(sourceify(fieldify(md_to_html(content.strip()))))
    count = f'<span class="count">{len(items)} 則</span>' if items else ""
    articles = "".join(f'<article class="item">{i}</article>' for i in items)
    note_html = "".join(f'<div class="sec-note">{n}</div>' for n in notes)
    return (f'<section id="{sec["slug"]}">'
            f'<header class="sec-head"><h2>{title}</h2>{count}</header>'
            f'{pre}{articles}{note_html}{excluded_html}</section>')


# ---- 頁面 -----------------------------------------------------------------

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
        sections.append({"title": title, "slug": f"{i:02d}-{slug}", "content": content.strip()})
    return {"date": path.stem, "meta": meta, "preamble": preamble, "sections": sections}


def dateline(day: dict, edition: int) -> str:
    iso = day["date"]
    try:
        y, m, d = (int(x) for x in iso.split("-"))
        wd = WEEKDAYS[date(y, m, d).weekday()]
    except ValueError:
        return f'<time datetime="{iso}">{iso}</time><span>第 {edition} 期</span>'
    return (f'<time datetime="{iso}">{y} 年 {m} 月 {d} 日</time>'
            f'<span>{wd}</span><span>第 {edition} 期</span>')


ACTIVE_JS = """<script>
(function () {
  var links = [].slice.call(document.querySelectorAll('.rail a, .toc-inline a'));
  if (!links.length || !('IntersectionObserver' in window)) return;
  var io = new IntersectionObserver(function (es) {
    es.forEach(function (e) {
      if (!e.isIntersecting) return;
      links.forEach(function (l) {
        if (l.getAttribute('href') === '#' + e.target.id) l.setAttribute('aria-current', 'true');
        else l.removeAttribute('aria-current');
      });
    });
  }, { rootMargin: '-15% 0px -75% 0px' });
  [].forEach.call(document.querySelectorAll('.issue section[id]'), function (s) { io.observe(s); });
})();
</script>"""


def render_day(day: dict, prev_d, next_d, prefix: str, edition: int) -> str:
    """prefix：從目前頁面走到「日期資料夾」的相對前綴（首頁為 ''，日頁為 '../'）。"""
    meta = day["meta"]
    title = meta.get("title") or f"{day['date']} 每日情報"
    sections = day["sections"]
    slugmap = {s["title"]: s["slug"] for s in sections}
    nav = "".join(f'<li><a href="#{s["slug"]}">{html.escape(s["title"])}</a></li>' for s in sections)

    head = [f'<header class="masthead"><p class="dateline">{dateline(day, edition)}</p>',
            f'<h1>{html.escape(title)}</h1>']
    if meta.get("summary"):
        head.append(f'<p class="deck">{html.escape(meta["summary"])}</p>')
    head.append("</header>")
    parts = ["".join(head)]
    if meta.get("sample", "").lower() == "true":
        parts.append('<p class="sample">這是版面範例頁，內容為示意，不是真實資訊。</p>')
    if sections:    # 窄螢幕：目錄變成橫向一列（寬螢幕改由左側欄顯示）
        parts.append(f'<nav class="toc-inline" aria-label="本期目錄"><ol>{nav}</ol></nav>')

    glance = [s for s in sections if is_glance(s)]
    rest = [s for s in sections if not is_glance(s)]
    parts.extend(render_section(s, slugmap) for s in glance)
    parts.append(LEGEND.replace("__BODY__", md_to_html(day["preamble"])) if day["preamble"]
                 else LEGEND.replace("__BODY__", ""))
    parts.extend(render_section(s, slugmap) for s in rest)

    pager = []
    if prev_d:
        pager.append(f'<a href="{prefix}{prev_d}/index.html"><small>上一期</small>{prev_d}</a>')
    if next_d:
        pager.append(f'<a class="next" href="{prefix}{next_d}/index.html"><small>下一期</small>{next_d}</a>')
    if pager:
        parts.append('<nav class="pager" aria-label="期數切換">' + "".join(pager) + "</nav>")
    return (f'<div class="layout"><aside class="rail"><nav aria-label="本期目錄">'
            f'<p class="rail-title">本期內容</p><ol>{nav}</ol></nav></aside>'
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


def simple_page(heading: str, inner: str) -> str:
    return f'<div class="plain"><header class="masthead"><h1>{heading}</h1></header>{inner}</div>'


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
        body = simple_page("尚無資料", "<p>第一期日報產生後會顯示在這裡。</p>")
        script = ""
    (out / "index.html").write_text(PAGE.format(
        title="每日情報", root="", fonts=FONTS, body=body, script=script), "utf-8")

    rows = "".join(
        f'<li><a href="../{d["date"]}/index.html"><span class="no">第 {total - i} 期</span>'
        f'<span class="when">{d["date"]}</span>'
        f'<span class="what">{html.escape(d["meta"].get("title", ""))}</span></a></li>'
        for i, d in enumerate(days))
    arch = simple_page("歷史", f'<ul class="issues">{rows or "<li>尚無資料</li>"}</ul>')
    (out / "archive" / "index.html").write_text(PAGE.format(
        title="歷史｜每日情報", root="../", fonts=FONTS, body=arch, script=""), "utf-8")

    search = simple_page("搜尋",
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
