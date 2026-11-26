"""Miniaturas novas dos vídeos já publicados (para trocar à mão no YouTube Studio) e capas quadradas de podcast.

Lê as fotos da pasta "Capas novas" (dentro da raiz do Drive), cada uma com o código do livro no nome:
"P07 - São Bernardo.jpg" (também .png, .webp, .avif). Para cada livro com foto:

- uma miniatura 1280x720 por vídeo publicado, no visual do canal (src/arte_selo.py), na pasta
  "<marca_curta> - Miniaturas prontas/P07 - São Bernardo/Cap 03 - <título do vídeo>.jpg";
- uma planilha "Miniaturas - lista" na mesma pasta, com o link do Studio de cada vídeo;
- uma capa quadrada 3000x3000 (serve para o podcast do YouTube e para o Spotify) em
  "<marca_curta> - Capas de podcast/P07 - São Bernardo.jpg".

As pastas de saída ficam AO LADO da raiz (nunca dentro: lá o robô acharia que são livros).
Nada muda no YouTube: só lê a lista de vídeos do canal (umas 20 unidades da cota).
Rodar de novo é seguro: o que já existe é pulado (use --refazer para gerar de novo).

Uso:
  python src/miniaturas_prontas.py                 # todos os livros com foto
  python src/miniaturas_prontas.py --so P07 P30    # só estes
  python src/miniaturas_prontas.py --dry-run       # só conta, não grava nada
"""

import argparse
import csv
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from comum import carregar_config, configurar_log, log, normalizar

PASTA_CAPAS = "capas novas"
EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".avif"}
_CODIGO = re.compile(r"^\s*([PF]\d{2,3})\s*[-–—_.]\s*(.+?)\s*$", re.IGNORECASE)
_NUMERO_ANTIGO = re.compile(r"(?:parte|part|vol(?:ume)?\.?|cap(?:[íi]tulo)?\.?)\s*(\d+)|(\d+)\s*/\s*\d+", re.IGNORECASE)
_DURACAO = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
MIN_SEGUNDOS = 181    # mais curto que isso é Short (fica de fora)
PLANILHA = "Miniaturas - lista"
# Lista opcional na pasta "Capas novas" para dar nome às fotos que chegaram com nome qualquer, uma por linha:
#   <ID do arquivo no Drive ou nome atual> => P35 - A Mão e a Luva.jpg
# O robô renomeia, e a lista vai para a lixeira quando tudo deu certo.
ARQ_RENOMEAR = "renomear.txt"


@dataclass
class Capa:
    codigo: str
    titulo: str
    arquivo: dict


@dataclass
class Video:
    video_id: str
    rotulo: str          # "Cap. 3", "Parte 2"
    detalhe: str = ""    # "Da Estrada", "Caps. 5 a 9"
    ordem: float = 0
    titulo_youtube: str = ""


@dataclass
class Livro:
    capa: Capa
    pasta: dict | None
    nome: str = ""
    autor: str = ""
    videos: list[Video] = field(default_factory=list)


# ---------------------------------------------------------------- partes sem Drive (testáveis)

def ler_capas(itens: list[dict]) -> list[Capa]:
    """Arquivos da pasta "Capas novas" -> capas com código. Nomes fora do padrão são ignorados."""
    capas = {}
    for item in itens:
        caminho = Path(item["name"])
        m = _CODIGO.match(caminho.stem)
        if caminho.suffix.lower() in EXT_IMAGEM and m:
            codigo = m.group(1).upper()
            capas[codigo] = Capa(codigo, m.group(2), item)   # repetido: o último (em ordem de nome) vale
    return sorted(capas.values(), key=lambda c: (c.codigo[0] != "P", int(c.codigo[1:])))


def achar_pasta(titulo: str, pastas: list[tuple[dict, str]], com_registro: set) -> dict | None:
    """Pasta do livro pelo título da capa. pastas = [(pasta, nome do livro sem o autor)].
    Prefere nome igual; senão, a pasta cujo nome contém o título (a mais curta); empate: a que tem vídeos."""
    alvo = normalizar(titulo)
    iguais = [p for p, nome in pastas if normalizar(nome) == alvo]
    contem = [p for p, nome in pastas if alvo and alvo in normalizar(p["name"])]
    for grupo in (iguais, contem):
        if grupo:
            return sorted(grupo, key=lambda p: (p["id"] not in com_registro, len(p["name"])))[0]
    return None


def videos_do_registro(estado: dict, titulos: dict[int, str]) -> list[Video]:
    """publicados.json -> um Video por vídeo (vídeo com vários capítulos = uma miniatura só)."""
    from arte_selo import adaptar_rotulo
    from metadados import intervalo, rotulo_e_titulo
    grupos: dict[str, list[tuple[int, dict]]] = {}
    for n, reg in estado.get("capitulos", {}).items():
        grupos.setdefault(reg["video_id"], []).append((int(n), reg))
    saida = []
    for vid, membros in grupos.items():
        membros.sort(key=lambda x: x[0])
        primeiro, reg = membros[0]
        if reg.get("parte"):
            rot = f"Parte {reg['parte']}"
            det = intervalo([(n, titulos.get(n, "")) for n, _ in membros]) if len(membros) > 1 else \
                rotulo_e_titulo(primeiro, titulos.get(primeiro, ""))[0]
        else:
            rot, det = adaptar_rotulo(*rotulo_e_titulo(primeiro, titulos.get(primeiro, "")))
        saida.append(Video(vid, rot, det, primeiro))
    for n, vid in (estado.get("completo") or {}).get("partes", {}).items():
        saida.append(Video(vid, f"Parte {n}", "Audiolivro completo", 10 ** 9 + int(n)))
    return sorted(saida, key=lambda v: v.ordem)


def ler_renomear(texto: str) -> list[tuple[str, str]]:
    """Linhas "antigo => novo" (linhas vazias e começadas com # são ignoradas)."""
    pares = []
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=>" not in linha:
            continue
        antigo, novo = (p.strip() for p in linha.split("=>", 1))
        if antigo and novo and _CODIGO.match(Path(novo).stem) and Path(novo).suffix.lower() in EXT_IMAGEM:
            pares.append((antigo, novo))
    return pares


def aplicar_renomear(drive, pasta_id: str) -> int:
    itens = drive.listar(pasta_id)
    lista = next((i for i in itens if i["name"] == ARQ_RENOMEAR), None)
    if not lista:
        return 0
    por_id = {i["id"]: i for i in itens}
    por_nome = {i["name"]: i for i in itens}
    feitas = faltou = 0
    for antigo, novo in ler_renomear(drive.ler_texto(lista["id"])):
        item = por_id.get(antigo) or por_nome.get(antigo)
        if not item:
            faltou += 1
            continue
        if item["name"] != novo:
            drive.api.files().update(fileId=item["id"], body={"name": novo},
                                     supportsAllDrives=True).execute(num_retries=5)
        feitas += 1
    if faltou:
        log.warning("Lista de nomes: %d linha(s) sem arquivo correspondente; a lista fica na pasta.", faltou)
    else:
        drive.lixeira(lista["id"])
    return feitas


def segundos(duracao_iso: str) -> int:
    m = _DURACAO.fullmatch(duracao_iso or "")
    if not m:
        return 0
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def distribuir_antigos(videos_canal: list[dict], livros: list[Livro], do_robo: set) -> int:
    """Vídeos que não estão em nenhum publicados.json (postados antes do robô) vão para o livro cujo nome aparece
    no título. Se aparecem vários, ganha o que vem primeiro no título ("Eldest (Ciclo da Herança #2)" é do Eldest,
    não do Herança); empate, o nome mais comprido. Shorts ficam de fora. Devolve quantos."""
    nomes = sorted(((normalizar(lv.nome), i) for i, lv in enumerate(livros) if len(lv.nome) >= 4),
                   key=lambda x: -len(x[0]))
    por_livro: dict[int, list[dict]] = {}
    for v in videos_canal:
        if v["id"] in do_robo or segundos((v.get("contentDetails") or {}).get("duration", "")) < MIN_SEGUNDOS:
            continue
        titulo = normalizar(v["snippet"]["title"])
        achados_titulo = [(titulo.find(nome), -len(nome), i) for nome, i in nomes if nome in titulo]
        dono = min(achados_titulo)[2] if achados_titulo else None
        if dono is not None:
            por_livro.setdefault(dono, []).append(v)
    achados = 0
    for i, antigos in por_livro.items():
        antigos.sort(key=lambda v: v["snippet"].get("publishedAt", ""))
        for k, v in enumerate(antigos, 1):
            m = _NUMERO_ANTIGO.search(v["snippet"]["title"])
            n = int(m.group(1) or m.group(2)) if m else k
            livros[i].videos.append(Video(v["id"], f"Parte {n}", "", -10 ** 6 + n + k / 1000))
            achados += 1
        livros[i].videos.sort(key=lambda x: x.ordem)
    return achados


def nome_arquivo(video: Video) -> str:
    m = re.fullmatch(r"(Cap\.|Parte)\s*(\d+)", video.rotulo)
    rot = f"{'Cap' if m.group(1) == 'Cap.' else 'Parte'} {int(m.group(2)):02d}" if m else video.rotulo
    titulo = re.sub(r'[\\/:*?"<>|]+', " ", video.titulo_youtube or video.detalhe or "").strip()
    titulo = re.sub(r"\s+", " ", titulo)[:90].rstrip(" .")
    return f"{rot} - {titulo}.jpg" if titulo else f"{rot}.jpg"


# ---------------------------------------------------------------- Drive

def _pasta_ao_lado_da_raiz(drive, raiz: str, nome: str) -> str:
    pai = (drive.api.files().get(fileId=raiz, fields="parents", supportsAllDrives=True)
           .execute(num_retries=5).get("parents") or ["root"])[0]
    return drive.pasta(pai, nome)


def _gravar_planilha(drive, pasta_id: str, linhas: list[list[str]], tmp: Path) -> None:
    from googleapiclient.http import MediaFileUpload
    arq = tmp / "lista.csv"
    with open(arq, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(linhas)
    midia = MediaFileUpload(str(arq), mimetype="text/csv", resumable=False)
    existente = drive.achar(pasta_id, PLANILHA)
    if existente:
        drive.api.files().update(fileId=existente["id"], media_body=midia, supportsAllDrives=True).execute(num_retries=5)
    else:
        drive.api.files().create(body={"name": PLANILHA, "parents": [pasta_id],
                                       "mimeType": "application/vnd.google-apps.spreadsheet"},
                                 media_body=midia, fields="id", supportsAllDrives=True).execute(num_retries=5)


def processar(drive, youtube, raiz: str, cfg: dict, so: list[str] | None = None, refazer: bool = False,
              dry_run: bool = False, sem_podcast: bool = False) -> int:
    import arte_selo
    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros
    from metadados import livro_e_autor

    video_cfg = cfg.get("video") or {}
    canal = (video_cfg.get("marca_curta") or video_cfg.get("marca") or "Canal").strip()
    marca = (video_cfg.get("marca") or "").strip()
    itens = drive.listar(raiz)
    pasta_capas = next((i for i in itens if drive.eh_pasta(i) and normalizar(i["name"]) == PASTA_CAPAS), None)
    if not pasta_capas:
        log.warning("Não achei a pasta 'Capas novas' na raiz do Drive.")
        return 1
    renomeadas = aplicar_renomear(drive, pasta_capas["id"])
    if renomeadas:
        log.info("Fotos renomeadas pela lista: %d", renomeadas)
    capas = ler_capas(drive.listar(pasta_capas["id"]))
    # Com --so, só esses livros são gerados de novo; a planilha continua com todos.
    escolhidos = {s.upper() for s in so} if so else None
    log.info("Capas com código: %d", len(capas))

    pastas = pastas_de_livros(drive, raiz)
    estados, com_registro = {}, set()
    for p in pastas:
        estado = drive.ler_json(p["id"], ARQ_PUBLICADOS, {"capitulos": {}})
        estados[p["id"]] = estado
        if estado.get("capitulos"):
            com_registro.add(p["id"])
    nomes = [(p, livro_e_autor({"titulo": p["name"]})[0]) for p in pastas]

    livros, do_robo = [], set()
    for est in estados.values():
        do_robo |= {r["video_id"] for r in est.get("capitulos", {}).values()}
        do_robo |= set((est.get("completo") or {}).get("partes", {}).values())
    for capa in capas:
        pasta = achar_pasta(capa.titulo, nomes, com_registro)
        lv = Livro(capa, pasta, nome=capa.titulo)
        if pasta:
            lv.nome, lv.autor = livro_e_autor({"titulo": pasta["name"]})
            lv.nome = capa.titulo   # o título que você escreveu no nome da foto manda
            estado = estados[pasta["id"]]
            titulos = {}
            if estado.get("capitulos"):
                dados = carregar_livro(drive, pasta)
                if dados:
                    titulos = {c.numero: c.titulo for c in dados.capitulos}
                    lv.autor = livro_e_autor(dados.ficha)[1] or lv.autor
            lv.videos = videos_do_registro(estado, titulos)
        livros.append(lv)

    canal_videos = youtube.videos_do_canal()
    por_id = {v["id"]: v for v in canal_videos}
    antigos = distribuir_antigos(canal_videos, livros, do_robo)
    for lv in livros:
        lv.videos = [v for v in lv.videos if v.video_id in por_id]   # apagados do canal ficam de fora
        for v in lv.videos:
            v.titulo_youtube = por_id[v.video_id]["snippet"]["title"]
    total = sum(len(lv.videos) for lv in livros)
    log.info("Vídeos: %d (%d postados antes do robô). Livros sem pasta: %d", total, antigos,
             sum(1 for lv in livros if not lv.pasta))
    if dry_run:
        for lv in livros:
            log.info("  %s: %d vídeo(s)", lv.capa.codigo, len(lv.videos))
        return 0

    saida = _pasta_ao_lado_da_raiz(drive, raiz, f"{canal} - Miniaturas prontas")
    saida_podcast = None if sem_podcast else _pasta_ao_lado_da_raiz(drive, raiz, f"{canal} - Capas de podcast")
    feitas = puladas = 0
    linhas = [["Código", "Livro", "Vídeo", "Arquivo", "Abrir no Studio", "Ver no YouTube", "Feito?"]]
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for lv in livros:
            pasta_capa = f"{lv.capa.codigo} - {lv.capa.titulo}"
            gerar = escolhidos is None or lv.capa.codigo in escolhidos
            if not gerar:
                for v in lv.videos:
                    linhas.append(_linha(lv, pasta_capa, v))
                continue
            foto = drive.baixar(lv.capa.arquivo["id"], tmp / "capas" / lv.capa.arquivo["name"])
            if saida_podcast:
                nome_q = f"{pasta_capa}.jpg"
                if refazer or not drive.achar(saida_podcast, nome_q):
                    q = arte_selo.capa_quadrada(foto, tmp / "q.jpg", lv.nome, lv.autor, lado=3000, marca=marca)
                    _substituir(drive, saida_podcast, q, nome_q)
            if not lv.videos:
                continue
            destino = drive.pasta(saida, pasta_capa)
            existentes = {i["name"]: i for i in drive.listar(destino)}
            esperados = {nome_arquivo(v) for v in lv.videos}
            for nome, item in existentes.items():   # sobra de uma execução anterior (vídeo que não é deste livro)
                if nome.lower().endswith(".jpg") and nome not in esperados:
                    drive.lixeira(item["id"])
            for v in lv.videos:
                nome = nome_arquivo(v)
                linhas.append(_linha(lv, pasta_capa, v))
                if nome in existentes and not refazer:
                    puladas += 1
                    continue
                img = arte_selo.miniatura(foto, tmp / "m.jpg", lv.nome, lv.autor, v.rotulo, v.detalhe,
                                          variante=video_cfg.get("miniatura_variante") or "destaque",
                                          rodape=marca.upper())
                _substituir(drive, destino, img, nome)
                feitas += 1
        _gravar_planilha(drive, saida, linhas, tmp)
    log.info("Miniaturas geradas: %d; já existiam: %d; total na lista: %d", feitas, puladas, len(linhas) - 1)
    return 0


def _linha(lv: Livro, pasta_capa: str, v: Video) -> list[str]:
    return [lv.capa.codigo, lv.nome, v.titulo_youtube, f"{pasta_capa}/{nome_arquivo(v)}",
            f"https://studio.youtube.com/video/{v.video_id}/edit", f"https://youtu.be/{v.video_id}", ""]


def _substituir(drive, pasta_id: str, arquivo: Path, nome: str) -> None:
    antigo = drive.achar(pasta_id, nome)
    if antigo:
        drive.lixeira(antigo["id"])
    drive.enviar(arquivo, pasta_id, nome, "image/jpeg")


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--so", nargs="*", help="códigos dos livros (ex.: P07 P30)")
    parser.add_argument("--refazer", action="store_true", help="gera de novo mesmo o que já existe")
    parser.add_argument("--sem-podcast", action="store_true", help="não gera as capas quadradas")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from google_api import Drive, YouTube, credenciais_do_ambiente
    credenciais = credenciais_do_ambiente()
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    so = [c for item in (args.so or []) for c in re.split(r"[\s,;]+", item) if c]
    return processar(Drive(credenciais), YouTube(credenciais), raiz, carregar_config(), so or None,
                     args.refazer, args.dry_run, args.sem_podcast)


if __name__ == "__main__":
    sys.exit(main())
