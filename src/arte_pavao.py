"""Identidade visual do canal Audiolivros Pavão: miniaturas, arte do vídeo e capa quadrada (podcast).

Ligado pelo canal.yaml do Pavão (video > estilo: pavao). Os outros canais continuam com a arte de video.py.

Cores: azul-petróleo #0E2A33 → verde-esmeralda #0F5C55 (fundo), dourado #F2B84B (destaques), creme #F4F1EA (texto).
O símbolo (folha verde com contorno dourado, círculo azul e livro aberto) é o mesmo da foto de perfil do canal.
Fontes livres (licença OFL) na pasta fontes/: Playfair Display (títulos) e Montserrat (o resto).
"""

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

FONTES = Path(__file__).resolve().parent.parent / "fontes"

PETROLEO = "#0E2A33"
PETROLEO_ESCURO = "#081A20"
ESMERALDA = "#0F5C55"
DOURADO = "#F2B84B"
CREME = "#F4F1EA"
VERDE_LOGO = "#04745C"
AZUL_LOGO = "#01407B"

VARIANTES = ("moldura", "destaque", "arte")


def rgb(h: str, a: int | None = 255) -> tuple:
    h = h.lstrip("#")
    cor = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return cor + (a,) if a is not None else cor


def fonte(familia: str, peso: str, tamanho: int) -> ImageFont.FreeTypeFont:
    arquivo = {"serifa": "PlayfairDisplay[wght].ttf", "sans": "Montserrat[wght].ttf"}[familia]
    try:
        f = ImageFont.truetype(str(FONTES / arquivo), tamanho)
        f.set_variation_by_name(peso)
        return f
    except (OSError, ValueError):
        negrito = peso in ("Bold", "ExtraBold", "Black", "SemiBold")
        for nome in (("DejaVuSans-Bold.ttf", "DejaVuSans.ttf")[not negrito],):
            try:
                return ImageFont.truetype(nome, tamanho)
            except OSError:
                pass
        return ImageFont.load_default(tamanho)


# ---------------------------------------------------------------- fundo, leque e símbolo

def degrade(w: int, h: int, c1: str = PETROLEO, c2: str = ESMERALDA, angulo: float = 25) -> Image.Image:
    """Degradê diagonal suave com vinheta escura nas bordas."""
    a, b = rgb(c1, None), rgb(c2, None)
    peq = Image.new("RGB", (64, 64))
    px = peq.load()
    ca, sa = math.cos(math.radians(angulo)), math.sin(math.radians(angulo))
    for y in range(64):
        for x in range(64):
            t = ((x / 63) * ca + (y / 63) * sa) / (ca + sa)
            t = t * t * (3 - 2 * t)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
    img = peq.resize((w, h), Image.BICUBIC)
    vinheta = Image.new("L", (w, h), 0)
    ImageDraw.Draw(vinheta).ellipse((-w * 0.25, -h * 0.35, w * 1.25, h * 1.35), fill=255)
    vinheta = vinheta.filter(ImageFilter.GaussianBlur(min(w, h) // 6))
    return Image.composite(img, Image.new("RGB", (w, h), rgb(PETROLEO_ESCURO, None)), vinheta)


def leque(w: int, h: int, origem: tuple, raio: float, n: int = 9, abertura=(200, 290), alfa: int = 60,
          espessura: int = 3) -> Image.Image:
    """Penas de pavão em traços dourados finos, para enfeitar o fundo. Camada RGBA."""
    s = 2
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ox, oy = origem[0] * s, origem[1] * s
    cor, cor2 = rgb(DOURADO, alfa), rgb(DOURADO, int(alfa * 0.45))
    for i in range(n):
        ang = math.radians(abertura[0] + (abertura[1] - abertura[0]) * i / max(1, n - 1))
        r = raio * s * (0.86 + 0.14 * ((i * 7) % 5) / 4)
        ex, ey = ox + r * math.cos(ang), oy + r * math.sin(ang)
        d.line([(ox, oy), (ex, ey)], fill=cor, width=espessura * s)
        for j in range(8, 40):
            t = j / 40
            px, py = ox + r * t * math.cos(ang), oy + r * t * math.sin(ang)
            comp = r * 0.10 * math.sin(math.pi * t)
            for lado in (-1, 1):
                a2 = ang + lado * math.radians(35)
                d.line([(px, py), (px + comp * math.cos(a2), py + comp * math.sin(a2))], fill=cor2, width=s)
        lh, lw = r * 0.16, r * 0.11
        rot = ang + math.pi / 2
        pts = []
        for k in range(60):
            t = 2 * math.pi * k / 60
            x, y = lw * math.sin(t) * (1 - 0.28 * max(0, -math.cos(t)) ** 2), -lh * math.cos(t)
            pts.append((ex + x * math.cos(rot) - y * math.sin(rot), ey + x * math.sin(rot) + y * math.cos(rot)))
        d.polygon(pts, outline=cor, width=espessura * s)
        d.ellipse((ex - lw * 0.35, ey - lw * 0.35, ex + lw * 0.35, ey + lw * 0.35), outline=cor, width=espessura * s)
    return img.resize((w, h), Image.LANCZOS)


def _folha(cx, cy, w, h, n=120):
    dir_, esq = [], []
    for i in range(n + 1):
        u = -1 + 2 * i / n
        x = w * (1 - abs(u) ** 2.3) ** 1.15
        dir_.append((cx + x, cy + h * u))
        esq.append((cx - x, cy + h * u))
    return dir_ + esq[::-1]


def _livro(d, cx, cy, larg, cor=CREME, sombra="#CFC6B0"):
    w, h = larg / 2, larg * 0.80
    for desloc, c in ((larg * 0.05, sombra), (0, cor)):
        for lado in (-1, 1):
            pts = []
            for i in range(25):
                t = i / 24
                x = cx + lado * (larg * 0.03 + (w - larg * 0.03) * t)
                y = cy - h / 2 + h * 0.14 * (1 - t) ** 1.5 - h * 0.04 * math.sin(math.pi * t)
                pts.append((x + lado * desloc * 0.5, y + desloc))
            for i in range(24, -1, -1):
                t = i / 24
                x = cx + lado * (larg * 0.03 + (w - larg * 0.03) * t)
                y = cy + h / 2 - h * 0.16 * t
                pts.append((x + lado * desloc * 0.5, y + desloc))
            d.polygon(pts, fill=rgb(c))


def simbolo(lado: int) -> Image.Image:
    """O logo do canal (o mesmo da foto de perfil), fundo transparente."""
    s = 4
    L = lado * s
    img = Image.new("RGBA", (L, L), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = L / 2
    h, w, borda = L * 0.365, L * 0.30, L * 0.014
    d.polygon(_folha(cx, cy, w, h), fill=rgb(DOURADO))
    d.polygon(_folha(cx, cy, w - borda * 1.4, h - borda * 2.0), fill=rgb(VERDE_LOGO))
    r = w * 0.70
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=rgb(DOURADO))
    r2 = r - borda
    d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), fill=rgb(AZUL_LOGO))
    _livro(d, cx, cy - r * 0.03, r * 0.98)
    return img.resize((lado, lado), Image.LANCZOS)


def selo(diam: int) -> Image.Image:
    """Selo redondo do canal: o símbolo num círculo petróleo com aro dourado (marca d'água e miniaturas)."""
    s = 4
    D = diam * s
    img = Image.new("RGBA", (D, D), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, D - 1, D - 1), fill=rgb(DOURADO))
    a = int(D * 0.045)
    d.ellipse((a, a, D - 1 - a, D - 1 - a), fill=rgb(PETROLEO))
    img = img.resize((diam, diam), Image.LANCZOS)
    simb = simbolo(int(diam * 1.02))
    img.alpha_composite(simb, ((diam - simb.width) // 2, (diam - simb.height) // 2))
    return img


# ---------------------------------------------------------------- texto

def _quebrar(d, texto: str, f, largura: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if not atual or d.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    return linhas


def _caber(d, texto: str, familia: str, peso: str, maximo: int, minimo: int, largura: int, max_linhas: int):
    """A maior fonte (entre minimo e maximo) em que o texto cabe em até max_linhas; corta com … se não couber."""
    tamanho = maximo
    while True:
        f = fonte(familia, peso, tamanho)
        linhas = _quebrar(d, texto, f, largura)
        largo = max((d.textlength(l, font=f) for l in linhas), default=0)
        if (len(linhas) <= max_linhas and largo <= largura) or tamanho <= minimo:
            break
        tamanho -= 4
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        while linhas[-1] and d.textlength(linhas[-1] + "…", font=f) > largura:
            linhas[-1] = linhas[-1].rsplit(" ", 1)[0] if " " in linhas[-1] else linhas[-1][:-1]
        linhas[-1] = linhas[-1].rstrip(" .,;:") + "…"
    return f, linhas


def titulo_curto(titulo: str) -> str:
    """Tira subtítulo ("Livro: subtítulo", "Livro – subtítulo", "Livro (Vol. 2)") para caber no celular."""
    for sep in (":", " – ", " — ", " - ", "("):
        if sep in titulo and titulo.index(sep) >= 3:
            titulo = titulo[:titulo.index(sep)]
    return titulo.strip()


def _texto(d, xy, linhas, f, cor, entrelinha=1.08, sombra=True) -> int:
    x, y = xy
    passo = int(f.size * entrelinha)
    for linha in linhas:
        if sombra:
            d.text((x + 3, y + 4), linha, font=f, fill=(0, 0, 0, 140))
        d.text((x, y), linha, font=f, fill=cor)
        y += passo
    return y


def _pilula(d, x, y, texto, f, fundo=DOURADO, cor=PETROLEO, pad=(28, 14), espaco=2) -> tuple:
    larg = sum(d.textlength(c, font=f) for c in texto) + espaco * (len(texto) - 1)
    caixa = d.textbbox((0, 0), "ÁCgj", font=f)
    alt = caixa[3] - caixa[1]
    w, h = larg + pad[0] * 2, alt + pad[1] * 2
    d.rounded_rectangle((x, y, x + w, y + h), radius=h // 2, fill=rgb(fundo))
    cx, ty = x + pad[0], y + pad[1] - caixa[1]
    for c in texto:
        d.text((cx, ty), c, font=f, fill=rgb(cor))
        cx += d.textlength(c, font=f) + espaco
    return w, h


def _capa_com_moldura(capa: Image.Image, altura: int, borda: int = 6) -> Image.Image:
    """Capa com filete dourado e sombra suave, pronta para colar (RGBA)."""
    img = ImageOps.contain(capa, (int(altura * 0.85), altura), Image.LANCZOS)
    w, h = img.width + borda * 2, img.height + borda * 2
    m = int(altura * 0.08)
    camada = Image.new("RGBA", (w + m * 2, h + m * 2), (0, 0, 0, 0))
    sombra = Image.new("L", camada.size, 0)
    ImageDraw.Draw(sombra).rectangle((m + 10, m + 18, m + w + 10, m + h + 18), fill=170)
    sombra = sombra.filter(ImageFilter.GaussianBlur(m // 2))
    camada.paste(Image.new("RGBA", camada.size, (0, 0, 0, 255)), (0, 0), sombra)
    ImageDraw.Draw(camada).rectangle((m, m, m + w - 1, m + h - 1), fill=rgb(DOURADO))
    camada.paste(img, (m + borda, m + borda))
    return camada, m


def _abrir(capa) -> Image.Image | None:
    if capa is None:
        return None
    if isinstance(capa, Image.Image):
        return capa.convert("RGB")
    return ImageOps.exif_transpose(Image.open(capa)).convert("RGB")


def _salvar(img: Image.Image, destino: Path) -> Path:
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    img = img.convert("RGB")
    if destino.suffix.lower() in (".jpg", ".jpeg"):
        img.save(destino, quality=90, optimize=True)   # miniatura do YouTube: até 2 MB
    else:
        img.save(destino)
    return destino


# ---------------------------------------------------------------- miniatura 1280x720

def miniatura(capa, destino: Path, livro: str, autor: str, rotulo: str, detalhe: str = "",
              variante: str = "destaque", largura: int = 1280, altura: int = 720,
              rodape: str = "AUDIOLIVROS PAVÃO", com_autor: bool = False) -> Path:
    """Miniatura do vídeo no visual do canal.

    rotulo: o destaque curto ("CAP. 3", "PARTE 2"); detalhe: linha menor opcional ("Capítulos 5 a 9").
    variantes: moldura (capa à esquerda com filete dourado), destaque (capa grande à direita sobre ela mesma
    desfocada) e arte (sem a capa: só a arte do canal; use quando não quiser mostrar a ilustração da editora).
    """
    W, H = largura, altura
    k = W / 1280
    foto = _abrir(capa)
    if variante not in VARIANTES:
        variante = "destaque"
    if foto is None:
        variante = "arte"
    titulo = titulo_curto(livro).upper() if variante != "arte" else titulo_curto(livro)

    if variante == "destaque":
        fundo = ImageOps.fit(foto, (W, H)).filter(ImageFilter.GaussianBlur(int(26 * k)))
        img = Image.blend(fundo, degrade(W, H), 0.78).convert("RGBA")
    else:
        img = degrade(W, H).convert("RGBA")
        img.alpha_composite(leque(W, H, (W + int(60 * k), H + int(90 * k)), 800 * k, n=9, abertura=(198, 266),
                                  alfa=45, espessura=max(1, int(3 * k))))
    d = ImageDraw.Draw(img)
    margem = int(56 * k)

    # Os textos são desenhados numa camada à parte e depois centralizados na altura.
    bloco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    db = ImageDraw.Draw(bloco)

    def detalhe_e_autor(y, x, larg, autor_aqui):
        if autor_aqui and autor:
            fa = fonte("sans", "SemiBold", int(40 * k))
            y = _texto(db, (x, y + int(4 * k)), [autor], fa, rgb(DOURADO)) + int(2 * k)
        if detalhe:
            fd = fonte("sans", "Medium", int(34 * k))
            y = _texto(db, (x, y + int(4 * k)), _quebrar(db, detalhe, fd, larg)[:1], fd, rgb(CREME, 225))
        return y

    if variante == "moldura":
        cam, m = _capa_com_moldura(foto, H - 2 * margem - int(20 * k))
        img.alpha_composite(cam, (margem - m, (H - cam.height) // 2))
        x = margem + cam.width - 2 * m + int(48 * k)
        larg = W - x - margem
        _, ph = _pilula(db, x, 0, rotulo.upper(), fonte("sans", "ExtraBold", int(50 * k)), pad=(int(30 * k), int(14 * k)))
        y = ph + int(26 * k)
        f, linhas = _caber(db, titulo, "serifa", "Black", int(118 * k), int(64 * k), larg, 3)
        y = _texto(db, (x, y), linhas, f, rgb(CREME), 1.02) + int(f.size * 0.18)
        y = detalhe_e_autor(y, x, larg, True)
        img.alpha_composite(bloco, (0, max(int(30 * k), (H - y) // 2 - int(10 * k))))
        s = selo(int(110 * k))
        img.alpha_composite(s, (W - s.width - int(26 * k), H - s.height - int(22 * k)))

    elif variante == "destaque":
        cam, m = _capa_com_moldura(foto, H - int(60 * k), borda=int(7 * k))
        cx = W - cam.width + m - int(40 * k)
        img.alpha_composite(cam, (cx, (H - cam.height) // 2))
        x, larg = margem, cx + m - margem - int(36 * k)
        partes = rotulo.split()
        palavra, numero = (" ".join(partes[:-1]), partes[-1]) if len(partes) > 1 else ("", rotulo)
        y = 0
        if palavra:
            fp = fonte("sans", "ExtraBold", int(46 * k))
            y = _texto(db, (x + int(6 * k), 0), [palavra.upper()], fp, rgb(CREME), 1.0) + int(14 * k)
        fn = fonte("serifa", "Black", int(220 * k))
        caixa = db.textbbox((0, 0), numero, font=fn)
        if caixa[2] - caixa[0] > larg:
            fn = fonte("serifa", "Black", int(220 * k * larg / (caixa[2] - caixa[0])))
            caixa = db.textbbox((0, 0), numero, font=fn)
        db.text((x + 4, y - caixa[1] + 6), numero, font=fn, fill=(0, 0, 0, 150))
        db.text((x, y - caixa[1]), numero, font=fn, fill=rgb(DOURADO))
        y += caixa[3] - caixa[1] + int(30 * k)
        f, linhas = _caber(db, titulo, "serifa", "Black", int(92 * k), int(56 * k), larg, 2)
        y = _texto(db, (x, y), linhas, f, rgb(CREME), 1.02) + int(f.size * 0.15)
        y = detalhe_e_autor(y, x, larg, com_autor)
        reserva = int(130 * k)   # espaço do selo embaixo
        img.alpha_composite(bloco, (0, max(int(30 * k), (H - reserva - y) // 2)))
        s = selo(int(90 * k))
        img.alpha_composite(s, (x, H - s.height - int(28 * k)))
        fa, texto = _caber(d, rodape or "", "sans", "SemiBold", int(28 * k), int(18 * k),
                           larg - s.width - int(18 * k), 1)
        if texto and texto[0]:
            caixa = d.textbbox((0, 0), texto[0], font=fa)
            d.text((x + s.width + int(18 * k), H - int(28 * k) - s.height // 2 - (caixa[3] + caixa[1]) // 2),
                   texto[0], font=fa, fill=rgb(CREME, 230))

    else:  # arte: sem a capa
        s = simbolo(int(560 * k))
        img.alpha_composite(s, (W - s.width + int(70 * k), (H - s.height) // 2))
        x, larg = margem + int(10 * k), int(760 * k)
        _, ph = _pilula(db, x, 0, rotulo.upper(), fonte("sans", "ExtraBold", int(50 * k)), pad=(int(30 * k), int(14 * k)))
        y = ph + int(30 * k)
        f, linhas = _caber(db, titulo, "serifa", "Black", int(128 * k), int(68 * k), larg, 3)
        y = _texto(db, (x, y), linhas, f, rgb(CREME), 1.02) + int(f.size * 0.18)
        y = detalhe_e_autor(y, x, larg, True)
        img.alpha_composite(bloco, (0, max(int(30 * k), (H - y) // 2)))
    return _salvar(img, destino)


def adaptar_rotulo(rotulo: str, titulo: str) -> tuple[str, str]:
    """Textos do robô -> textos da miniatura: 'Capítulo 3' vira 'Cap. 3'; o livro completo vira 'Parte 2'."""
    rotulo, titulo = (rotulo or "").strip(), (titulo or "").strip()
    cap = re.fullmatch(r"cap[íi]tulo\s+(\d+)", rotulo, re.IGNORECASE)
    if cap:
        return f"Cap. {int(cap.group(1))}", titulo
    completo = re.fullmatch(r"audiolivro completo(?:\s*[–-]\s*parte\s+(\d+)\s+de\s+(\d+))?", rotulo, re.IGNORECASE)
    if completo:
        if completo.group(1):
            return f"Parte {completo.group(1)}", f"Audiolivro completo · parte {completo.group(1)} de {completo.group(2)}"
        return "Completo", "Audiolivro completo"
    return rotulo, titulo


def arte(capa, destino: Path, livro: str, autor: str, rotulo: str, titulo: str, largura: int, altura: int,
         cores: dict, miniatura_: bool = False) -> Path:
    """Mesmo uso de video.gerar_arte: serve tanto para a miniatura (1280x720) quanto para a imagem do vídeo."""
    rot, detalhe = adaptar_rotulo(rotulo, titulo)
    variante = cores.get("miniatura_variante") or "destaque"
    rodape = "AUDIOLIVROS PAVÃO" if miniatura_ else (cores.get("cta") or "AUDIOLIVROS PAVÃO")
    return miniatura(capa, destino, livro, autor, rot, detalhe, variante, largura, altura, rodape=rodape,
                     com_autor=not miniatura_)


# ---------------------------------------------------------------- capa quadrada (podcast / playlist)

def capa_quadrada(capa, destino: Path, livro: str, autor: str, lado: int = 1400, linha_extra: str = "Audiolivro completo") -> Path:
    """Capa 1:1 de um livro para o podcast/playlist: capa do livro no meio com moldura, título e selo do canal."""
    L = lado
    k = L / 1400
    foto = _abrir(capa)
    img = degrade(L, L).convert("RGBA")
    img.alpha_composite(leque(L, L, (L + int(80 * k), L + int(80 * k)), 900 * k, n=9, abertura=(196, 268),
                              alfa=45, espessura=max(1, int(3 * k))))
    img.alpha_composite(leque(L, L, (-int(80 * k), L + int(80 * k)), 900 * k, n=9, abertura=(272, 344),
                              alfa=45, espessura=max(1, int(3 * k))))
    d = ImageDraw.Draw(img)
    margem = int(80 * k)
    y = margem
    if foto is not None:
        cam, m = _capa_com_moldura(foto, int(720 * k), borda=int(8 * k))
        img.alpha_composite(cam, ((L - cam.width) // 2, y - m))
        y += cam.height - 2 * m + int(56 * k)
    else:
        s = simbolo(int(640 * k))
        img.alpha_composite(s, ((L - s.width) // 2, y))
        y += s.height + int(20 * k)
    f, linhas = _caber(d, titulo_curto(livro), "serifa", "Black", int(120 * k), int(64 * k), L - 2 * margem, 2)
    for linha in linhas:
        caixa = d.textbbox((0, 0), linha, font=f)
        x = (L - (caixa[2] - caixa[0])) // 2 - caixa[0]
        d.text((x + 3, y + 4), linha, font=f, fill=(0, 0, 0, 140))
        d.text((x, y), linha, font=f, fill=rgb(CREME))
        y += int(f.size * 1.04)
    if autor:
        fa = fonte("sans", "SemiBold", int(46 * k))
        caixa = d.textbbox((0, 0), autor, font=fa)
        d.text(((L - (caixa[2] - caixa[0])) // 2, y + int(10 * k)), autor, font=fa, fill=rgb(DOURADO))
    # rodapé: selo + nome do canal
    s = selo(int(110 * k))
    fr = fonte("sans", "Bold", int(34 * k))
    texto = f"AUDIOLIVROS PAVÃO  •  {linha_extra.upper()}" if linha_extra else "AUDIOLIVROS PAVÃO"
    larg = s.width + int(20 * k) + d.textlength(texto, font=fr)
    x0 = int((L - larg) / 2)
    yb = L - margem - s.height + int(20 * k)
    img.alpha_composite(s, (x0, yb))
    caixa = d.textbbox((0, 0), texto, font=fr)
    d.text((x0 + s.width + int(20 * k), yb + (s.height - (caixa[3] - caixa[1])) // 2 - caixa[1]), texto, font=fr,
           fill=rgb(CREME, 235))
    return _salvar(img, destino)
