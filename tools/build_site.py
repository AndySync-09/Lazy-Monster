"""Build the public website: site/index.html (the source you edit) -> docs/index.html (what GitHub Pages serves).

The served page is a small shell: the title and social-preview tags stay as plain HTML (search engines and
link previews need them), and the page itself is compressed, base64-encoded and unpacked by JavaScript in
the browser. "View page source" shows the shell and one long encoded line instead of the markup.

Honest limit: this hides the markup from casual view-source only. The browser's DevTools always show the
live page, and site/index.html is in this repository.

    python tools/build_site.py
"""
import base64
import re
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC, OUT = ROOT / "site" / "index.html", ROOT / "docs" / "index.html"
KEEP = re.compile(r'<(?:title>.*?</title|meta\s[^>]*(?:name="(?:description|twitter:[^"]*|theme-color)"|property="og:[^"]*")[^>]*|'
                  r'link\s[^>]*rel="(?:icon|canonical|apple-touch-icon)"[^>]*)>', re.S | re.I)


def build(src: Path = SRC, out: Path = OUT) -> int:
    html = src.read_text(encoding="utf-8")
    head = html[: html.lower().find("</head>")] if "</head>" in html.lower() else ""
    keep = "\n".join(m.group(0) for m in KEEP.finditer(head))
    c = zlib.compressobj(9, zlib.DEFLATED, -15)                    # raw deflate, what DecompressionStream calls "deflate-raw"
    packed = base64.b64encode(c.compress(html.encode("utf-8")) + c.flush()).decode("ascii")
    shell = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{keep}
<style>html,body{{margin:0;min-height:100%;background:#1B1250}}</style>
</head><body>
<noscript><p style="font:16px sans-serif;color:#fff;padding:24px">Lazy-Monster's site needs JavaScript. The project: <a style="color:#C6F432" href="https://github.com/AndySync-09/Lazy-Monster">github.com/AndySync-09/Lazy-Monster</a></p></noscript>
<script>(async()=>{{const b=atob("{packed}"),u=new Uint8Array(b.length);for(let i=0;i<b.length;i++)u[i]=b.charCodeAt(i);
const h=await new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream("deflate-raw"))).text();
document.open();document.write(h);document.close();}})();</script>
</body></html>
"""
    out.write_text(shell, encoding="utf-8")
    return len(shell)


if __name__ == "__main__":
    n = build()
    print(f"built {OUT.relative_to(ROOT)} ({n // 1024} KB) from {SRC.relative_to(ROOT)}")
    sys.exit(0)
