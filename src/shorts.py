"""Shorts: um trecho de 35–55 s de cada capítulo, em vídeo vertical com legenda grande na tela."""

import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from comum import log, normalizar
from cortar import Palavra
from metadados import _licenca, _limpar, hashtags_video, link_playlist, livro_e_autor, rotulo_e_titulo, tags_video
from metadados import titulo_short
from video import _fonte, _quebrar

LARGURA, ALTURA = 1080, 1920
_FIM_DE_FRASE = (".", "!", "?", "…")
# Partes do livro que não rendem um bom Short
_SEM_SHORT = ("abertura", "creditos", "glossario", "agradecimentos", "guia de pronuncia", "sumario",
              "dedicatoria", "apendice", "orelha", "contra")


def merece_short(numero: int, titulo: str) -> bool:
    rotulo, _ = rotulo_e_titulo(numero, titulo)
    return not normalizar(rotulo).startswith(_SEM_SHORT)


def _fim_de_frase(p: Palavra) -> bool:
    return p.texto.strip().endswith(_FIM_DE_FRASE)


def escolher_trecho(palavras: list[Palavra], minimo: float = 35, maximo: float = 55,
                    pular: float = 20) -> list[Palavra]:
    """Um trecho que começa numa frase nova (depois do título do capítulo) e termina num ponto final.

    Se não houver ponto final entre `minimo` e `maximo` segundos, corta na última palavra antes de `maximo`.
    """
    if not palavras:
        return []
    # começo: primeira palavra que abre frase depois de `pular` segundos (o título fica de fora)
    inicio = next((i for i in range(1, len(palavras))
                   if palavras[i].inicio >= pular and _fim_de_frase(palavras[i - 1])), None)
    if inicio is None:
        inicio = next((i for i, p in enumerate(palavras) if p.inicio >= min(pular, palavras[-1].inicio)), 0)
    t0 = palavras[inicio].inicio
    fim, ultimo_que_cabe = None, inicio
    for j in range(inicio, len(palavras)):
        dur = palavras[j].fim - t0
        if dur > maximo:
            break
        ultimo_que_cabe = j
        if dur >= minimo and _fim_de_frase(palavras[j]):
            fim = j   # continua procurando: prefere o ponto final mais tardio que ainda cabe
    if fim is None:
        fim = ultimo_que_cabe
    return palavras[inicio:fim + 1]


# ---------------------------------------------------------------- legenda queimada (ASS)

def _tempo_ass(seg: float) -> str:
    cs = int(round(max(seg, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escapar_ass(texto: str) -> str:
    return texto.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def gerar_ass(trecho: list[Palavra], palavras_por_tela: int = 3, cor_destaque: str = "#f2b84b") -> str:
    """Legenda estilo Shorts: poucas palavras por vez, letras grandes, contorno preto."""
    if not trecho:
        return ""
    t0 = trecho[0].inicio
    r, g, b = (int(cor_destaque.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    cor_ass = f"&H00{b:02X}{g:02X}{r:02X}"
    cabecalho = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {LARGURA}", f"PlayResY: {ALTURA}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        f"Style: Fala,DejaVu Sans,96,{cor_ass},&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,7,3,5,80,80,0,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    eventos = []
    grupo: list[Palavra] = []
    for i, p in enumerate(trecho):
        grupo.append(p)
        ultimo = i == len(trecho) - 1
        if len(grupo) >= palavras_por_tela or _fim_de_frase(p) or p.texto.strip().endswith(",") or ultimo:
            inicio = grupo[0].inicio - t0
            # a tela fica até a próxima fala começar (sem piscar entre grupos)
            fim = (trecho[i + 1].inicio - t0) if not ultimo else (p.fim - t0 + 0.5)
            texto = _escapar_ass(" ".join(w.texto.strip() for w in grupo)).upper()
            eventos.append(f"Dialogue: 0,{_tempo_ass(inicio)},{_tempo_ass(fim)},Fala,,0,0,0,,{texto}")
            grupo = []
    return "\n".join(cabecalho + eventos) + "\n"


# ---------------------------------------------------------------- arte vertical e render

def gerar_arte_vertical(capa: Path | None, destino: Path, livro: str, rotulo: str, cores: dict) -> Path:
    """Fundo com a capa desfocada, capa no alto, nome do livro e do capítulo. O meio fica livre para a legenda."""
    escuro = Image.new("RGB", (LARGURA, ALTURA), cores["cor_fundo"])
    if capa:
        original = ImageOps.exif_transpose(Image.open(capa)).convert("RGB")
        fundo = ImageOps.fit(original, (LARGURA, ALTURA)).filter(ImageFilter.GaussianBlur(40))
        tela = Image.blend(fundo, escuro, 0.6)
        capa_img = ImageOps.contain(original, (720, 660))
        tela.paste(capa_img, ((LARGURA - capa_img.width) // 2, 150))
    else:
        tela = escuro
    desenho = ImageDraw.Draw(tela)
    y = 1380
    for texto, fonte, cor, linhas in ((rotulo, _fonte(70, True), cores["cor_destaque"], 2),
                                      (livro, _fonte(58, True), cores["cor_texto"], 3)):
        for linha in _quebrar(desenho, texto, fonte, LARGURA - 160, linhas):
            w = desenho.textlength(linha, font=fonte)
            desenho.text(((LARGURA - w) / 2, y), linha, font=fonte, fill=cor)
            y += int(fonte.size * 1.25)
        y += 30
    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino


def renderizar_short(arte: Path, audio: Path, inicio: float, duracao: float, ass: str, destino: Path) -> Path:
    pasta = destino.parent
    (pasta / "legenda.ass").write_text(ass, encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-loop", "1", "-framerate", "15", "-i", str(arte.resolve()),
            "-ss", f"{inicio:.2f}", "-t", f"{duracao:.2f}", "-i", str(audio.resolve()),
            # caminho relativo (cwd = pasta) evita problemas de escape no filtro "ass"
            "-vf", "ass=legenda.ass", "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "15",
            "-c:a", "aac", "-b:a", "160k", "-af", f"afade=t=out:st={max(duracao - 0.8, 0):.2f}:d=0.8",
            "-t", f"{duracao:.2f}", "-movflags", "+faststart", str(destino.resolve()),
        ],
        check=True, cwd=pasta,
    )
    return destino


def descricao_short(ficha: dict, numero: int, titulo_cap: str, video_capitulo: str, playlist_id: str | None) -> str:
    rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
    livro, autor = livro_e_autor(ficha)
    linhas = []
    if playlist_id:   # o link da playlist vem primeiro: é o que aparece sem abrir a descrição
        linhas.append(f"📚 Ouça o livro todo: {link_playlist(playlist_id)}")
    linhas.append(f"▶ Este capítulo inteiro: https://youtu.be/{video_capitulo}")
    linhas += ["", f"Trecho do audiolivro {livro}" + (f", de {autor}" if autor else "") + f" – {rotulo}"
               + (f": {titulo}" if titulo else "") + "."]
    if ficha.get("narrador"):
        linhas.append(f"Narração: {ficha['narrador']}")
    linhas.append(_licenca(ficha))
    linhas += ["", " ".join(["#Shorts", *hashtags_video(ficha)][:5])]
    return _limpar("\n".join(linhas))[:5000]


def gerar_short(livro, capitulo, audio: Path, palavras: list[Palavra], capa: Path | None, cfg: dict,
                pasta_tmp: Path) -> tuple[Path | None, float]:
    """Monta o MP4 vertical do Short. Retorna (None, 0) se o capítulo for curto demais."""
    trecho = escolher_trecho(palavras)
    if not trecho or trecho[-1].fim - trecho[0].inicio < 15:
        return None, 0.0
    inicio = max(trecho[0].inicio - 0.15, 0)
    duracao = min(trecho[-1].fim - inicio + 0.6, 59)
    rotulo, _ = rotulo_e_titulo(capitulo.numero, capitulo.titulo)
    arte = gerar_arte_vertical(capa, pasta_tmp / "short_arte.png", livro.ficha["titulo"], rotulo, cfg["video"])
    video = renderizar_short(arte, audio, inicio, duracao, gerar_ass(trecho, cor_destaque=cfg["video"]["cor_destaque"]),
                             pasta_tmp / "short.mp4")
    return video, duracao


def publicar_short(youtube, livro, capitulo, registro: dict, estado: dict, audio: Path, palavras: list[Palavra],
                   capa: Path | None, cfg: dict, privacidade: str, pasta_tmp: Path) -> str | None:
    """Gera e envia o Short de um capítulo. Retorna o ID (ou None se o capítulo for curto demais)."""
    video, duracao = gerar_short(livro, capitulo, audio, palavras, capa, cfg, pasta_tmp)
    if not video:
        log.info("  capítulo %d curto demais para um Short; pulando.", capitulo.numero)
        registro["short"] = "pulado"
        return None
    pub = cfg["publicacao"]
    snippet = {
        "title": titulo_short(livro.ficha, capitulo.numero, capitulo.titulo),
        "description": descricao_short(livro.ficha, capitulo.numero, capitulo.titulo,
                                       registro["video_id"] + (f"?t={int(registro['inicio'])}" if registro.get("inicio") else ""),
                                       estado.get("playlist_id")),
        "tags": tags_video(livro.ficha) + ["shorts"],
        "categoryId": str(pub["categoria_id"]),
        "defaultLanguage": pub["idioma"],
        "defaultAudioLanguage": pub["idioma"],
    }
    status = {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False,
              "containsSyntheticMedia": bool(livro.ficha.get("voz_sintetica", False))}
    video_id = youtube.enviar_video(video, snippet, status)
    registro["short"] = video_id
    log.info("  Short publicado: %s (%.0f s)", video_id, duracao)
    return video_id


def exemplo_local(capa: Path | None, audio: Path, palavras: list[Palavra], cfg: dict, saida: Path) -> Path:
    """Gera um Short sem acessar o Google (para conferir o visual)."""
    with tempfile.TemporaryDirectory() as tmp:
        trecho = escolher_trecho(palavras)
        inicio = max(trecho[0].inicio - 0.15, 0)
        duracao = min(trecho[-1].fim - inicio + 0.6, 59)
        arte = gerar_arte_vertical(capa, Path(tmp) / "arte.png", "Livro de Teste", "Capítulo 1", cfg["video"])
        return renderizar_short(arte, audio, inicio, duracao, gerar_ass(trecho), saida)
