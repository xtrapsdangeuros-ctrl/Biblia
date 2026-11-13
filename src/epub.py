"""Lê um .epub e devolve as seções do livro na ordem do sumário, prontas para narrar."""

import html
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from comum import normalizar

# Seções do começo do livro que não fazem sentido em áudio
_PULAR = ("rosto", "creditos", "dedicatoria", "sumario", "indice", "mapa", "copyright", "ficha catalografica",
          "dlivros", "capa", "folha de rosto", "outras obras", "obras do autor", "ficha tecnica")
# Seção com menos que isso é só uma página divisória ("PARTE UM"): o título dela é lido no começo da próxima.
MIN_CARACTERES = 1500


@dataclass
class Secao:
    titulo: str        # como está no sumário: "1: Filho da neblina"
    texto: str         # texto corrido, parágrafos separados por linha em branco
    antes: str = ""    # títulos de páginas divisórias que vêm antes ("Parte um: Acima do silêncio")

    @property
    def caracteres(self) -> int:
        return len(texto_falado(self))


def _texto_do_html(conteudo: str) -> str:
    conteudo = re.sub(r"<(head|style|script)[^>]*>.*?</\1>", "", conteudo, flags=re.S | re.I)
    conteudo = re.sub(r"<(br|/p|/h\d|/div|/li|/blockquote)[^>]*>", "\n", conteudo, flags=re.I)
    conteudo = re.sub(r"<[^>]+>", "", conteudo)   # sem espaço: a letra capitular "<span>T</span>avian" vira "Tavian"
    texto = html.unescape(conteudo).replace("\xa0", " ")
    paragrafos = [" ".join(p.split()) for p in texto.split("\n")]
    return "\n\n".join(p for p in paragrafos if p)


def _sumario(z: zipfile.ZipFile) -> list[tuple[str, str]]:
    """[(título, caminho do arquivo dentro do epub)] na ordem do sumário (toc.ncx ou nav.xhtml)."""
    ncx = next((n for n in z.namelist() if n.endswith(".ncx")), None)
    if ncx:
        base = PurePosixPath(ncx).parent
        pontos = re.findall(r"<navPoint\b.*?<text>(.*?)</text>.*?<content\s+src=\"([^\"]+)\"", z.read(ncx).decode("utf-8", "ignore"), re.S)
        return [(html.unescape(t).strip(), str(base / s.split("#")[0])) for t, s in pontos]
    nav = next((n for n in z.namelist() if re.search(r"nav\.x?html$", n)), None)
    if nav:
        base = PurePosixPath(nav).parent
        links = re.findall(r"<a[^>]+href=\"([^\"#]+)[^\"]*\"[^>]*>(.*?)</a>", z.read(nav).decode("utf-8", "ignore"), re.S)
        return [(html.unescape(re.sub(r"<[^>]+>", "", t)).strip(), str(base / h)) for h, t in links]
    return []


def _ordem_leitura(z: zipfile.ZipFile) -> list[str]:
    opf = next(n for n in z.namelist() if n.endswith(".opf"))
    base = PurePosixPath(opf).parent
    conteudo = z.read(opf).decode("utf-8", "ignore")
    itens = {}
    for tag in re.findall(r"<item\b[^>]*>", conteudo):
        i, h = re.search(r'id="([^"]+)"', tag), re.search(r'href="([^"]+)"', tag)
        if i and h:
            itens[i.group(1)] = str(base / h.group(1))
    return [itens[i] for i in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', conteudo) if i in itens]


def ler_epub(caminho) -> list[Secao]:
    with zipfile.ZipFile(caminho) as z:
        ordem = _ordem_leitura(z)
        sumario = [(t, h) for t, h in _sumario(z) if h in ordem]
        # cada entrada do sumário vai do seu arquivo até o arquivo da próxima entrada
        inicio = {h: t for t, h in reversed(sumario)}
        blocos, atual = [], None
        for arquivo in ordem:
            if arquivo in inicio:
                atual = [inicio[arquivo], []]
                blocos.append(atual)
            if atual is not None:
                atual[1].append(_texto_do_html(z.read(arquivo).decode("utf-8", "ignore")))

    secoes, antes = [], []
    for titulo, textos in blocos:
        if normalizar(titulo).startswith(_PULAR):
            continue
        texto = _sem_titulo_repetido("\n\n".join(t for t in textos if t), titulo)
        if len(texto) < MIN_CARACTERES:
            antes.append(titulo)
            continue
        secoes.append(Secao(titulo, texto, ". ".join(_frase(a) for a in antes)))
        antes = []
    return secoes


def _sem_titulo_repetido(texto: str, titulo: str) -> str:
    """Tira o título do começo do texto quando ele aparece escrito ali ("PREFÁCIO"), para não ser lido duas vezes."""
    primeiro, _, resto = texto.partition("\n\n")
    chave = lambda t: re.sub(r"[^a-z0-9]", "", normalizar(t))  # noqa: E731
    if resto and (chave(primeiro) == chave(titulo) or chave(titulo).endswith(chave(primeiro)) and len(chave(primeiro)) > 3):
        return resto
    return texto


def _frase(titulo: str) -> str:
    """'PARTE UM: ACIMA DO SILÊNCIO' -> 'Parte um: acima do silêncio' (texto todo em maiúsculas soa como sigla)."""
    return titulo.capitalize() if titulo.isupper() else titulo


def titulo_falado(titulo: str) -> str:
    """Como o narrador anuncia a seção: '1: Filho da neblina' -> 'Capítulo 1: Filho da neblina'."""
    if m := re.match(r"^(\d+)\s*[:.\-–]\s*(.*)$", titulo):
        return f"Capítulo {m.group(1)}: {m.group(2)}"
    if m := re.match(r"^(I-\d+)\s*[:.\-–]\s*(.*)$", titulo):
        return f"Interlúdio {m.group(1)}: {m.group(2)}"
    return _frase(titulo)


def titulo_arquivo(titulo: str) -> str:
    """Título que vai no nome do MP3 (e daí no título do vídeo): 'Capítulo 1 - Filho da neblina'."""
    # "As Crônicas da Serra Alta — Prelúdio" -> "Prelúdio - As Crônicas da Serra Alta"
    if m := re.match(r"^(.+?)\s+[—–-]\s+(Prel[uú]dio|Pr[oó]logo|Ep[ií]logo|Interl[uú]dio)$", titulo, re.I):
        return f"{m.group(2)} - {m.group(1)}"
    return titulo_falado(titulo).replace(": ", " - ", 1)


def texto_falado(secao: Secao) -> str:
    partes = [f"{secao.antes}." if secao.antes else "", f"{titulo_falado(secao.titulo)}.", secao.texto]
    return "\n\n".join(p for p in partes if p)
