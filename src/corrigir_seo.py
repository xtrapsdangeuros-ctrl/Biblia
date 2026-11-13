"""Corrige o SEO dos vídeos JÁ publicados, aos poucos, sem estourar a cota do YouTube.

Funciona em duas etapas, para nada mudar sem você ver antes:
  1. Prévia: monta a lista de mudanças (título, descrição, tags, playlists e comentário com o link da playlist)
     e grava no Drive ("Audiolivros/SEO - plano de correção.json"). NADA muda no YouTube.
  2. Aplicar: aprova essa lista e aplica até N mudanças por dia (cada uma gasta 50 unidades da cota).
     As execuções diárias do robô continuam a lista aprovada até acabar.

Proteções:
  - vídeos que o robô não publicou (os antigos) só ganham tags e hashtags: título e texto ficam iguais;
  - vídeos com muitas views (seo.proteger_titulo_acima_de_views) ou listados em seo.titulos_protegidos
    nunca têm o título trocado;
  - se alguém mexeu no vídeo depois da prévia, o robô pula esse vídeo (não desfaz a sua mudança).

Uso:
  python src/corrigir_seo.py --previa
  python src/corrigir_seo.py --aplicar --max 40
  python src/corrigir_seo.py --continuar        # todo dia; só faz algo se a lista já foi aprovada
"""

import argparse
import collections
import os
import re
import sys
import time
from datetime import datetime, timezone

from comum import carregar_config, configurar_log, log, so_audiolivro
import metadados
from metadados import (_corrigir, descricao_playlist, hashtags_video, link_playlist, tags_video, titulo_playlist,
                       titulo_short)

ARQ_PLANO = "SEO - plano de correção.json"
CUSTO = 50   # videos.update, playlists.update e commentThreads.insert gastam 50 unidades cada
PAUSA_SEG = 2   # entre uma mudança e outra: muitas seguidas fazem o YouTube recusar (erro 429)
_MARCADOR = re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s")
_CAMPOS = ("title", "description", "tags")


def agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ vídeos antigos (fora do robô)

def ficha_de_titulo_antigo(titulo: str) -> dict | None:
    """'Áudiolivro Lumenor PARTE 1 DE 3 (Ciclo do Despertar #3) - Ricrdo Montemor (Voz Humana HD)'
    -> {'titulo': 'Lumenor', 'autor': 'Ricardo Montemor', 'serie': 'Ciclo do Despertar', 'volume': 3}."""
    if titulo.upper().startswith("AUDIOLIVRO "):   # já está no padrão novo
        return None
    if not re.search(r"[áa]udio\s?livro|audiobook|parte\s+\d|\d\s*/\s*\d|vol\.?\s*\d|livro\s+\d", titulo, re.IGNORECASE):
        return None   # não parece audiolivro (live, aviso, etc.)
    principal, *extras = [p.strip() for p in titulo.split("|")]
    principal = re.sub(r"^[áa]udio\s?livro\s+", "", principal, flags=re.IGNORECASE)
    livro = re.split(r"\s+(?:parte\s+\d|vol\.?\s*\d|\d+\s*/\s*\d+|\(|-\s)", principal, maxsplit=1,
                     flags=re.IGNORECASE)[0].strip()
    if len(livro) < 3:
        return None
    ficha = {"titulo": livro}
    serie = re.search(r"\(([^()#]+?)\s*#\s*(\d+)\)", principal)
    if serie:
        ficha.update(serie=serie.group(1).strip(), volume=int(serie.group(2)))
    else:
        ficha["serie"] = next((e for e in reversed(extras) if len(e.split()) >= 4), "")
        volume = re.search(r"\b(?:livro|vol\.?)\s*(\d+)", principal, re.IGNORECASE)
        if volume:
            ficha["volume"] = int(volume.group(1))
    autor = re.search(r"\s-\s+([^()|]+?)\s*(?:\(|$)", principal)
    if autor:
        ficha["autor"] = _corrigir(autor.group(1).strip())
    else:
        texto = (titulo + " " + ficha.get("serie", "")).lower()
        ficha["autor"] = next((a for chave, a in metadados.AUTOR_DA_SERIE.items() if chave in texto), "")
    return ficha


# ------------------------------------------------------------------ comparação

def snippet_atual(video: dict) -> dict:
    sn = video["snippet"]
    atual = {"title": sn["title"], "description": sn.get("description", ""), "tags": sn.get("tags", []),
             "categoryId": sn.get("categoryId", "27")}
    for campo in ("defaultLanguage", "defaultAudioLanguage"):
        if sn.get(campo):
            atual[campo] = sn[campo]
    return atual


def mesclar(atual: dict, novo: dict, manter_titulo: bool) -> dict:
    """Snippet completo para o videos.update: o que já existe + o que muda (o título fica, se protegido)."""
    saida = {**atual, **{k: v for k, v in novo.items() if k in _CAMPOS or k.startswith("default")}}
    if manter_titulo:
        saida["title"] = atual["title"]
    return saida


def campos_mudados(antes: dict, depois: dict) -> list[str]:
    return [c for c in _CAMPOS if (antes.get(c) or "") != (depois.get(c) or "")]


def titulo_protegido(video: dict, seo: dict) -> bool:
    views = int(video.get("statistics", {}).get("viewCount", 0))
    return video["id"] in set(seo.get("titulos_protegidos") or []) or views >= int(seo.get("proteger_titulo_acima_de_views", 1000))


def texto_comentario(playlist_id: str, cta: dict) -> str:
    linhas = [f"📚 Ouça o livro todo, em ordem, nesta playlist: {link_playlist(playlist_id)}"]
    if cta.get("canal"):
        linhas.append(f"🔔 Inscreva-se para receber os próximos capítulos: {cta['canal']}")
    return "\n".join(linhas)


# ------------------------------------------------------------------ montar a lista

def _novos_do_livro(livro, estado: dict, cfg: dict, videos: dict) -> list[tuple[str, dict, list[str]]]:
    """[(video_id, snippet novo, números dos capítulos)] de capítulos, Shorts e livro completo deste livro."""
    from atualizar import snippets_do_livro
    from completo import descricao_parte, titulo_parte
    from shorts import descricao_short

    saida = [(itens[0][1]["video_id"], snippet, [n for n, _ in itens])
             for itens, snippet in snippets_do_livro(livro, estado, cfg)]
    playlist_id = estado.get("playlist_id")
    for c in livro.capitulos:
        reg = estado["capitulos"].get(str(c.numero)) or {}
        short = reg.get("short")
        if isinstance(short, str) and short != "pulado":
            alvo = reg["video_id"] + (f"?t={int(reg['inicio'])}" if reg.get("inicio") else "")
            saida.append((short, {"title": titulo_short(livro.ficha, c.numero, c.titulo),
                                  "description": descricao_short(livro.ficha, c.numero, c.titulo, alvo, playlist_id),
                                  "tags": tags_video(livro.ficha, ["shorts"])}, []))
    partes = (estado.get("completo") or {}).get("partes") or {}
    for n, vid in partes.items():
        atual = videos.get(vid)
        if not atual:
            continue
        # os tempos dos capítulos são aproveitados da descrição que já está no ar
        linhas = [l for l in atual["snippet"].get("description", "").splitlines() if _MARCADOR.match(l)]
        total = re.search(r"\b(\d+)\s+(?:de|DE)\s+(\d+)\)", atual["snippet"]["title"])
        if len(linhas) < 3:
            continue
        outras = {int(k): v for k, v in partes.items() if k != n}
        saida.append((vid, {"title": titulo_parte(livro.ficha, int(n), int(total.group(2)) if total else 1),
                            "description": descricao_parte(livro.ficha, int(n), int(total.group(2)) if total else 1,
                                                           linhas, playlist_id, outras),
                            "tags": tags_video(livro.ficha, ["audiolivro completo"])}, []))
    return saida


def montar_plano(drive, youtube, raiz: str, cfg: dict) -> dict:
    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros

    seo = cfg.get("seo") or {}
    cta = cfg.get("cta") or {}
    videos = {v["id"]: v for v in youtube.videos_do_canal()}
    log.info("%d vídeos no canal.", len(videos))
    itens, geridos = [], set()
    playlists: dict[str, tuple[dict, list[str]]] = {}

    for pasta in pastas_de_livros(drive, raiz):
        livro = carregar_livro(drive, pasta)
        if not livro:
            continue
        estado = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
        if not estado.get("capitulos"):
            continue
        ids_do_livro = []
        for vid, novo, numeros in _novos_do_livro(livro, estado, cfg, videos):
            geridos.add(vid)
            ids_do_livro.append(vid)
            v = videos.get(vid)
            if not v:
                continue
            antes = snippet_atual(v)
            protegido = titulo_protegido(v, seo)
            depois = mesclar(antes, novo, protegido)
            mudou = campos_mudados(antes, depois)
            if mudou:
                itens.append({"tipo": "video", "id": vid, "livro": livro.nome, "views": int(v["statistics"].get("viewCount", 0)),
                              "campos": mudou, "titulo_protegido": protegido, "antes": antes, "depois": depois})
            # comentário com o link da playlist (só nos vídeos públicos de capítulo)
            reg = estado["capitulos"].get(numeros[0]) if numeros else None
            if (seo.get("comentar_playlist", True) and reg and not reg.get("comentario") and estado.get("playlist_id")
                    and v["status"]["privacyStatus"] == "public"):
                itens.append({"tipo": "comentario", "id": vid, "livro": livro.nome, "pasta_id": pasta["id"],
                              "capitulos": numeros, "depois": {"texto": texto_comentario(estado["playlist_id"], cta)}})
        if estado.get("playlist_id"):
            playlists[estado["playlist_id"]] = (livro.ficha, ids_do_livro, livro.nome)

    # vídeos antigos, de antes do robô: só tags e hashtags (título e texto ficam como estão)
    for vid, v in videos.items():
        if vid in geridos or v["status"]["privacyStatus"] != "public":
            continue
        ficha = ficha_de_titulo_antigo(v["snippet"]["title"])
        if not ficha:
            continue
        antes = snippet_atual(v)
        novo = dict(antes)
        if len(antes["tags"]) < 5:
            novo["tags"] = tags_video({**ficha, "tags": antes["tags"]})
        if "#" not in antes["description"]:
            novo["description"] = (antes["description"].rstrip() + "\n\n" + " ".join(hashtags_video(ficha))).strip()
        mudou = campos_mudados(antes, novo)
        if mudou:
            itens.append({"tipo": "video", "id": vid, "livro": f"(antigo) {ficha['titulo']}", "antigo": True,
                          "views": int(v["statistics"].get("viewCount", 0)), "campos": mudou, "titulo_protegido": True,
                          "antes": antes, "depois": novo})

    # playlists: nome e descrição no padrão novo; pública quando o livro já tem vídeo público
    for p in youtube.ler_playlists(list(playlists)):
        ficha, ids, nome = playlists[p["id"]]
        tem_publico = any(videos.get(i, {}).get("status", {}).get("privacyStatus") == "public" for i in ids)
        antes = {"title": p["snippet"]["title"], "description": p["snippet"].get("description", ""),
                 "privacidade": p["status"]["privacyStatus"]}
        depois = {"title": titulo_playlist(ficha), "description": descricao_playlist(ficha),
                  "privacidade": "public" if tem_publico else antes["privacidade"]}
        if antes != depois:
            itens.append({"tipo": "playlist", "id": p["id"], "livro": nome, "antes": antes, "depois": depois,
                          "campos": [k for k in depois if antes[k] != depois[k]]})

    # a ordem importa: primeiro o que mais ajuda (vídeos públicos com views), depois o resto
    ordem = {"playlist": 0, "video": 1, "comentario": 2}
    itens.sort(key=lambda i: (ordem[i["tipo"]], -i.get("views", 0)))
    return {"criado": agora(), "aprovado": False, "itens": itens}


# ------------------------------------------------------------------ relatório

def _curto(texto: str, n: int = 75) -> str:
    texto = " ".join(str(texto).split())
    texto = texto if len(texto) <= n else texto[: n - 1] + "…"
    return texto.replace("|", "\\|")   # o "|" do título não pode quebrar a tabela


def relatorio(plano: dict, por_dia: int) -> list[str]:
    itens = plano["itens"]
    pendentes = [i for i in itens if not i.get("feito")]
    tipos = collections.Counter(i["tipo"] for i in pendentes)
    linhas = ["# SEO: lista de correções", "",
              f"Lista criada em {plano['criado'][:16].replace('T', ' ')} (UTC). "
              + ("**Aprovada**: o robô aplica um pouco por dia." if plano.get("aprovado")
                 else "**Ainda não aprovada**: nada mudou no YouTube."), "",
              f"- Vídeos: {tipos['video']} (antigos, só tags e hashtags: {sum(1 for i in pendentes if i.get('antigo'))})",
              f"- Playlists: {tipos['playlist']}", f"- Comentários com o link da playlist: {tipos['comentario']}",
              f"- Cota: {CUSTO * len(pendentes):,} unidades no total; com {por_dia} por dia, "
              f"termina em {-(-len(pendentes) // max(1, por_dia))} dia(s).".replace(",", "."), ""]
    feitos = [i for i in itens if i.get("feito")]
    if feitos:
        linhas += [f"Já feitos: {len(feitos)} (pulados por terem mudado depois da prévia: "
                   f"{sum(1 for i in feitos if str(i['feito']).startswith('pulado'))}).", ""]
    linhas += ["## Títulos", "", "| Vídeo | Views | Antes | Depois |", "|---|---|---|---|"]
    for i in pendentes:
        if i["tipo"] == "video" and "title" in i["campos"]:
            linhas.append(f"| [{i['id']}](https://youtu.be/{i['id']}) | {i['views']} | {_curto(i['antes']['title'])} "
                          f"| {_curto(i['depois']['title'])} |")
    linhas += ["", "## Só descrição e tags (título fica igual)", "", "| Vídeo | Views | Título | Muda |", "|---|---|---|---|"]
    for i in pendentes:
        if i["tipo"] == "video" and "title" not in i["campos"]:
            nota = " (título protegido)" if i.get("titulo_protegido") and not i.get("antigo") else ""
            linhas.append(f"| [{i['id']}](https://youtu.be/{i['id']}) | {i['views']} | {_curto(i['antes']['title'], 60)} "
                          f"| {', '.join(i['campos'])}{nota} |")
    linhas += ["", "## Playlists", "", "| Playlist | Antes | Depois |", "|---|---|---|"]
    for i in pendentes:
        if i["tipo"] == "playlist":
            linhas.append(f"| [{_curto(i['livro'], 40)}](https://www.youtube.com/playlist?list={i['id']}) "
                          f"| {_curto(i['antes']['title'], 50)} ({i['antes']['privacidade']}) "
                          f"| {_curto(i['depois']['title'], 50)} ({i['depois']['privacidade']}) |")
    exemplos = [i for i in pendentes if i["tipo"] == "video" and "description" in i["campos"]][:3]
    if exemplos:
        linhas += ["", "## Exemplos de descrição (antes e depois)"]
        for i in exemplos:
            linhas += ["", f"<details><summary>{_curto(i['antes']['title'], 90)}</summary>", "",
                       "**Antes:**", "```", i["antes"]["description"][:1500], "```", "**Depois:**", "```",
                       i["depois"]["description"][:1500], "```", f"**Tags depois:** {', '.join(i['depois']['tags'])}",
                       "", "</details>"]
    return linhas


def publicar_relatorio(linhas: list[str]) -> None:
    texto = "\n".join(linhas) + "\n"
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto[:900_000])
    with open("plano_seo.md", "w", encoding="utf-8") as f:
        f.write(texto)


# ------------------------------------------------------------------ aplicar

def aplicar(drive, youtube, raiz: str, cfg: dict, maximo: int, aprovar: bool) -> dict | None:
    from google_api import LimiteDiario, SemPermissao
    from livro import ARQ_PUBLICADOS

    plano = drive.ler_json(raiz, ARQ_PLANO, {})
    if not plano.get("itens"):
        log.info("Não há lista de correções de SEO. Rode a prévia primeiro.")
        return None
    if aprovar and not plano.get("aprovado"):
        plano["aprovado"] = agora()
    if not plano.get("aprovado"):
        log.info("A lista de correções de SEO ainda não foi aprovada; nada foi alterado.")
        return plano
    pendentes = [i for i in plano["itens"] if not i.get("feito")]
    if not pendentes:
        log.info("Lista de correções de SEO já terminou.")
        return plano
    lote = pendentes[:maximo * 2]   # lê o estado atual só do que pode ser feito hoje
    atuais = {v["id"]: v for v in youtube.ler_videos(list({i["id"] for i in lote if i["tipo"] != "playlist"}))}
    feitos, pode_comentar = 0, True
    for item in lote:
        if feitos >= maximo:
            break
        if feitos:
            time.sleep(PAUSA_SEG)
        try:
            if item["tipo"] == "video":
                v = atuais.get(item["id"])
                if not v:
                    item["feito"] = "pulado: vídeo não existe mais"
                    continue
                agora_no_ar = snippet_atual(v)
                if any(agora_no_ar.get(c) != item["antes"].get(c) for c in ("title", "description")):
                    item["feito"] = "pulado: mudou depois da prévia"
                    log.info("Pulado (mudou depois da prévia): %s", item["id"])
                    continue
                youtube.atualizar_metadados(item["id"], item["depois"])
            elif item["tipo"] == "playlist":
                d = item["depois"]
                youtube.atualizar_playlist(item["id"], d["title"], d["description"], d["privacidade"])
            elif item["tipo"] == "comentario":
                if not pode_comentar or item["id"] not in atuais:
                    continue
                comentario_id = youtube.comentar(item["id"], item["depois"]["texto"])
                estado = drive.ler_json(item["pasta_id"], ARQ_PUBLICADOS, {"capitulos": {}})
                for n in item["capitulos"]:
                    if n in estado["capitulos"]:
                        estado["capitulos"][n]["comentario"] = comentario_id
                drive.gravar_json(item["pasta_id"], ARQ_PUBLICADOS, estado)
        except LimiteDiario as motivo:
            log.warning("Limite do YouTube (%s) depois de %d mudança(s). Continua na próxima execução.", motivo, feitos)
            break
        except Exception:
            drive.gravar_json(raiz, ARQ_PLANO, plano)   # guarda o que já foi feito antes de parar
            raise
        except SemPermissao:
            log.warning("A autorização atual não permite comentar. Rode scripts/autorizar.py de novo e troque o "
                        "segredo GOOGLE_REFRESH_TOKEN. Os comentários ficam para depois.")
            pode_comentar = False
            continue
        item["feito"] = agora()
        feitos += 1
        log.info("SEO %s atualizado: %s", item["tipo"], item["id"])
        if feitos % 10 == 0:
            drive.gravar_json(raiz, ARQ_PLANO, plano)
    drive.gravar_json(raiz, ARQ_PLANO, plano)
    log.info("Correções de SEO nesta execução: %d. Faltam %d.", feitos,
             sum(1 for i in plano["itens"] if not i.get("feito")))
    return plano


def main() -> int:
    configurar_log()
    if so_audiolivro("Correção de SEO"):
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    modo = parser.add_mutually_exclusive_group(required=True)
    modo.add_argument("--previa", action="store_true", help="monta a lista de mudanças; não altera nada")
    modo.add_argument("--aplicar", action="store_true", help="aprova a lista do Drive e aplica até --max mudanças")
    modo.add_argument("--continuar", action="store_true", help="continua uma lista já aprovada (uso diário)")
    parser.add_argument("--max", type=int, help="quantas mudanças fazer agora (padrão: seo.mudancas_por_dia)")
    args = parser.parse_args()

    from google_api import Drive, YouTube, credenciais_do_ambiente
    cfg = carregar_config()
    por_dia = args.max or int((cfg.get("seo") or {}).get("mudancas_por_dia", 40))
    credenciais = credenciais_do_ambiente()
    drive, youtube = Drive(credenciais), YouTube(credenciais)
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    if args.previa:
        plano = montar_plano(drive, youtube, raiz, cfg)
        drive.gravar_json(raiz, ARQ_PLANO, plano)
    else:
        plano = aplicar(drive, youtube, raiz, cfg, por_dia, aprovar=args.aplicar)
    if plano:
        publicar_relatorio(relatorio(plano, por_dia))
    return 0


if __name__ == "__main__":
    sys.exit(main())
