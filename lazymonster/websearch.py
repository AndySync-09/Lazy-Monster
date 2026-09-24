"""Web research for any brain that has no built-in web search (local models).

Search (DuckDuckGo by default, no key; Brave Search if BRAVE_API_KEY is set),
fetch the top pages, keep their readable text, and let the brain summarise it
with sources. The same path works for OpenAI-compatible cloud endpoints too."""
import html
import os
import re
from html.parser import HTMLParser
from typing import List, Tuple
from urllib.parse import parse_qs, unquote, urlparse

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LazyMonster/1.1 (+https://github.com/AndySync-09/Lazy-Monster)"}


def parse_ddg(page: str, limit: int = 5) -> List[Tuple[str, str]]:
    """(title, url) pairs from DuckDuckGo's HTML results page."""
    out = []
    for m in re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href, title = html.unescape(m.group(1)), re.sub(r"<[^>]+>", "", html.unescape(m.group(2))).strip()
        if "uddg=" in href:                                     # /l/?uddg=<real url>
            href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("http") and "duckduckgo.com/y.js" not in href:
            out.append((title or href, href))
        if len(out) >= limit:
            break
    return out


def search(query: str, limit: int = 5) -> List[Tuple[str, str]]:
    import requests
    key = os.environ.get("BRAVE_API_KEY", "")
    if key:
        r = requests.get("https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": limit},
                         headers={"Accept": "application/json", "X-Subscription-Token": key}, timeout=10)
        r.raise_for_status()
        return [(x.get("title", ""), x.get("url", "")) for x in r.json().get("web", {}).get("results", [])][:limit]
    r = requests.post("https://html.duckduckgo.com/html/", data={"q": query}, headers=UA, timeout=10)
    r.raise_for_status()
    return parse_ddg(r.text, limit)


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def page_text(page: str, limit: int = 3000) -> str:
    p = _Text()
    try:
        p.feed(page)
    except Exception:
        pass
    return re.sub(r"\s+", " ", " ".join(p.parts))[:limit]


def fetch(url: str, limit: int = 3000) -> str:
    import requests
    r = requests.get(url, headers=UA, timeout=8, stream=True)
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "html"):
        return ""
    raw = r.raw.read(400_000, decode_content=True)
    return page_text(raw.decode(r.encoding or "utf-8", errors="replace"), limit)


def research(client, question: str, pages: int = 3) -> str:
    """Search, read the top pages, summarise with the given chat client."""
    hits = search(question, limit=6)
    if not hits:
        return "ERROR: the web search returned nothing"
    docs = []
    for title, url in hits:
        if len(docs) >= pages:
            break
        try:
            text = fetch(url)
        except Exception:
            text = ""
        if len(text) > 200:
            docs.append((title, url, text))
    if not docs:
        return "Search results (pages could not be read):\n" + "\n".join(f"- {t}: {u}" for t, u in hits[:5])
    ctx = "\n\n".join(f"[{i + 1}] {t} ({u})\n{x}" for i, (t, u, x) in enumerate(docs))
    msg = [{"role": "system", "content": "Answer from the sources only, in 5-8 plain sentences with key facts and dates. "
                                         "Cite sources as [1], [2]."},
           {"role": "user", "content": f"Question: {question}\n\nSources:\n{ctx}"}]
    data = client.chat(msg)
    answer = (data["choices"][0]["message"].get("content") or "").strip()
    return answer + "\nSources:\n" + "\n".join(f"- [{i + 1}] {t}: {u}" for i, (t, u, _) in enumerate(docs))
