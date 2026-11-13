"""Personagens desenhados por código: vegetais (canal trabalhista) e pessoas da Bíblia.

Cada personagem vira 4 "poses" (boca aberta/fechada x olhos abertos/fechados), desenhadas em dobro do tamanho e
reduzidas uma vez só (bordas lisas). Na animação o robô só cola a pose certa em cada quadro.
"""

from dataclasses import dataclass, field

from PIL import Image, ImageDraw

ESCALA = 2   # desenha em dobro e reduz: contornos sem serrilhado
CONTORNO = (40, 28, 22)


@dataclass
class Personagem:
    nome: str                 # chave usada no roteiro
    rotulo: str               # nome que aparece na tela
    tipo: str                 # tomate, cenoura, repolho, berinjela, batata, alface, pessoa
    voz: str = "pt-BR-Chirp3-HD-Charon"
    cor: tuple = (220, 60, 50)
    extras: dict = field(default_factory=dict)   # pessoa: pele, roupa, barba, cabelo, cajado, coroa, altura


# ---------------------------------------------------------------- elenco pronto

ELENCO = {
    # canal trabalhista: a turma da horta
    "tomatinho": Personagem("tomatinho", "Tomatinho", "tomate", "pt-BR-Chirp3-HD-Puck", (226, 58, 48),
                            {"bone": (40, 90, 170)}),
    "dona_cenoura": Personagem("dona_cenoura", "Dona Cenoura", "cenoura", "pt-BR-Chirp3-HD-Kore", (240, 130, 40)),
    "seu_repolho": Personagem("seu_repolho", "Seu Repolho", "repolho", "pt-BR-Chirp3-HD-Fenrir", (120, 175, 80),
                              {"gravata": (150, 30, 40), "bigode": True}),
    "dra_berinjela": Personagem("dra_berinjela", "Dra. Berinjela", "berinjela", "pt-BR-Chirp3-HD-Aoede",
                                (110, 50, 130), {"oculos": True}),
    "batatinha": Personagem("batatinha", "Batatinha", "batata", "pt-BR-Chirp3-HD-Leda", (205, 160, 95)),
    "alface": Personagem("alface", "Alface", "alface", "pt-BR-Chirp3-HD-Orus", (130, 200, 90)),
}


def pessoa(nome: str, rotulo: str, voz: str = "pt-BR-Chirp3-HD-Charon", **extras) -> Personagem:
    """Pessoa da Bíblia: pele, roupa, manto, barba (cor), cabelo (cor), cajado, coroa, funda, altura (1 = normal)."""
    return Personagem(nome, rotulo, "pessoa", voz, extras.get("roupa", (180, 150, 110)), extras)


# ---------------------------------------------------------------- desenho

def _escurecer(cor, f=0.75):
    return tuple(int(c * f) for c in cor[:3])


def _clarear(cor, f=0.35):
    return tuple(int(c + (255 - c) * f) for c in cor[:3])


def _rosto(d: ImageDraw.ImageDraw, cx: float, cy: float, s: float, boca: bool, olhos: bool, extras: dict):
    """Olhos grandes, sobrancelhas e boca (aberta = falando)."""
    dx, r = 22 * s, 13 * s
    for lado in (-1, 1):
        x = cx + lado * dx
        if olhos:
            d.ellipse((x - r, cy - r * 1.2, x + r, cy + r * 1.2), fill="white", outline=CONTORNO, width=int(3 * s))
            d.ellipse((x - r * 0.5, cy - r * 0.4, x + r * 0.5, cy + r * 0.6), fill=CONTORNO)
            d.ellipse((x - r * 0.25, cy - r * 0.25, x, cy), fill="white")
        else:
            d.arc((x - r, cy - r * 0.6, x + r, cy + r * 0.8), 200, 340, fill=CONTORNO, width=int(4 * s))
    if extras.get("oculos"):
        for lado in (-1, 1):
            x = cx + lado * dx
            d.ellipse((x - r * 1.5, cy - r * 1.5, x + r * 1.5, cy + r * 1.5), outline=(30, 30, 30), width=int(4 * s))
        d.line((cx - dx + r * 1.5, cy, cx + dx - r * 1.5, cy), fill=(30, 30, 30), width=int(4 * s))
    by = cy + 34 * s
    if boca:
        d.ellipse((cx - 13 * s, by - 9 * s, cx + 13 * s, by + 13 * s), fill=(120, 25, 30), outline=CONTORNO,
                  width=int(3 * s))
        d.ellipse((cx - 7 * s, by + 3 * s, cx + 7 * s, by + 11 * s), fill=(235, 110, 120))
    else:
        d.arc((cx - 16 * s, by - 14 * s, cx + 16 * s, by + 8 * s), 20, 160, fill=CONTORNO, width=int(4 * s))
    if extras.get("bigode"):
        for lado in (-1, 1):
            d.chord((cx + (lado * 24 - 18) * s, by - 20 * s, cx + (lado * 24 + 18) * s, by + 2 * s), 180, 360,
                    fill=(70, 50, 35))


def _bracos_pernas(d, cx, base, larg, s, cor):
    for lado in (-1, 1):
        d.line((cx + lado * 18 * s, base - 4 * s, cx + lado * 22 * s, base + 48 * s), fill=CONTORNO, width=int(7 * s))
        d.ellipse((cx + lado * 22 * s - 13 * s, base + 40 * s, cx + lado * 22 * s + 15 * s, base + 54 * s),
                  fill=CONTORNO)
        ombro_y = base - 70 * s
        d.line((cx + lado * larg * 0.92, ombro_y, cx + lado * (larg + 30 * s), ombro_y + 50 * s), fill=CONTORNO,
               width=int(7 * s))
        d.ellipse((cx + lado * (larg + 30 * s) - 9 * s, ombro_y + 42 * s, cx + lado * (larg + 30 * s) + 9 * s,
                   ombro_y + 60 * s), fill=_escurecer(cor, 0.9), outline=CONTORNO, width=int(2 * s))


def _vegetal(p: Personagem, d: ImageDraw.ImageDraw, w: int, h: int, boca: bool, olhos: bool):
    s = ESCALA
    cx, base = w / 2, h - 60 * s
    cor, x = p.cor, p.extras
    if p.tipo == "tomate":
        r = 95 * s
        cy = base - r
        _bracos_pernas(d, cx, base, r, s, cor)
        d.ellipse((cx - r * 1.05, cy - r, cx + r * 1.05, cy + r), fill=cor, outline=CONTORNO, width=int(5 * s))
        d.ellipse((cx - r * 0.6, cy - r * 0.75, cx - r * 0.25, cy - r * 0.45), fill=_clarear(cor, 0.5))
        for ang in range(5):   # folhinhas
            import math
            a = math.radians(-90 + (ang - 2) * 35)
            d.polygon([(cx, cy - r * 0.95), (cx + math.cos(a) * 45 * s, cy - r * 0.95 + math.sin(a) * 30 * s - 8 * s),
                       (cx + math.cos(a) * 20 * s, cy - r * 0.85)], fill=(60, 140, 50), outline=CONTORNO)
        if x.get("bone"):
            d.chord((cx - r * 0.75, cy - r * 1.15, cx + r * 0.75, cy - r * 0.35), 180, 360, fill=x["bone"],
                    outline=CONTORNO, width=int(4 * s))
            d.rectangle((cx, cy - r * 0.78, cx + r * 1.0, cy - r * 0.68), fill=x["bone"], outline=CONTORNO)
        _rosto(d, cx, cy - 5 * s, s, boca, olhos, x)
    elif p.tipo == "cenoura":
        larg, alt = 80 * s, 260 * s
        topo = base - alt
        _bracos_pernas(d, cx, base - 20 * s, larg * 0.7, s, cor)
        for i in (-1, 0, 1):
            d.polygon([(cx + i * 20 * s, topo + 10 * s), (cx + i * 55 * s, topo - 70 * s),
                       (cx + i * 30 * s + 10 * s, topo + 5 * s)], fill=(70, 160, 60), outline=CONTORNO)
        d.polygon([(cx - larg, topo), (cx + larg, topo), (cx + 12 * s, base), (cx - 12 * s, base)], fill=cor,
                  outline=CONTORNO, width=int(5 * s))
        d.ellipse((cx - larg, topo - 25 * s, cx + larg, topo + 25 * s), fill=cor, outline=CONTORNO, width=int(5 * s))
        for k in range(4):
            yy = topo + (60 + 45 * k) * s
            d.line((cx - larg * (0.7 - 0.15 * k), yy, cx - larg * (0.35 - 0.1 * k), yy), fill=_escurecer(cor),
                   width=int(4 * s))
        _rosto(d, cx, topo + 55 * s, s * 0.9, boca, olhos, x)
    elif p.tipo == "repolho":
        r = 120 * s
        cy = base - r
        _bracos_pernas(d, cx, base, r, s, cor)
        d.ellipse((cx - r * 1.1, cy - r, cx + r * 1.1, cy + r), fill=cor, outline=CONTORNO, width=int(5 * s))
        for k, f in enumerate((0.9, 0.7, 0.5)):
            d.arc((cx - r * f, cy - r * f, cx + r * f, cy + r * f), 200 + k * 10, 340 - k * 10,
                  fill=_escurecer(cor, 0.7), width=int(5 * s))
        if x.get("gravata"):
            gy = cy + r * 0.45
            d.polygon([(cx - 12 * s, gy), (cx + 12 * s, gy), (cx + 20 * s, gy + 70 * s), (cx, gy + 90 * s),
                       (cx - 20 * s, gy + 70 * s)], fill=x["gravata"], outline=CONTORNO)
        _rosto(d, cx, cy - 15 * s, s * 1.1, boca, olhos, x)
    elif p.tipo == "berinjela":
        larg, alt = 85 * s, 270 * s
        topo = base - alt
        _bracos_pernas(d, cx, base, larg, s, cor)
        d.ellipse((cx - larg * 0.8, topo, cx + larg * 0.8, topo + alt * 0.6), fill=cor, outline=CONTORNO,
                  width=int(5 * s))
        d.ellipse((cx - larg, topo + alt * 0.3, cx + larg, base), fill=cor, outline=CONTORNO, width=int(5 * s))
        d.rectangle((cx - larg * 0.75, topo + alt * 0.3, cx + larg * 0.75, topo + alt * 0.6), fill=cor)
        d.polygon([(cx - 45 * s, topo + 15 * s), (cx + 45 * s, topo + 15 * s), (cx + 10 * s, topo - 40 * s),
                   (cx - 10 * s, topo - 40 * s)], fill=(70, 130, 60), outline=CONTORNO)
        d.ellipse((cx - larg * 0.5, topo + 30 * s, cx - larg * 0.2, topo + 80 * s), fill=_clarear(cor, 0.3))
        _rosto(d, cx, topo + 95 * s, s, boca, olhos, x)
    elif p.tipo == "batata":
        r = 100 * s
        cy = base - r
        _bracos_pernas(d, cx, base, r, s, cor)
        d.ellipse((cx - r * 1.15, cy - r * 0.95, cx + r * 1.15, cy + r), fill=cor, outline=CONTORNO, width=int(5 * s))
        for px, py in ((-60, -50), (55, 40), (-40, 60), (70, -30)):
            d.ellipse((cx + px * s - 5 * s, cy + py * s - 4 * s, cx + px * s + 5 * s, cy + py * s + 4 * s),
                      fill=_escurecer(cor, 0.7))
        _rosto(d, cx, cy - 10 * s, s, boca, olhos, x)
    else:   # alface
        r = 105 * s
        cy = base - r
        _bracos_pernas(d, cx, base, r, s, cor)
        import math
        for k in range(10):
            a = math.radians(k * 36)
            d.ellipse((cx + math.cos(a) * r * 0.45 - r * 0.6, cy + math.sin(a) * r * 0.45 - r * 0.6,
                       cx + math.cos(a) * r * 0.45 + r * 0.6, cy + math.sin(a) * r * 0.45 + r * 0.6),
                      fill=cor, outline=CONTORNO, width=int(4 * s))
        d.ellipse((cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7), fill=_clarear(cor, 0.25))
        _rosto(d, cx, cy, s, boca, olhos, x)


def _pessoa(p: Personagem, d: ImageDraw.ImageDraw, w: int, h: int, boca: bool, olhos: bool):
    s = ESCALA * float(p.extras.get("altura", 1.0))
    x = p.extras
    cx, base = w / 2, h - 30 * ESCALA
    pele = x.get("pele", (225, 180, 140))
    roupa = x.get("roupa", (180, 150, 110))
    manto = x.get("manto")
    corpo_topo = base - 230 * s
    # túnica (trapézio) e manto
    d.polygon([(cx - 55 * s, corpo_topo), (cx + 55 * s, corpo_topo), (cx + 85 * s, base), (cx - 85 * s, base)],
              fill=roupa, outline=CONTORNO, width=int(4 * ESCALA))
    if manto:
        d.polygon([(cx - 58 * s, corpo_topo), (cx - 10 * s, corpo_topo), (cx - 40 * s, base), (cx - 88 * s, base)],
                  fill=manto, outline=CONTORNO, width=int(3 * ESCALA))
    d.line((cx - 60 * s, corpo_topo + 95 * s, cx + 60 * s, corpo_topo + 95 * s), fill=_escurecer(roupa, 0.6),
           width=int(8 * s))   # cinto
    # braços
    for lado in (-1, 1):
        d.line((cx + lado * 50 * s, corpo_topo + 15 * s, cx + lado * 80 * s, corpo_topo + 110 * s), fill=roupa,
               width=int(26 * s))
        d.ellipse((cx + lado * 80 * s - 14 * s, corpo_topo + 100 * s, cx + lado * 80 * s + 14 * s,
                   corpo_topo + 126 * s), fill=pele, outline=CONTORNO, width=int(2 * ESCALA))
    if x.get("cajado"):
        d.line((cx + 95 * s, corpo_topo - 60 * s, cx + 85 * s, base), fill=(110, 75, 40), width=int(10 * s))
        d.arc((cx + 70 * s, corpo_topo - 95 * s, cx + 120 * s, corpo_topo - 40 * s), 180, 360, fill=(110, 75, 40),
              width=int(10 * s))
    if x.get("funda"):
        d.line((cx - 80 * s, corpo_topo + 113 * s, cx - 105 * s, corpo_topo + 170 * s), fill=(90, 60, 30),
               width=int(4 * s))
        d.ellipse((cx - 115 * s, corpo_topo + 165 * s, cx - 95 * s, corpo_topo + 185 * s), fill=(130, 130, 130))
    # cabeça
    hr = 62 * s
    hy = corpo_topo - hr * 0.85
    cabelo = x.get("cabelo", (60, 40, 30))
    d.ellipse((cx - hr, hy - hr, cx + hr, hy + hr), fill=pele, outline=CONTORNO, width=int(4 * ESCALA))
    d.chord((cx - hr * 1.02, hy - hr * 1.05, cx + hr * 1.02, hy + hr * 0.35), 180, 360, fill=cabelo)
    if x.get("lenco"):
        d.chord((cx - hr * 1.15, hy - hr * 1.15, cx + hr * 1.15, hy + hr * 0.6), 160, 380, fill=x["lenco"],
                outline=CONTORNO, width=int(3 * ESCALA))
    if x.get("barba"):
        d.chord((cx - hr * 0.95, hy - hr * 0.2, cx + hr * 0.95, hy + hr * 1.35), 0, 180, fill=x["barba"])
    if x.get("coroa"):
        cy0 = hy - hr * 0.95
        d.polygon([(cx - 40 * s, cy0), (cx - 40 * s, cy0 - 35 * s), (cx - 20 * s, cy0 - 15 * s), (cx, cy0 - 40 * s),
                   (cx + 20 * s, cy0 - 15 * s), (cx + 40 * s, cy0 - 35 * s), (cx + 40 * s, cy0)],
                  fill=(240, 195, 60), outline=CONTORNO)
    _rosto(d, cx, hy - 5 * s, s * 0.8, boca, olhos, {})
    if x.get("barba"):   # a boca aparece por cima da barba
        by = hy - 5 * s + 34 * s * 0.8
        if boca:
            d.ellipse((cx - 11 * s, by - 7 * s, cx + 11 * s, by + 10 * s), fill=(120, 25, 30))


def poses(p: Personagem, altura: int) -> dict:
    """{(boca, olhos): imagem RGBA} com a altura pedida (em pixels finais)."""
    w0, h0 = 420 * ESCALA, 520 * ESCALA
    saida = {}
    for boca in (False, True):
        for olhos in (True, False):
            img = Image.new("RGBA", (w0, h0), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            (_pessoa if p.tipo == "pessoa" else _vegetal)(p, d, w0, h0, boca, olhos)
            caixa = img.getbbox() or (0, 0, w0, h0)
            img = img.crop(caixa)
            fator = altura / img.height
            saida[(boca, olhos)] = img.resize((max(1, int(img.width * fator)), altura), Image.LANCZOS)
    return saida
