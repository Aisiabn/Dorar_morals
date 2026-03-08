#!/usr/bin/env python3
"""
morals_export.py — Export dorar.net/alakhlaq to EPUB + Markdown
Usage:
    python dorar_export.py
    TEST_PAGES=10 python dorar_export.py
"""

import os
import re
import time
import uuid
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ── Config ────────────────────────────────────────────────────────────────────
START_URL    = "https://dorar.net/alakhlaq"
PAGE_RE      = re.compile(r"/alakhlaq/(\d+)")
SKIP_CRUMBS  = 2          # skip: home + encyclopedia name
DELAY        = 1.0
TIMEOUT      = 20
TEST_PAGES   = int(os.getenv("TEST_PAGES") or 0)
OUT_DIR      = Path("output")
EPUB_PATH    = OUT_DIR / "morals.epub"
MD_DIR       = OUT_DIR / "md"
BOOK_TITLE   = "موسوعة الأخلاق"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
        "Chrome/109.0.0.0"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

LEVEL_NAMES  = {1: "باب", 2: "فصل", 3: "مبحث", 4: "مطلب", 5: "فرع", 6: "مسألة"}
# اسم أبناء كل مستوى (جمع)
CHILDREN_NAMES = {1: "فصل", 2: "مبحث", 3: "مطلب", 4: "فرع", 5: "مسألة"}


def _count_phrase(n: int, child_type: str) -> str:
    """يولّد عبارة 'وفيه X ...' بصيغة عربية صحيحة."""
    if n == 1:
        return f"وفيه {child_type} واحد"
    elif n == 2:
        return f"وفيه {child_type}ان"
    elif 3 <= n <= 10:
        # جمع قياسي بإضافة ات/ون — نستخدم صيغة بسيطة
        plurals = {
            "فصل": "فصول", "مبحث": "مباحث", "مطلب": "مطالب",
            "فرع": "فروع", "مسألة": "مسائل",
        }
        return f"وفيه {n} {plurals.get(child_type, child_type + 'ات')}"
    else:
        plurals = {
            "فصل": "فصلاً", "مبحث": "مبحثاً", "مطلب": "مطلباً",
            "فرع": "فرعاً", "مسألة": "مسألةً",
        }
        return f"وفيه {n} {plurals.get(child_type, child_type)}"
INDEX_LEVELS = {1, 2, 3}

PUA_RE  = re.compile(r"[\ue000-\uf8ff]")
SAFE_RE = re.compile(r'[\\/:*?"<>|]')

NAV_TEXT_RE = re.compile(
    r"السابق|التالي|انظر\s+أيض|الرابط\s+المختصر|مشاركة|share",
    re.I,
)

REMOVE_SELECTORS = [
    "nav", "header", "footer", "script", "style", "form",
    ".card-title", ".dorar-bg-lightGreen", ".collapse",
    "h3#more-titles",
]

# ── HTTP Session ──────────────────────────────────────────────────────────────
_session = requests.Session()
_session.headers.update(HEADERS)


def fetch(url: str) -> BeautifulSoup | None:
    try:
        r = _session.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        r.encoding = "utf-8"
        return BeautifulSoup(r.text, "html.parser")
    except Exception as exc:
        print(f"  [ERROR] {url}: {exc}")
        return None


# ── Data Classes ──────────────────────────────────────────────────────────────
@dataclass
class Page:
    pid:          str
    url:          str
    title:        str
    level:        int
    breadcrumb:   list[str]
    body_html:    str
    footnotes:    list[tuple[str, str]]  # [(fn_id, text)]

    def epub_filename(self) -> str:
        return f"p{self.pid}.xhtml"


@dataclass
class IndexPage:
    pid:      str
    title:    str
    level:    int
    children: list[str]  # direct child titles

    def epub_filename(self) -> str:
        return f"p{self.pid}.xhtml"


Item = Page | IndexPage

# ── Discovery ────────────────────────────────────────────────────────────────
def discover_urls() -> list[str]:
    urls, seen = [], set()
    url = START_URL
    while url:
        if url in seen:
            break
        seen.add(url)
        urls.append(url)
        print(f"  [{len(urls):>4}] {url}")
        if TEST_PAGES and len(urls) >= TEST_PAGES:
            break
        soup = fetch(url)
        if not soup:
            break
        time.sleep(DELAY)
        url = _next_url(soup, url)
    return urls


def _next_url(soup: BeautifulSoup, current: str) -> str | None:
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not PAGE_RE.search(href):
            continue
        txt = a.get_text(strip=True)
        if txt == "التالي":
            return urljoin(current, href)
    return None


# ── Parsing ──────────────────────────────────────────────────────────────────
def page_title(soup: BeautifulSoup) -> str:
    # العنوان في h1.h5-responsive وليس og:title (يعيد اسم الموسوعة)
    h1 = soup.find("h1", class_="h5-responsive")
    if h1:
        return h1.get_text(strip=True)
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].split(" - ")[0].strip()
    t = soup.find("title")
    return t.get_text().split(" - ")[0].strip() if t else "بدون عنوان"


def page_breadcrumb(soup: BeautifulSoup) -> list[str]:
    bc_el = soup.find("ol", class_="breadcrumb")
    if not bc_el:
        return []
    return [li.get_text(strip=True) for li in bc_el.find_all("li") if li.get_text(strip=True)]


def extract_content(soup: BeautifulSoup, pid: str) -> tuple[str, list[tuple[str, str]]]:
    """Return (inner_html, [(fn_id, fn_text)])."""
    body = soup.find("div", class_="col-12 position-relative") or soup.find("div", class_=re.compile(r"col-12"))
    if not body:
        return "", []

    body = BeautifulSoup(str(body), "html.parser")   # work on a copy

    for sel in REMOVE_SELECTORS:
        for el in body.select(sel):
            el.decompose()

    for a in body.find_all("a"):
        if NAV_TEXT_RE.search(a.get_text()):
            a.decompose()

    footnotes: list[tuple[str, str]] = []
    fn_n = 0

    # Process tips in reverse so counter matches document order after reversal
    tips = list(body.find_all(class_="tip"))
    for span in reversed(tips):
        fn_text = (
            span.get("data-original-title")
            or span.get("data-content")
            or span.get("data-tippy-content")
            or span.get_text(strip=True)
        )
        fn_n += 1
        fn_id = f"fn-{pid}-{fn_n}"
        footnotes.insert(0, (fn_id, fn_text))
        anchor = BeautifulSoup(
            f'<sup><a href="#{fn_id}">[{fn_n}]</a></sup>', "html.parser"
        )
        span.replace_with(anchor)

    for span in body.find_all("span"):
        cls = set(span.get("class", []))
        txt = span.get_text()

        if "aaya" in cls:
            span.replace_with(f"﴿{txt}﴾")
        elif "hadith" in cls:
            span.replace_with(f"«{txt}»")
        elif "sora" in cls:
            span.replace_with(PUA_RE.sub("", txt))
        elif "title-2" in cls:
            h = BeautifulSoup(f"<h4>{txt}</h4>", "html.parser")
            span.replace_with(h)
        elif "title-1" in cls:
            h = BeautifulSoup(f"<h5>{txt}</h5>", "html.parser")
            span.replace_with(h)

    return body.decode_contents(), footnotes


# ── Scrape All ────────────────────────────────────────────────────────────────
def scrape_all() -> list[Page]:
    urls = discover_urls()
    print(f"\n{len(urls)} pages found. Parsing content…\n")
    pages: list[Page] = []

    for i, url in enumerate(urls, 1):
        pid = f"{i:05d}"
        print(f"  parse {pid}: {url}")
        soup = fetch(url)
        if not soup:
            continue
        time.sleep(DELAY)

        title = page_title(soup)
        bc    = page_breadcrumb(soup)

        # Guarantee last crumb == title
        if not bc or bc[-1] != title:
            bc.append(title)

        depth = max(0, len(bc) - SKIP_CRUMBS - 1)
        level = min(depth + 1, 6)

        body_html, footnotes = extract_content(soup, pid)
        pages.append(Page(pid, url, title, level, bc, body_html, footnotes))

    return pages


# ── Build Flat Document Order (with index pages) ───────────────────────────────
def build_document(pages: list[Page]) -> list[Item]:
    """
    Walk pages in order; before the first page of each new section at
    levels 1–3, insert an IndexPage listing its direct children.
    """
    # Pre-pass: collect direct children per section key
    section_children: dict[tuple, list[str]] = defaultdict(list)
    for p in pages:
        ancestors = p.breadcrumb[SKIP_CRUMBS:]      # strip home + book
        for depth in range(min(len(ancestors) - 1, 3)):
            parent_key   = tuple(ancestors[: depth + 1])
            child_name   = ancestors[depth + 1] if depth + 1 < len(ancestors) else p.title
            kids = section_children[parent_key]
            if child_name not in kids:
                kids.append(child_name)

    seen_idx: set[tuple] = set()
    idx_n    = 0
    result: list[Item] = []

    for p in pages:
        ancestors = p.breadcrumb[SKIP_CRUMBS:]
        for depth in range(min(len(ancestors) - 1, 3)):
            key   = tuple(ancestors[: depth + 1])
            level = depth + 1
            if key not in seen_idx:
                seen_idx.add(key)
                idx_n += 1
                result.append(
                    IndexPage(
                        pid      = f"idx{idx_n:04d}",
                        title    = ancestors[depth],
                        level    = level,
                        children = section_children[key],
                    )
                )
        result.append(p)

    return result


# ── Markdown Export ───────────────────────────────────────────────────────────
def safe_name(s: str, maxlen: int = 80) -> str:
    s = SAFE_RE.sub("", s).replace(" ", "_")
    return s[:maxlen]


def _ancestors_dirs(bc: list[str]) -> list[str]:
    """Folder segments from breadcrumb (skip home+book, skip page itself)."""
    return [safe_name(s) for s in bc[SKIP_CRUMBS:-1]]


def html_to_md(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")

    def walk(node) -> str:
        if isinstance(node, NavigableString):
            return str(node)
        if not isinstance(node, Tag):
            return ""
        name = node.name

        if name in ("script", "style"):
            return ""
        if name in ("h4",):
            return f"\n\n#### {node.get_text(strip=True)}\n\n"
        if name in ("h5",):
            return f"\n\n##### {node.get_text(strip=True)}\n\n"
        if name == "p":
            inner = "".join(walk(c) for c in node.children)
            return f"\n\n{inner.strip()}\n\n"
        if name in ("ul", "ol"):
            items = [f"- {li.get_text(strip=True)}" for li in node.find_all("li")]
            return "\n" + "\n".join(items) + "\n\n"
        if name == "br":
            return "  \n"
        if name == "sup":
            return node.get_text()
        return "".join(walk(c) for c in node.children)

    md = walk(soup)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def export_markdown(items: list[Item]) -> None:
    MD_DIR.mkdir(parents=True, exist_ok=True)

    # Build a lookup: section_key → folder path (resolved on first real Page)
    section_dirs: dict[tuple, Path] = {}

    def _section_dir(bc: list[str], depth: int) -> Path:
        key = tuple(bc[SKIP_CRUMBS: SKIP_CRUMBS + depth + 1])
        if key not in section_dirs:
            parts = [safe_name(s) for s in bc[SKIP_CRUMBS: SKIP_CRUMBS + depth + 1]]
            section_dirs[key] = MD_DIR.joinpath(*parts)
        return section_dirs[key]

    for item in items:
        if isinstance(item, Page):
            parts = _ancestors_dirs(item.breadcrumb)
            folder = MD_DIR.joinpath(*parts) if parts else MD_DIR
            folder.mkdir(parents=True, exist_ok=True)
            fname  = f"{item.pid}_{safe_name(item.title)}.md"
            hashes = "#" * item.level
            md     = html_to_md(item.body_html)
            fn_block = ""
            if item.footnotes:
                lines = [f"[^{fid.split('-')[-1]}]: {txt}"
                         for fid, txt in item.footnotes]
                fn_block = "\n\n---\n\n" + "\n".join(lines)
            content = (
                f"{hashes} {item.title}\n\n"
                f"> المصدر: {item.url}\n\n"
                f"{md}{fn_block}\n"
            )
            (folder / fname).write_text(content, encoding="utf-8")

        elif isinstance(item, IndexPage):
            # Determine folder from the first Page that belongs to this section
            # We store by (level, title) — resolved later if needed
            # Use section_dirs cache keyed on what we know
            # Best we can do without page's bc: write to a flat fallback
            pass   # filled in second pass below

    # Second pass for IndexPages: we now have section_dirs populated
    for item in items:
        if not isinstance(item, IndexPage):
            continue
        # Find matching section dir
        matched = None
        for key, dpath in section_dirs.items():
            if len(key) == item.level and key[-1] == item.title:
                matched = dpath
                break
        if matched is None:
            matched = MD_DIR / safe_name(item.title)

        matched.mkdir(parents=True, exist_ok=True)
        hashes  = "#" * item.level
        n       = len(item.children)
        bullets = "\n".join(f"{i}. {c}" for i, c in enumerate(item.children, 1))
        child_type = CHILDREN_NAMES.get(item.level, "قسم")
        phrase     = _count_phrase(len(item.children), child_type)
        content = f"{hashes} {item.title}\n\n{phrase}:\n\n{bullets}\n"
        (matched / "_index.md").write_text(content, encoding="utf-8")

    print(f"  → Markdown → {MD_DIR}")


# ── EPUB Export ───────────────────────────────────────────────────────────────
EPUB_CSS = """\
@charset "UTF-8";
body {
    direction: rtl;
    font-family: Amiri, "Traditional Arabic", "Scheherazade New", Arial, sans-serif;
    line-height: 1.9;
    margin: 1em 2em;
    color: #333;
}
h1, h2, h3, h4, h5, h6 {
    font-size: 1.1em;
    color: #2c3e50;
    margin: 1em 0 0.4em;
    font-weight: bold;
}
p { margin: 0.4em 0 0.9em; text-align: justify; }
.ayah  { color: #1a5276; }
.hadith { color: #1e8449; }
ol, ul  { margin: 0.4em 0; padding-right: 1.5em; }
sup a   { color: #888; font-size: 0.8em; text-decoration: none; }
.footnotes {
    border-top: 1px solid #ccc;
    margin-top: 2em;
    padding-top: 0.8em;
    font-size: 0.9em;
}
.footnotes ol { padding-right: 1em; }
"""

_XHTML_TMPL = """\
<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="ar" dir="rtl">
<head>
  <meta charset="utf-8"/>
  <title>{title}</title>
  <link rel="stylesheet" type="text/css" href="../styles/book.css"/>
</head>
<body>
{body}
</body>
</html>"""


def _xhtml(title: str, body: str) -> str:
    return _XHTML_TMPL.format(title=title, body=body)


def _page_xhtml(p: Page) -> str:
    h = f"<h{p.level}>{p.title}</h{p.level}>"
    fn_sec = ""
    if p.footnotes:
        items = "".join(
            f'<li id="{fid}"><sup>[{fid.split("-")[-1]}]</sup> {txt}</li>'
            for fid, txt in p.footnotes
        )
        fn_sec = f'<div class="footnotes"><ol>{items}</ol></div>'
    return _xhtml(p.title, f"{h}\n{p.body_html}\n{fn_sec}")


def _index_xhtml(ip: IndexPage) -> str:
    child_type = CHILDREN_NAMES.get(ip.level, "قسم")
    phrase     = _count_phrase(len(ip.children), child_type)
    h   = f"<h{ip.level}>{ip.title}</h{ip.level}>"
    lis = "".join(f"<li>{c}</li>" for c in ip.children)
    body = f"{h}\n<p>{phrase}:</p>\n<ol>{lis}</ol>"
    return _xhtml(ip.title, body)


def _cover_xhtml(total_pages: int) -> str:
    body = (
        f'<div style="text-align:center;padding:4em 2em">'
        f"<h1>{BOOK_TITLE}</h1>"
        f"<p>عدد الصفحات: {total_pages}</p>"
        f"</div>"
    )
    return _xhtml(BOOK_TITLE, body)


# ── NCX / NAV builders ───────────────────────────────────────────────────────
def _build_toc_tree(entries: list[tuple]) -> list[dict]:
    """entries: [(level, title, pid), ...] → nested dicts."""
    root: list[dict] = []
    stack: list[tuple[int, list]] = []   # (level, children_list)

    for level, title, pid in entries:
        node = {"level": level, "title": title, "pid": pid, "children": []}
        while stack and stack[-1][0] >= level:
            stack.pop()
        target = stack[-1][1] if stack else root
        target.append(node)
        stack.append((level, node["children"]))

    return root


def _render_ncx(nodes: list[dict], po: list, indent: int = 4) -> list[str]:
    lines = []
    sp    = " " * indent
    for n in nodes:
        po[0] += 1
        lines += [
            f'{sp}<navPoint id="np-{n["pid"]}" playOrder="{po[0]}">',
            f'{sp}  <navLabel><text>{n["title"]}</text></navLabel>',
            f'{sp}  <content src="pages/{n["pid"]}.xhtml"/>',
        ]
        if n["children"]:
            lines += _render_ncx(n["children"], po, indent + 2)
        lines.append(f"{sp}</navPoint>")
    return lines


def _render_nav_ol(nodes: list[dict], indent: int = 2) -> list[str]:
    if not nodes:
        return []
    sp    = " " * indent
    lines = [f"{sp}<ol>"]
    for n in nodes:
        href = f'pages/{n["pid"]}.xhtml'
        if n["children"]:
            lines.append(f'{sp}  <li><a href="{href}">{n["title"]}</a>')
            lines += _render_nav_ol(n["children"], indent + 4)
            lines.append(f"{sp}  </li>")
        else:
            lines.append(f'{sp}  <li><a href="{href}">{n["title"]}</a></li>')
    lines.append(f"{sp}</ol>")
    return lines


def _nav_xhtml(entries: list[tuple]) -> str:
    tree  = _build_toc_tree(entries)
    inner = "\n".join(_render_nav_ol(tree))
    return f"""\
<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:epub="http://www.idpf.org/2007/ops"
      xml:lang="ar" dir="rtl">
<head><meta charset="utf-8"/><title>المحتويات</title></head>
<body>
<nav epub:type="toc" id="toc">
  <h1>المحتويات</h1>
{inner}
</nav>
</body>
</html>"""


# ── EPUB assembly ─────────────────────────────────────────────────────────────
def export_epub(items: list[Item]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    uid   = str(uuid.uuid4())
    pages = [i for i in items if isinstance(i, Page)]

    toc_entries: list[tuple] = []   # (level, title, pid)
    man_items:   list[str]   = []
    spine_refs:  list[str]   = []

    with zipfile.ZipFile(EPUB_PATH, "w", zipfile.ZIP_DEFLATED) as zf:

        # mimetype — must be uncompressed & first
        zf.writestr(
            zipfile.ZipInfo("mimetype"),
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )

        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
            '  <rootfiles>\n'
            '    <rootfile full-path="OEBPS/content.opf"'
            ' media-type="application/oebps-package+xml"/>\n'
            '  </rootfiles>\n'
            '</container>',
        )

        zf.writestr("OEBPS/styles/book.css", EPUB_CSS)
        zf.writestr("OEBPS/pages/cover.xhtml", _cover_xhtml(len(pages)))

        man_items  = [
            '<item id="ncx"    href="toc.ncx"         media-type="application/x-dtbncx+xml"/>',
            '<item id="nav"    href="nav.xhtml"        media-type="application/xhtml+xml" properties="nav"/>',
            '<item id="css"    href="styles/book.css"  media-type="text/css"/>',
            '<item id="cover"  href="pages/cover.xhtml" media-type="application/xhtml+xml"/>',
        ]
        spine_refs = ['<itemref idref="cover"/>']

        for item in items:
            fn   = item.epub_filename()
            iid  = f"p{item.pid}"

            if isinstance(item, Page):
                zf.writestr(f"OEBPS/pages/{fn}", _page_xhtml(item))
            else:
                zf.writestr(f"OEBPS/pages/{fn}", _index_xhtml(item))

            man_items.append(
                f'<item id="{iid}" href="pages/{fn}"'
                ' media-type="application/xhtml+xml"/>'
            )
            spine_refs.append(f'<itemref idref="{iid}"/>')
            toc_entries.append((item.level, item.title, item.pid))

        # content.opf
        manifest = "\n    ".join(man_items)
        spine    = "\n    ".join(spine_refs)
        zf.writestr(
            "OEBPS/content.opf",
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<package xmlns="http://www.idpf.org/2007/opf" version="3.0"'
            f' unique-identifier="uid" xml:lang="ar">\n'
            f'  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
            f'    <dc:title>{BOOK_TITLE}</dc:title>\n'
            f'    <dc:language>ar</dc:language>\n'
            f'    <dc:identifier id="uid">{uid}</dc:identifier>\n'
            f'  </metadata>\n'
            f'  <manifest>\n    {manifest}\n  </manifest>\n'
            f'  <spine toc="ncx">\n    {spine}\n  </spine>\n'
            f'</package>',
        )

        # toc.ncx
        tree = _build_toc_tree(toc_entries)
        po   = [0]
        ncx_pts = "\n".join(_render_ncx(tree, po))
        zf.writestr(
            "OEBPS/toc.ncx",
            f'<?xml version="1.0" encoding="utf-8"?>\n'
            f'<!DOCTYPE ncx PUBLIC "-//NISO//DTD ncx 2005-1//EN"'
            f' "http://www.daisy.org/z3986/2005/ncx-2005-1.dtd">\n'
            f'<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">\n'
            f'  <head>\n'
            f'    <meta name="dtb:uid" content="{uid}"/>\n'
            f'    <meta name="dtb:depth" content="6"/>\n'
            f'  </head>\n'
            f'  <docTitle><text>{BOOK_TITLE}</text></docTitle>\n'
            f'  <navMap>\n{ncx_pts}\n  </navMap>\n'
            f'</ncx>',
        )

        # nav.xhtml (EPUB3)
        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(toc_entries))

    print(f"  → EPUB  → {EPUB_PATH}")


# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    mode = f"TEST ({TEST_PAGES} صفحات)" if TEST_PAGES else "FULL"
    print(f"=== dorar_export  [{mode}] ===\n")

    print("1) اكتشاف الصفحات…")
    raw_pages = scrape_all()
    print(f"   {len(raw_pages)} صفحة\n")

    print("2) بناء الهيكل…")
    items = build_document(raw_pages)
    idx_count = sum(1 for i in items if isinstance(i, IndexPage))
    print(f"   {len(items)} عنصر ({idx_count} فهارس تلقائية)\n")

    print("3) تصدير Markdown…")
    export_markdown(items)

    print("4) بناء EPUB…")
    export_epub(items)

    print("\n✓ اكتمل")


if __name__ == "__main__":
    main()
