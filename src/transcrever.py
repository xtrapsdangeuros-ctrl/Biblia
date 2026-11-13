"""Transcrição dos capítulos (usada pelas legendas e pelos Shorts), com cache no Drive.

Cada capítulo é transcrito uma única vez: o resultado fica em `transcricoes/<numero>.json` na pasta do livro.
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path

from comum import log
from cortar import Palavra, transcrever

PASTA_TRANSCRICOES = "transcricoes"
PEDACO_SEG = 20 * 60   # áudio longo é transcrito em pedaços de 20 min, e o progresso fica salvo no Drive


class TempoEsgotado(Exception):
    """Acabou o tempo de trabalho do dia no meio de uma transcrição (o que já foi feito está salvo)."""
_FIM_DE_FRASE = (".", "!", "?", "…", ":", ";")


def juntar_audios(audios: list[Path], destino: Path) -> Path:
    """Emenda as partes (A, B...) de um capítulo num único arquivo de áudio."""
    if len(audios) == 1:
        return audios[0]
    entradas = [arg for a in audios for arg in ("-i", str(a))]
    emenda = "".join(f"[{i}:a]" for i in range(len(audios))) + f"concat=n={len(audios)}:v=0:a=1[a]"
    subprocess.run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex", emenda, "-map", "[a]",
                    "-c:a", "aac", "-b:a", "160k", str(destino)], check=True)
    return destino


def baixar_capitulo(drive, capitulo, pasta_tmp: Path) -> Path:
    partes = [drive.baixar(a["id"], pasta_tmp / f"parte{i:02d}{Path(a['name']).suffix}")
              for i, a in enumerate(capitulo.arquivos)]
    return juntar_audios(partes, pasta_tmp / "capitulo.m4a")


def _como_json(palavras: list[Palavra]) -> list:
    return [[p.texto, round(p.inicio, 2), round(p.fim, 2)] for p in palavras]


def salvar_transcricao(drive, pasta_livro_id: str, numero: int, palavras: list[Palavra]) -> None:
    pasta = drive.pasta(pasta_livro_id, PASTA_TRANSCRICOES)
    drive.gravar_texto(pasta, f"{numero}.json", json.dumps(_como_json(palavras), ensure_ascii=False),
                       "application/json")


def _duracao(audio: Path) -> float:
    try:
        from video import duracao_audio
        return duracao_audio(audio)
    except Exception:
        return 0.0


def _pedaco(audio: Path, inicio: float, destino: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{inicio:.2f}", "-i", str(audio), "-t", str(PEDACO_SEG),
                    "-vn", "-ac", "1", "-ar", "16000", str(destino)], check=True)
    return destino


def transcrever_retomavel(drive, pasta: str, nome_parcial: str, audio: Path, modelo: str, rotulo: str,
                         prazo: float | None = None) -> list[Palavra]:
    """Transcreve o áudio todo. Áudio longo vai em pedaços de 20 min, e cada pedaço pronto fica salvo no Drive
    (`nome_parcial`, na `pasta`). Se a máquina for desligada ou o `prazo` (time.monotonic) passar, a próxima
    execução continua de onde parou. No fim o arquivo parcial é apagado."""
    duracao = _duracao(audio)
    parcial = drive.achar(pasta, nome_parcial)
    dados = json.loads(drive.ler_texto(parcial["id"])) if parcial else {"ate": 0, "palavras": []}
    palavras, ate = [Palavra(*p) for p in dados["palavras"]], float(dados["ate"])

    if ate == 0 and duracao <= PEDACO_SEG * 1.5:   # áudio curto: de uma vez só
        log.info("Transcrevendo %s...", rotulo)
        palavras = transcrever(audio, modelo)
    else:
        log.info("Transcrevendo %s em pedaços (%.0f de %.0f min já feitos)...", rotulo, ate / 60, duracao / 60)
        with tempfile.TemporaryDirectory() as tmp:
            while ate < duracao - 1:
                trecho = transcrever(_pedaco(audio, ate, Path(tmp) / "pedaco.wav"), modelo)
                palavras += [Palavra(p.texto, p.inicio + ate, p.fim + ate) for p in trecho]
                ate = min(duracao, ate + PEDACO_SEG)
                if ate < duracao - 1:
                    drive.gravar_texto(pasta, nome_parcial, json.dumps({"ate": ate, "palavras": _como_json(palavras)},
                                                                       ensure_ascii=False), "application/json")
                    if prazo and time.monotonic() > prazo:
                        raise TempoEsgotado(f"{rotulo}: {ate / 60:.0f} de {duracao / 60:.0f} min")
    parcial = drive.achar(pasta, nome_parcial)
    if parcial:
        drive.lixeira(parcial["id"])
    return palavras


def palavras_do_capitulo(drive, livro, capitulo, audio: Path, modelo: str, prazo: float | None = None) -> list[Palavra]:
    """Lê a transcrição do Drive ou transcreve agora (e guarda para a próxima vez), retomando se parou no meio."""
    pasta = drive.pasta(livro.pasta["id"], PASTA_TRANSCRICOES)
    nome = f"{capitulo.numero}.json"
    salvo = drive.achar(pasta, nome)
    if salvo:
        return [Palavra(*p) for p in json.loads(drive.ler_texto(salvo["id"]))]
    palavras = transcrever_retomavel(drive, pasta, f"{capitulo.numero}.parcial.json", audio, modelo,
                                     f"'{livro.nome}' – capítulo {capitulo.numero}", prazo)
    drive.gravar_texto(pasta, nome, json.dumps(_como_json(palavras), ensure_ascii=False), "application/json")
    return palavras


def _tempo_srt(seg: float) -> str:
    ms = int(round(seg * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def agrupar_linhas(palavras: list[Palavra], max_caracteres: int = 42, max_segundos: float = 5.0) -> list[list[Palavra]]:
    """Quebra a fala em blocos curtos de legenda, preferindo terminar no fim de frase."""
    blocos, atual = [], []
    for p in palavras:
        texto_atual = " ".join(w.texto.strip() for w in atual)
        estoura = atual and (len(texto_atual) + 1 + len(p.texto.strip()) > max_caracteres
                             or p.fim - atual[0].inicio > max_segundos)
        if estoura:
            blocos.append(atual)
            atual = []
        atual.append(p)
        if p.texto.strip().endswith(_FIM_DE_FRASE):
            blocos.append(atual)
            atual = []
    if atual:
        blocos.append(atual)
    return blocos


def gerar_srt(palavras: list[Palavra]) -> str:
    linhas = []
    for i, bloco in enumerate(agrupar_linhas(palavras), start=1):
        texto = " ".join(w.texto.strip() for w in bloco)
        linhas += [str(i), f"{_tempo_srt(bloco[0].inicio)} --> {_tempo_srt(bloco[-1].fim)}", texto, ""]
    return "\n".join(linhas)
