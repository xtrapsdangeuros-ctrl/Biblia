"""Vídeos animados com o HyperFrames (HTML + GSAP gravado quadro a quadro pelo Chrome, licença Apache-2.0).

Mesmo roteiro YAML do animacao.py, com animação mais caprichada: os vegetais (desenhados em SVG) entram pulando,
respiram, piscam, gesticulam e mexem a boca enquanto falam; a legenda acende palavra por palavra; o cartão de
destaque cai do alto. As pessoas da Bíblia usam os desenhos do personagens.py. As vozes e a música são as mesmas
do animacao.py (Google TTS por personagem + trilha gerada por código, que abaixa quando alguém fala).

Precisa do programa "hyperframes" (Node 22): npm install -g hyperframes@<versão>. Sem ele, usar animacao.renderizar.
"""

import html
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import animacao as A
import personagens as P

log = logging.getLogger(__name__)

TINTA = "#2a1c16"
AMARELO = "#ffd23f"


def disponivel() -> bool:
    return bool(_comando())


def _comando() -> list[str] | None:
    if os.environ.get("HYPERFRAMES_CLI"):
        return os.environ["HYPERFRAMES_CLI"].split()
    caminho = shutil.which("hyperframes")
    return [caminho] if caminho else None


def _hex(cor) -> str:
    return "#%02x%02x%02x" % tuple(int(c) for c in cor[:3])


def _misturar(cor, alvo, f: float) -> str:
    return _hex([c + (a - c) * f for c, a in zip(cor[:3], alvo)])


# ---------------------------------------------------------------- personagens em SVG

def _rosto(dy: int, oculos: bool) -> str:
    lentes = (f'<circle cx="-34" cy="-10" r="36" fill="none" stroke="#1e1e1e" stroke-width="7"/>'
              f'<circle cx="34" cy="-10" r="36" fill="none" stroke="#1e1e1e" stroke-width="7"/>') if oculos else ""
    return f"""<g transform="translate(0,{dy})">
      <g class="olhos">
        <ellipse cx="-34" cy="-10" rx="20" ry="24" fill="#fff" stroke="{TINTA}" stroke-width="5"/>
        <ellipse cx="34" cy="-10" rx="20" ry="24" fill="#fff" stroke="{TINTA}" stroke-width="5"/>
        <circle cx="-30" cy="-6" r="10" fill="{TINTA}"/><circle cx="38" cy="-6" r="10" fill="{TINTA}"/>
        <circle cx="-26" cy="-11" r="4" fill="#fff"/><circle cx="42" cy="-11" r="4" fill="#fff"/>
      </g>
      <g class="palpebras" style="opacity:0">
        <path d="M-56 -8 Q-34 6 -12 -8" stroke="{TINTA}" stroke-width="7" fill="none" stroke-linecap="round"/>
        <path d="M12 -8 Q34 6 56 -8" stroke="{TINTA}" stroke-width="7" fill="none" stroke-linecap="round"/>
      </g>
      {lentes}
      <path class="boca-fechada" d="M-24 44 Q0 66 24 44" stroke="{TINTA}" stroke-width="7" fill="none" stroke-linecap="round"/>
      <g class="boca-aberta" style="opacity:0">
        <ellipse cx="0" cy="52" rx="22" ry="18" fill="#7a1a1e" stroke="{TINTA}" stroke-width="5"/>
        <ellipse cx="0" cy="62" rx="12" ry="6" fill="#ec7080"/>
      </g></g>"""


def _corpo_vegetal(p: P.Personagem) -> tuple[str, int]:
    """Desenho do corpo (sem rosto) e a altura do rosto, centrado em (0,0) num quadro de 600x660."""
    cor, escura, clara = _hex(p.cor), _misturar(p.cor, (0, 0, 0), 0.3), _misturar(p.cor, (255, 255, 255), 0.4)
    ex = p.extras
    if p.tipo == "tomate":
        bone = _hex(ex.get("bone", (40, 90, 170)))
        return (f'<ellipse cx="0" cy="0" rx="190" ry="170" fill="{cor}" stroke="{TINTA}" stroke-width="8"/>'
                f'<ellipse cx="-90" cy="-90" rx="40" ry="26" fill="{clara}" opacity=".8"/>'
                f'<path d="M-120 -150 Q0 -260 120 -150 L130 -120 L-130 -120 Z" fill="{bone}" stroke="{TINTA}" stroke-width="7"/>'
                f'<rect x="0" y="-132" width="190" height="22" rx="10" fill="{bone}" stroke="{TINTA}" stroke-width="6"/>', 20)
    if p.tipo == "repolho":
        gravata = _hex(ex.get("gravata", (150, 30, 40)))
        return (f'<ellipse cx="0" cy="0" rx="220" ry="200" fill="{cor}" stroke="{TINTA}" stroke-width="8"/>'
                f'<path d="M-150 -60 Q0 -190 150 -60" stroke="{escura}" stroke-width="10" fill="none"/>'
                f'<path d="M-110 -90 Q0 -160 110 -90" stroke="{escura}" stroke-width="10" fill="none"/>'
                f'<path d="M-40 -40 Q-70 -60 -88 -30" stroke="#5a3a20" stroke-width="14" fill="none" stroke-linecap="round"/>'
                f'<path d="M40 -40 Q70 -60 88 -30" stroke="#5a3a20" stroke-width="14" fill="none" stroke-linecap="round"/>'
                f'<path d="M-22 120 L22 120 L34 230 L0 262 L-34 230 Z" fill="{gravata}" stroke="{TINTA}" stroke-width="6"/>', 20)
    if p.tipo == "berinjela":
        return (f'<path d="M0 -230 C120 -230 150 -80 160 40 C175 200 90 260 0 260 C-90 260 -175 200 -160 40 '
                f'C-150 -80 -120 -230 0 -230 Z" fill="{cor}" stroke="{TINTA}" stroke-width="8"/>'
                f'<path d="M-70 -215 Q0 -320 70 -215 Q0 -190 -70 -215 Z" fill="#3f8a3a" stroke="{TINTA}" stroke-width="6"/>'
                f'<ellipse cx="-70" cy="-120" rx="20" ry="45" fill="{clara}" opacity=".7"/>', -10)
    if p.tipo == "cenoura":
        return (f'<path d="M-150 -170 Q0 -200 150 -170 Q120 120 0 290 Q-120 120 -150 -170 Z" fill="{cor}" '
                f'stroke="{TINTA}" stroke-width="8"/>'
                f'<path d="M-40 -180 Q-90 -300 -30 -310 Q0 -250 0 -185 Q20 -280 70 -300 Q90 -240 40 -180 Z" '
                f'fill="#4f9a3c" stroke="{TINTA}" stroke-width="6"/>'
                f'<path d="M-90 80 L-50 84 M60 150 L90 146 M-70 190 L-40 194" stroke="{escura}" stroke-width="7" '
                f'stroke-linecap="round"/>'
                f'<path d="M-130 -150 Q-170 -230 -60 -200" fill="#7b4a2a" stroke="{TINTA}" stroke-width="6"/>', -40)
    if p.tipo == "batata":
        return (f'<path d="M-180 -20 C-190 -150 -60 -200 30 -180 C170 -160 210 -40 190 60 C170 180 40 210 -60 190 '
                f'C-170 170 -175 90 -180 -20 Z" fill="{cor}" stroke="{TINTA}" stroke-width="8"/>'
                f'<circle cx="-110" cy="90" r="9" fill="{escura}"/><circle cx="120" cy="-90" r="8" fill="{escura}"/>'
                f'<circle cx="130" cy="110" r="10" fill="{escura}"/><circle cx="-60" cy="-130" r="7" fill="{escura}"/>', 10)
    if p.tipo == "alface":
        folhas = "".join(f'<ellipse cx="{x}" cy="{y}" rx="95" ry="80" fill="{cor}" stroke="{TINTA}" stroke-width="7"/>'
                         for x, y in ((-130, -60), (130, -60), (-110, 90), (110, 90), (0, -140)))
        return (folhas + f'<ellipse cx="0" cy="0" rx="170" ry="160" fill="{clara}" stroke="{TINTA}" stroke-width="8"/>'
                f'<path d="M0 -150 L0 150" stroke="{cor}" stroke-width="8" opacity=".6"/>', 10)
    return (f'<ellipse cx="0" cy="0" rx="180" ry="180" fill="{cor}" stroke="{TINTA}" stroke-width="8"/>', 10)


def svg_vegetal(p: P.Personagem) -> str:
    corpo, dy = _corpo_vegetal(p)
    cor = _hex(p.cor)
    pernas = (f'<g stroke="{TINTA}" stroke-width="12" stroke-linecap="round">'
              f'<line x1="-50" y1="150" x2="-60" y2="300"/><line x1="50" y1="150" x2="60" y2="300"/>'
              f'<ellipse cx="-70" cy="304" rx="32" ry="14" fill="{TINTA}"/>'
              f'<ellipse cx="70" cy="304" rx="32" ry="14" fill="{TINTA}"/></g>')
    bracos = "".join(
        f'<g class="braco-{lado}"><line x1="{s * 165}" y1="20" x2="{s * 250}" y2="140" stroke="{TINTA}" '
        f'stroke-width="12" stroke-linecap="round"/><circle cx="{s * 252}" cy="146" r="18" fill="{cor}" '
        f'stroke="{TINTA}" stroke-width="5"/></g>' for lado, s in (("e", -1), ("d", 1)))
    return (f'<svg viewBox="-300 -330 600 660" width="100%" height="100%">'
            f'<ellipse cx="0" cy="318" rx="170" ry="20" fill="rgba(0,0,0,.18)"/>'
            f'<g class="corpo">{pernas}{bracos}{corpo}{_rosto(dy, bool(p.extras.get("oculos")))}</g></svg>')


def _tem_svg(p: P.Personagem) -> bool:
    return p.tipo in ("tomate", "repolho", "berinjela", "cenoura", "batata", "alface", "pessoa")


OMBRO_PESSOA = (100, -40)


def svg_pessoa(p: P.Personagem) -> str:
    """Pessoa da Bíblia em SVG: cabeça grande, olhos com brilho, sobrancelhas, túnica com dobras e cinto,
    mangas, sandálias; opcionais: manto (faixa), barba, cabelo, lenço/véu, coroa, cajado e funda."""
    x = p.extras
    cor = lambda chave, padrao: tuple(x.get(chave) or padrao)
    pele = cor("pele", (225, 180, 140))
    roupa = cor("roupa", (180, 150, 110))
    cabelo = cor("cabelo", (60, 40, 30))
    P_, Ps = _hex(pele), _misturar(pele, (90, 40, 20), 0.25)
    R, Rs, Rc = _hex(roupa), _misturar(roupa, (0, 0, 0), 0.25), _misturar(roupa, (255, 255, 255), 0.25)
    C = _hex(cabelo)
    T = TINTA
    ox, oy = OMBRO_PESSOA
    # pernas e sandálias
    pernas = "".join(
        f'<rect x="{sx - 17}" y="240" width="34" height="58" rx="14" fill="{P_}" stroke="{T}" stroke-width="6"/>'
        f'<path d="M{sx - 36} 296 Q{sx} 280 {sx + 40} 296 L{sx + 40} 308 L{sx - 36} 308 Z" fill="#7a4a26" stroke="{T}" stroke-width="6"/>'
        f'<line x1="{sx - 14}" y1="276" x2="{sx + 16}" y2="290" stroke="#7a4a26" stroke-width="7"/>'
        for sx in (-48, 48))
    # túnica
    corpo = (f'<path d="M-{ox} {oy - 10} Q-128 110 -158 286 Q0 304 158 286 Q128 110 {ox} {oy - 10} Q0 {oy - 38} -{ox} {oy - 10} Z" '
             f'fill="{R}" stroke="{T}" stroke-width="8" stroke-linejoin="round"/>'
             f'<path d="M-60 120 Q-72 200 -88 280 M58 130 Q70 210 84 282 M0 140 L4 290" stroke="{Rs}" stroke-width="7" '
             f'fill="none" stroke-linecap="round" opacity=".8"/>'
             f'<path d="M-118 74 Q0 96 118 74 L121 102 Q0 124 -121 102 Z" fill="#8a5a30" stroke="{T}" stroke-width="6"/>'
             f'<path d="M-26 {oy - 22} L0 10 L26 {oy - 22} Z" fill="{Ps}" stroke="{T}" stroke-width="5" stroke-linejoin="round"/>')
    if x.get("manto"):
        M = _hex(x["manto"])
        corpo += (f'<path d="M-{ox - 10} {oy - 16} Q-20 30 70 284 L128 284 Q40 40 -{ox - 60} {oy - 28} Z" fill="{M}" '
                  f'stroke="{T}" stroke-width="7" stroke-linejoin="round"/>')
    # braços (mangas largas + mão); o direito segura o cajado ou a funda
    def braco(lado, s):
        hx, hy = s * 150, 128
        extra = ""
        if lado == "d" and x.get("cajado"):
            extra = (f'<path d="M{hx + 6} 300 L{hx + 14} -170 Q{hx + 16} -230 {hx + 58} -226 Q{hx + 92} -220 {hx + 82} -186" '
                     f'stroke="{T}" stroke-width="22" fill="none" stroke-linecap="round"/>'
                     f'<path d="M{hx + 6} 300 L{hx + 14} -170 Q{hx + 16} -230 {hx + 58} -226 Q{hx + 92} -220 {hx + 82} -186" '
                     f'stroke="#8b5a2b" stroke-width="11" fill="none" stroke-linecap="round"/>')
        if lado == "d" and x.get("funda"):
            extra += (f'<path d="M{hx} {hy} Q{hx + 30} {hy + 70} {hx + 18} {hy + 120} M{hx} {hy} Q{hx - 12} {hy + 70} {hx + 6} {hy + 120}" '
                      f'stroke="#6b4a2a" stroke-width="5" fill="none"/>'
                      f'<ellipse cx="{hx + 12}" cy="{hy + 126}" rx="17" ry="11" fill="#7a5532" stroke="{T}" stroke-width="5"/>'
                      f'<circle cx="{hx + 12}" cy="{hy + 122}" r="7" fill="#9a9a9a"/>')
        manga = f"M{s * (ox - 6)} {oy} Q{s * 150} {oy + 40} {s * 158} {hy - 24}"
        return (f'<g class="braco-{lado}">{extra}'
                f'<path d="{manga}" stroke="{T}" stroke-width="52" fill="none" stroke-linecap="round"/>'
                f'<path d="{manga}" stroke="{R}" stroke-width="38" fill="none" stroke-linecap="round"/>'
                f'<circle cx="{hx}" cy="{hy}" r="24" fill="{P_}" stroke="{T}" stroke-width="6"/></g>')
    bracos = braco("e", -1) + braco("d", 1)
    # cabeça
    hy = -150
    atras = ""
    if x.get("lenco"):
        L = _hex(x["lenco"])
        atras = (f'<path d="M-112 {hy - 30} Q-130 {hy + 90} -120 {hy + 150} L120 {hy + 150} Q130 {hy + 90} 112 {hy - 30} Z" '
                 f'fill="{_misturar(x["lenco"], (0, 0, 0), 0.15)}" stroke="{T}" stroke-width="7"/>')
    cabelo_svg = (f'<path d="M-94 {hy - 4} Q-100 {hy - 104} 0 {hy - 108} Q100 {hy - 104} 94 {hy - 4} '
                  f'Q78 {hy - 58} 30 {hy - 66} Q10 {hy - 40} -20 {hy - 62} Q-72 {hy - 58} -94 {hy - 4} Z" '
                  f'fill="{C}" stroke="{T}" stroke-width="7" stroke-linejoin="round"/>')
    if x.get("lenco"):
        L = _hex(x["lenco"])
        cabelo_svg = (f'<path d="M-104 {hy + 10} Q-112 {hy - 112} 0 {hy - 114} Q112 {hy - 112} 104 {hy + 10} '
                      f'Q82 {hy - 62} 0 {hy - 70} Q-82 {hy - 62} -104 {hy + 10} Z" fill="{L}" stroke="{T}" stroke-width="7"/>'
                      f'<path d="M-86 {hy - 52} Q0 {hy - 86} 86 {hy - 52}" stroke="{_misturar(x["lenco"], (0, 0, 0), 0.25)}" '
                      f'stroke-width="8" fill="none"/>')
    barba = ""
    if x.get("barba"):
        B = _hex(x["barba"])
        barba = (f'<path d="M-90 {hy - 4} Q-96 {hy + 104} 0 {hy + 122} Q96 {hy + 104} 90 {hy - 4} '
                 f'Q66 {hy + 46} 0 {hy + 40} Q-66 {hy + 46} -90 {hy - 4} Z" fill="{B}" stroke="{T}" stroke-width="7" '
                 f'stroke-linejoin="round"/>'
                 f'<path d="M-40 {hy + 36} Q0 {hy + 22} 40 {hy + 36}" stroke="{B}" stroke-width="16" stroke-linecap="round" fill="none"/>')
    coroa = ""
    if x.get("coroa"):
        coroa = (f'<path d="M-70 {hy - 82} L-74 {hy - 140} L-38 {hy - 110} L0 {hy - 154} L38 {hy - 110} L74 {hy - 140} L70 {hy - 82} Z" '
                 f'fill="#f2c335" stroke="{T}" stroke-width="7" stroke-linejoin="round"/>'
                 f'<circle cx="0" cy="{hy - 100}" r="9" fill="#d23a3a"/><circle cx="-44" cy="{hy - 94}" r="6" fill="#3a7bd2"/>'
                 f'<circle cx="44" cy="{hy - 94}" r="6" fill="#3a7bd2"/>')
    sobr = _misturar(x.get("barba") or cabelo, (0, 0, 0), 0.2)
    rosto = (f'<g class="sobrancelhas"><path d="M-56 {hy - 42} Q-36 {hy - 54} -16 {hy - 44}" stroke="{sobr}" stroke-width="9" '
             f'fill="none" stroke-linecap="round"/><path d="M16 {hy - 44} Q36 {hy - 54} 56 {hy - 42}" stroke="{sobr}" '
             f'stroke-width="9" fill="none" stroke-linecap="round"/></g>'
             f'<g class="olhos"><ellipse cx="-34" cy="{hy - 12}" rx="17" ry="21" fill="#fff" stroke="{T}" stroke-width="5"/>'
             f'<ellipse cx="34" cy="{hy - 12}" rx="17" ry="21" fill="#fff" stroke="{T}" stroke-width="5"/>'
             f'<circle cx="-31" cy="{hy - 8}" r="10" fill="{T}"/><circle cx="37" cy="{hy - 8}" r="10" fill="{T}"/>'
             f'<circle cx="-27" cy="{hy - 13}" r="4" fill="#fff"/><circle cx="41" cy="{hy - 13}" r="4" fill="#fff"/></g>'
             f'<g class="palpebras" style="opacity:0"><path d="M-52 {hy - 10} Q-34 {hy + 2} -16 {hy - 10}" stroke="{T}" '
             f'stroke-width="7" fill="none" stroke-linecap="round"/><path d="M16 {hy - 10} Q34 {hy + 2} 52 {hy - 10}" '
             f'stroke="{T}" stroke-width="7" fill="none" stroke-linecap="round"/></g>'
             f'<path d="M-4 {hy + 4} Q8 {hy + 22} -6 {hy + 26}" stroke="{Ps}" stroke-width="6" fill="none" stroke-linecap="round"/>'
             f'<ellipse cx="-58" cy="{hy + 20}" rx="16" ry="10" fill="#f08a8a" opacity=".35"/>'
             f'<ellipse cx="58" cy="{hy + 20}" rx="16" ry="10" fill="#f08a8a" opacity=".35"/>'
             f'<path class="boca-fechada" d="M-20 {hy + 46} Q0 {hy + 62} 20 {hy + 46}" stroke="{T}" stroke-width="7" '
             f'fill="none" stroke-linecap="round"/>'
             f'<g class="boca-aberta" style="opacity:0"><ellipse cx="0" cy="{hy + 52}" rx="18" ry="15" fill="#7a1a1e" '
             f'stroke="{T}" stroke-width="5"/><ellipse cx="0" cy="{hy + 60}" rx="10" ry="5" fill="#ec7080"/></g>')
    cabeca = (f'<g class="cabeca">{atras}'
              f'<circle cx="-92" cy="{hy + 6}" r="18" fill="{P_}" stroke="{T}" stroke-width="6"/>'
              f'<circle cx="92" cy="{hy + 6}" r="18" fill="{P_}" stroke="{T}" stroke-width="6"/>'
              f'<rect x="-24" y="{hy + 70}" width="48" height="50" fill="{P_}" stroke="{T}" stroke-width="6"/>'
              f'<ellipse cx="0" cy="{hy}" rx="92" ry="96" fill="{P_}" stroke="{T}" stroke-width="8"/>'
              f'{cabelo_svg}{coroa}{barba}{rosto}</g>')
    return (f'<svg viewBox="-300 -330 600 660" width="100%" height="100%">'
            f'<ellipse cx="0" cy="314" rx="150" ry="18" fill="rgba(0,0,0,.18)"/>'
            f'<g class="corpo">{pernas}{corpo}{bracos}{cabeca}</g></svg>')




# ---------------------------------------------------------------- composição

def _legenda_blocos(texto: str, por: int = 4) -> list[list[str]]:
    p = texto.split()
    return [p[i:i + por] for i in range(0, len(p), por)]


def composicao(rot: A.Roteiro, total: float, pasta: Path, audio: str) -> str:
    """Monta o index.html (e os desenhos em pasta/assets). As falas já precisam ter início e duração."""
    w, h = rot.tamanho
    short = rot.formato == "short"
    assets = pasta / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    clips, js = [], []
    esc = html.escape

    # cenários (um por cena; o primeiro já aparece no quadro 0, que vira a miniatura dos players)
    for i, c in enumerate(rot.cenas):
        arq = assets / f"cenario_{i}.png"
        A.cenario(c.cenario, w, h).save(arq)
        ini = 0 if i == 0 else round(c.inicio - 0.2, 3)
        fim = total if i == len(rot.cenas) - 1 else rot.cenas[i + 1].inicio - 0.2
        clips.append(f'<img id="fundo{i}" class="clip fundo" src="assets/{arq.name}" data-start="{ini}" '
                     f'data-duration="{round(fim - ini, 3)}" data-track-index="0" style="z-index:0">')
        if i:
            clips.append(f'<div id="corte{i}" class="clip corte" data-start="{ini}" data-duration="0.5" '
                         f'data-track-index="10" style="z-index:50"><i></i></div>')
            js.append(f'tl.fromTo("#corte{i} i", {{opacity: 0.85}}, {{opacity: 0, duration: 0.45, ease: "power2.out"}}, {ini});')

    # gancho: texto grande antes da primeira fala
    fg = next((f for c in rot.cenas for f in c.falas if f.gancho), None)
    primeira = (fg.inicio + fg.duracao + 0.25) if fg else (rot.cenas[0].falas[0].inicio if rot.cenas and rot.cenas[0].falas else 2.0)
    if rot.gancho:
        clips.append(f'<div id="gancho" class="clip" data-start="0" data-duration="{primeira:.2f}" data-track-index="5" '
                     f'style="z-index:30"><div class="gancho-txt">{esc(rot.gancho.upper())}</div></div>')
        js.append('tl.from("#gancho .gancho-txt", {scale: 0.85, rotation: -4, duration: 0.45, ease: "back.out(2.2)"}, 0);')
        js.append(f'tl.to("#gancho .gancho-txt", {{scale: 1.05, duration: 0.25, yoyo: true, repeat: 1, ease: "sine.inOut"}}, 0.6);')
        js.append(f'tl.to("#gancho .gancho-txt", {{y: -60, opacity: 0, duration: 0.3, ease: "power2.in"}}, {max(0.2, primeira - 0.32):.2f});')

    # personagens
    alt_base = h * (0.30 if short else 0.42)
    chao = h * (0.672 if short else 0.9)
    leg_top = 400 * w / 1080 if short else h * 0.80
    alt_max = chao - leg_top - 230 * w / 1080 if short else h * 0.62
    pid = 0
    for ci, c in enumerate(rot.cenas):
        ini = round(c.inicio - 0.2, 3) if ci else 0.0
        dur = round(c.fim - ini + 0.2, 3)
        nomes = [n for n in c.personagens if n in rot.elenco]
        xs = A._posicoes(len(nomes), w, h, short)
        for k, (nome, x) in enumerate(zip(nomes, xs)):
            pid += 1
            el = f"p{pid}"
            p = rot.elenco[nome]
            # o Golias (tamanho 1.6) cresce, mas sem cobrir a legenda (que fica acima de todos)
            alt = min(alt_base * float(p.extras.get("tamanho", 1)), alt_max)
            larg = min(alt / 1.1, w * 0.48)
            if p.tipo == "pessoa":
                miolo = svg_pessoa(p)
            elif _tem_svg(p):
                miolo = svg_vegetal(p)
            else:
                poses = P.poses(p, int(alt))
                for (boca, olhos), img in poses.items():
                    img.save(assets / f"{nome}_{int(boca)}{int(olhos)}.png")
                larg = min(poses[(False, True)].width, w * 0.48)
                miolo = (f'<i class="olhos"></i><img class="boca-fechada" src="assets/{nome}_01.png">'
                         f'<img class="boca-aberta" src="assets/{nome}_11.png" style="opacity:0">'
                         f'<img class="palpebras" src="assets/{nome}_00.png" style="opacity:0">')
            clips.append(f'<div id="{el}" class="clip personagem" data-start="{ini}" data-duration="{dur}" '
                         f'data-track-index="{1 + k}" style="z-index:{10 + k};left:{x - larg / 2:.0f}px;'
                         f'top:{chao - alt:.0f}px;width:{larg:.0f}px;height:{alt:.0f}px"><div class="rig">{miolo}</div></div>')
            lado = -1 if x < w / 2 else 1
            entra = ini + (0.2 if ci else 0.05)
            js.append(f'tl.from("#{el} .rig", {{x: {lado * w * 0.65:.0f}, rotation: {lado * 12}, duration: 0.55, ease: "back.out(1.6)"}}, {entra:.2f});')
            js.append(f'tl.fromTo("#{el} .rig", {{scaleY: 0.86, scaleX: 1.1}}, {{scaleY: 1, scaleX: 1, duration: 0.35, ease: "elastic.out(1.2,0.4)"}}, {entra + 0.5:.2f});')
            if _tem_svg(p):
                js.append(f'tl.to("#{el} .corpo", {{scaleY: 1.025, transformOrigin: "50% 100%", duration: 0.8, yoyo: true, '
                          f'repeat: {max(1, int(dur / 0.8) - 2)}, ease: "sine.inOut"}}, {entra + 0.9:.2f});')
            t = entra + 1.3 + k * 0.7
            while t < ini + dur - 0.3:
                js.append(f'tl.set("#{el} .olhos", {{opacity: 0}}, {t:.2f}); tl.set("#{el} .palpebras", {{opacity: 1}}, {t:.2f});')
                js.append(f'tl.set("#{el} .olhos", {{opacity: 1}}, {t + 0.13:.2f}); tl.set("#{el} .palpebras", {{opacity: 0}}, {t + 0.13:.2f});')
                t += 2.9 + k * 0.6
            for f in c.falas:
                if f.quem != nome:
                    continue
                t0, t1 = f.inicio, f.inicio + f.duracao
                js.append(f'tl.to("#{el} .rig", {{y: -28, duration: 0.14, yoyo: true, repeat: 1, ease: "power2.out"}}, {t0:.2f});')
                if _tem_svg(p):
                    ox, oy = OMBRO_PESSOA if p.tipo == "pessoa" else (165, 20)
                    braco, origem = ("d", f"{ox} {oy}") if lado < 0 else ("e", f"{-ox} {oy}")
                    if p.tipo == "pessoa":   # a cabeça acompanha a fala: inclina e as sobrancelhas sobem
                        js.append(f'tl.to("#{el} .cabeca", {{rotation: {lado * -5}, svgOrigin: "0 -40", duration: 0.3, '
                                  f'yoyo: true, repeat: 1, ease: "sine.inOut"}}, {t0:.2f});')
                        js.append(f'tl.to("#{el} .sobrancelhas", {{y: -7, duration: 0.18, yoyo: true, repeat: 1, '
                                  f'ease: "power2.out"}}, {t0 + 0.05:.2f});')
                    vezes = max(1, int(f.duracao / 0.5)) | 1
                    js.append(f'tl.to("#{el} .braco-{braco}", {{rotation: {-lado * 35}, svgOrigin: "{origem}", '
                              f'duration: 0.25, yoyo: true, repeat: {vezes}, ease: "sine.inOut"}}, {t0 + 0.1:.2f});')
                t, aberta = t0, True
                while t < t1 - 0.05:
                    js.append(f'tl.set("#{el} .boca-aberta", {{opacity: {int(aberta)}}}, {t:.2f}); '
                              f'tl.set("#{el} .boca-fechada", {{opacity: {int(not aberta)}}}, {t:.2f});')
                    aberta = not aberta
                    t += 0.11
                js.append(f'tl.set("#{el} .boca-aberta", {{opacity: 0}}, {t1:.2f}); tl.set("#{el} .boca-fechada", {{opacity: 1}}, {t1:.2f});')
        if c.destaque:
            pid += 1
            ini_d = max(c.inicio, primeira) if rot.gancho and ci == 0 else c.inicio   # depois do gancho
            dur_d = min(3.4, c.fim - ini_d)
            clips.append(f'<div id="d{pid}" class="clip destaque" data-start="{ini_d:.2f}" data-duration="{dur_d:.2f}" '
                         f'data-track-index="6" style="z-index:35"><div class="cartao">{esc(c.destaque)}</div></div>')
            js.append(f'tl.from("#d{pid} .cartao", {{y: -300, rotation: -8, duration: 0.5, ease: "back.out(1.8)"}}, {ini_d:.2f});')
            js.append(f'tl.to("#d{pid} .cartao", {{y: -300, opacity: 0, duration: 0.3, ease: "power2.in"}}, {ini_d + dur_d - 0.35:.2f});')

    # legenda karaokê e nome de quem fala
    gid = 0
    for c in rot.cenas:
        for f in c.falas:
            if f.gancho:   # o gancho já está escrito grande na tela
                continue
            blocos = _legenda_blocos(f.texto)
            pesos = [sum(len(x) + 1 for x in b) for b in blocos]
            t = f.inicio
            for b, peso in zip(blocos, pesos):
                gid += 1
                dur_b = f.duracao * peso / sum(pesos)
                spans = " ".join(f'<span class="w" id="g{gid}w{i}">{esc(x)}</span>' for i, x in enumerate(b))
                clips.append(f'<div id="g{gid}" class="clip legenda" data-start="{t:.2f}" data-duration="{dur_b:.2f}" '
                             f'data-track-index="7" style="z-index:40">{spans}</div>')
                js.append(f'tl.from("#g{gid} .w", {{y: 40, opacity: 0, scale: 0.7, duration: 0.18, stagger: 0.04, ease: "back.out(2)"}}, {t:.2f});')
                tw = t + 0.2
                for i, x in enumerate(b):
                    dw = max(0.12, (dur_b - 0.2) * (len(x) + 1) / peso)
                    js.append(f'tl.to("#g{gid}w{i}", {{color: "{AMARELO}", duration: 0.06}}, {tw:.2f}); '
                              f'tl.to("#g{gid}w{i}", {{color: "#ffffff", duration: 0.06}}, {tw + dw - 0.06:.2f});')
                    tw += dw
                t += dur_b
            p = rot.elenco.get(f.quem)
            if p:
                gid += 1
                clips.append(f'<div id="n{gid}" class="clip quem" data-start="{f.inicio:.2f}" data-duration="{f.duracao:.2f}" '
                             f'data-track-index="8" style="z-index:40">{esc(p.rotulo)}</div>')

    s = w / 1080 if short else h / 1080
    css = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {w}px; height: {h}px; overflow: hidden; background: #f3e7cf; }}
#root {{ position: relative; width: 100%; height: 100%; font-family: "Archivo Black"; overflow: hidden; }}
.fundo {{ position: absolute; left: 0; top: 0; width: {w}px; height: {h}px; }}
.corte {{ position: absolute; inset: 0; }}
.corte i {{ position: absolute; inset: 0; background: #000; }}
.personagem {{ position: absolute; }}
.rig {{ position: relative; width: 100%; height: 100%; transform-origin: 50% 100%; }}
.rig img {{ position: absolute; left: 0; bottom: 0; width: 100%; }}
#gancho {{ position: absolute; left: {w * 0.12:.0f}px; right: {w * 0.12:.0f}px; top: {h * (0.10 if short else 0.08):.0f}px; text-align: center; }}
.gancho-txt {{ font-size: {(104 if len(rot.gancho) <= 18 else 84 if len(rot.gancho) <= 30 else 70) * s:.0f}px; line-height: 1.02; color: {AMARELO}; -webkit-text-stroke: {10 * s:.0f}px {TINTA};
  paint-order: stroke fill; text-shadow: 0 {12 * s:.0f}px 0 {TINTA}; }}
.destaque {{ position: absolute; left: {w * 0.08:.0f}px; right: {w * 0.08:.0f}px; top: {h * (0.088 if short else 0.08):.0f}px;
  display: flex; justify-content: center; }}
.cartao {{ background: #fffaf0; border: {8 * s:.0f}px solid {TINTA}; border-radius: {28 * s:.0f}px; padding: {26 * s:.0f}px {40 * s:.0f}px;
  font-family: "Playfair Display"; font-weight: 700; font-size: {72 * s:.0f}px; color: #3c2415; text-align: center;
  box-shadow: 0 {14 * s:.0f}px 0 {TINTA}; }}
.legenda {{ position: absolute; left: {w * 0.07:.0f}px; right: {w * 0.07:.0f}px; top: {leg_top:.0f}px; text-align: center;
  font-size: {92 * s if short else 70 * s:.0f}px; line-height: 1.1; color: #fff; -webkit-text-stroke: {9 * s:.0f}px {TINTA};
  paint-order: stroke fill; }}
.legenda .w {{ display: inline-block; }}
.quem {{ position: absolute; left: 0; right: 0; top: {leg_top - 80 * s:.0f}px; text-align: center; font-family: Nunito;
  font-weight: 800; font-size: {46 * s:.0f}px; color: {TINTA}; }}"""
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="UTF-8" /><meta name="viewport" content="width={w}, height={h}" />
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>{css}
</style></head>
<body><div id="root" data-composition-id="main" data-start="0" data-duration="{total:.2f}" data-width="{w}" data-height="{h}">
{chr(10).join(clips)}
<audio id="trilha" src="assets/{audio}" data-start="0" data-duration="{total:.2f}" data-track-index="9"></audio>
</div>
<script>
const tl = gsap.timeline({{ paused: true }});
{chr(10).join(js)}
window.__timelines["main"] = tl;
tl.seek(0);
</script></body></html>"""


def renderizar(rot: A.Roteiro, destino: Path, chave_tts: str | None = None, musica: Path | None = None,
               fps: int = 30) -> Path:
    cmd = _comando()
    if not cmd:
        raise RuntimeError("programa hyperframes não instalado")
    destino.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        total = A.preparar_vozes(rot, tmp, chave_tts)
        audio = A.mixar_audio(rot, tmp, total, musica)
        proj = tmp / "projeto"
        (proj / "assets").mkdir(parents=True)
        shutil.copy(audio, proj / "assets" / "trilha.m4a")
        (proj / "index.html").write_text(composicao(rot, total, proj, "trilha.m4a"), encoding="utf-8")
        env = {**os.environ, "DO_NOT_TRACK": "1", "HYPERFRAMES_NO_PREVIEW_DISCOVERY": "1"}
        r = subprocess.run([*cmd, "render", "--output", str(destino.resolve()), "--fps", str(fps), "--crf", "23", "--quiet"],
                           cwd=proj, capture_output=True, text=True, env=env)
        if r.returncode != 0 or not destino.exists():
            raise RuntimeError(f"hyperframes falhou: {(r.stderr or r.stdout)[-1500:]}")
    return destino
