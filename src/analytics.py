"""Relatório de analytics do canal: números gerais, vídeos mais vistos e (se autorizado) dados do período.

Parte 1 (sempre funciona, usa a autorização atual): inscritos, views totais, nº de vídeos e
views/likes/comentários de cada vídeo.
Parte 2 (precisa do escopo yt-analytics.readonly): views, horas assistidas, duração média,
inscritos ganhos/perdidos, origem do tráfego e países nos últimos N dias. Sem o escopo, o relatório
avisa como liberar e mostra só a parte 1.

Uso:
  python src/analytics.py --dias 28
O relatório sai no terminal e, no GitHub Actions, no resumo da execução.
"""

import argparse
import datetime as dt
import os
import sys

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

import discreto
from comum import configurar_log
from google_api import credenciais_do_ambiente

ORIGENS = {
    "YT_SEARCH": "Pesquisa do YouTube", "SUGGESTED": "Vídeos sugeridos", "BROWSE": "Página inicial / Inscrições",
    "PLAYLIST": "Playlists", "EXT_URL": "Sites externos", "CHANNEL": "Página do canal", "NO_LINK_OTHER": "Direto / outros",
    "SHORTS": "Feed de Shorts", "NOTIFICATION": "Notificações", "YT_OTHER_PAGE": "Outras páginas do YouTube",
    "END_SCREEN": "Tela final", "ANNOTATION": "Cards", "RELATED_VIDEO": "Vídeos relacionados", "SUBSCRIBER": "Inscritos",
    "HASHTAGS": "Hashtags", "SOUND_PAGE": "Página de som", "LIVE_REDIRECT": "Live", "YT_PLAYLIST_PAGE": "Página de playlist",
}


def n(valor) -> str:
    return f"{int(valor or 0):,}".replace(",", ".")


def tabela(cabecalho: list[str], linhas: list[list]) -> list[str]:
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(str(c).replace("|", "/") for c in linha) + " |" for linha in linhas]
    return saida


def todos_os_videos(yt, uploads_id: str) -> list[dict]:
    ids, pagina = [], None
    while True:
        resp = yt.playlistItems().list(part="contentDetails", playlistId=uploads_id, maxResults=50,
                                       pageToken=pagina).execute(num_retries=3)
        ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
        pagina = resp.get("nextPageToken")
        if not pagina:
            break
    ids = list(dict.fromkeys(ids))  # a playlist de envios pode repetir o mesmo vídeo entre páginas
    videos = []
    for i in range(0, len(ids), 50):
        resp = yt.videos().list(part="snippet,statistics,status,contentDetails", id=",".join(ids[i:i + 50])).execute(num_retries=3)
        videos += resp.get("items", [])
    return videos


def parte_geral(yt) -> tuple[list[str], dict]:
    canal = yt.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()["items"][0]
    est = canal["statistics"]
    videos = todos_os_videos(yt, canal["contentDetails"]["relatedPlaylists"]["uploads"])
    publicos = [v for v in videos if v["status"]["privacyStatus"] == "public"]
    linhas = [f"# Analytics do canal: {canal['snippet']['title']}", "",
              f"Gerado em {dt.datetime.now(dt.timezone.utc):%d/%m/%Y %H:%M} UTC", "", "## Números gerais", ""]
    linhas += tabela(["Métrica", "Valor"], [
        ["Inscritos", "oculto" if est.get("hiddenSubscriberCount") else n(est.get("subscriberCount"))],
        ["Views totais", n(est.get("viewCount"))],
        ["Vídeos no canal", n(len(videos))],
        ["Públicos / não listados / privados",
         " / ".join(n(sum(v["status"]["privacyStatus"] == p for v in videos)) for p in ("public", "unlisted", "private"))],
    ])
    top = sorted(videos, key=lambda v: int(v["statistics"].get("viewCount", 0)), reverse=True)[:15]
    linhas += ["", "## Vídeos mais vistos (desde sempre)", ""]
    linhas += tabela(["#", "Vídeo", "Publicado", "Views", "Likes", "Comentários"], [
        [i + 1, v["snippet"]["title"][:70], v["snippet"]["publishedAt"][:10],
         n(v["statistics"].get("viewCount")), n(v["statistics"].get("likeCount")), n(v["statistics"].get("commentCount"))]
        for i, v in enumerate(top)])
    recentes = sorted(publicos, key=lambda v: v["snippet"]["publishedAt"], reverse=True)[:10]
    linhas += ["", "## Últimos vídeos públicos", ""]
    linhas += tabela(["Vídeo", "Publicado", "Views", "Likes"], [
        [v["snippet"]["title"][:70], v["snippet"]["publishedAt"][:10],
         n(v["statistics"].get("viewCount")), n(v["statistics"].get("likeCount"))] for v in recentes])
    return linhas, {v["id"]: v["snippet"]["title"] for v in videos}


def parte_periodo(credenciais, dias: int, titulos: dict) -> list[str]:
    ya = build("youtubeAnalytics", "v2", credentials=credenciais, cache_discovery=False)
    fim = dt.date.today() - dt.timedelta(days=1)
    inicio = fim - dt.timedelta(days=dias - 1)
    base = dict(ids="channel==MINE", startDate=inicio.isoformat(), endDate=fim.isoformat())

    def consulta(**kw):
        return ya.reports().query(**base, **kw).execute(num_retries=3).get("rows") or []

    try:
        total = consulta(metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost,likes")
    except HttpError as erro:
        if erro.resp.status in (401, 403):
            return ["", f"## Últimos {dias} dias", "",
                    "> A autorização atual não inclui o **YouTube Analytics** (horas assistidas, origem do tráfego etc.).",
                    "> Para liberar: rode de novo `python scripts/autorizar.py` no seu computador (ele já pede o escopo novo)",
                    "> e troque o segredo `GOOGLE_REFRESH_TOKEN` no GitHub pelo valor novo."]
        raise
    linhas = ["", f"## Últimos {dias} dias ({inicio:%d/%m} a {fim:%d/%m/%Y})", ""]
    if total:
        views, minutos, media, ganhos, perdidos, likes = total[0]
        linhas += tabela(["Métrica", "Valor"], [
            ["Views", n(views)], ["Horas assistidas", n(minutos / 60)],
            ["Duração média por view", f"{int(media) // 60} min {int(media) % 60:02d} s"],
            ["Inscritos ganhos / perdidos", f"+{n(ganhos)} / -{n(perdidos)}"], ["Likes", n(likes)]])
    linhas += ["", "### Vídeos com mais views no período", ""]
    top = consulta(dimensions="video", metrics="views,estimatedMinutesWatched,averageViewPercentage",
                   sort="-views", maxResults=10)
    linhas += tabela(["Vídeo", "Views", "Horas", "% assistido"],
                     [[titulos.get(v, v)[:70], n(vi), n(m / 60), f"{p:.0f}%"] for v, vi, m, p in top])
    linhas += ["", "### De onde vêm as views", ""]
    origens = consulta(dimensions="insightTrafficSourceType", metrics="views", sort="-views")
    soma = sum(r[1] for r in origens) or 1
    linhas += tabela(["Origem", "Views", "%"], [[ORIGENS.get(o, o), n(v), f"{100 * v / soma:.0f}%"] for o, v in origens])
    linhas += ["", "### Países", ""]
    paises = consulta(dimensions="country", metrics="views", sort="-views", maxResults=8)
    linhas += tabela(["País", "Views"], [[p, n(v)] for p, v in paises])
    linhas += ["", "### Por dia", ""]
    diario = consulta(dimensions="day", metrics="views,estimatedMinutesWatched,subscribersGained", sort="day")
    linhas += tabela(["Dia", "Views", "Horas", "Inscritos"],
                     [[d[8:10] + "/" + d[5:7], n(v), n(m / 60), n(s)] for d, v, m, s in diario])
    return linhas


def main() -> int:
    configurar_log()
    args = argparse.ArgumentParser()
    args.add_argument("--dias", type=int, default=28)
    dias = args.parse_args().dias
    credenciais = credenciais_do_ambiente()
    yt = build("youtube", "v3", credentials=credenciais, cache_discovery=False)
    linhas, titulos = parte_geral(yt)
    linhas += parte_periodo(credenciais, dias, titulos)
    relatorio = "\n".join(linhas) + "\n"
    print(relatorio)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(relatorio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
