"""Shorts do modo Bíblia: a leitura de cada dia também sai em vídeos verticais de até ~3 minutos.

Cada capítulo do dia é transcrito (uma vez só; a transcrição fica no Drive) e dividido em partes de tamanho
parecido, sempre num fim de frase, sem passar de `max_segundos` (o YouTube trata como Short o vídeo vertical de até
3 min). Cada parte vira um Short com legenda grande na tela, no visual das artes do canal, e entra na playlist
dos Shorts. A descrição leva o link da leitura completa do dia.
"""

import json
import math
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageOps

import arte_biblia
from comum import log
from cortar import Palavra

LARGURA, ALTURA = 1080, 1920
_FIM = (".", "!", "?", "…", ";", ":")
PASTA_TRANSCRICOES = "Transcrições"

PADRAO = {
    "ativo": False,
    "max_segundos": 175,
    "dias_por_execucao": 1,
    "minutos_maximos": 45,
    "modelo_whisper": "small",
    "fundo": "",          # imagem vertical (1080x1920) do canal; vazio = montada a partir das artes da miniatura
    "titulo": "{livro} {capitulo}{parte_txt} | Bíblia em Áudio",
    "descricao": ("{livro} {capitulo}{parte_txt}: leitura em áudio da Bíblia Sagrada, Dia {dia} de {total_dias}.\n\n"
                  "▶️ Leitura completa de hoje: {link_dia}\n"
                  "📅 Comece pelo Dia 1: {link_plano}\n\n"
                  "{credito_linha}#BíbliaEmÁudio #{livro_sem_espaco} #Shorts"),
    "playlist": {"titulo": "Bíblia em 1 Ano – Shorts",
                 "descricao": "A leitura diária da Bíblia em vídeos curtos, em ordem."},
    "linha_rodape": "",
}


def config(conf_biblia: dict) -> dict:
    proprio = dict(conf_biblia.get("shorts") or {})
    saida = {**PADRAO, **proprio}
    saida["playlist"] = {**PADRAO["playlist"], **(proprio.get("playlist") or {})}
    return saida


# ---------------------------------------------------------------- divisão em partes

def dividir_partes(palavras: list[Palavra], duracao: float, maximo: float) -> list[tuple[float, float]]:
    """(início, fim) de cada parte: partes de tamanho parecido, cortadas num fim de frase, nenhuma maior que
    `maximo`. Sem fim de frase que sirva, corta na maior pausa entre palavras."""
    if duracao <= maximo or not palavras:
        return [(0.0, duracao)] if duracao <= maximo else _por_tempo(duracao, maximo)
    partes, inicio = [], 0.0
    restante = duracao
    while restante > maximo:
        n = math.ceil(restante / maximo)
        alvo = inicio + restante / n
        limite = inicio + maximo
        candidatos = [p.fim for p in palavras if inicio + 20 < p.fim <= limite and p.texto.strip().endswith(_FIM)]
        if not candidatos:   # sem pontuação: a maior pausa antes do limite
            pausas = [(b.inicio - a.fim, (a.fim + b.inicio) / 2) for a, b in zip(palavras, palavras[1:])
                      if inicio + 20 < a.fim and b.inicio <= limite]
            candidatos = [max(pausas)[1]] if pausas else [limite]
        corte = min(candidatos, key=lambda t: abs(t - alvo))
        # o corte fica no meio do silêncio depois do fim da frase (sem comer a próxima palavra)
        seguinte = next((p.inicio for p in palavras if p.inicio >= corte - 0.01), corte)
        corte = min((corte + seguinte) / 2, limite) if seguinte > corte else corte
        partes.append((inicio, corte))
        inicio = corte
        restante = duracao - inicio
    partes.append((inicio, duracao))
    return partes


def _por_tempo(duracao: float, maximo: float) -> list[tuple[float, float]]:
    n = math.ceil(duracao / maximo)
    passo = duracao / n
    return [(i * passo, (i + 1) * passo if i < n - 1 else duracao) for i in range(n)]


# ---------------------------------------------------------------- arte vertical e legenda

def arte_vertical(fundo_mini: Path | None, fundo_vertical: Path | None, destino: Path, dia: int, livro: str,
                  capitulo: int, parte: int, partes: int, rodape: str = "") -> Path:
    if fundo_vertical:
        tela = ImageOps.fit(Image.open(fundo_vertical).convert("RGB"), (LARGURA, ALTURA))
    elif fundo_mini:
        mini = Image.open(fundo_mini).convert("RGB").resize((1280, 720))
        tela = ImageOps.fit(mini.crop((60, 40, 760, 680)), (LARGURA, ALTURA)).filter(ImageFilter.GaussianBlur(2))
        icone = mini.crop((815, 200, 1205, 545))
        icone = icone.resize((int(icone.width * 1.5), int(icone.height * 1.5)))
        mascara = Image.new("L", icone.size, 0)
        ImageDraw.Draw(mascara).ellipse((10, 10, icone.width - 10, icone.height - 10), fill=255)
        tela.paste(icone, ((LARGURA - icone.width) // 2, 200), mascara.filter(ImageFilter.GaussianBlur(25)))
    else:
        tela = Image.new("RGB", (LARGURA, ALTURA), "#efe3c8")
    d = ImageDraw.Draw(tela)
    # moldura dupla dourada, como nas outras artes
    d.rectangle((24, 24, LARGURA - 25, ALTURA - 25), outline=arte_biblia.DOURADO, width=5)
    d.rectangle((40, 40, LARGURA - 41, ALTURA - 41), outline=arte_biblia.DOURADO, width=2)

    selo = f"DIA {dia}"
    fonte = arte_biblia.lora(70)
    w = d.textlength(selo, font=fonte) + 80
    d.rounded_rectangle(((LARGURA - w) / 2, 780, (LARGURA + w) / 2, 900), radius=16, fill=arte_biblia.MARROM)
    d.text((LARGURA / 2, 840), selo, font=fonte, fill=arte_biblia.CREME, anchor="mm")
    titulo = f"{livro} {capitulo}"
    d.text((LARGURA / 2, 1060), titulo, font=arte_biblia._caber(d, titulo, arte_biblia.titulo_fonte, 150, 940),
           fill=arte_biblia.MARROM, anchor="ms")
    if partes > 1:
        d.text((LARGURA / 2, 1150), f"Parte {parte} de {partes}", font=arte_biblia.lora(64),
               fill=arte_biblia.DOURADO, anchor="ms")
    if rodape:
        d.text((LARGURA / 2, ALTURA - 110), rodape,
               font=arte_biblia._caber(d, rodape, lambda t: arte_biblia.lora(t, "Medium"), 44, 900),
               fill=arte_biblia.TEXTO, anchor="ms")
    destino.parent.mkdir(parents=True, exist_ok=True)
    tela.save(destino)
    return destino


def _tempo_ass(seg: float) -> str:
    cs = int(round(max(seg, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def gerar_ass(palavras: list[Palavra], inicio: float, fim: float, por_tela: int = 4) -> str:
    """Legenda em letras grandes, marrom com contorno claro, na parte de baixo da tela."""
    cabecalho = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {LARGURA}", f"PlayResY: {ALTURA}", "WrapStyle: 0",
        "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        # cor ASS = &HAABBGGRR: marrom #3C2415 com contorno creme
        "Style: Fala,Lora,112,&H0015243C,&H0015243C,&H00D8EBF5,&H00000000,-1,0,0,0,100,100,0,0,1,5,0,2,80,80,520,1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    trecho = [p for p in palavras if p.inicio >= inicio - 0.05 and p.fim <= fim + 0.05]
    eventos, grupo = [], []
    for i, p in enumerate(trecho):
        grupo.append(p)
        ultimo = i == len(trecho) - 1
        if len(grupo) >= por_tela or p.texto.strip().endswith(_FIM + (",",)) or ultimo:
            ini = grupo[0].inicio - inicio
            fim_ev = (trecho[i + 1].inicio - inicio) if not ultimo else (p.fim - inicio + 0.6)
            texto = " ".join(w.texto.strip() for w in grupo).replace("{", "(").replace("}", ")").replace("\\", "")
            eventos.append(f"Dialogue: 0,{_tempo_ass(ini)},{_tempo_ass(fim_ev)},Fala,,0,0,0,,{texto}")
            grupo = []
    return "\n".join(cabecalho + eventos) + "\n"


def renderizar(arte: Path, audio: Path, inicio: float, fim: float, ass: str, destino: Path) -> Path:
    import subprocess
    pasta = destino.parent
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "legenda.ass").write_text(ass, encoding="utf-8")
    duracao = fim - inicio
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-loop", "1", "-framerate", "15", "-i", str(arte.resolve()),
        "-ss", f"{inicio:.2f}", "-t", f"{duracao:.2f}", "-i", str(audio.resolve()),
        "-vf", f"ass=legenda.ass:fontsdir={arte_biblia.FONTES}", "-map", "0:v", "-map", "1:a",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", "15",
        "-c:a", "aac", "-b:a", "128k", "-af", f"afade=t=out:st={max(duracao - 0.6, 0):.2f}:d=0.6",
        "-t", f"{duracao:.2f}", "-movflags", "+faststart", str(destino.resolve())], check=True, cwd=pasta)
    return destino


# ---------------------------------------------------------------- transcrição guardada no Drive

def palavras_do_capitulo(drive, raiz: str, cap, audio: Path, modelo: str) -> list[Palavra]:
    from cortar import transcrever
    pasta = drive.pasta(raiz, PASTA_TRANSCRICOES)
    nome = f"{cap.ordem_livro:02d} {cap.livro} {cap.numero:03d}.json"
    item = drive.achar(pasta, nome)
    if item:
        return [Palavra(*p) for p in json.loads(drive.ler_texto(item["id"]))]
    palavras = transcrever(audio, modelo)
    drive.gravar_texto(pasta, nome, json.dumps([[p.texto, p.inicio, p.fim] for p in palavras], ensure_ascii=False),
                       "application/json")
    return palavras


# ---------------------------------------------------------------- publicação

def publicar_shorts(drive, youtube, raiz: str, cfg: dict, conf: dict, plano, estado: dict,
                    dry_run: bool = False, transcrever_fn=None) -> int:
    """Publica os Shorts dos dias que já têm o vídeo longo e ainda não têm Shorts. Devolve quantos Shorts saíram."""
    from biblia import _baixar_imagem, _playlist, _preencher, _sem_espaco, campos, link_video
    from google_api import LimiteDiario
    from video import duracao_audio

    sconf = config(conf)
    if not sconf.get("ativo"):
        return 0
    dias_feitos = estado.get("dias") or {}
    shorts = estado.setdefault("shorts", {})
    pendentes = [int(d) for d in sorted(dias_feitos, key=int) if not (shorts.get(d) or {}).get("completo")]
    pendentes = pendentes[:int(sconf.get("dias_por_execucao") or 1)]
    if not pendentes:
        return 0
    prazo = time.monotonic() + float(sconf.get("minutos_maximos") or 45) * 60
    privacidade = conf.get("privacidade") or "private"
    idioma = (cfg.get("publicacao") or {}).get("idioma", "pt-BR")
    transcrever_fn = transcrever_fn or (lambda cap, audio: palavras_do_capitulo(
        drive, raiz, cap, audio, sconf.get("modelo_whisper") or "small"))
    publicados = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        fundo_mini = _baixar_imagem(drive, raiz, (conf.get("miniatura") or {}).get("fundo") or "", tmp / "mini")
        fundo_vertical = _baixar_imagem(drive, raiz, sconf.get("fundo") or "", tmp / "vertical")
        for dia in pendentes:
            caps = plano[dia - 1]
            registro = shorts.setdefault(str(dia), {"videos": {}})
            valores_dia = campos(conf, dia, len(plano), caps, None, estado, cta=cfg.get("cta"))
            valores_dia["link_dia"] = link_video(dias_feitos[str(dia)]["video_id"])
            for cap in caps:
                chave_cap = f"{cap.livro} {cap.numero}"
                audio = drive.baixar(cap.arquivo["id"], tmp / "audios" / f"{cap.ordem_livro}_{cap.numero}.mp3")
                duracao = duracao_audio(audio)
                palavras = transcrever_fn(cap, audio)
                partes = dividir_partes(palavras, duracao, float(sconf["max_segundos"]))
                for n, (ini, fim) in enumerate(partes, start=1):
                    chave = f"{chave_cap} #{n}"
                    if chave in registro["videos"]:
                        continue
                    if time.monotonic() > prazo:
                        log.info("Shorts: tempo de hoje acabou; continua na próxima execução.")
                        return publicados
                    v = {**valores_dia, "livro": cap.livro, "capitulo": cap.numero, "parte": n,
                         "partes": len(partes), "livro_sem_espaco": _sem_espaco(cap.livro),
                         "parte_txt": f" – parte {n} de {len(partes)}" if len(partes) > 1 else ""}
                    titulo = " ".join(_preencher(sconf["titulo"], v).split())[:100]
                    descricao = _preencher(sconf["descricao"], v).strip()[:5000]
                    if dry_run:
                        log.info("[dry-run] Short do dia %d: %d s", dia, int(fim - ini))
                        continue
                    arte = arte_vertical(fundo_mini, fundo_vertical, tmp / "arte.png", dia, cap.livro, cap.numero,
                                         n, len(partes), _preencher(sconf.get("linha_rodape") or "", v))
                    video = renderizar(arte, audio, ini, fim, gerar_ass(palavras, ini, fim), tmp / "short" / "s.mp4")
                    snippet = {"title": titulo, "description": descricao, "categoryId": str(conf.get("categoria_id") or "27"),
                               "tags": [f"{cap.livro} {cap.numero}", "Bíblia em áudio", "Shorts"],
                               "defaultLanguage": idioma, "defaultAudioLanguage": idioma}
                    try:
                        vid = youtube.enviar_video(video, snippet, {"privacyStatus": privacidade,
                                                                    "selfDeclaredMadeForKids": False})
                    except LimiteDiario as motivo:
                        log.warning("Shorts: limite diário do YouTube (%s); continua amanhã.", motivo)
                        drive.gravar_json(raiz, "biblia.json", estado)
                        return publicados
                    registro["videos"][chave] = vid
                    publicados += 1
                    log.info("Short do dia %d enviado (%d s): %s", dia, int(fim - ini), vid)
                    try:
                        pl = _playlist(youtube, estado, "shorts", {"playlists": {"shorts": sconf["playlist"]}},
                                       v, privacidade)
                        youtube.adicionar_na_playlist(pl, vid)
                    except Exception as erro:
                        log.warning("Short fora da playlist: %s", erro)
                    drive.gravar_json(raiz, "biblia.json", estado)
            if not dry_run:
                registro["completo"] = True
                drive.gravar_json(raiz, "biblia.json", estado)
    return publicados


def estimativa(plano, max_segundos: float = 175, bytes_por_segundo: float = 3000) -> tuple[int, float]:
    """(total de Shorts, média por dia) pelo tamanho dos arquivos (áudio de 24 kbps = 3.000 bytes por segundo)."""
    total = sum(max(1, math.ceil((c.tamanho / bytes_por_segundo) / max_segundos)) for dia in plano for c in dia)
    return total, total / max(1, len(plano))
