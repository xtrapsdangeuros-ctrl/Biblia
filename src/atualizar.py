"""Reaplica a ficha do livro (título, descrição, tags) nos vídeos que já foram publicados.

Use depois de mudar a ficha.txt de um livro. Cada vídeo atualizado fica marcado no publicados.json; se o
YouTube atingir o limite diário no meio, é só rodar de novo depois que ele continua de onde parou.

Uso:
  python src/atualizar.py --livro "Ricardo Montemor Despertar (Cyclo do Despertar Vol. 4)" --dry-run
  python src/atualizar.py --livro "..."            # atualiza os que ainda não foram atualizados
  python src/atualizar.py --livro "..." --forcar   # atualiza todos de novo (ex.: mudou a ficha outra vez)
"""

import argparse
import os
import sys
from datetime import datetime, timezone

import discreto
from comum import carregar_config, configurar_log, log, normalizar, so_audiolivro
from metadados import snippet_video


def montar_snippet(ficha: dict, numero: int, titulo_cap: str, playlist_id: str | None,
                   anterior_id: str | None, pub: dict, cta: dict | None = None) -> dict:
    return snippet_video(ficha, [(numero, titulo_cap, 0.0)], None, playlist_id, anterior_id, pub, cta)


def agrupar_videos(estado: dict) -> list[list[tuple[str, dict]]]:
    """Um item por vídeo, em ordem (um vídeo longo tem vários capítulos)."""
    videos: list[list[tuple[str, dict]]] = []
    for numero, registro in sorted(estado["capitulos"].items(), key=lambda kv: int(kv[0])):
        if videos and videos[-1][0][1]["video_id"] == registro["video_id"]:
            videos[-1].append((numero, registro))
        else:
            videos.append([(numero, registro)])
    return videos


def snippets_do_livro(livro, estado: dict, cfg: dict) -> list[tuple[list[tuple[str, dict]], dict]]:
    """[(itens do vídeo, snippet novo)] para cada vídeo de capítulo já publicado, com anterior e próximo."""
    titulos = {str(c.numero): c.titulo for c in livro.capitulos}
    videos = agrupar_videos(estado)
    saida = []
    for posicao, itens in enumerate(videos):
        primeiro = itens[0][1]
        anterior_id = videos[posicao - 1][0][1]["video_id"] if posicao else None
        proximo_id = videos[posicao + 1][0][1]["video_id"] if posicao + 1 < len(videos) else None
        caps = [(int(n), titulos.get(n, ""), float(r.get("inicio", 0))) for n, r in itens]
        parte = primeiro.get("parte") if len(itens) > 1 else None
        snippet = snippet_video(livro.ficha, caps, parte, estado.get("playlist_id"), anterior_id, cfg["publicacao"],
                                cfg.get("cta") or {}, float(primeiro.get("duracao_total", 0)) or caps[-1][2] + 1,
                                proximo_id)
        saida.append((itens, snippet))
    return saida


def atualizar_livro(drive, youtube, pasta: dict, cfg: dict, dry_run: bool, forcar: bool) -> int:
    from google_api import LimiteDiario
    from livro import ARQ_PUBLICADOS, carregar_livro

    livro = carregar_livro(drive, pasta)
    if livro.problemas:
        log.error("Ficha com problema, nada foi alterado:\n%s", "\n".join(f"  - {p}" for p in livro.problemas))
        return 1
    estado = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
    feitos = 0
    for itens, snippet in snippets_do_livro(livro, estado, cfg):
        primeiro = itens[0][1]
        if forcar or not primeiro.get("metadados_atualizados"):
            if dry_run:
                if feitos == 0:
                    log.info("[dry-run] exemplo (%s):\nTítulo: %s\nTags: %s\n%s",
                             primeiro["video_id"], snippet["title"], ", ".join(snippet["tags"]), snippet["description"])
            else:
                try:
                    youtube.atualizar_metadados(primeiro["video_id"], snippet)
                except LimiteDiario as motivo:
                    log.warning("Limite diário do YouTube (%s) depois de %d vídeo(s). Rode de novo amanhã.", motivo, feitos)
                    drive.gravar_json(pasta["id"], ARQ_PUBLICADOS, estado)
                    return 0
                quando = datetime.now(timezone.utc).isoformat(timespec="seconds")
                for _, r in itens:
                    r["metadados_atualizados"] = quando
                if feitos % 10 == 9:
                    drive.gravar_json(pasta["id"], ARQ_PUBLICADOS, estado)   # salva o progresso de tempos em tempos
            feitos += 1

    if not dry_run:
        drive.gravar_json(pasta["id"], ARQ_PUBLICADOS, estado)
    log.info("%s: %d vídeo(s) %s.", livro.nome, feitos, "seriam atualizados" if dry_run else "atualizados")
    return 0


def main() -> int:
    configurar_log()
    if so_audiolivro("Reaplicar a ficha"):
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--livro", required=True, type=discreto.resolver,
                        help="número do livro no log, nome da pasta ou um trecho único dele")
    parser.add_argument("--dry-run", action="store_true", help="só mostra como ficaria")
    parser.add_argument("--forcar", action="store_true", help="atualiza também os que já foram atualizados")
    args = parser.parse_args()

    from google_api import Drive, YouTube, credenciais_do_ambiente
    from livro import pastas_de_livros, pedido_casa

    credenciais = credenciais_do_ambiente()
    drive, youtube = Drive(credenciais), YouTube(credenciais)
    pastas = [p for p in pastas_de_livros(drive, os.environ["DRIVE_PASTA_RAIZ"])
              if pedido_casa(args.livro, p["name"])]
    if len(pastas) != 1:
        log.error("O livro pedido '%s' corresponde a %d pastas: %s", args.livro, len(pastas),
                  ", ".join(discreto.rotulo(p["name"]) for p in pastas) or "nenhuma")
        return 1
    return atualizar_livro(drive, youtube, pastas[0], carregar_config(), args.dry_run, args.forcar)


if __name__ == "__main__":
    sys.exit(main())
