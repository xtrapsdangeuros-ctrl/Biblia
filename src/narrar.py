"""Narra livros a partir do .epub com uma voz do Google e grava os capítulos em MP3 na pasta do livro.

Para um livro ser narrado, a ficha dele precisa ter `narrar: true` (e, se quiser, `voz: pt-BR-Chirp3-HD-Achernar`),
e a pasta precisa ter o arquivo .epub. Os capítulos vão para `capitulos/` com nomes "005 - Capítulo 1 - Título.mp3";
daí o robô de publicação posta normalmente, um por vez, como faz com qualquer livro.

A cota grátis do Google é por mês. O robô conta os caracteres enviados (em `narracao.json`, na pasta Audiolivros)
e para antes de passar de `narracao.caracteres_por_mes` (config.yaml); no mês seguinte ele continua de onde parou.

Uso:
  python src/narrar.py             # GitHub Actions, todo dia
  python src/narrar.py --dry-run   # só mostra o que narraria e quantos caracteres gastaria
"""

import argparse
import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from comum import carregar_config, configurar_log, ler_nome_capitulo, log, nome_arquivo_capitulo, normalizar, pausado

ARQ_USO = "narracao.json"


def mes_atual() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _ficha(drive, itens: list[dict]) -> dict:
    from livro import NOMES_FICHA, _ler_ficha
    item = next((i for i in itens if normalizar(i["name"]) in NOMES_FICHA), None)
    try:
        return _ler_ficha(drive, item) if item else {}
    except Exception as erro:   # ficha com defeito: o robô de publicação já avisa
        log.warning("Não consegui ler a ficha: %s", erro)
        return {}


def processar(drive, raiz: str, cfg: dict, dry_run: bool = False) -> int:
    import vozes
    from epub import ler_epub, texto_falado, titulo_arquivo
    from livro import PASTA_CAPITULOS, pastas_de_livros

    ncfg = cfg.get("narracao") or {}
    limite = int(ncfg.get("caracteres_por_mes", 850_000))
    prazo = time.monotonic() + ncfg.get("minutos_maximos", 240) * 60
    chave = os.environ.get("GOOGLE_TTS_API_KEY")
    uso = drive.ler_json(raiz, ARQ_USO, {"meses": {}})
    mes = mes_atual()
    usado = uso["meses"].get(mes, 0)
    feitos = 0

    for pasta in pastas_de_livros(drive, raiz):
        if pausado(cfg, pasta["name"]):
            continue
        itens = drive.listar(pasta["id"])
        ficha = _ficha(drive, itens)
        if not ficha.get("narrar") or ficha.get("ativo") is False:
            continue
        arquivo_epub = next((i for i in itens if i["name"].lower().endswith(".epub")), None)
        if not arquivo_epub:
            log.warning("'%s' pede narração, mas não tem arquivo .epub na pasta.", pasta["name"])
            continue
        if not chave and not dry_run:
            log.error("Falta o segredo GOOGLE_TTS_API_KEY no GitHub: não dá para narrar '%s'.", pasta["name"])
            return 1
        voz = ficha.get("voz") or ncfg.get("voz", "pt-BR-Chirp3-HD-Achernar")

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            secoes = ler_epub(drive.baixar(arquivo_epub["id"], tmp / "livro.epub"))
            pasta_caps = drive.pasta(pasta["id"], PASTA_CAPITULOS) if not dry_run else None
            prontos = set()
            if pasta_caps:
                prontos = {lido[0] for i in drive.listar(pasta_caps) if (lido := ler_nome_capitulo(i["name"]))}
            faltam = [(n, s) for n, s in enumerate(secoes, start=1) if n not in prontos]
            log.info("'%s': %d seções no livro, %d já narradas, %d faltando (%s caracteres). Voz: %s.",
                     pasta["name"], len(secoes), len(secoes) - len(faltam), len(faltam),
                     f"{sum(s.caracteres for _, s in faltam):,}".replace(",", "."), voz)

            for numero, secao in faltam:
                n = secao.caracteres
                if usado + n > limite:
                    log.info("Cota grátis do mês quase no fim (%s de %s caracteres). A narração continua no "
                             "próximo mês.", f"{usado:,}".replace(",", "."), f"{limite:,}".replace(",", "."))
                    return 0
                if time.monotonic() > prazo:
                    log.info("Tempo de hoje esgotado; continua amanhã.")
                    return 0
                nome = nome_arquivo_capitulo(numero, titulo_arquivo(secao.titulo), ".mp3", largura=3)
                if dry_run:
                    log.info("[dry-run] narraria %s (%d caracteres)", nome, n)
                    usado += n
                    continue
                log.info("Narrando %s (%d caracteres)...", nome, n)
                mp3 = vozes.narrar_google(texto_falado(secao), voz, chave, tmp / "capitulo.mp3",
                                          ncfg.get("idioma", "pt-BR"))
                drive.enviar(mp3, pasta_caps, nome=nome, mime="audio/mpeg")
                mp3.unlink()
                usado += n
                uso["meses"][mes] = usado
                drive.gravar_json(raiz, ARQ_USO, uso)
                feitos += 1

    log.info("Capítulos narrados hoje: %d. Caracteres usados neste mês: %s de %s.", feitos,
             f"{usado:,}".replace(",", "."), f"{limite:,}".replace(",", "."))
    return 0


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    from google_api import Drive, credenciais_do_ambiente
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    return processar(Drive(credenciais_do_ambiente()), raiz, carregar_config(), args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
