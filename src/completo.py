"""Livro completo: junta todos os capítulos em vídeos de até ~11h, com marcadores de capítulo na descrição."""

import tempfile
from pathlib import Path

from comum import log
from metadados import _licenca, _limpar, hashtags_video, linha_principal, link_playlist, livro_e_autor, rotulo_e_titulo, \
    tags_video, titulo_completo
from video import duracao_audio, gerar_arte, gerar_video

LIMITE_DESCRICAO = 5000


def dividir_em_partes(duracoes: list[float], max_segundos: float) -> list[list[int]]:
    """Agrupa capítulos inteiros (índices) em partes que não passam de max_segundos."""
    partes, atual, soma = [], [], 0.0
    for i, d in enumerate(duracoes):
        if atual and soma + d > max_segundos:
            partes.append(atual)
            atual, soma = [], 0.0
        atual.append(i)
        soma += d
    if atual:
        partes.append(atual)
    return partes


def formatar_marcador(seg: float) -> str:
    seg = int(seg)
    h, resto = divmod(seg, 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def marcadores(rotulos: list[str], duracoes: list[float]) -> list[str]:
    """'00:00 Abertura', '12:31 Cap. 1'... (o YouTube transforma em capítulos clicáveis)."""
    linhas, t = [], 0.0
    for rotulo, d in zip(rotulos, duracoes):
        linhas.append(f"{formatar_marcador(t)} {rotulo}")
        t += d
    return linhas


def rotulo_curto(numero: int, titulo: str) -> str:
    rotulo, titulo = rotulo_e_titulo(numero, titulo)
    rotulo = rotulo.replace("Capítulo", "Cap.")
    return f"{rotulo}: {titulo}" if titulo else rotulo


def titulo_parte(ficha: dict, parte: int, total: int) -> str:
    return titulo_completo(ficha, parte, total)


def descricao_parte(ficha: dict, parte: int, total: int, linhas_marcadores: list[str],
                    playlist_id: str | None, outras: dict[int, str]) -> str:
    detalhe = "livro completo" + (f", parte {parte} de {total}" if total > 1 else "")
    topo = [linha_principal(ficha, detalhe)]
    if playlist_id:
        topo.append(f"▶ Capítulo por capítulo (playlist): {link_playlist(playlist_id)}")
    for n, vid in sorted(outras.items()):
        topo.append(f"▶ Parte {n}: https://youtu.be/{vid}")
    topo.append("")
    sinopse = str(ficha.get("descricao") or "").strip()
    if sinopse:
        topo += [sinopse.split("\n\n")[0], ""]
    rodape = ["", _licenca(ficha), "", " ".join(hashtags_video(ficha, ["audiolivrocompleto"]))]

    # Os marcadores são a parte mais importante; se não couber tudo, a sinopse é que encolhe.
    corpo = ["Capítulos:", *linhas_marcadores]
    texto = "\n".join(topo + corpo + rodape)
    if len(texto) > LIMITE_DESCRICAO:
        texto = "\n".join([t for t in topo if t.startswith(("Audiolivro", "▶"))] + [""] + corpo + rodape)
    return _limpar(texto)[:LIMITE_DESCRICAO]


def publicar_livro_completo(drive, youtube, livro, estado: dict, cfg: dict, privacidade: str,
                            max_partes: int) -> int:
    """Publica as partes que faltam (no máximo max_partes nesta execução). Retorna quantas publicou."""
    from livro import ARQ_PUBLICADOS

    capitulos = [c for c in livro.capitulos if str(c.numero) in estado["capitulos"]]
    registro = estado.setdefault("completo", {"partes": {}})
    max_seg = cfg["extras"]["horas_por_parte"] * 3600
    publicadas = 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # Durações: medidas uma vez e guardadas, para não baixar tudo de novo a cada execução.
        if "duracoes" not in registro:
            from transcrever import baixar_capitulo
            duracoes = {}
            for c in capitulos:
                pasta_cap = tmp / f"d{c.numero}"
                pasta_cap.mkdir()
                duracoes[str(c.numero)] = round(sum(duracao_audio(drive.baixar(a["id"], pasta_cap / f"{i}{Path(a['name']).suffix}"))
                                                    for i, a in enumerate(c.arquivos)), 2)
                for f in pasta_cap.iterdir():
                    f.unlink()
            registro["duracoes"] = duracoes
            drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)

        duracoes = [registro["duracoes"][str(c.numero)] for c in capitulos]
        grupos = dividir_em_partes(duracoes, max_seg)
        total = len(grupos)
        capa = drive.baixar(livro.capa["id"], tmp / livro.capa["name"]) if livro.capa else None

        for n, grupo in enumerate(grupos, start=1):
            if str(n) in registro["partes"]:
                continue
            if publicadas >= max_partes:
                break
            caps = [capitulos[i] for i in grupo]
            log.info("Livro completo '%s': parte %d de %d (%d capítulos, %.1f h)", livro.nome, n, total,
                     len(caps), sum(duracoes[i] for i in grupo) / 3600)
            pasta_parte = tmp / f"parte{n}"
            pasta_parte.mkdir()
            audios = [drive.baixar(a["id"], pasta_parte / f"{c.numero:06d}_{j}{Path(a['name']).suffix}")
                      for c in caps for j, a in enumerate(c.arquivos)]
            rotulo = "Audiolivro Completo" + (f" – Parte {n} de {total}" if total > 1 else "")
            arte = gerar_arte(capa, pasta_parte / "arte.png", *livro_e_autor(livro.ficha),
                              rotulo, "", cfg["video"]["largura"], cfg["video"]["altura"], cfg["video"])
            video = gerar_video(arte, audios, pasta_parte / "completo.mp4", cfg["video"].get("copiar_audio", True))
            linhas = marcadores([rotulo_curto(c.numero, c.titulo) for c in caps], [duracoes[i] for i in grupo])
            outras = {int(k): v for k, v in registro["partes"].items()}
            pub = cfg["publicacao"]
            snippet = {
                "title": titulo_parte(livro.ficha, n, total),
                "description": descricao_parte(livro.ficha, n, total, linhas, estado.get("playlist_id"), outras),
                "tags": tags_video(livro.ficha),
                "categoryId": str(pub["categoria_id"]),
                "defaultLanguage": pub["idioma"],
                "defaultAudioLanguage": pub["idioma"],
            }
            status = {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False,
                      "containsSyntheticMedia": bool(livro.ficha.get("voz_sintetica", False))}
            video_id = youtube.enviar_video(video, snippet, status)
            registro["partes"][str(n)] = video_id
            drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)
            log.info("  publicado: %s", video_id)
            if estado.get("playlist_id"):
                try:
                    youtube.adicionar_na_playlist(estado["playlist_id"], video_id)
                except Exception as erro:
                    log.warning("  não entrou na playlist: %s", erro)
            for f in pasta_parte.iterdir():
                f.unlink()
            publicadas += 1
        if len(registro["partes"]) == total:
            registro["concluido"] = True
            drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)
    return publicadas
