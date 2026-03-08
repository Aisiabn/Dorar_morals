"""
inspect_dorar.py — يفحص بنية HTML لصفحة من dorar.net
شغّله: python inspect_dorar.py
"""
import requests
from bs4 import BeautifulSoup

URL = "https://dorar.net/akhlaq/1"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 "
        "Chrome/109.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ar,en-US;q=0.9,en;q=0.8",
}

r = requests.get(URL, headers=HEADERS, timeout=20)
print(f"Status: {r.status_code}\n")
soup = BeautifulSoup(r.text, "html.parser")

# ── 1. og:title و title ──────────────────────────────────────────────────
og = soup.find("meta", property="og:title")
print(f"og:title   : {og['content'] if og else 'NOT FOUND'}")
print(f"<title>    : {soup.title.text.strip() if soup.title else 'NOT FOUND'}")

# ── 2. Breadcrumb ─────────────────────────────────────────────────────────
print("\n── Breadcrumb elements ──")
for el in soup.find_all(class_=True):
    cls = " ".join(el.get("class", []))
    if "breadcrumb" in cls.lower():
        print(f"  TAG={el.name}  CLASS={cls}")
        print(f"  TEXT={el.get_text(' > ', strip=True)[:120]}")
        break

# ── 3. زر التالي ──────────────────────────────────────────────────────────
print("\n── Next page links ──")
for a in soup.find_all("a", href=True):
    t = a.get_text(strip=True)
    if any(x in t for x in ["التالي", "›", "»", "next"]):
        print(f"  TEXT={t!r}  HREF={a['href']}")

# ── 4. حاوية المحتوى الرئيسي ─────────────────────────────────────────────
print("\n── Main content containers (first 5) ──")
candidates = []
for tag in ["main", "article", "section", "div"]:
    for el in soup.find_all(tag, class_=True):
        cls = " ".join(el.get("class", []))
        candidates.append((tag, cls, len(el.get_text())))
candidates.sort(key=lambda x: -x[2])
for tag, cls, length in candidates[:5]:
    print(f"  <{tag}> class={cls!r}  textlen={length}")

# ── 5. الـ classes الخاصة (tip, aaya, hadith …) ───────────────────────────
print("\n── Special span classes found ──")
special = set()
for span in soup.find_all("span", class_=True):
    for c in span.get("class", []):
        special.add(c)
print("  ", special)

# ── 6. عناصر مهمة أخرى ───────────────────────────────────────────────────
print("\n── h1/h2/h3 tags ──")
for h in soup.find_all(["h1","h2","h3"]):
    print(f"  <{h.name}> class={h.get('class',[])}  text={h.get_text(strip=True)[:80]}")