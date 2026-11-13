"""Procura a capa de cada livro sem imagem na pasta e salva no Drive como capa.jpg.

Fontes, em ordem: Google Livros (prefere edições em português) e Open Library.
Só é feito para livros privados (uso pessoal): capa de edição comercial em vídeo público pode dar problema
de direitos. Para trocar a capa encontrada, basta substituir o capa.jpg na pasta.

Uso:
  python src/capas.py            # procura e salva no Drive
  python src/capas.py --dry-run  # só mostra o que encontraria
"""

import argparse
import io
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

import discreto
from comum import configurar_log, log

ALTURA_MINIMA = 300
ULTIMOS_ERROS: list[str] = []   # por que a última busca não achou nada (vai para o resumo do GitHub)
# A Wikipédia recusa (429) robôs sem identificação; ela pede nome e um endereço de contato.
_AGENTE = {"User-Agent": "audiolivro-robo/1.0 (capas)"}


def _baixar(url: str, timeout: int = 30) -> bytes:
    pedido = urllib.request.Request(url, headers=_AGENTE)
    with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
        return resposta.read()


def _json(url: str) -> dict:
    return json.loads(_baixar(url).decode("utf-8"))


def termos_de_busca(nome_pasta: str) -> str:
    """'Ricardo Montemor Despertar (Cyclo do Despertar Vol. 4)' -> 'Ricardo Montemor Despertar'."""
    sem_parenteses = re.sub(r"\([^)]*\)", " ", nome_pasta)
    sem_volume = re.sub(r"\bvol(?:ume)?\.?\s*\d+\b", " ", sem_parenteses, flags=re.IGNORECASE)
    return " ".join(sem_volume.split())


def _imagem_valida(dados: bytes) -> bool:
    try:
        imagem = Image.open(io.BytesIO(dados))
        return imagem.height >= ALTURA_MINIMA and imagem.width >= ALTURA_MINIMA * 0.5
    except Exception:
        return False


def titulo_combina(termos: str, titulo: str, autores: str = "") -> bool:
    """O livro achado precisa ter no título a última palavra forte do nome da pasta, que costuma ser o título
    ("Gervásio Ramalho Marcelina" -> "marcelina"). Evita capa de outro livro só porque o autor é o mesmo."""
    de_autor = set(_simples(autores).split())
    fortes = [p for p in _simples(termos).split() if len(p) >= 4 and p not in de_autor]
    return not fortes or fortes[-1] in _simples(titulo).split()


def candidatos_google(termos: str, chave: str | None) -> list[str]:
    urls = []
    for idioma in ("pt", None):
        parametros = {"q": termos, "maxResults": 10, "printType": "books"}
        if idioma:
            parametros["langRestrict"] = idioma
        if chave:
            parametros["key"] = chave
        try:
            dados = _json("https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(parametros))
        except urllib.error.HTTPError as erro:
            if erro.code == 403 and chave:   # a chave não pode usar a Books API: tenta sem chave
                motivo = erro.read().decode("utf-8", "ignore")
                motivo = "chave restrita a outras APIs" if "API_KEY_SERVICE_BLOCKED" in motivo or "blocked" in motivo \
                    else "Books API desativada" if "SERVICE_DISABLED" in motivo or "has not been used" in motivo \
                    else motivo[:120]
                log.info("  A chave do Google não serve para o Google Livros (%s); tentando sem chave.", motivo)
                ULTIMOS_ERROS.append(f"chave do Google recusada: {motivo}")
                return candidatos_google(termos, None)
            log.info("  Google Livros indisponível (%s)", erro)
            ULTIMOS_ERROS.append(f"Google Livros: {erro}")
            return urls
        except Exception as erro:
            ULTIMOS_ERROS.append(f"Google Livros: {erro}")
            log.info("  Google Livros indisponível (%s)", erro)
            return urls
        for volume in dados.get("items", []):
            info = volume.get("volumeInfo", {})
            if not titulo_combina(termos, info.get("title", "") + " " + info.get("subtitle", ""),
                                  " ".join(info.get("authors") or [])):
                continue
            links = info.get("imageLinks", {})
            for tamanho in ("extraLarge", "large", "medium", "small", "thumbnail"):
                if links.get(tamanho):
                    url = links[tamanho].replace("http://", "https://").replace("&edge=curl", "")
                    # zoom=0 costuma devolver a maior imagem disponível
                    urls += [re.sub(r"zoom=\d", "zoom=0", url), url]
                    break
        if urls:
            return urls
    return urls


def candidatos_openlibrary(termos: str) -> list[str]:
    try:
        dados = _json("https://openlibrary.org/search.json?" + urllib.parse.urlencode(
            {"q": termos, "fields": "cover_i,title", "limit": 10}))
    except Exception as erro:
        log.info("  Open Library indisponível (%s)", erro)
        ULTIMOS_ERROS.append(f"Open Library: {erro}")
        return []
    return [f"https://covers.openlibrary.org/b/id/{d['cover_i']}-L.jpg?default=false"
            for d in dados.get("docs", []) if d.get("cover_i")]


def _simples(texto: str) -> str:
    from comum import normalizar
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", normalizar(re.sub(r"\([^)]*\)", " ", texto))).split())


def candidatos_wikipedia(termos: str) -> list[str]:
    """Imagem principal do artigo do livro na Wikipédia (pt, depois en). Só vale o artigo cujo título é o fim
    do nome da pasta ("Henrique Saldanha O Senhor das Marés" -> "O Senhor das Marés"), para não pegar a foto do autor."""
    alvo = _simples(termos)
    urls = []
    for idioma in ("pt", "en"):
        time.sleep(1.5)   # sem pressa: a Wikipédia limita pedidos seguidos
        try:
            dados = _json(f"https://{idioma}.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
                "action": "query", "format": "json", "generator": "search", "gsrsearch": termos, "gsrlimit": 5,
                "prop": "pageimages", "piprop": "original|thumbnail", "pithumbsize": 1000}))
        except Exception as erro:
            ULTIMOS_ERROS.append(f"Wikipédia: {erro}")
            continue
        paginas = sorted((dados.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
        for pagina in paginas:
            titulo = _simples(pagina.get("title", ""))
            if len(titulo) < 4 or not alvo.endswith(titulo):
                continue
            for tipo in ("thumbnail", "original"):
                fonte = (pagina.get(tipo) or {}).get("source", "")
                if fonte and not fonte.lower().endswith(".svg"):
                    urls.append(fonte)
        if urls:
            return urls
    return urls


def buscar_capa(nome_pasta: str, chave_google: str | None = None) -> tuple[bytes, str] | None:
    termos = termos_de_busca(nome_pasta)
    ULTIMOS_ERROS.clear()
    for url in candidatos_google(termos, chave_google) + candidatos_openlibrary(termos) + candidatos_wikipedia(termos):
        try:
            dados = _baixar(url)
        except Exception:
            continue
        if _imagem_valida(dados):
            return dados, url
        ULTIMOS_ERROS.append("imagem pequena demais")
    return None


def _aviso_github(texto: str) -> None:
    """No GitHub Actions, a linha aparece no resumo da execução (dá para ler sem abrir o log)."""
    if os.environ.get("GITHUB_ACTIONS"):
        print(f"::notice title=Capas::{texto}", flush=True)


def processar_drive(dry_run: bool) -> int:
    from google_api import Drive, credenciais_do_ambiente
    from livro import carregar_livro, pastas_de_livros, privacidade_do_livro

    drive = Drive(credenciais_do_ambiente())
    # Sem chave o Google Livros quase sempre recusa (limite compartilhado). A chave das vozes serve, se a
    # "Books API" estiver ativada no mesmo projeto do Google Cloud.
    chave = os.environ.get("GOOGLE_BOOKS_API_KEY") or os.environ.get("GOOGLE_TTS_API_KEY") or None
    resultado: list[str] = []
    for pasta in pastas_de_livros(drive, os.environ["DRIVE_PASTA_RAIZ"]):
        livro = carregar_livro(drive, pasta)
        if not livro or livro.capa:
            continue
        if privacidade_do_livro(livro.ficha) != "private":
            log.info("'%s' é público: capa automática desligada (coloque a sua imagem na pasta).", livro.nome)
            continue
        log.info("Procurando capa para '%s'...", livro.nome)
        try:
            achada = buscar_capa(livro.nome, chave)
        except Exception as erro:   # um livro com problema não pode impedir os outros
            resultado.append(f"{livro.nome}: erro na busca ({erro})")
            continue
        if not achada:
            log.warning("  Não achei capa para '%s'; o vídeo sai com fundo liso.", livro.nome)
            resultado.append(f"{livro.nome}: não achei ({'; '.join(dict.fromkeys(ULTIMOS_ERROS)) or 'nenhum resultado'})")
            continue
        dados, url = achada
        log.info("  Capa encontrada: %s", url)
        resultado.append(f"{livro.nome}: capa encontrada")
        if dry_run:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            arquivo = Path(tmp) / "capa.jpg"
            Image.open(io.BytesIO(dados)).convert("RGB").save(arquivo, quality=92)
            drive.enviar(arquivo, pasta["id"], "capa.jpg", "image/jpeg")
    if resultado:
        achadas = sum(r.endswith("capa encontrada") for r in resultado)
        detalhes = "" if discreto.ativo() else " " + " | ".join(resultado)   # no modo discreto, só os números
        _aviso_github(f"{achadas} de {len(resultado)} capas encontradas.{detalhes}")
    return 0


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    return processar_drive(parser.parse_args().dry_run)


if __name__ == "__main__":
    sys.exit(main())
