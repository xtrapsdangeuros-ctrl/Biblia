"""Troca a miniatura dos vídeos que saíram sem capa, depois que a capa do livro aparece na pasta do Drive.

A imagem dentro do vídeo não muda (seria preciso enviar o vídeo de novo); só a miniatura, que é o que aparece na
busca e na lista do canal. Cada troca custa ~50 unidades da cota diária do YouTube.

Uso:
  python src/miniaturas.py             # GitHub Actions (depois de procurar as capas)
  python src/miniaturas.py --dry-run   # só mostra quais vídeos mudariam
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from comum import carregar_config, configurar_log, log, so_audiolivro


def _quando(texto: str | None) -> datetime:
    if not texto:
        return datetime.min.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(texto.replace("Z", "+00:00"))


def precisa_trocar(registro: dict, capa: dict, feitas: dict | None = None) -> bool:
    """O vídeo foi publicado antes de a capa existir na pasta e a miniatura ainda não foi trocada."""
    ja = (feitas or {}).get(registro.get("video_id")) or registro.get("miniatura_capa")
    return not ja and _quando(registro.get("data")) < _quando(capa.get("createdTime"))


def processar(drive, youtube, raiz: str, cfg: dict, dry_run: bool = False) -> int:
    from googleapiclient.errors import HttpError

    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros
    # Registro próprio (e não o publicados.json), para poder rodar junto com a publicação sem pisar nela.
    ARQ = "miniaturas.json"
    from main import produzir_miniatura
    from video import gerar_arte

    trocadas = 0
    for pasta in pastas_de_livros(drive, raiz):
        livro = carregar_livro(drive, pasta)
        if not livro or not livro.capa:
            continue
        estado = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
        feitas = drive.ler_json(pasta["id"], ARQ, {}) if estado["capitulos"] else {}
        por_numero = {str(c.numero): c for c in livro.capitulos}
        pendentes, vistos = [], set()
        for n, r in sorted(estado["capitulos"].items(), key=lambda kv: int(kv[0])):
            if r["video_id"] not in vistos and precisa_trocar(r, livro.capa, feitas):
                pendentes.append((n, r))
            vistos.add(r["video_id"])   # vídeo com vários capítulos: uma miniatura só
        if not pendentes:
            continue
        log.info("'%s': %d vídeo(s) sem a capa na miniatura.", livro.nome, len(pendentes))
        if dry_run:
            continue
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            capa = drive.baixar(livro.capa["id"], tmp / livro.capa["name"])
            for numero, registro in pendentes:
                cap = por_numero.get(numero)
                titulo = cap.titulo if cap else ""
                if registro.get("parte"):
                    from metadados import intervalo
                    membros = [(int(n), por_numero[n].titulo if n in por_numero else "")
                               for n, r in estado["capitulos"].items() if r["video_id"] == registro["video_id"]]
                    imagem = gerar_arte(capa, tmp / f"mini_{numero}.jpg", livro.ficha["titulo"],
                                        livro.ficha.get("autor") or "", f"Parte {registro['parte']}",
                                        intervalo(sorted(membros)), 1280, 720, cfg["video"], miniatura=True)
                else:
                    imagem = produzir_miniatura(capa, livro.ficha, int(numero), titulo, tmp / f"mini_{numero}.jpg", cfg)
                try:
                    youtube.definir_miniatura(registro["video_id"], imagem)
                except HttpError as erro:
                    conteudo = (erro.content or b"").lower()
                    if erro.resp.status == 429 or (erro.resp.status == 403 and b"quota" in conteudo):
                        log.warning("O YouTube não aceita mais miniaturas hoje (limite diário); o resto fica para amanhã.")
                        drive.gravar_json(pasta["id"], ARQ, feitas)
                        return 0
                    log.warning("  Não consegui trocar a miniatura de %s: %s", registro["video_id"], erro)
                    continue
                feitas[registro["video_id"]] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                trocadas += 1
                log.info("  Miniatura com capa: %s", registro["video_id"])
        drive.gravar_json(pasta["id"], ARQ, feitas)
    log.info("Miniaturas trocadas: %d", trocadas)
    return 0


def main() -> int:
    configurar_log()
    if so_audiolivro("Miniaturas"):
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from google_api import Drive, YouTube, credenciais_do_ambiente
    credenciais = credenciais_do_ambiente()
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    return processar(Drive(credenciais), YouTube(credenciais), raiz, carregar_config(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
