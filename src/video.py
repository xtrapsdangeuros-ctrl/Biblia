"""Gera a arte (capa + títulos), a miniatura e o vídeo MP4 com ffmpeg."""

import json
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

_FONTES_NEGRITO = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]
_FONTES_NORMAL = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/Library/Fonts/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
]


def _fonte(tamanho: int, negrito: bool) -> ImageFont.FreeTypeFont:
    for caminho in _FONTES_NEGRITO if negrito else _FONTES_NORMAL:
        if Path(caminho).exists():
            return ImageFont.truetype(caminho, tamanho)
    return ImageFont.load_default(tamanho)


def _quebrar(desenho: ImageDraw.ImageDraw, texto: str, fonte, largura_max: int, max_linhas: int) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        teste = f"{atual} {palavra}".strip()
        if desenho.textlength(teste, font=fonte) <= largura_max:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = palavra
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        linhas[-1] = linhas[-1].rstrip(" .,;:") + "…"
    return linhas


def gerar_arte(capa: Path | None, destino: Path, livro: str, autor: str, rotulo: str, titulo: str,
               largura: int, altura: int, cores: dict, miniatura: bool = False) -> Path:
    """Desenha capa à esquerda e textos à direita sobre um fundo feito da própria capa desfocada."""
    margem = largura // 20
    escurecer = Image.new("RGB", (largura, altura), cores["cor_fundo"])
    if capa:
        original = ImageOps.exif_transpose(Image.open(capa)).convert("RGB")
        fundo = ImageOps.fit(original, (largura, altura)).filter(ImageFilter.GaussianBlur(largura // 40))
        tela = Image.blend(fundo, escurecer, 0.72)
        lado_capa = altura - 2 * margem
        capa_img = ImageOps.contain(original, (int(lado_capa * 0.8), lado_capa))
        tela.paste(capa_img, (margem, (altura - capa_img.height) // 2))
        x_texto = margem * 2 + capa_img.width
    else:
        tela = escurecer
        x_texto = margem * 2

    desenho = ImageDraw.Draw(tela)
    largura_texto = largura - x_texto - margem
    escala = altura / 1080

    # Na miniatura o capítulo vira o destaque; no vídeo, o nome do livro.
    blocos = []
    if miniatura:
        blocos.append((rotulo, _fonte(int(150 * escala), True), cores["cor_destaque"], 2))
        blocos.append((livro, _fonte(int(72 * escala), True), cores["cor_texto"], 3))
    else:
        blocos.append((livro, _fonte(int(84 * escala), True), cores["cor_texto"], 3))
        blocos.append((autor, _fonte(int(44 * escala), False), cores["cor_texto"], 1))
        blocos.append((rotulo, _fonte(int(72 * escala), True), cores["cor_destaque"], 1))
        if titulo:
            blocos.append((titulo, _fonte(int(56 * escala), False), cores["cor_texto"], 3))

    linhas_por_bloco = [(_quebrar(desenho, t, f, largura_texto, n), f, c) for t, f, c, n in blocos if t]
    espaco = int(36 * escala)
    altura_total = sum(len(ls) * int(f.size * 1.2) for ls, f, _ in linhas_por_bloco) + espaco * (len(linhas_por_bloco) - 1)
    y = (altura - altura_total) // 2
    for linhas, fonte, cor in linhas_por_bloco:
        for linha in linhas:
            desenho.text((x_texto, y), linha, font=fonte, fill=cor)
            y += int(fonte.size * 1.2)
        y += espaco

    # Chamada para o público numa faixa embaixo (só no vídeo; a miniatura fica limpa)
    if not miniatura and cores.get("cta"):
        fonte = _fonte(int(38 * escala), True)
        faixa = int(fonte.size * 2.2)
        tela.paste(Image.new("RGB", (largura, faixa), cores["cor_fundo"]), (0, altura - faixa))
        caixa = desenho.textbbox((0, 0), cores["cta"], font=fonte)
        desenho.text(((largura - (caixa[2] - caixa[0])) // 2, altura - faixa + (faixa - (caixa[3] - caixa[1])) // 2
                      - caixa[1]), cores["cta"], font=fonte, fill=cores["cor_destaque"])

    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() in (".jpg", ".jpeg"):
        tela.save(destino, quality=88, optimize=True)  # miniatura precisa ter menos de 2 MB
    else:
        tela.save(destino)
    return destino


def duracao_audio(audio: Path) -> float:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(audio)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(saida)["format"]["duration"])


def _formato_audio(audio: Path) -> tuple | None:
    """(codec, taxa, canais) da primeira faixa de áudio, ou None se não der para ler."""
    try:
        saida = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels", "-of", "json", str(audio)],
            check=True, capture_output=True, text=True,
        ).stdout
        s = json.loads(saida)["streams"][0]
        return s["codec_name"], s["sample_rate"], s["channels"]
    except Exception:
        return None


# Som que o MP4 aceita como está: copiar é umas 4x mais rápido que converter (e o arquivo fica menor).
_COPIAVEIS = {"mp3", "aac"}


def pode_copiar_audio(audios: list[Path]) -> bool:
    """Todas as partes têm o mesmo formato, e é um formato que dá para pôr no MP4 sem converter."""
    formatos = {_formato_audio(a) for a in audios}
    if len(formatos) != 1:
        return False
    formato = formatos.pop()
    return formato is not None and formato[0] in _COPIAVEIS


def gerar_video(arte: Path, audios: list[Path], destino: Path, copiar_audio: bool = True) -> Path:
    """Imagem parada + áudio (as partes A, B... são emendadas em sequência).

    1 quadro por segundo deixa a renderização rápida e o arquivo pequeno. Quando dá, o som é copiado como está
    (sem converter): isso era 3/4 do tempo de montar o vídeo, e tempo aqui é minuto gasto do GitHub.
    """
    duracao = sum(duracao_audio(a) for a in audios)
    imagem = ["-loop", "1", "-framerate", "1", "-i", str(arte)]
    video = ["-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    fim = ["-t", f"{duracao:.3f}", "-movflags", "+faststart", str(destino)]

    if copiar_audio and pode_copiar_audio(audios):
        lista = destino.with_name(destino.stem + "_partes.txt")
        # Lista do ffmpeg para emendar sem converter; um ' no nome do arquivo vira '\''
        nomes = [Path(a).resolve().as_posix().replace("'", "'\\''") for a in audios]
        lista.write_text("".join(f"file '{n}'\n" for n in nomes), encoding="utf-8")
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-v", "error", *imagem,
                 "-f", "concat", "-safe", "0", "-i", str(lista),
                 "-map", "0:v", "-map", "1:a:0", *video, "-c:a", "copy", *fim],
                check=True,
            )
            return destino
        except subprocess.CalledProcessError:
            pass   # algum arquivo estranho: cai no jeito antigo (converte o som)
        finally:
            lista.unlink(missing_ok=True)

    entradas = [arg for a in audios for arg in ("-i", str(a))]
    emenda = "".join(f"[{i + 1}:a]" for i in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[a]"
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error", *imagem,
            *entradas,
            "-filter_complex", emenda,
            "-map", "0:v", "-map", "[a]", *video,
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", *fim,
        ],
        check=True,
    )
    return destino
