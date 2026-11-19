"""Miniatura do dia no modo Bíblia, desenhada por cima de um fundo sem texto feito pelo canal.

Layout (1280x720): selo "DIA N" no alto, nome do livro grande, capítulos em dourado, um filete com losango e
duas linhas de texto do canal embaixo. O lado direito fica livre para o desenho do fundo.
Fontes livres (licença OFL) na pasta fontes/: Playfair Display (nome do livro) e Lora (o resto).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONTES = Path(__file__).resolve().parent.parent / "fontes"
MARROM = "#3C2415"
DOURADO = "#B8872E"
CREME = "#F3DFA0"
TEXTO = "#5A3A22"


def _fonte(arquivo: str, tamanho: int, peso: str) -> ImageFont.FreeTypeFont:
    try:
        fonte = ImageFont.truetype(str(FONTES / arquivo), tamanho)
        fonte.set_variation_by_name(peso)
        return fonte
    except (OSError, ValueError):
        return ImageFont.truetype("DejaVuSerif-Bold.ttf", tamanho) if peso == "Bold" else \
            ImageFont.truetype("DejaVuSerif.ttf", tamanho)


def titulo_fonte(t):
    return _fonte("PlayfairDisplay[wght].ttf", t, "Bold")


def lora(t, peso="Bold"):
    return _fonte("Lora[wght].ttf", t, peso)


def _caber(desenho, texto: str, criar, maximo: int, largura: int):
    """A maior fonte (até `maximo`) em que o texto cabe na largura."""
    tamanho = maximo
    while tamanho > 20:
        fonte = criar(tamanho)
        if desenho.textlength(texto, font=fonte) <= largura:
            return fonte
        tamanho -= 4
    return criar(tamanho)


def textos_do_dia(capitulos: list[tuple[str, int]]) -> tuple[str, str]:
    """[('Gênesis',1),('Gênesis',2),('Gênesis',3)] -> ('Gênesis', 'Capítulos 1 a 3');
    [('Salmos',23)] -> ('Salmos', 'Salmo 23'); dois livros -> ('Rute · 1 Samuel', 'Rute 4 · 1 Samuel 1 e 2')."""
    livros = list(dict.fromkeys(l for l, _ in capitulos))
    if len(livros) == 1:
        numeros = [n for _, n in capitulos]
        if len(numeros) == 1:
            rotulo = "Salmo" if livros[0].lower() == "salmos" else "Capítulo"
            return livros[0], f"{rotulo} {numeros[0]}"
        return livros[0], f"Capítulos {numeros[0]} a {numeros[-1]}"
    partes = []
    for livro in livros:
        numeros = [n for l, n in capitulos if l == livro]
        lista = str(numeros[0]) if len(numeros) == 1 else (
            f"{numeros[0]} a {numeros[-1]}" if len(numeros) > 3 else
            ", ".join(map(str, numeros[:-1])) + f" e {numeros[-1]}")
        partes.append(f"{livro} {lista}")
    return " · ".join(livros), " · ".join(partes)


def miniatura(fundo: Path, destino: Path, dia: int, capitulos: list[tuple[str, int]], linha1: str = "",
              linha2: str = "") -> Path:
    base = ImageOps.fit(Image.open(fundo).convert("RGB"), (1280, 720))
    desenho = ImageDraw.Draw(base)
    largura = 700   # do x=64 até antes do desenho do lado direito

    # selo "DIA N"
    selo = f"DIA {dia}"
    fonte_selo = _caber(desenho, selo, lambda t: lora(t), 66, 290)
    caixa = desenho.textbbox((0, 0), selo, font=fonte_selo)
    w = max(320, caixa[2] - caixa[0] + 70)
    desenho.rounded_rectangle((60, 60, 60 + w, 170), radius=14, fill=MARROM)
    desenho.text((60 + w / 2, 115), selo, font=fonte_selo, fill=CREME, anchor="mm")

    livro, caps = textos_do_dia(capitulos)
    fonte_livro = _caber(desenho, livro, titulo_fonte, 150, largura)
    desenho.text((64, 330), livro, font=fonte_livro, fill=MARROM, anchor="ls")
    fonte_caps = _caber(desenho, caps, lambda t: lora(t), 66, largura)
    desenho.text((64, 460), caps, font=fonte_caps, fill=DOURADO, anchor="ls")

    # filete com losango
    desenho.line((60, 530, 316, 530), fill=DOURADO, width=3)
    desenho.line((344, 530, 600, 530), fill=DOURADO, width=3)
    desenho.polygon([(330, 520), (340, 530), (330, 540), (320, 530)], fill=DOURADO)

    if linha1:
        desenho.text((64, 600), linha1, font=_caber(desenho, linha1, lambda t: lora(t, "Medium"), 38, largura),
                     fill=TEXTO, anchor="ls")
    if linha2:
        desenho.text((64, 645), linha2, font=_caber(desenho, linha2, lambda t: lora(t, "Medium"), 28, largura),
                     fill=TEXTO, anchor="ls")
    destino.parent.mkdir(parents=True, exist_ok=True)
    base.save(destino, quality=90, optimize=True)
    return destino


# ---------------------------------------------------------------- audiolivros no canal da Bíblia

def _linhas(desenho, texto: str, criar, maximo: int, largura: int, max_linhas: int = 3, altura_max: float = 1e9):
    """Quebra o texto em até `max_linhas` linhas, com a maior fonte em que tudo cabe (também na altura)."""
    tamanho = maximo
    while tamanho > 24:
        fonte = criar(tamanho)
        linhas, atual = [], ""
        for palavra in texto.split():
            teste = f"{atual} {palavra}".strip()
            if desenho.textlength(teste, font=fonte) <= largura:
                atual = teste
            else:
                linhas.append(atual)
                atual = palavra
        linhas.append(atual)
        linhas = [l for l in linhas if l]
        if (len(linhas) <= max_linhas and len(linhas) * tamanho * 1.08 <= altura_max
                and all(desenho.textlength(l, font=fonte) <= largura for l in linhas)):
            return fonte, linhas
        tamanho -= 4
    return criar(tamanho), [texto]


def arte_audiolivro(fundo: Path, capa: Path | None, destino: Path, titulo: str, autor: str, detalhe: str,
                    largura: int = 1280, altura: int = 720, selo: str = "AUDIOLIVRO",
                    rodape: str = "") -> Path:
    """Miniatura (1280x720) ou arte do vídeo (1920x1080) no estilo do canal: fundo de pergaminho com moldura,
    capa do livro à direita (onde fica o símbolo do canal) com moldura dourada e sombra, textos à esquerda."""
    from PIL import ImageFilter
    s = largura / 1280
    base = ImageOps.fit(Image.open(fundo).convert("RGB"), (largura, altura))
    if capa:
        img = Image.open(capa).convert("RGB")
        alto = int(560 * s)
        larg = int(img.width * alto / img.height)
        if larg > 420 * s:   # capa muito larga: limita pela largura
            larg = int(420 * s)
            alto = int(img.height * larg / img.width)
        img = img.resize((larg, alto), Image.LANCZOS)
        cx, cy = int(1010 * s), int(370 * s)
        x0, y0 = cx - larg // 2, cy - alto // 2
        borda = max(4, int(10 * s))
        sombra = Image.new("RGBA", base.size, (0, 0, 0, 0))
        ImageDraw.Draw(sombra).rectangle((x0 - borda + int(14 * s), y0 - borda + int(18 * s),
                                          x0 + larg + borda + int(14 * s), y0 + alto + borda + int(18 * s)),
                                         fill=(60, 36, 21, 150))
        sombra = sombra.filter(ImageFilter.GaussianBlur(int(16 * s)))
        base = Image.alpha_composite(base.convert("RGBA"), sombra).convert("RGB")
        d = ImageDraw.Draw(base)
        d.rectangle((x0 - borda, y0 - borda, x0 + larg + borda, y0 + alto + borda), fill=DOURADO)
        d.rectangle((x0 - 2, y0 - 2, x0 + larg + 1, y0 + alto + 1), fill=MARROM)
        base.paste(img, (x0, y0))
    d = ImageDraw.Draw(base)
    esquerda, area = int(64 * s), int(680 * s) if capa else int(720 * s)

    # selo
    fonte_selo = lora(int(40 * s))
    w = d.textlength(selo, font=fonte_selo) + 56 * s
    d.rounded_rectangle((60 * s, 60 * s, 60 * s + w, 132 * s), radius=int(12 * s), fill=MARROM)
    d.text((60 * s + w / 2, 96 * s), selo, font=fonte_selo, fill=CREME, anchor="mm")

    # título (até 3 linhas), autor, filete, detalhe
    fonte_t, linhas = _linhas(d, titulo, titulo_fonte, int(100 * s), area, altura_max=190 * s)
    y = 150 * s + fonte_t.size * 0.95
    for linha in linhas:
        d.text((esquerda, y), linha, font=fonte_t, fill=MARROM, anchor="ls")
        y += fonte_t.size * 1.08
    if autor:
        y += 6 * s
        fonte_a = _caber(d, autor, lambda t: lora(t), int(48 * s), area)
        d.text((esquerda, y + fonte_a.size * 0.4), autor, font=fonte_a, fill=DOURADO, anchor="ls")
        y += fonte_a.size * 1.1
    y += 24 * s
    d.line((60 * s, y, 280 * s, y), fill=DOURADO, width=max(2, int(3 * s)))
    d.line((308 * s, y, 528 * s, y), fill=DOURADO, width=max(2, int(3 * s)))
    d.polygon([(294 * s, y - 10 * s), (304 * s, y), (294 * s, y + 10 * s), (284 * s, y)], fill=DOURADO)
    if detalhe:
        fonte_d = _caber(d, detalhe, lambda t: lora(t, "SemiBold"), int(46 * s), area)
        d.text((esquerda, y + 58 * s), detalhe, font=fonte_d, fill=TEXTO, anchor="ls")
    if rodape:
        fonte_r = _caber(d, rodape, lambda t: lora(t, "Medium"), int(28 * s), area)
        d.text((esquerda, altura - 46 * s), rodape, font=fonte_r, fill=TEXTO, anchor="ls")
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() in (".jpg", ".jpeg"):
        base.save(destino, quality=90, optimize=True)
    else:
        base.save(destino)
    return destino
