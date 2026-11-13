"""Modo Bíblia: um vídeo por dia com a leitura do plano "Bíblia em 1 ano".

Liga com `modo: biblia` no canal.yaml. As pastas ficam assim no Drive (dentro da pasta raiz do canal):

  <pasta dos áudios>/            (canal.yaml > biblia > pasta_audios)
    01 Gênesis/  01ge01.mp3, 01ge02.mp3, ...   (o último número do nome do arquivo é o capítulo)
    02 Êxodo/    ...
    40 Mateus/   ...                            (a pasta 40 em diante é o Novo Testamento)

Os capítulos, na ordem das pastas, são divididos em `dias` leituras de tamanho parecido (pelo tamanho dos
arquivos). Cada dia vira um vídeo com título, descrição (com minutagem e o crédito da tradução), miniatura e três
playlists (o plano, o Testamento e o livro). O vídeo do dia anterior ganha o link "Leitura de amanhã".
Tudo o que é texto do canal vem do canal.yaml; os modelos daqui são só o padrão.
"""

import re
import tempfile
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import discreto
from comum import eh_audio, log, normalizar

ARQ_ESTADO = "biblia.json"
PRIMEIRO_LIVRO_NT = 40
LIMITE_BOM = 70
LIMITE_TITULO = 100

PADRAO = {
    "pasta_audios": "Áudios",
    "dias": 365,
    "videos_por_dia": 1,
    "privacidade": "private",
    "titulo": "{referencia} | Bíblia em Áudio | Dia {dia} de {total_dias}",
    "titulo_curto": "{referencia} | Dia {dia} de {total_dias}",
    "descricao": (
        "{referencia} em áudio: leitura completa da Bíblia Sagrada, Dia {dia} de {total_dias}.\n\n"
        "📖 Leitura de hoje: {referencia}\n"
        "📅 Plano Bíblia em 1 Ano: Dia {dia} de {total_dias}\n"
        "▶️ Comece pelo Dia 1: {link_plano}\n"
        "⏭️ Leitura de amanhã: {link_proximo}\n\n"
        "{minutagem}"
        "{credito_linha}"
        "{hashtags}"
    ),
    "sem_proximo": "sai amanhã, no mesmo horário",
    "credito": "",
    "hashtags": ["#BíbliaEmÁudio", "#{livro_sem_espaco}", "#BíbliaEm1Ano"],
    "tags": ["Bíblia em áudio", "Bíblia Sagrada", "Bíblia falada", "Bíblia narrada", "Bíblia em 1 ano",
             "leitura bíblica diária", "ouvir a Bíblia", "Palavra de Deus", "biblia em audio"],
    "comentario": "",
    "playlists": {
        "plano": {"titulo": "Bíblia em 1 Ano – Leitura Diária (Dia 1 ao {total_dias})",
                  "descricao": "A Bíblia Sagrada completa em áudio, um vídeo por dia, em ordem. Comece pelo Dia 1."},
        "at": {"titulo": "Antigo Testamento em Áudio – Bíblia Completa",
               "descricao": "Todos os livros do Antigo Testamento em áudio, de Gênesis a Malaquias."},
        "nt": {"titulo": "Novo Testamento em Áudio – Bíblia Completa",
               "descricao": "Todos os livros do Novo Testamento em áudio, de Mateus ao Apocalipse."},
        "livro": {"titulo": "{livro} Completo em Áudio – Bíblia Sagrada",
                  "descricao": "O livro de {livro} completo em áudio, capítulo por capítulo."},
    },
    "imagem": "",          # imagem opcional (caminho no Drive a partir da raiz, ex.: "Artes/fundo.png")
    # Artes do canal (caminhos no Drive a partir da raiz). Vazio = o robô desenha um fundo liso.
    "fundo_video": "",     # imagem que aparece durante a leitura (1920x1080)
    "tela_final": "",      # imagem dos últimos segundos (1920x1080), com os espaços da tela final do YouTube
    "tela_final_segundos": 20,
    "miniatura": {"fundo": "", "linha1": "", "linha2": ""},   # fundo sem texto (1280x720) + 2 linhas embaixo
    "categoria_id": "27",
}


@dataclass
class Capitulo:
    livro: str
    ordem_livro: int
    numero: int
    arquivo: dict

    @property
    def tamanho(self) -> int:
        try:
            return int(self.arquivo.get("size") or 0)
        except (TypeError, ValueError):
            return 0


def config(cfg: dict) -> dict:
    """canal.yaml > biblia, por cima do padrão (as playlists são mescladas uma a uma)."""
    proprio = dict(cfg.get("biblia") or {})
    saida = {**PADRAO, **proprio}
    saida["miniatura"] = {**PADRAO["miniatura"], **(proprio.get("miniatura") or {})}
    saida["playlists"] = {k: {**v, **((proprio.get("playlists") or {}).get(k) or {})}
                          for k, v in PADRAO["playlists"].items()}
    return saida


def ligado(cfg: dict) -> bool:
    return str(cfg.get("modo") or "").strip().lower() == "biblia"


# ---------------------------------------------------------------- capítulos e plano

def ordem_e_nome(pasta: str) -> tuple[int, str] | None:
    """'01 Gênesis' -> (1, 'Gênesis'); '49 - Efésios' -> (49, 'Efésios'); '34  Naum' -> (34, 'Naum')."""
    m = re.match(r"^\s*(\d{1,3})\s*[-–.]?\s*(.+?)\s*$", unicodedata.normalize("NFC", pasta))
    return (int(m.group(1)), " ".join(m.group(2).split())) if m else None


def numero_do_arquivo(nome: str) -> int | None:
    """'01ge01.mp3' -> 1; 'Gênesis 12.mp3' -> 12; '19sl150.mp3' -> 150 (o último número do nome)."""
    numeros = re.findall(r"\d+", Path(nome).stem)
    return int(numeros[-1]) if numeros else None


def capitulos_da_biblia(drive, pasta_audios: str) -> tuple[list[Capitulo], list[str]]:
    """Todos os capítulos, na ordem dos livros e dos capítulos, e uma lista de avisos (buracos, repetidos)."""
    capitulos, avisos = [], []
    pastas = []
    for item in drive.listar(pasta_audios):
        if drive.eh_pasta(item) and (on := ordem_e_nome(item["name"])):
            pastas.append((on[0], on[1], item))
    for ordem, livro, pasta in sorted(pastas, key=lambda p: p[0]):
        vistos = {}
        for arq in drive.listar(pasta["id"]):
            if drive.eh_pasta(arq) or not eh_audio(arq["name"]):
                continue
            n = numero_do_arquivo(arq["name"])
            if n is None:
                avisos.append(f"{livro}: arquivo sem número de capítulo ({arq['name']})")
            elif n in vistos:
                avisos.append(f"{livro} {n}: capítulo repetido; usei o primeiro")
            else:
                vistos[n] = arq
        if not vistos:
            avisos.append(f"{livro}: pasta sem áudios")
            continue
        faltam = sorted(set(range(1, max(vistos) + 1)) - set(vistos))
        if faltam:
            avisos.append(f"{livro}: faltam os capítulos {', '.join(map(str, faltam))}")
        capitulos += [Capitulo(livro, ordem, n, vistos[n]) for n in sorted(vistos)]
    return capitulos, avisos


def dividir(capitulos: list[Capitulo], dias: int) -> list[list[Capitulo]]:
    """Divide os capítulos (em ordem) em `dias` leituras de tamanho parecido. Arquivos sem tamanho contam igual."""
    if not capitulos:
        return []
    dias = max(1, min(dias, len(capitulos)))
    pesos = [c.tamanho for c in capitulos]
    if not all(pesos):
        pesos = [1] * len(capitulos)
    total = sum(pesos)
    acumulado, soma = [], 0
    for p in pesos:
        soma += p
        acumulado.append(soma)
    cortes, inicio = [], 0
    for k in range(1, dias):
        alvo = total * k / dias
        # o corte fica entre o primeiro capítulo possível e o último que ainda deixa um por dia restante
        menor, maior = inicio + 1, len(capitulos) - (dias - k)
        melhor = min(range(menor, maior + 1), key=lambda i: abs(acumulado[i - 1] - alvo))
        cortes.append(melhor)
        inicio = melhor
    limites = [0, *cortes, len(capitulos)]
    return [capitulos[a:b] for a, b in zip(limites, limites[1:])]


def _lista(numeros: list[int]) -> str:
    if len(numeros) == 1:
        return str(numeros[0])
    if len(numeros) <= 3:
        return ", ".join(map(str, numeros[:-1])) + f" e {numeros[-1]}"
    return f"{numeros[0]} a {numeros[-1]}"


def referencia(capitulos: list[Capitulo]) -> str:
    """'Gênesis 1, 2 e 3', 'Salmos 23 a 27', 'Salmo 23', 'Rute 4 e 1 Samuel 1 e 2'."""
    partes = []
    for livro, grupo in _por_livro(capitulos):
        numeros = [c.numero for c in grupo]
        nome = "Salmo" if normalizar(livro) == "salmos" and len(numeros) == 1 else livro
        partes.append(f"{nome} {_lista(numeros)}")
    return " e ".join(partes)


def _por_livro(capitulos: list[Capitulo]) -> list[tuple[str, list[Capitulo]]]:
    grupos: list[tuple[str, list[Capitulo]]] = []
    for c in capitulos:
        if grupos and grupos[-1][0] == c.livro:
            grupos[-1][1].append(c)
        else:
            grupos.append((c.livro, [c]))
    return grupos


# ---------------------------------------------------------------- textos

class _Campos(dict):
    def __missing__(self, chave):
        return ""


def _preencher(modelo: str, campos: dict) -> str:
    return str(modelo or "").format_map(_Campos(campos))


def _tempo(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def _sem_espaco(texto: str) -> str:
    return re.sub(r"[^\w]", "", texto.replace(" ", ""))


def link_video(video_id: str | None) -> str:
    return f"https://youtu.be/{video_id}" if video_id else ""


def link_playlist(playlist_id: str | None) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}" if playlist_id else ""


def campos(conf: dict, dia: int, total_dias: int, caps: list[Capitulo], inicios: list[float] | None,
           estado: dict, proximo_id: str | None = None, cta: dict | None = None) -> dict:
    ref = referencia(caps)
    livro = caps[0].livro
    minutagem = ""
    if inicios and len(caps) >= 3:   # o YouTube só cria capítulos clicáveis com 3 marcações ou mais
        minutagem = "Capítulos deste vídeo:\n" + "\n".join(
            f"{_tempo(t)} {c.livro} {c.numero}" for c, t in zip(caps, inicios)) + "\n\n"
    base = {"referencia": ref, "dia": dia, "total_dias": total_dias, "livro": livro,
            "livro_sem_espaco": _sem_espaco(livro)}
    hashtags = " ".join(_preencher(h, base) for h in conf.get("hashtags") or [])
    playlists = estado.get("playlists") or {}
    credito = str(conf.get("credito") or "").strip()
    return {**base, "minutagem": minutagem, "credito": credito, "hashtags": hashtags,
            "credito_linha": f"Texto bíblico: {credito}\n\n" if credito else "",
            "link_plano": link_playlist(playlists.get("plano")) or "playlist do plano no canal",
            "link_livro": link_playlist(playlists.get(f"livro:{livro}")),
            "link_at": link_playlist(playlists.get("at")), "link_nt": link_playlist(playlists.get("nt")),
            "link_proximo": link_video(proximo_id) or conf.get("sem_proximo", ""),
            "link_canal": (cta or {}).get("canal", "")}


def titulo(conf: dict, valores: dict) -> str:
    texto = " ".join(_preencher(conf["titulo"], valores).split())
    if len(texto) > LIMITE_BOM and conf.get("titulo_curto"):
        texto = " ".join(_preencher(conf["titulo_curto"], valores).split())
    return texto.replace("<", "‹").replace(">", "›")[:LIMITE_TITULO]


def descricao(conf: dict, valores: dict) -> str:
    texto = _preencher(conf["descricao"], valores)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    return texto.replace("<", "‹").replace(">", "›")[:5000]


def tags(conf: dict, caps: list[Capitulo]) -> list[str]:
    do_dia = [f"{c.livro} {c.numero}" for c in caps[:4]]
    do_dia += [f"{caps[0].livro} em áudio", f"{caps[0].livro} completo", normalizar(f"{caps[0].livro} {caps[0].numero}")]
    saida, total = [], 0
    for t in dict.fromkeys(do_dia + list(conf.get("tags") or [])):
        if total + len(t) + 1 > 450:
            break
        saida.append(t)
        total += len(t) + 1
    return saida


def snippet(conf: dict, valores: dict, caps: list[Capitulo], idioma: str) -> dict:
    return {"title": titulo(conf, valores), "description": descricao(conf, valores), "tags": tags(conf, caps),
            "categoryId": str(conf.get("categoria_id") or "27"), "defaultLanguage": idioma,
            "defaultAudioLanguage": idioma}


# ---------------------------------------------------------------- publicação

def _testamentos(caps: list[Capitulo]) -> list[str]:
    return list(dict.fromkeys("nt" if c.ordem_livro >= PRIMEIRO_LIVRO_NT else "at" for c in caps))


def _playlist(youtube, estado: dict, chave: str, conf: dict, valores: dict, privacidade: str) -> str:
    playlists = estado.setdefault("playlists", {})
    if not playlists.get(chave):
        modelo = conf["playlists"]["livro" if chave.startswith("livro:") else chave]
        playlists[chave] = youtube.criar_playlist(_preencher(modelo["titulo"], valores),
                                                  _preencher(modelo.get("descricao", ""), valores), privacidade)
    return playlists[chave]


def _achar(drive, pasta_id: str, nome: str) -> dict | None:
    """Como drive.achar, mas sem ligar para acento composto ou não (o Mac envia "í" como "i" + acento),
    maiúsculas e espaços sobrando."""
    alvo = normalizar(" ".join(unicodedata.normalize("NFC", nome).split()))
    return next((i for i in drive.listar(pasta_id)
                 if normalizar(" ".join(unicodedata.normalize("NFC", i["name"]).split())) == alvo), None)


def _ajustar(imagem: Path, largura: int, altura: int, destino: Path) -> Path:
    from PIL import Image, ImageOps
    ImageOps.fit(Image.open(imagem).convert("RGB"), (largura, altura)).save(destino)
    return destino


def estilo_miniatura(conf: dict) -> str:
    """Muda quando o modelo da miniatura muda: os dias já publicados ganham a miniatura nova."""
    import hashlib
    import json
    return hashlib.sha1(json.dumps(conf.get("miniatura") or {}, sort_keys=True).encode()).hexdigest()[:10]


def fazer_miniatura(drive, raiz: str, conf: dict, cores: dict, dia: int, total_dias: int, caps: list[Capitulo],
                    valores: dict, imagem, tmp: Path) -> Path:
    import arte_biblia
    from video import gerar_arte
    modelo = conf.get("miniatura") or {}
    fundo = _baixar_imagem(drive, raiz, modelo.get("fundo") or "", tmp / "mini")
    if fundo:
        return arte_biblia.miniatura(fundo, tmp / f"miniatura_{dia}.jpg", dia, [(c.livro, c.numero) for c in caps],
                                     _preencher(modelo.get("linha1", ""), valores),
                                     _preencher(modelo.get("linha2", ""), valores))
    return gerar_arte(imagem, tmp / f"miniatura_{dia}.jpg", valores["referencia"], "", f"Dia {dia}", "", 1280, 720,
                      cores, miniatura=True)


def com_tela_final(video: Path, tela: Path, segundos: float, destino: Path) -> Path:
    """Acrescenta a tela final (imagem parada, em silêncio) no fim do vídeo."""
    import subprocess
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", str(video),
        "-loop", "1", "-framerate", "1", "-t", f"{segundos:.0f}", "-i", str(tela),
        "-f", "lavfi", "-t", f"{segundos:.0f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-filter_complex",
        "[0:v]format=yuv420p,setsar=1,fps=1[v0];[1:v]format=yuv420p,setsar=1,fps=1[v1];"
        "[0:a]aresample=48000,aformat=channel_layouts=stereo[a0];[v0][a0][v1][2:a]concat=n=2:v=1:a=1[v][a]",
        "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(destino)],
        check=True)
    return destino


def atualizar_miniaturas(drive, youtube, raiz: str, cfg: dict, conf: dict, plano, estado: dict) -> None:
    """Dias já publicados com um modelo de miniatura antigo ganham a miniatura nova (sem reenviar o vídeo)."""
    estilo = estilo_miniatura(conf)
    pendentes = [d for d, r in (estado.get("dias") or {}).items() if r.get("miniatura") != estilo]
    if not pendentes or not (conf.get("miniatura") or {}).get("fundo"):
        return
    cores = {**cfg["video"], **(conf.get("cores") or {})}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for d in sorted(pendentes, key=int)[:20]:
            caps = plano[int(d) - 1]
            valores = campos(conf, int(d), len(plano), caps, None, estado, cta=cfg.get("cta"))
            try:
                arquivo = fazer_miniatura(drive, raiz, conf, cores, int(d), len(plano), caps, valores, None, tmp)
                youtube.definir_miniatura(estado["dias"][d]["video_id"], arquivo)
                estado["dias"][d]["miniatura"] = estilo
                log.info("Dia %s: miniatura trocada pelo modelo novo.", d)
            except Exception as erro:
                log.warning("Não consegui trocar a miniatura do dia %s: %s", d, erro)
    drive.gravar_json(raiz, ARQ_ESTADO, estado)


def _baixar_imagem(drive, raiz: str, caminho: str, destino_dir: Path) -> Path | None:
    if not caminho:
        return None
    pasta = raiz
    partes = [p for p in caminho.split("/") if p]
    for parte in partes[:-1]:
        achado = _achar(drive, pasta, parte)
        if not achado:
            return None
        pasta = achado["id"]
    arquivo = _achar(drive, pasta, partes[-1])
    if not arquivo:
        log.warning("Arte não encontrada no Drive (%s); usando o padrão.", caminho)
        return None
    return drive.baixar(arquivo["id"], destino_dir / Path(partes[-1]).name)


def publicar_dia(drive, youtube, raiz: str, cfg: dict, conf: dict, plano: list[list[Capitulo]], dia: int,
                 estado: dict, dry_run: bool) -> str | None:
    from video import duracao_audio, gerar_arte, gerar_video

    caps = plano[dia - 1]
    total_dias = len(plano)
    privacidade = conf.get("privacidade") or "private"
    idioma = (cfg.get("publicacao") or {}).get("idioma", "pt-BR")
    cores = {**cfg["video"], **(conf.get("cores") or {})}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        audios, inicios, total = [], [], 0.0
        for i, c in enumerate(caps):
            audio = drive.baixar(c.arquivo["id"], tmp / "audios" / f"{i:03d}_{c.arquivo['name']}")
            inicios.append(total)
            total += duracao_audio(audio)
            audios.append(audio)
        valores = campos(conf, dia, total_dias, caps, inicios, estado, cta=cfg.get("cta"))
        dados = snippet(conf, valores, caps, idioma)
        log.info("Dia %d de %d: %d capítulo(s), %.0f min (%s)", dia, total_dias, len(caps), total / 60, privacidade)
        if dry_run:
            log.info("[dry-run] Título: %s\n%s", dados["title"], dados["description"])
            return None
        # Playlists antes do envio: assim a descrição já sai com os links delas.
        chaves = ["plano", *_testamentos(caps), *[f"livro:{livro}" for livro, _ in _por_livro(caps)]]
        for chave in chaves:
            try:
                livro = chave.split(":", 1)[1] if chave.startswith("livro:") else caps[0].livro
                _playlist(youtube, estado, chave, conf, {**valores, "livro": livro}, privacidade)
            except Exception as erro:
                log.warning("Não consegui criar a playlist %s: %s", discreto.Seguro(chave.split(":")[0]), erro)
        valores = campos(conf, dia, total_dias, caps, inicios, estado, cta=cfg.get("cta"))
        dados = snippet(conf, valores, caps, idioma)
        imagem = _baixar_imagem(drive, raiz, conf.get("imagem") or "", tmp)
        ref = valores["referencia"]
        arte = _baixar_imagem(drive, raiz, conf.get("fundo_video") or "", tmp / "fundo")
        if arte:
            arte = _ajustar(arte, cores["largura"], cores["altura"], tmp / "arte.png")
        else:
            arte = gerar_arte(imagem, tmp / "arte.png", ref, "Bíblia em Áudio", f"Dia {dia} de {total_dias}", "",
                              cores["largura"], cores["altura"], cores)
        miniatura = fazer_miniatura(drive, raiz, conf, cores, dia, total_dias, caps, valores, imagem, tmp)
        video = gerar_video(arte, audios, tmp / "video.mp4", cores.get("copiar_audio", True))
        tela = _baixar_imagem(drive, raiz, conf.get("tela_final") or "", tmp / "tela")
        if tela and float(conf.get("tela_final_segundos") or 0) > 0:
            video = com_tela_final(video, _ajustar(tela, cores["largura"], cores["altura"], tmp / "tela.png"),
                                   float(conf["tela_final_segundos"]), tmp / "video_final.mp4")
        status = {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False,
                  "containsSyntheticMedia": bool(conf.get("voz_sintetica", False))}
        video_id = youtube.enviar_video(video, dados, status)
        log.info("Dia %d enviado: %s", dia, video_id)
        estado.setdefault("dias", {})[str(dia)] = {"miniatura": estilo_miniatura(conf),
            "video_id": video_id, "data": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "capitulos": [[c.livro, c.numero] for c in caps], "inicios": [round(t, 1) for t in inicios]}
        drive.gravar_json(raiz, ARQ_ESTADO, estado)   # grava logo: se algo abaixo falhar, o dia não é reenviado

        try:
            youtube.definir_miniatura(video_id, miniatura)
        except Exception as erro:
            log.warning("Não consegui definir a miniatura: %s", erro)
        for chave in chaves:
            if not (estado.get("playlists") or {}).get(chave):
                continue
            try:
                youtube.adicionar_na_playlist(estado["playlists"][chave], video_id)
            except Exception as erro:
                log.warning("Não consegui pôr o dia %d na playlist %s: %s", dia, discreto.Seguro(chave.split(":")[0]), erro)
        if privacidade == "public" and conf.get("comentario"):
            try:
                youtube.comentar(video_id, _preencher(conf["comentario"], valores))
            except Exception as erro:
                log.warning("Não consegui comentar: %s", erro)
        _link_no_anterior(youtube, conf, cfg, plano, dia, estado, video_id, idioma)
        drive.gravar_json(raiz, ARQ_ESTADO, estado)
    return video_id


def _link_no_anterior(youtube, conf, cfg, plano, dia, estado, video_id, idioma) -> None:
    anterior = (estado.get("dias") or {}).get(str(dia - 1))
    if not anterior:
        return
    caps = plano[dia - 2]
    valores = campos(conf, dia - 1, len(plano), caps, anterior.get("inicios"), estado, proximo_id=video_id,
                     cta=cfg.get("cta"))
    try:
        youtube.atualizar_metadados(anterior["video_id"], snippet(conf, valores, caps, idioma))
        anterior["proximo"] = video_id
    except Exception as erro:
        log.warning("Não consegui pôr o link de amanhã no dia %d: %s", dia - 1, erro)


def rodar(drive, youtube, raiz: str, cfg: dict, dry_run: bool = False, dia_pedido: int | None = None,
          quantos: int | None = None) -> int:
    from google_api import LimiteDiario

    conf = config(cfg)
    pasta = _achar(drive, raiz, conf["pasta_audios"])
    if not pasta:
        log.error("Não achei a pasta dos áudios da Bíblia (canal.yaml > biblia > pasta_audios).")
        return 1
    caps, avisos = capitulos_da_biblia(drive, pasta["id"])
    for aviso in avisos:
        log.warning("Bíblia: %s", aviso)
    plano = dividir(caps, int(conf["dias"]))
    if not plano:
        log.error("Nenhum capítulo encontrado na pasta dos áudios.")
        return 1
    estado = drive.ler_json(raiz, ARQ_ESTADO, {"dias": {}})
    if not estado.get("plano"):   # o plano fica gravado: arquivos novos depois não mudam os dias já publicados
        estado["plano"] = [[[c.livro, c.numero] for c in dia] for dia in plano]
    else:
        por_ref = {(c.livro, c.numero): c for c in caps}
        gravado = [[por_ref.get((l, n)) for l, n in dia] for dia in estado["plano"]]
        if all(all(dia) for dia in gravado):
            plano = gravado
        else:
            log.warning("O plano gravado cita capítulos que não estão mais na pasta; usando a divisão nova.")
    log.info("Bíblia: %d capítulos em %d dias; %d dia(s) já publicados.", len(caps), len(plano),
             len(estado.get("dias") or {}))

    if not dry_run:
        atualizar_miniaturas(drive, youtube, raiz, cfg, conf, plano, estado)
    if dia_pedido:
        pendentes = [dia_pedido]
    else:
        feitos = {int(d) for d in (estado.get("dias") or {})}
        hoje = datetime.now(timezone.utc).date().isoformat()
        ja_hoje = sum(1 for r in (estado.get("dias") or {}).values() if str(r.get("data", "")).startswith(hoje))
        limite = quantos if quantos is not None else int(conf.get("videos_por_dia") or 1) - ja_hoje
        pendentes = [d for d in range(1, len(plano) + 1) if d not in feitos][:max(0, limite)]
        if not pendentes:
            log.info("Bíblia: nada para publicar agora (o dia de hoje já saiu ou o plano terminou).")
    for dia in pendentes:
        if not 1 <= dia <= len(plano):
            log.error("Dia %d fora do plano (1 a %d).", dia, len(plano))
            return 1
        try:
            publicar_dia(drive, youtube, raiz, cfg, conf, plano, dia, estado, dry_run)
        except LimiteDiario as motivo:
            log.warning("Limite diário do YouTube (%s); continua amanhã.", motivo)
            return 0
    # Shorts: a leitura dos dias já publicados também em vídeos verticais (canal.yaml > biblia > shorts)
    import shorts_biblia
    sconf = shorts_biblia.config(conf)
    if sconf.get("ativo"):
        total, media = shorts_biblia.estimativa(plano, float(sconf["max_segundos"]))
        log.info("Shorts: cerca de %d no plano (média de %.1f por dia).", total, media)
        try:
            feitos = shorts_biblia.publicar_shorts(drive, youtube, raiz, cfg, conf, plano, estado, dry_run)
            log.info("Shorts publicados nesta execução: %d", feitos)
        except LimiteDiario as motivo:
            log.warning("Limite diário do YouTube nos Shorts (%s); continua amanhã.", motivo)
    return 0
