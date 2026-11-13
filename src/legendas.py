"""Legendas: envia ao YouTube a transcrição de cada capítulo publicado (ajuda na busca e em quem ouve sem som)."""

from pathlib import Path

from comum import log
from cortar import Palavra
from transcrever import gerar_srt


def enviar_legenda(youtube, capitulo, registro: dict, palavras: list[Palavra], pasta_tmp: Path, idioma: str) -> bool:
    """Retorna True se enviou. Erros de permissão/limite sobem para quem chamou (SemPermissao / LimiteDiario)."""
    if not palavras:
        log.info("  capítulo %d sem fala reconhecida; legenda pulada.", capitulo.numero)
        registro["legenda"] = "pulado"
        return False
    srt = pasta_tmp / f"legenda_{capitulo.numero}.srt"
    srt.write_text(gerar_srt(palavras), encoding="utf-8")
    youtube.inserir_legenda(registro["video_id"], srt, idioma=idioma)
    registro["legenda"] = True
    log.info("  legenda enviada para %s", registro["video_id"])
    return True
