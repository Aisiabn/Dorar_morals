"""
inspect_dorar.py — يفحص بنية dorar.net/alakhlaq
"""
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
        "Chrome/109.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

def fetch(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    print(f"\n{'='*60}")
    print(f"URL   : {url}")
    print(f"Status: {r.status_code}")
    return BeautifulSoup(r.text, "html.parser") if r.status_code == 200 else None

# ── الخطوة 1: صفحة الفهرس — اكتشف روابط المحتوى ──────────────────────────
soup = fetch("https://dorar.net/alakhlaq")
if soup:
    print("\n── كل الروابط الداخلية (/akhlaq أو /morals أو /alakhlaq) ──")
    found = set()
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if any(x in h for x in ["/akhlaq", "/morals", "/alakhlaq"]):
            found.add(h)
    for h in sorted(found)[:30]:
        print(f"  {h}")

# ── الخطوة 2: جرب أول رابط محتوى ─────────────────────────────────────────
CONTENT_URL = "https://dorar.net/alakhlaq/10"
soup2 = fetch(CONTENT_URL)
if soup2:
    og = soup2.find("meta", property="og:title")
    print(f"\nog:title : {og['content'] if og else 'NOT FOUND'}")

    print("\n── Breadcrumb ──")
    bc = soup2.find("ol", class_="breadcrumb")
    if bc:
        items = [li.get_text(strip=True) for li in bc.find_all("li")]
        print("  " + " > ".join(items))

    print("\n── Next page links ──")
    for a in soup2.find_all("a", href=True):
        t = a.get_text(strip=True)
        if any(x in t for x in ["التالي", "›", "»", "next", "السابق", "‹", "«"]):
            print(f"  TEXT={t!r}  HREF={a['href']}")

    print("\n── أكبر 5 حاويات محتوى ──")
    candidates = []
    for tag in ["main", "article", "section", "div"]:
        for el in soup2.find_all(tag, class_=True):
            cls = " ".join(el.get("class", []))
            txt = el.get_text()
            if len(txt) > 200:
                candidates.append((tag, cls, len(txt)))
    candidates.sort(key=lambda x: -x[2])
    seen = set()
    for tag, cls, ln in candidates:
        if cls not in seen:
            seen.add(cls)
            print(f"  <{tag}> class={cls!r}  textlen={ln}")
        if len(seen) >= 5:
            break

    print("\n── Special span classes ──")
    special = set()
    for span in soup2.find_all("span", class_=True):
        for c in span.get("class", []):
            special.add(c)
    print(" ", special)

    print("\n── h1/h2/h3 ──")
    for h in soup2.find_all(["h1","h2","h3"]):
        print(f"  <{h.name}> class={h.get('class',[])}  text={h.get_text(strip=True)[:80]}")

    print("\n── data-* attributes (tips/footnotes) ──")
    for el in soup2.find_all(True):
        attrs = {k:v for k,v in el.attrs.items() if k.startswith("data-")}
        if attrs:
            print(f"  <{el.name}> {attrs}")
            break

    print("\n── العناوين التي تحتوي روابط (في نهاية الصفحة) ──")
    for h in soup2.find_all(["h1","h2","h3","h4","h5","h6"]):
        links = h.find_all("a")
        if links:
            print(f"  <{h.name}> class={h.get('class',[])} text={h.get_text(strip=True)[:80]}")
            for a in links:
                print(f"    → href={a.get('href','')}  text={a.get_text(strip=True)[:60]}")

    print("\n── آخر 3 عناصر رئيسية في حاوية المحتوى ──")
    content = (
        soup2.find("div", class_=lambda c: c and "col-12" in c and "position-relative" in c)
        or soup2.find("div", class_=lambda c: c and "amiri_custom_content" in c)
    )
    if content:
        children = [c for c in content.children if hasattr(c, "name") and c.name]
        for el in children[-5:]:
            print(f"  <{el.name}> class={el.get('class',[])} text={el.get_text(strip=True)[:100]}")