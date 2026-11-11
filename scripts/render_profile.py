#!/usr/bin/env python3
"""Refresh pinned repositories + contributions and render a fully self-contained SVG README.

GITHUB_TOKEN=... python scripts/render_profile.py --refresh
python scripts/render_profile.py                    # offline, cached data
STATIC=1 python scripts/render_profile.py           # no animation; final frame
python scripts/render_profile.py --data data/demo.json --out demo-cards

Requires Pillow and fonttools/pyftsubset for glyph-subset WOFFs. Remote fetch is
only performed with --refresh. No live API calls occur inside the README images.
"""
from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from html import escape
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from PIL import Image, ImageEnhance, ImageOps, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
LOGIN = "CBS041"
PUBLIC_PROFILE = f"https://github.com/{LOGIN}"
DATA_FILE = ROOT / "data" / "profile.json"
COLORS = {
    "bg": "#0A0A0A", "card": "#111113", "border": "#29292D",
    "primary": "#EDEDED", "muted": "#A1A1AA", "quiet": "#71717A",
    "accent": "#036CB4", "accent_light": "#56B7F7", "darkblue": "#10263B",
}
MAX_PINNED = 4


def normalize_pinned(nodes: list[dict]) -> list[dict]:
    """GraphQL order is meaningful: first cards correspond to profile pinned order."""
    output = []
    for node in nodes:
        if not node or node.get("isPrivate") or not node.get("name"):
            continue
        url = str(node.get("url") or "")
        if not url.startswith("https://github.com/"):
            continue
        desc = re.sub(r"\s+", " ", str(node.get("description") or "")).strip()
        output.append({
            "name": str(node["name"]),
            "description": desc or "Confira o código e a documentação do projeto.",
            "url": url,
            "language": (node.get("primaryLanguage") or {}).get("name") or "Repositório",
        })
        if len(output) >= MAX_PINNED:
            break
    return output


def refresh_data(path: Path = DATA_FILE) -> None:
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("Defina GITHUB_TOKEN ou GH_TOKEN para usar --refresh.")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=364)
    query = """query($login:String!,$from:DateTime!,$to:DateTime!){
      user(login:$login){
        avatarUrl(size:256)
        pinnedItems(first:6,types:REPOSITORY){ nodes{... on Repository{
          name description url isPrivate primaryLanguage{name}
        }}}
        contributionsCollection(from:$from,to:$to){
          contributionCalendar{ weeks{contributionDays{date contributionCount}} }
        }
      }
    }"""
    request_body = json.dumps({"query": query, "variables": {
        "login": LOGIN, "from": f"{start.isoformat()}T00:00:00Z",
        "to": f"{end.isoformat()}T23:59:59Z",
    }}).encode("utf-8")
    req = Request("https://api.github.com/graphql", data=request_body, method="POST", headers={
        "Authorization": "Bearer " + token,
        "User-Agent": "CBS041-profile-README-generator",
        "Accept": "application/vnd.github+json",
        "Content-Type": "application/json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urlopen(req, timeout=30) as response:
        payload = json.load(response)
    if payload.get("errors"):
        raise RuntimeError("GraphQL error: " + json.dumps(payload["errors"], ensure_ascii=False))
    user = (payload.get("data") or {}).get("user")
    if not user:
        raise RuntimeError("Usuário não encontrado no GitHub GraphQL.")
    pins = normalize_pinned((user.get("pinnedItems") or {}).get("nodes") or [])
    if not pins:
        raise RuntimeError("Nenhum repositório fixado público retornado; não substituir dados existentes.")
    weeks = user["contributionsCollection"]["contributionCalendar"]["weeks"]
    values = {d["date"]: int(d["contributionCount"])
              for week in weeks for d in week["contributionDays"]}
    expected = [(start + timedelta(days=i)).isoformat() for i in range(365)]
    missing = [d for d in expected if d not in values]
    if missing:
        raise RuntimeError(f"Calendário incompleto: {len(missing)} datas ausentes.")
    days = [{"date": d, "count": values[d]} for d in expected]
    # Only automatically download the existing GitHub avatar. A local custom
    # assets/portrait.png takes precedence and is never replaced.
    portrait_path = ROOT / "assets" / "github-avatar.png"
    if not (ROOT / "assets" / "portrait.png").exists():
        try:
            photo_req = Request(user["avatarUrl"], headers={"User-Agent": "CBS041-profile-README-generator"})
            with urlopen(photo_req, timeout=15) as response:
                photo = response.read(1_000_001)
            if len(photo) > 1_000_000:
                raise ValueError("Avatar acima de 1 MB")
            image = Image.open(io.BytesIO(photo)).convert("RGB")
            portrait_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(portrait_path, optimize=True)
        except Exception as exc:
            print(f"Aviso: avatar inacessível; mantendo imagem anterior ({exc}).")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": 1, "user": LOGIN, "pinned": pins,
                                "days": days, "generated_at": datetime.now(timezone.utc).isoformat()},
                               ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Atualizado: {len(pins)} repositórios fixados e {len(days)} dias.")


def validate_data(data: dict) -> None:
    if data.get("user") != LOGIN or data.get("schema_version") != 1:
        raise ValueError("JSON de outro usuário ou versão incompatível")
    days = data.get("days", [])
    keys = [x["date"] for x in days]
    if len(keys) != len(set(keys)) or any(int(d["count"]) < 0 for d in days):
        raise ValueError("Dias duplicados ou contribuições inválidas")
    for day in days:
        date.fromisoformat(day["date"])


def compute_stats(days: list[dict], today: date) -> dict:
    counters = {date.fromisoformat(d["date"]): int(d["count"]) for d in days}
    anchor = today if counters.get(today, 0) > 0 else today - timedelta(days=1)
    streak = 0
    while counters.get(anchor, 0) > 0:
        streak += 1
        anchor -= timedelta(days=1)
    totals = defaultdict(int)
    for d, v in counters.items():
        totals[(d.year, d.month)] += v
    months = []
    for offset in range(11, -1, -1):
        absolute = today.year * 12 + today.month - 1 - offset
        year, month = divmod(absolute, 12)
        months.append({"year": year, "month": month + 1, "total": totals[(year, month + 1)]})
    busiest = max(counters.items(), key=lambda item: (item[1], -item[0].toordinal()), default=None)
    return {"months": months, "streak": streak,
            "active_days": sum(v > 0 for v in counters.values()),
            "total": sum(counters.values()),
            "busiest": (busiest[0].isoformat(), busiest[1]) if busiest and busiest[1] else None}


def truncate(s: str, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", str(s)).strip()
    if len(s) <= max_chars:
        return s
    return s[:max_chars - 1].rstrip().rstrip(".,;:") + "…"


def wrap_description(value: str, max_chars: int = 50, lines: int = 2) -> list[str]:
    words = str(value).split()
    result = []
    for word in words:
        if not result or len(result[-1]) + len(word) + 1 > max_chars:
            result.append(word)
        else:
            result[-1] += " " + word
    if len(result) > lines:
        result = result[:lines]
        result[-1] = truncate(result[-1], max_chars - 1).rstrip("…") + "…"
    return result


def get_font_path(family: str, style: str = "Regular") -> Path:
    family_key = family.replace(" ", "_").upper()
    override = os.getenv(f"{family_key}_{style.upper()}_PATH")
    if override:
        return Path(override)
    match = subprocess.run(["fc-match", "-f", "%{file}\n", f"{family}:style={style}"],
                           capture_output=True, text=True, check=True)
    return Path(match.stdout.strip().splitlines()[0])


def ascii_portrait(path: Path | None) -> str:
    """ASCII characters derived from the real profile photo, when supplied."""
    if path is not None and path.is_file():
        photo = Image.open(path).convert("RGB")
        image = ImageOps.fit(photo, (34, 24))
        image = ImageEnhance.Contrast(image.convert("L")).enhance(1.55)
        chars = "@%#*+=-:. "
        lines = []
        for y in range(24):
            lines.append("".join(chars[min(len(chars)-1, round(image.getpixel((x,y)) / 255 * (len(chars)-1)))] for x in range(34)))
        return "\n".join(lines)
    # No fictional face: a small terminal-styled monogram until portrait arrives.
    return "\n".join([
        "..................................",
        "...........::::::.................",
        ".......::##########::.............",
        ".....:###::::::::###:.............",
        "....:##:..........:##:............",
        "...:##:....CSS...:##:............",
        "...:##:...........:##:...........",
        "...:##:...........:##:...........",
        "...:##:.....@@....:##:...........",
        "...:##:...........:##:...........",
        "...:##:...........:##:...........",
        "....:##:.........:##:............",
        ".....:###::::::::###:.............",
        ".......::##########::.............",
        "...........::::::.................",
        ".......CASSIANO / DEV.............",
        "......PORTFOLIO.SYSTEM............",
        "..................................",
        "..................................",
        "..................................",
        "..................................",
        "..................................",
        "..................................",
        "..................................",
    ])


def font_css(data: dict, portrait_art: str) -> str:
    """Embed subset WOFF font data URIs for isolated SVG <img> environments."""
    dynamic = " ".join((p["name"] + " " + p["description"] + " " + p["language"])
                       for p in data.get("pinned", []))
    glyphs = ("0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ "
              "áàâãéêíóôõúüçÁÉÍÓÚÇ ·—•↗←→/:.,!?+-()%#@_=<>\n"
              "Cassiano Santos Estudante de Engenharia de Software Full Stack Backend"
              "Em busca de estágio Desenvolvimento Web APIs Sistemas Qualidade"
              "PROJETOS FIXADOS ATIVIDADE RECENTE CONTRIBUIÇÕES POR MÊS"
              "SEQUÊNCIA DIAS ATIVOS DIA MAIS PRODUTIVO Nenhum dado ainda"
              "Jan Fev Mar Abr Mai Jun Jul Ago Set Out Nov Dez" + dynamic + portrait_art)
    output = []
    with tempfile.TemporaryDirectory() as tmp:
        chars = Path(tmp) / "glyphs.txt"
        chars.write_text(glyphs, encoding="utf-8")
        configurations = [
            ("Inter", "Regular", 400, "ProfileInter"),
            ("Inter", "SemiBold", 600, "ProfileInter"),
            ("Inter", "Bold", 700, "ProfileInter"),
            ("DejaVu Sans Mono", "Regular", 400, "ProfileMono"),
        ]
        for family, style, weight, alias in configurations:
            path = get_font_path(family, style)
            if not path.is_file():
                raise FileNotFoundError(f"Fonte ausente: {family} {style}")
            result = Path(tmp) / f"font-{len(output)}.woff"
            subprocess.run(["pyftsubset", str(path), f"--text-file={chars}",
                            f"--output-file={result}", "--flavor=woff",
                            "--layout-features=*", "--notdef-glyph", "--recommended-glyphs"],
                           check=True, capture_output=True)
            b64 = base64.b64encode(result.read_bytes()).decode("ascii")
            output.append(f"@font-face{{font-family:'{alias}';font-style:normal;font-weight:{weight};src:url(data:font/woff;base64,{b64}) format('woff')}}")
    return "\n".join(output)


def txt(x: float, y: float, value: object, size: float = 18, fill: str | None = None,
        weight: int = 400, props: str = "") -> str:
    return (f'<text x="{x}" y="{y}" font-size="{size}" '
            f'fill="{fill or COLORS["primary"]}" font-weight="{weight}" {props}>'
            f'{escape(str(value))}</text>')


def style(fonts: str, static: bool) -> str:
    animations = "" if static else """
    @keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
    @keyframes grow{from{transform:scaleY(0)}to{transform:scaleY(1)}}
    @keyframes glow{0%,100%{opacity:.4}50%{opacity:.9}}
    .reveal{opacity:0;animation:rise .78s cubic-bezier(.2,.7,.2,1) both;animation-delay:var(--d,0s)}
    .grow{transform-box:fill-box;transform-origin:center bottom;animation:grow .7s ease-out both;animation-delay:var(--d,0s)}
    .glow{animation:glow 3.4s ease-in-out infinite}
    """
    return (f"<style><![CDATA[{fonts}\n"
            "text{font-family:'ProfileInter',Arial,sans-serif}"
            ".mono{font-family:'ProfileMono',monospace}"
            + animations + "\n@media(prefers-reduced-motion:reduce){"
            "*,*::before,*::after{animation:none!important;transition:none!important}"
            ".reveal{opacity:1!important;transform:none!important}"
            ".grow{transform:none!important}"
            "animate{display:none!important}"
            "}\n]]></style>")


def svg_shell(w: int, h: int, label: str, content: str, fonts: str, static: bool) -> str:
    accent, border, card = COLORS['accent'], COLORS['border'], COLORS['card']
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'viewBox="0 0 {w} {h}" role="img" aria-label="{escape(label, quote=True)}">'
            f'<title>{escape(label)}</title>{style(fonts, static)}'
            f'<rect x=".8" y=".8" width="{w-1.6}" height="{h-1.6}" rx="15" '
            f'fill="{card}" stroke="{border}" stroke-width="1.5"/>'
            f'<rect x="1" y="1" width="3" height="{h-2}" rx="1.5" fill="{accent}"/>'
            f'<path d="M{w-235} 1 H{w-16} Q{w-1} 1 {w-1} 16 V{min(h-1,120)} Z" fill="{accent}" opacity=".045"/>'
            + content + '</svg>\n')


def arrow(x: int, y: int) -> str:
    """Draw a vector arrow instead of relying on missing font glyphs."""
    return (f'<path d="M{x} {y+14} L{x+14} {y} M{x+5} {y} H{x+14} V{y+9}" '
            f'fill="none" stroke="{COLORS["accent_light"]}" stroke-width="2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>')


def hero_card(fonts: str, ascii_art: str, static: bool) -> str:
    c = COLORS
    heading = f'''<g class="reveal" style="--d:.00s">
      {txt(36,44,'CASSIANO.TECH  /  SOFTWARE ENGINEERING',12,c['accent_light'],600,'letter-spacing="1.5"')}
      {txt(36,110,'Cassiano Santos',56,c['primary'],700)}
      {txt(36,149,'Full Stack Developer',22,c['primary'],600)}
      {txt(36,176,'Foco em Backend · TypeScript · Node.js · APIs',16,c['muted'])}
      {txt(36,213,'Estudante de Engenharia de Software · Aberto a estágio',16,c['muted'])}
      <circle cx="45" cy="244" r="5" fill="{c['accent_light']}"/>
      {txt(59,249,'Construindo projetos reais, um commit de cada vez.',14,c['primary'],400)}
      </g>'''
    frame = f'<rect x="701" y="29" width="230" height="243" rx="13" fill="#0C141B" stroke="{c["border"]}"/>'
    label = txt(714,48,"$ cat avatar.txt",11,c['accent_light'],400,'class="mono"')
    lines = ascii_art.splitlines()[:24]
    portrait = ''.join(txt(716, 64 + i*8.14, line, 8.4, c['accent_light'],400,
                            f'class="mono reveal" xml:space="preserve" style="--d:{.10+i*.028:.3f}s"')
                       for i, line in enumerate(lines))
    footer = txt(715,262,"[ ASCII / 34x24 ]",10,c['quiet'],400,'class="mono"')
    underline = f'<rect x="37" y="270" width="120" height="3" rx="1.5" fill="{c["accent"]}"/>'
    if not static:
        underline = (f'<rect x="37" y="270" height="3" rx="1.5" fill="{c["accent"]}">'
                     '<animate attributeName="width" from="0" to="120" begin="0.35s" dur="1s" fill="freeze"/>'
                     '</rect>')
    return svg_shell(960, 290,"Cassiano Santos · Full Stack Developer com foco em Backend",
                     heading+frame+label+portrait+footer+underline,fonts,static)


def tile_card(kind: str, title: str, detail: str, index: int, fonts: str, static: bool) -> str:
    c = COLORS
    glyph = {"portfolio":"</>","linkedin":"in","github":"git"}[kind]
    group = f'''<g class="reveal" style="--d:{.23+.13*index:.2f}s">
       <rect x="21" y="20" width="47" height="45" rx="9" fill="{c['darkblue']}"/>
       {txt(44,48,glyph,17,c['accent_light'],700,'text-anchor="middle"')}
       {txt(82,39,title,20,c['primary'],600)}
       {txt(82,61,detail,12,c['muted'])}
       {arrow(272,26)}
       </g>'''
    return svg_shell(310,88,title+" — "+detail,group,fonts,static)


def repo_card(repo: dict, index: int, fonts: str, static: bool) -> str:
    c = COLORS
    name = truncate(repo['name'], 30)
    lines = wrap_description(repo['description'], max_chars=49, lines=2)
    content = f'''<g class="reveal" style="--d:{.66+.20*index:.2f}s">
     {txt(23,30,f'{index+1:02} / PINNED REPO',11,c['accent_light'],600,'letter-spacing="1.15"')}
     {txt(23,65,name,22,c['primary'],700)}
     {txt(23,93,lines[0] if lines else '',14,c['muted'])}
     {txt(23,115,lines[1] if len(lines)>1 else '',14,c['muted'])}
     <rect x="22" y="134" width="{min(200,25+len(repo['language'])*9)}" height="22" rx="6" fill="{c['darkblue']}"/>
     {txt(33,149,repo['language'],11,c['accent_light'],600)}
     {arrow(419,20)}
     </g>'''
    return svg_shell(466,169,repo['name'] + ': ' + repo['description'],content,fonts,static)


def activity_card(days: list[dict], today: date, fonts: str, static: bool) -> str:
    c = COLORS
    stats = compute_stats(days,today)
    month_labels = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez']
    max_total = max([m['total'] for m in stats['months']],default=0)
    content = f'''<g class="reveal" style="--d:1.70s">
       {txt(32,45,'ATIVIDADE / ÚLTIMOS 12 MESES',13,c['accent_light'],600,'letter-spacing="1.2"')}
       {txt(926,45,'Dados sincronizados com GitHub',12,c['quiet'],400,'text-anchor="end"')}
       </g>'''
    for i,m in enumerate(stats['months']):
        x = 45+i*74
        h = max(4, round(102*m['total']/max_total)) if max_total else 4
        y = 182-h
        bar = f'<rect x="{x}" y="{y}" width="42" height="{h}" rx="5" fill="{c["accent"] if m["total"] else c["border"]}" opacity="{.6+ .4*m["total"]/max_total if max_total else 1:.2f}" class="grow" style="--d:{1.9+i*.055:.3f}s"/>'
        content += bar
        content += txt(x+21, 199, month_labels[m['month']-1],12,c['muted'],400,'text-anchor="middle"')
    most = stats['busiest']
    metrics = [
        ('SEQUÊNCIA',str(stats['streak'])+' dias' if days else '—'),
        ('DIAS ATIVOS',str(stats['active_days']) if days else '—'),
        ('MELHOR DIA',f'{date.fromisoformat(most[0]).strftime("%d/%m")} · {most[1]}' if most else '—'),
    ]
    for i,(label,value) in enumerate(metrics):
        x = 33+i*306
        content += (f'<path d="M{x} 218 h284" stroke="{c["border"]}"/>'
                    f'<g class="reveal" style="--d:{2.45+i*.10:.2f}s">'
                    f'{txt(x,239,label,10,c["quiet"],600,'letter-spacing="1.4"')}'
                    f'{txt(x,269,value,23,c["primary"],700)}' + '</g>')
    if not days:
        content += txt(480,211,'Contribuições disponíveis após a primeira sincronização',12,c['quiet'],400,'text-anchor="middle"')
    return svg_shell(960,289,'Contribuições mensais, sequência, dias ativos e melhor dia',content,fonts,static)


def color_for_contributions(n: int, max_n: int) -> str:
    if n <= 0:
        return COLORS['border']
    a = min(1, n/max(1,max_n))
    lo=(12,56,84);hi=(39,147,222)
    rgb=tuple(round(u+(v-u)*(0.20+0.80*a)) for u,v in zip(lo,hi))
    return '#%02x%02x%02x'%rgb


def contributions_card(days: list[dict], today: date, fonts: str, static: bool) -> str:
    c=COLORS
    values = {date.fromisoformat(d['date']):int(d['count']) for d in days}
    max_n = max(values.values(),default=0)
    total = sum(values.values())
    title = f'{total} CONTRIBUIÇÕES' if days else 'AGUARDANDO SINCRONIZAÇÃO'
    content = (f'<g class="reveal" style="--d:2.70s">'
               f'{txt(30,43,"MAPA DE CONTRIBUIÇÕES",13,c["accent_light"],600)}'
               + txt(930,43,title,11,c["muted"],600,'text-anchor="end"')
               + '</g>')
    sunday=today-timedelta(days=(today.weekday()+1)%7)
    first=sunday-timedelta(weeks=52)
    for w in range(53):
        for weekday in range(7):
            d=first+timedelta(days=7*w+weekday)
            if d > today:
                continue
            n=values.get(d,0)
            x,y=65+w*16,73+weekday*16
            fill=color_for_contributions(n,max_n)
            op=1 if not days or d in values else .4
            content += (f'<rect x="{x}" y="{y}" width="12" height="12" rx="3" fill="{fill}" opacity="{op}" class="reveal" style="--d:{2.8+w*.014:.3f}s">'
                        f'<title>{d.isoformat()}: {n} contribuições</title></rect>')
    for i,label in [(1,'Seg'),(3,'Qua'),(5,'Sex')]:
        content += txt(27,83+i*16,label,11,c['quiet'])
    content += txt(728,211,'MENOS',11,c['quiet'],600)
    for i,num in enumerate([0,1,2,4,9]):
        content += f'<rect x="{784+i*23}" y="199" width="15" height="15" rx="3" fill="{color_for_contributions(num,9)}"/>'
    content += txt(919,211,'MAIS',11,c['quiet'],600)
    return svg_shell(960,229,'Mapa de contribuições do GitHub',content,fonts,static)


def render_all(data: dict, destination: Path, static: bool, today: date | None = None, fonts: str | None = None) -> list[Path]:
    validate_data(data)
    destination.mkdir(parents=True,exist_ok=True)
    today=today or date.today()
    preferred = ROOT/'assets'/'portrait.png'
    github=ROOT/'assets'/'github-avatar.png'
    art=ascii_portrait(preferred if preferred.exists() else github if github.exists() else None)
    fonts = font_css(data,art) if fonts is None else fonts
    pieces = {
        'hero.svg':hero_card(fonts,art,static),
        'tile-portfolio.svg':tile_card('portfolio','Portfólio','cassiano.tech',0,fonts,static),
        'tile-linkedin.svg':tile_card('linkedin','LinkedIn','Vamos conversar?',1,fonts,static),
        'tile-github.svg':tile_card('github','GitHub','@CBS041',2,fonts,static),
        'activity.svg':activity_card(data.get('days',[]),today,fonts,static),
        'contributions.svg':contributions_card(data.get('days',[]),today,fonts,static),
    }
    for i,repo in enumerate(data.get('pinned',[])[:MAX_PINNED]):
        pieces[f'repo-{i+1:02}.svg']=repo_card(repo,i,fonts,static)
    result=[]
    for name,markup in pieces.items():
        ElementTree.fromstring(markup)  # XML validity, no external assets
        file=destination/name
        file.write_text(markup,encoding='utf-8')
        result.append(file)
    for obsolete in destination.glob('repo-*.svg'):
        if obsolete not in result:
            obsolete.unlink()
    return result


def img(name: str, alt: str, width: str) -> str:
    alt=escape(alt,quote=True)
    return (f'<picture><source media="(prefers-reduced-motion: reduce)" '
            f'srcset="./cards/static/{name}.svg" />'
            f'<img src="./cards/{name}.svg" alt="{alt}" width="{width}" /></picture>')


def build_readme(data: dict) -> str:
    """README must update links/order too when pinned repositories change."""
    validate_data(data)
    parts=[
        '<!-- AUTOGERADO por scripts/render_profile.py: editar o gerador, não este arquivo. -->',
        '<div align="center">',
        f'<a href="https://cassiano.tech">{img("hero", "Cassiano Santos — Full Stack e Backend", "100%")}</a>',
        '<p>',
        f'<a href="https://cassiano.tech">{img("tile-portfolio", "Portfólio", "32.5%")}</a>',
        f'<a href="https://www.linkedin.com/in/cassiano-b-santos">{img("tile-linkedin", "LinkedIn", "32.5%")}</a>',
        f'<a href="https://github.com/CBS041?tab=repositories">{img("tile-github", "Repositórios do GitHub", "32.5%")}</a>',
        '</p>', '</div>',
        '', '### Projetos fixados',
        '',
    ]
    pins=data.get('pinned',[])[:MAX_PINNED]
    if pins:
        # two-card rows, so GitHub never needs to run JavaScript or external SVG links
        for i in range(0,len(pins),2):
            parts.append('<p align="center">')
            for ix,repo in enumerate(pins[i:i+2],i):
                safe_url=escape(repo['url'],quote=True)
                safe_title=repo['name'] + ' — ' + truncate(repo['description'],70)
                parts.append(f'<a href="{safe_url}">{img(f"repo-{ix+1:02}",safe_title,"49%")}</a>')
            parts.append('</p>')
    else:
        parts += ['*Os primeiros repositórios fixados serão carregados na primeira execução do workflow.*','']
    parts += [
        '', '### Atividade',
        '<div align="center">',
        img('activity','Resumo mensal de contribuições do GitHub','100%'),
        img('contributions','Calendário de contribuições do GitHub','100%'),
        '</div>',
        '',
        '<p align="center"><sub>TypeScript · Node.js · React · Next.js · PostgreSQL · Docker</sub></p>',
        '<p align="center"><sub>Aprender construindo. Melhorar refatorando. Evoluir entregando.</sub></p>',
        '',
        '<!-- Fixados e descrições sincronizados pela API GraphQL do GitHub. -->',
        ''
    ]
    return '\n'.join(parts)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh',action='store_true',help='Atualizar os fixados, o avatar e as contribuições via GraphQL')
    parser.add_argument('--data',type=Path,default=DATA_FILE,help='Arquivo JSON de entrada')
    parser.add_argument('--out',type=Path,default=ROOT/'cards',help='Pasta de saída')
    args=parser.parse_args()
    if args.refresh:
        refresh_data(args.data)
    data=json.loads(args.data.read_text(encoding='utf-8'))
    static=os.getenv('STATIC','0')=='1'
    dest=args.out
    if not dest.is_absolute():
        dest=ROOT/dest
    portrait_path=ROOT/'assets'/'portrait.png'
    avatar_path=ROOT/'assets'/'github-avatar.png'
    portrait=ascii_portrait(portrait_path if portrait_path.exists() else avatar_path if avatar_path.exists() else None)
    fonts=font_css(data,portrait)
    if not static:
        render_all(data,dest/'static',static=True,fonts=fonts)
    files=render_all(data,dest,static=static,fonts=fonts)
    if dest.resolve()==(ROOT/'cards').resolve():
        (ROOT/'README.md').write_text(build_readme(data),encoding='utf-8')
    print(f'{len(files)} SVGs ({"estáticos" if static else "animados + fallback de movimento reduzido"}).')

if __name__=='__main__':
    main()
