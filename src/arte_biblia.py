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
