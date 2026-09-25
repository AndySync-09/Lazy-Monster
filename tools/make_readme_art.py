"""Animated SVG art for the README (docs/assets/readme/): the hero stage, the two edition cards, the moods strip
and the icon set. Pure CSS animation inside each SVG, so GitHub plays it in an <img>. No emojis, brand colours only.

    python tools/make_readme_art.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "assets" / "readme"
FONT = "'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"
SK = {"classic": ("#9579FF", "#5B3DE0", "#DDFF6A", "#9CCB12", "#5B3DE0"),
      "mint": ("#5EE6C1", "#1FA588", "#FFB3D1", "#FF5FA2", "#1B8F76"),
      "sunset": ("#FFB36B", "#F2545B", "#FFE66D", "#F5C451", "#C9434A"),
      "midnight": ("#4B5BD6", "#1E245C", "#7CF3FF", "#2BC8E0", "#191E4E"),
      "bubblegum": ("#FF9CCB", "#E24C9A", "#DDFF6A", "#9CCB12", "#C23F84")}

CSS = """
.m *{transform-box:fill-box}
.br{transform-origin:50% 100%;animation:br 2.6s ease-in-out infinite}
.slp .br{animation-duration:4.8s}
.hl{transform-origin:100% 100%}.hr{transform-origin:0% 100%}
.slp .hl{transform:rotate(-14deg)}.slp .hr{transform:rotate(14deg)}
.tl{transform-origin:0% 50%;animation:tl 3.2s ease-in-out infinite}
.lid{transform-origin:50% 50%;animation:bl 4.4s infinite}
.z{opacity:0;animation:z 3.6s ease-in infinite}
.dt{animation:dt 1.2s ease-in-out infinite}
.mo{transform-origin:50% 50%}.spk .mo{animation:tk .28s ease-in-out infinite alternate}
.hop .br{animation:hop 1.2s cubic-bezier(.3,1.4,.5,1) infinite}
.lsn .br{animation:tlt 2.4s ease-in-out infinite}
.halo{transform-origin:50% 50%;animation:hal 1.6s ease-in-out infinite}
.doc{transform-origin:50% 100%;animation:bob 1.1s ease-in-out infinite}
.pu{animation:look 5s ease-in-out infinite}
@keyframes br{0%,100%{transform:scale(1,1)}50%{transform:scale(1.03,.97)}}
@keyframes tl{0%,100%{transform:rotate(0)}50%{transform:rotate(-14deg)}}
@keyframes bl{0%,93%,100%{transform:scaleY(1)}96%{transform:scaleY(.08)}}
@keyframes z{0%{opacity:0;transform:translate(0,10px) scale(.6)}25%{opacity:1}100%{opacity:0;transform:translate(24px,-40px) scale(1.1)}}
@keyframes dt{0%,100%{transform:translateY(0);opacity:.5}50%{transform:translateY(-9px);opacity:1}}
@keyframes tk{from{transform:scale(1,.5)}to{transform:scale(1.05,1.35)}}
@keyframes hop{0%,55%,100%{transform:translateY(0) scale(1,1)}20%{transform:translateY(-34px) scale(.97,1.04)}45%{transform:translateY(0) scale(1.06,.93)}}
@keyframes tlt{0%,100%{transform:rotate(-4deg)}50%{transform:rotate(4deg)}}
@keyframes hal{0%,100%{opacity:.45;transform:scale(.95)}50%{opacity:.95;transform:scale(1.08)}}
@keyframes bob{0%,100%{transform:translateY(0) rotate(-5deg)}50%{transform:translateY(-8px) rotate(5deg)}}
@keyframes look{0%,40%,100%{transform:translate(0,0)}50%,65%{transform:translate(-5px,-2px)}75%,90%{transform:translate(5px,1px)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""

ACC = {
 "shades": '<rect x="128" y="152" width="58" height="36" rx="12" fill="#16142B"/><rect x="214" y="152" width="58" height="36" rx="12" fill="#16142B"/><path d="M186,168 L214,168" stroke="#16142B" stroke-width="6"/><path d="M136,160 l14,0 M222,160 l14,0" stroke="#fff" stroke-width="4" opacity=".6"/>',
 "party": '<path d="M200,20 L168,92 L232,92 Z" fill="#FF5FA2"/><circle cx="200" cy="18" r="10" fill="#F5C451"/><path d="M178,70 L222,70" stroke="#fff" stroke-width="6" opacity=".7"/>',
 "cricket": '<path d="M132,100 Q200,40 268,100 Z" fill="#F3F1FF"/><path d="M200,98 Q262,96 300,110 L268,100 Z" fill="#CFC9F2"/><circle cx="200" cy="56" r="6" fill="#F2545B"/>',
 "band": '<path d="M92,128 Q200,78 308,128 L304,146 Q200,98 96,146 Z" fill="#F5C451"/>',
}


def monster(uid, x, y, scale=1.0, skin="classic", mood="listen", outfit="", delay=0.0):
    """One monster at (x, y) = centre of its feet line, 400x360 artboard scaled."""
    b1, b2, h1, h2, ft = SK[skin]
    cls = {"sleep": "slp", "listen": "lsn", "speak": "spk", "done": "hop", "think": "thk", "act": "act"}[mood]
    d = f"animation-delay:{-delay:.2f}s"
    eyes = ('<path d="M134,172 q22,16 44,0 M222,172 q22,16 44,0" stroke="#0D1117" stroke-width="8" fill="none" stroke-linecap="round"/>'
            if mood == "sleep" else
            f'<g class="lid" style="{d}"><ellipse cx="156" cy="170" rx="21" ry="23" fill="#fff"/><ellipse cx="244" cy="170" rx="21" ry="23" fill="#fff"/>'
            f'<g class="pu" style="{d}"><g transform="translate({6 if mood=="think" else 0} {-7 if mood=="think" else (5 if mood=="act" else 0)})">'
            '<circle cx="158" cy="174" r="10" fill="#0D1117"/><circle cx="246" cy="174" r="10" fill="#0D1117"/>'
            '<circle cx="161" cy="170" r="3.5" fill="#fff"/><circle cx="249" cy="170" r="3.5" fill="#fff"/></g></g></g>')
    mouth = ('<path d="M180,204 q20,20 40,0" stroke="#22105E" stroke-width="7" fill="none" stroke-linecap="round"/>' if mood == "done" else
             f'<g class="mo" style="{d}"><ellipse cx="200" cy="210" rx="15" ry="11" fill="#22105E"/><ellipse cx="200" cy="214" rx="8" ry="4" fill="#FF7FA8" opacity=".8"/></g>')
    extra = ""
    if mood == "sleep":
        extra += "".join(f'<text class="z" style="animation-delay:{-(delay+k*1.2):.2f}s" x="{300+26*k}" y="{[100,70,36][k]}" font-size="{[30,40,52][k]}" fill="#C6F432" font-family="{FONT}" font-weight="800">z</text>' for k in range(3))
    if mood == "think":
        extra += "".join(f'<circle class="dt" style="animation-delay:{k*.15:.2f}s" cx="{176+24*k}" cy="38" r="8" fill="#C6F432"/>' for k in range(3))
    halo = f'<ellipse class="halo" cx="200" cy="190" rx="200" ry="170" fill="url(#g{uid})"/>' if mood == "listen" else ""
    doc = ('<g class="doc"><rect x="300" y="228" width="44" height="54" rx="6" fill="#F3F1FF"/><rect x="308" y="240" width="28" height="4" rx="2" fill="#7C5CFF"/>'
           '<rect x="308" y="250" width="22" height="4" rx="2" fill="#7C5CFF"/><rect x="308" y="260" width="26" height="4" rx="2" fill="#C6F432"/></g>') if mood == "act" else ""
    return f'''<g transform="translate({x - 200*scale:.1f} {y - 288*scale:.1f}) scale({scale})"><g class="m {cls}">
<defs><linearGradient id="b{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{b1}"/><stop offset="1" stop-color="{b2}"/></linearGradient>
<linearGradient id="h{uid}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{h1}"/><stop offset="1" stop-color="{h2}"/></linearGradient>
<radialGradient id="g{uid}"><stop offset="0" stop-color="#C6F432" stop-opacity=".5"/><stop offset="1" stop-color="#C6F432" stop-opacity="0"/></radialGradient></defs>
{halo}<ellipse cx="200" cy="292" rx="140" ry="12" fill="#000" opacity=".35"/>
<g class="br" style="{d}">
<path class="hl" d="M131,104 L118,52 Q116,44 124,47 L166,90 Z" fill="url(#h{uid})"/><path class="hr" d="M269,104 L282,52 Q284,44 276,47 L234,90 Z" fill="url(#h{uid})"/>
<path class="tl" style="{d}" d="M312,210 q30,-6 38,22" stroke="{ft}" stroke-width="18" fill="none" stroke-linecap="round"/>
<path d="M66,262 C58,168 112,86 200,86 C288,86 342,168 334,262 Q332,284 310,284 L90,284 Q68,284 66,262 Z" fill="url(#b{uid})"/>
<path d="M92,150 C110,112 150,96 186,94" stroke="#fff" stroke-opacity=".28" stroke-width="9" fill="none" stroke-linecap="round"/>
<ellipse cx="200" cy="236" rx="92" ry="40" fill="#fff" opacity=".13"/>{eyes}
<circle cx="128" cy="198" r="12" fill="#FF8FB8" opacity="{.85 if mood=="done" else .45}"/><circle cx="272" cy="198" r="12" fill="#FF8FB8" opacity="{.85 if mood=="done" else .45}"/>
{mouth}<rect x="96" y="262" width="58" height="26" rx="13" fill="{ft}"/><rect x="246" y="262" width="58" height="26" rx="13" fill="{ft}"/>
{ACC.get(outfit, "")}{doc}</g>{extra}</g></g>'''


def svg(w, h, body, label, extra_css=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{label}">'
            f'<style>{CSS}{extra_css}</style>{body}</svg>\n')


def bg(w, h, uid, glow="#2A1E6E"):
    return (f'<defs><radialGradient id="bg{uid}" cx=".5" cy=".55" r=".75"><stop offset="0" stop-color="{glow}"/><stop offset="1" stop-color="#0D0A1F"/></radialGradient>'
            f'<pattern id="dp{uid}" width="28" height="28" patternUnits="userSpaceOnUse"><circle cx="14" cy="14" r="1.8" fill="#9579FF" opacity=".25"/></pattern></defs>'
            f'<rect width="{w}" height="{h}" rx="28" fill="url(#bg{uid})"/><rect width="{w}" height="{h}" rx="28" fill="url(#dp{uid})"/>')


def confetti(w, h, n, seed):
    out, cols = [], ["#C6F432", "#FF5FA2", "#9DB8FF", "#FFE66D", "#5EE6C1"]
    for i in range(n):
        x = (seed * 97 + i * 131) % w
        y0 = (seed * 53 + i * 71) % h
        dur = 5 + (i * 37 % 50) / 10
        s = 6 + i % 3 * 3
        out.append(f'<rect class="cf" x="{x}" y="{y0}" width="{s}" height="{s}" rx="1.5" fill="{cols[i % 5]}" '
                   f'style="animation-duration:{dur:.1f}s;animation-delay:{-(i*0.7)%dur:.1f}s"/>')
    return "".join(out)


CF_CSS = ".cf{transform-origin:50% 50%;animation:cf 6s linear infinite;opacity:.8}@keyframes cf{0%{transform:translateY(-60px) rotate(0)}100%{transform:translateY(520px) rotate(540deg)}}"


def hero():
    W, H = 1280, 520
    b = bg(W, H, "h", "#3A2385")
    b += f'<g opacity=".55">{confetti(W, H, 34, 3)}</g>'
    # spotlight + stage
    b += '<defs><radialGradient id="spot" cx=".5" cy=".5" r=".5"><stop offset="0" stop-color="#C6F432" stop-opacity=".22"/><stop offset="1" stop-color="#C6F432" stop-opacity="0"/></radialGradient></defs>'
    b += f'<ellipse class="sp" cx="640" cy="380" rx="560" ry="120" fill="url(#spot)"/>'
    b += (f'<text x="640" y="150" text-anchor="middle" font-family="{FONT}" font-weight="900" font-size="58" fill="#F3F1FF" letter-spacing="-1">Say it. <tspan fill="#C6F432">The monster does it.</tspan></text>'
          f'<text x="640" y="192" text-anchor="middle" font-family="{FONT}" font-weight="600" font-size="20" fill="#CFC9F2" letter-spacing="3">A LOCAL-FIRST VOICE AGENT FOR YOUR PC AND YOUR MAC</text>')
    row = [("mint", "listen", ""), ("sunset", "think", "party"), ("classic", "done", "shades"), ("midnight", "speak", "cricket"), ("bubblegum", "sleep", "")]
    xs = [200, 420, 640, 860, 1080]
    for i, (sk, md, of) in enumerate(row):
        sc = .62 if i == 2 else .5
        b += monster(f"h{i}", xs[i], 408, sc, sk, md, of, delay=i * .35)
    # NEW sticker
    b += (f'<g class="stk"><g transform="translate(1085 70) rotate(8)"><rect x="-120" y="-30" width="240" height="60" rx="10" fill="#FF5FA2" stroke="#16142B" stroke-width="4"/>'
          f'<text x="0" y="10" text-anchor="middle" font-family="{FONT}" font-weight="900" font-size="26" fill="#fff" letter-spacing="1">NOW ON macOS</text></g></g>')
    b += (f'<g class="stk2"><g transform="translate(190 66) rotate(-6)"><rect x="-128" y="-26" width="256" height="52" rx="10" fill="#C6F432" stroke="#16142B" stroke-width="4"/>'
          f'<text x="0" y="9" text-anchor="middle" font-family="{FONT}" font-weight="900" font-size="22" fill="#16142B" letter-spacing="1">WINDOWS AI PC</text></g></g>')
    # ticker
    msg = "SAY IT. THE MONSTER DOES IT.   ///   NPU + GPU + CPU ON INTEL AI PCs   ///   MLX + VISION ON APPLE SILICON   ///   WORKS OFFLINE: BRAIN-BREAK   ///   NO TELEMETRY   ///   "
    b += '<rect x="0" y="456" width="1280" height="64" fill="#C6F432"/><clipPath id="tk"><rect x="0" y="456" width="1280" height="64"/></clipPath>'
    b += (f'<g clip-path="url(#tk)"><g class="tick"><text x="0" y="498" font-family="{FONT}" font-weight="900" font-size="26" fill="#16142B" letter-spacing="1">{msg*3}</text></g></g>')
    css = CF_CSS + (".tick{animation:tick 24s linear infinite}@keyframes tick{to{transform:translateX(-2214px)}}"
                    ".stk{transform-origin:1085px 70px;animation:stk 1.6s cubic-bezier(.3,1.6,.5,1) infinite}@keyframes stk{0%,70%,100%{transform:scale(1)}80%{transform:scale(1.12) rotate(-2deg)}}"
                    ".stk2{transform-origin:190px 66px;animation:stk 2.2s cubic-bezier(.3,1.6,.5,1) infinite .8s}"
                    ".sp{animation:sp 2.4s ease-in-out infinite}@keyframes sp{50%{opacity:.55}}")
    return svg(W, H, f'<clipPath id="rr"><rect width="{W}" height="{H}" rx="28"/></clipPath><g clip-path="url(#rr)">{b}</g>',
               "Five Lazy-Monsters in five skins and moods on a stage; now on Windows AI PCs and macOS on Apple Silicon", css)


def edition(kind):
    W, H = 620, 380
    mac = kind == "mac"
    b = bg(W, H, kind, "#16324A" if mac else "#2A1E6E")
    title = "APPLE SILICON" if mac else "INTEL AI PC"
    sub = "M1 · M2 · M3 · M4" if mac else "CORE ULTRA · NPU"
    lanes = ([("GPU · MLX", "hears you, quick brain", "#9DB8FF"), ("VISION", "reads your screen", "#5EE6C1"), ("KEYCHAIN", "keeps your keys", "#FFE66D")] if mac else
             [("NPU", "wake word, reads screens", "#C6F432"), ("GPU", "hears you, quick brain", "#9DB8FF"), ("CPU", "the voice", "#FF5FA2")])
    # chip
    pins = "".join(f'<rect x="{-66+i*22}" y="-98" width="8" height="18" rx="3"/><rect x="{-66+i*22}" y="80" width="8" height="18" rx="3"/>'
                   f'<rect x="-98" y="{-66+i*22}" width="18" height="8" rx="3"/><rect x="80" y="{-66+i*22}" width="18" height="8" rx="3"/>' for i in range(7))
    b += (f'<g transform="translate(150 262)"><g fill="#8C95A6">{pins}</g><rect class="chip" x="-82" y="-82" width="164" height="164" rx="22" fill="#1B2030" stroke="#C6F432" stroke-width="4"/>'
          f'<rect x="-64" y="-64" width="128" height="128" rx="14" fill="#252B3D"/>'
          f'<text x="0" y="-4" text-anchor="middle" font-family="{FONT}" font-weight="900" font-size="{17 if mac else 18}" fill="#F3F1FF">{title}</text>'
          f'<text x="0" y="22" text-anchor="middle" font-family="{FONT}" font-weight="700" font-size="12" fill="#C6F432">{sub}</text></g>')
    b += monster(kind, 150, 186, .32, "midnight" if mac else "classic", "done" if mac else "listen", "shades" if mac else "", 0)
    for i, (n, what, c) in enumerate(lanes):
        y = 150 + i * 78
        b += (f'<path d="M232,262 C270,262 262,{y} 300,{y}" stroke="{c}" stroke-width="4" fill="none" stroke-dasharray="4 12" class="fl" style="animation-delay:{-i*.3}s"/>'
              f'<rect x="300" y="{y-28}" width="290" height="56" rx="14" fill="#ffffff" fill-opacity=".06" stroke="{c}" stroke-width="2.5"/>'
              f'<circle class="pl" cx="324" cy="{y}" r="8" fill="{c}" style="animation-delay:{i*.4}s"/>'
              f'<text x="344" y="{y-3}" font-family="{FONT}" font-weight="900" font-size="18" fill="{c}">{n}</text>'
              f'<text x="344" y="{y+17}" font-family="{FONT}" font-size="14" fill="#CFC9F2">{what}</text>')
    b += (f'<text x="30" y="46" font-family="{FONT}" font-weight="900" font-size="30" fill="#F3F1FF">{"macOS" if mac else "Windows 10 · 11"}</text>'
          f'<text x="30" y="72" font-family="{FONT}" font-size="15" fill="#CFC9F2">{"apple branch · Lazy-Monster.app" if mac else "main branch · the flagship"}</text>')
    css = (".fl{animation:fl 1s linear infinite}@keyframes fl{to{stroke-dashoffset:-32}}"
           ".pl{animation:pl 1.4s ease-in-out infinite}@keyframes pl{50%{opacity:.3}}"
           ".chip{animation:ch 1.8s ease-in-out infinite}@keyframes ch{50%{stroke-opacity:.35}}")
    return svg(W, H, f'<clipPath id="rr{kind}"><rect width="{W}" height="{H}" rx="28"/></clipPath><g clip-path="url(#rr{kind})">{b}</g>',
               f"Lazy-Monster on {'macOS with Apple Silicon' if mac else 'a Windows Intel AI PC'}", css)


def moods():
    W, H = 1280, 300
    b = bg(W, H, "md", "#221650")
    row = [("sleep", "classic", "#9579FF"), ("listen", "mint", "#5EE6C1"), ("think", "midnight", "#7CF3FF"),
           ("act", "sunset", "#FFB36B"), ("speak", "bubblegum", "#FF9CCB"), ("done", "classic", "#C6F432")]
    for i, (md, sk, c) in enumerate(row):
        x = 110 + i * 212
        b += f'<rect x="{x-94}" y="22" width="188" height="256" rx="22" fill="#fff" fill-opacity=".04" stroke="{c}" stroke-width="3"/>'
        b += monster(f"md{i}", x, 200, .4, sk, md, "", delay=i * .4)
        b += f'<text x="{x}" y="252" text-anchor="middle" font-family="{FONT}" font-weight="900" font-size="20" letter-spacing="3" fill="{c}">{md.upper()}</text>'
    return svg(W, H, f'<clipPath id="rrm"><rect width="{W}" height="{H}" rx="28"/></clipPath><g clip-path="url(#rrm)">{b}</g>',
               "Six moods in five skins: sleep, listen, think, act, speak, done")


ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" width="48" height="48"><style>'
        '.p{animation:p 1.6s ease-in-out infinite}.b{transform-origin:24px 24px;transform-box:view-box;animation:b 2.4s ease-in-out infinite}'
        '.s{transform-origin:24px 24px;transform-box:view-box;animation:s 6s linear infinite}'
        '@keyframes p{50%{opacity:.35}}@keyframes b{50%{transform:translateY(-3px)}}@keyframes s{to{transform:rotate(360deg)}}'
        '@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>{}</svg>\n')
ICONS = {
 "laptop": '<g class="b"><rect x="9" y="11" width="30" height="20" rx="3" fill="none" stroke="#7C5CFF" stroke-width="3"/><path d="M5 36h38" stroke="#7C5CFF" stroke-width="3.5" stroke-linecap="round"/><path class="p" d="M19 21q5 4 10 0" stroke="#C6F432" stroke-width="3" fill="none" stroke-linecap="round"/></g>',
 "silicon": '<g fill="#7C5CFF">' + "".join(f'<rect x="{15+i*6}" y="6" width="3" height="6" rx="1"/><rect x="{15+i*6}" y="36" width="3" height="6" rx="1"/><rect x="6" y="{15+i*6}" width="6" height="3" rx="1"/><rect x="36" y="{15+i*6}" width="6" height="3" rx="1"/>' for i in range(3)) +
            '</g><rect x="12" y="12" width="24" height="24" rx="5" fill="none" stroke="#7C5CFF" stroke-width="3"/><rect class="p" x="19" y="19" width="10" height="10" rx="2" fill="#C6F432"/>',
 "desktop": '<rect x="6" y="8" width="36" height="24" rx="3" fill="none" stroke="#7C5CFF" stroke-width="3"/><path d="M18 40h12M24 32v8" stroke="#7C5CFF" stroke-width="3" stroke-linecap="round"/><rect class="p" x="12" y="14" width="8" height="12" rx="2" fill="#C6F432"/><rect class="p" style="animation-delay:.5s" x="22" y="14" width="14" height="5" rx="2" fill="#FF5FA2"/>',
 "palette": '<g class="s"><circle cx="24" cy="24" r="17" fill="none" stroke="#7C5CFF" stroke-width="3"/><circle cx="24" cy="12" r="4" fill="#C6F432"/><circle cx="34" cy="20" r="4" fill="#FF5FA2"/><circle cx="31" cy="32" r="4" fill="#5EE6C1"/><circle cx="17" cy="32" r="4" fill="#FFB36B"/><circle cx="14" cy="20" r="4" fill="#9DB8FF"/></g>',
 "mood": '<circle cx="24" cy="24" r="18" fill="none" stroke="#7C5CFF" stroke-width="3"/><g class="p"><circle cx="18" cy="21" r="2.6" fill="#7C5CFF"/><circle cx="30" cy="21" r="2.6" fill="#7C5CFF"/></g><path d="M16 29q8 7 16 0" stroke="#C6F432" stroke-width="3.2" fill="none" stroke-linecap="round"/>',
 "key": '<g class="b"><circle cx="17" cy="24" r="8" fill="none" stroke="#7C5CFF" stroke-width="3.2"/><path d="M25 24h16M35 24v6M40 24v4" stroke="#7C5CFF" stroke-width="3.2" stroke-linecap="round"/><circle class="p" cx="17" cy="24" r="3" fill="#C6F432"/></g>',
 "app": '<rect class="b" x="8" y="8" width="32" height="32" rx="9" fill="none" stroke="#7C5CFF" stroke-width="3"/><path d="M17 21l-3-9 8 6M31 21l3-9-8 6" fill="#C6F432"/><path d="M14 36q10-16 20 0" fill="#7C5CFF"/><path class="p" d="M19 29h2M27 29h2" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>',
 "play": '<circle cx="24" cy="24" r="18" fill="none" stroke="#7C5CFF" stroke-width="3"/><path class="p" d="M20 16l12 8-12 8z" fill="#C6F432"/>',
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hero.svg").write_text(hero(), encoding="utf-8")
    (OUT / "edition-windows.svg").write_text(edition("win"), encoding="utf-8")
    (OUT / "edition-mac.svg").write_text(edition("mac"), encoding="utf-8")
    (OUT / "moods.svg").write_text(moods(), encoding="utf-8")
    for n, body in ICONS.items():
        (OUT / "icons" / f"{n}.svg").write_text(ICON.replace("{}", body), encoding="utf-8")
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))


if __name__ == "__main__":
    main()
