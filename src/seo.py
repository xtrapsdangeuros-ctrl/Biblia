"""Auditoria de SEO dos vídeos do canal: o que falta em título, descrição, tags e legendas, e onde
o canal aparece na busca do YouTube para "audiolivro <livro>".

Uso:
  python src/seo.py --buscas 6      # cada busca gasta 100 unidades da cota diária (10.000)
O relatório sai no terminal e, no GitHub Actions, no resumo da execução.
"""

import argparse
import collections
import os
import re
import sys

from googleapiclient.discovery import build

from analytics import n, tabela, todos_os_videos
import discreto
import metadados
from comum import configurar_log
from google_api import credenciais_do_ambiente

PALAVRAS_CHAVE = ("audiolivro", "audiobook", "áudiolivro", "audio livro", "livro narrado")
_DURACAO = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")
_MARCADOR = re.compile(r"^\s*\(?\d{1,2}:\d{2}(?::\d{2})?\)?\s", re.M)


def segundos(iso: str) -> int:
    h, m, s = (int(x or 0) for x in _DURACAO.match(iso).groups())
    return h * 3600 + m * 60 + s


def tem_palavra(texto: str) -> bool:
    texto = texto.lower()
    return any(p in texto for p in PALAVRAS_CHAVE)


def nome_do_livro(titulo: str) -> str:
    """'O Senhor das Marés (Henrique Saldanha) – Parte 1: ...' -> 'O Senhor das Marés'."""
    return re.split(r"\s+[–(/|-]\s*|\s+\(|#", titulo)[0].strip()


def problemas(v: dict) -> list[str]:
    sn, det = v["snippet"], v["contentDetails"]
    titulo, desc, tags = sn["title"], sn.get("description", ""), sn.get("tags", [])
    curto = segundos(det["duration"]) <= 180
    lista = []
    if len(titulo) > 70:
        lista.append("título > 70 caracteres (corta na busca)")
    if not tem_palavra(titulo) and not curto:
        lista.append('título sem "audiolivro"')
    elif tem_palavra(titulo) and not tem_palavra(titulo[:45]) and not curto:
        lista.append('"audiolivro" só no fim do título (cortado no celular)')
    if len(desc) < 250:
        lista.append("descrição curta (< 250 caracteres)")
    if not tem_palavra(desc[:160]):
        lista.append('"audiolivro" fora das 2 primeiras linhas da descrição')
    if len(tags) < 5:
        lista.append(f"poucas tags ({len(tags)})")
    if segundos(det["duration"]) > 600 and len(_MARCADOR.findall(desc)) < 3:
        lista.append("vídeo longo sem capítulos (marcadores de tempo)")
    if det.get("caption") != "true":
        lista.append("sem legenda")
    if "#" not in desc and "#" not in titulo:
        lista.append("sem hashtags")
    if not sn.get("defaultAudioLanguage", "").startswith("pt"):
        lista.append("idioma do áudio não definido")
    return lista


def auditoria(videos: list[dict]) -> list[str]:
    publicos = [v for v in videos if v["status"]["privacyStatus"] == "public"]
    por_video = {v["id"]: problemas(v) for v in publicos}
    contagem = collections.Counter(p for lista in por_video.values() for p in lista)
    total = len(publicos) or 1
    linhas = ["# Auditoria de SEO", "", f"{n(len(publicos))} vídeos públicos analisados.", "",
              "## Problemas mais comuns", ""]
    linhas += tabela(["Problema", "Vídeos", "% dos públicos"],
                     [[p, n(q), f"{100 * q / total:.0f}%"] for p, q in contagem.most_common()])
    titulos = collections.Counter(v["snippet"]["title"].strip().lower() for v in publicos)
    repetidos = [(t, q) for t, q in titulos.items() if q > 1]
    if repetidos:
        linhas += ["", "## Títulos repetidos (o YouTube trata como conteúdo duplicado)", ""]
        linhas += tabela(["Título", "Vezes"], [[t[:80], q] for t, q in sorted(repetidos, key=lambda x: -x[1])[:15]])
    # comparação: o que os vídeos que mais deram certo têm de diferente dos novos
    top = sorted(publicos, key=lambda v: int(v["statistics"].get("viewCount", 0)), reverse=True)[:10]
    novos = sorted(publicos, key=lambda v: v["snippet"]["publishedAt"], reverse=True)[:10]
    linhas += ["", "## Os 10 mais vistos × os 10 mais novos", ""]

    def media(grupo, f):
        return sum(f(v) for v in grupo) / (len(grupo) or 1)

    linhas += tabela(["", "Mais vistos", "Mais novos"], [
        ["Tamanho médio do título", f"{media(top, lambda v: len(v['snippet']['title'])):.0f}",
         f"{media(novos, lambda v: len(v['snippet']['title'])):.0f}"],
        ['Começa com "Audiolivro"', sum(tem_palavra(v["snippet"]["title"][:12]) for v in top),
         sum(tem_palavra(v["snippet"]["title"][:12]) for v in novos)],
        ["Duração média (min)", f"{media(top, lambda v: segundos(v['contentDetails']['duration'])) / 60:.0f}",
         f"{media(novos, lambda v: segundos(v['contentDetails']['duration'])) / 60:.0f}"],
        ["Média de tags", f"{media(top, lambda v: len(v['snippet'].get('tags', []))):.0f}",
         f"{media(novos, lambda v: len(v['snippet'].get('tags', []))):.0f}"],
    ])
    piores = sorted(publicos, key=lambda v: (-len(por_video[v["id"]]), v["snippet"]["publishedAt"]))[:15]
    linhas += ["", "## Vídeos com mais pontos a corrigir", ""]
    linhas += tabela(["Vídeo", "Views", "Problemas"],
                     [[v["snippet"]["title"][:60], n(v["statistics"].get("viewCount")), "; ".join(por_video[v["id"]])]
                      for v in piores])
    return linhas


def posicao_na_busca(yt, canal_id: str, videos: list[dict], buscas: int) -> list[str]:
    if buscas <= 0:
        return []
    publicos = [v for v in videos if v["status"]["privacyStatus"] == "public"]
    livros = collections.Counter()
    for v in sorted(publicos, key=lambda v: v["snippet"]["publishedAt"], reverse=True):
        livro = nome_do_livro(v["snippet"]["title"]).replace("Áudiolivro ", "")
        for autor in metadados.AUTORES_CONHECIDOS:   # "Autor Título" -> "Título" (lista do canal.yaml)
            if livro.startswith(autor + " "):
                livro = livro[len(autor) + 1:]
        if len(livro) >= 4:
            livros[livro] += 1
    linhas = ["", "## Posição na busca do YouTube (Brasil)", "",
              "Busca feita como um visitante anônimo: o resultado real varia por pessoa.", ""]
    resultado = []
    for livro, _ in livros.most_common(buscas):
        termo = f"audiolivro {livro}"
        itens = yt.search().list(part="snippet", q=termo, type="video", maxResults=50, regionCode="BR",
                                 relevanceLanguage="pt").execute(num_retries=3).get("items", [])
        nossa = next((i + 1 for i, it in enumerate(itens) if it["snippet"]["channelId"] == canal_id), None)
        primeiro = itens[0]["snippet"] if itens else {}
        resultado.append([termo, f"{nossa}º" if nossa else "fora do top 50",
                          f"{primeiro.get('channelTitle', '')}: {primeiro.get('title', '')[:50]}"])
    linhas += tabela(["Busca", "Nosso melhor vídeo", "1º lugar"], resultado)
    return linhas


def exportar(videos: list[dict], destino: str) -> None:
    """Grava título, descrição, tags e números de cada vídeo num JSON (para comparar antes e depois)."""
    import json
    dados = [{"id": v["id"], "privacidade": v["status"]["privacyStatus"], "publicado": v["snippet"]["publishedAt"],
              "titulo": v["snippet"]["title"], "descricao": v["snippet"].get("description", ""),
              "tags": v["snippet"].get("tags", []), "views": int(v["statistics"].get("viewCount", 0)),
              "duracao": segundos(v["contentDetails"]["duration"]), "legenda": v["contentDetails"].get("caption")}
             for v in videos]
    if discreto.ativo():   # no GitHub: só no relatório do Drive (nunca no log nem em artifact)
        discreto.anexar("Vídeos do canal (JSON)", json.dumps(dados, ensure_ascii=False, indent=1))
        return
    with open(destino, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)


def main() -> int:
    configurar_log()
    args = argparse.ArgumentParser()
    args.add_argument("--buscas", type=int, default=6)
    args.add_argument("--exportar", help="grava os dados de todos os vídeos neste arquivo JSON")
    opcoes = args.parse_args()
    buscas = opcoes.buscas
    yt = build("youtube", "v3", credentials=credenciais_do_ambiente(), cache_discovery=False)
    canal = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    videos = todos_os_videos(yt, canal["contentDetails"]["relatedPlaylists"]["uploads"])
    if opcoes.exportar:
        exportar(videos, opcoes.exportar)
    linhas = auditoria(videos) + posicao_na_busca(yt, canal["id"], videos, buscas)
    relatorio = "\n".join(linhas) + "\n"
    print(relatorio)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("\n" + relatorio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
