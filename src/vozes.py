"""Vozes sintéticas: Google Cloud Text-to-Speech (usada na narração dos livros) e utilidades de áudio."""

import base64
import json
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

URL_GOOGLE = "https://texttospeech.googleapis.com/v1/"
LIMITE_BYTES_GOOGLE = 4500   # a API aceita até 5000 bytes por pedido


class ErroVoz(Exception):
    pass


def dividir_texto(texto: str, limite_bytes: int = LIMITE_BYTES_GOOGLE) -> list[str]:
    """Pedaços de até limite_bytes, cortando entre parágrafos (ou frases, se um parágrafo for enorme)."""
    unidades = []
    for paragrafo in [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]:
        if len(paragrafo.encode()) <= limite_bytes:
            unidades.append(paragrafo)
            continue
        for frase in [f.strip() for f in re.split(r"(?<=[.!?…])\s+", paragrafo) if f.strip()]:
            while len(frase.encode()) > limite_bytes:   # frase gigante: corta no último espaço que cabe
                corte = frase.encode()[:limite_bytes].decode("utf-8", "ignore").rfind(" ")
                unidades.append(frase[:corte])
                frase = frase[corte:].strip()
            unidades.append(frase)
    pedacos, atual = [], ""
    for u in unidades:
        candidato = f"{atual}\n\n{u}" if atual else u
        if len(candidato.encode()) > limite_bytes and atual:
            pedacos.append(atual)
            candidato = u
        atual = candidato
    if atual:
        pedacos.append(atual)
    return pedacos


def google(caminho: str, chave: str, corpo: dict | None = None, tentativas: int = 5) -> dict:
    url = URL_GOOGLE + caminho + ("&" if "?" in caminho else "?") + urllib.parse.urlencode({"key": chave})
    dados = json.dumps(corpo).encode() if corpo is not None else None
    for tentativa in range(1, tentativas + 1):
        pedido = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
        try:
            return json.load(urllib.request.urlopen(pedido, timeout=120))
        except urllib.error.HTTPError as erro:
            if erro.code in (429, 500, 502, 503, 504) and tentativa < tentativas:
                time.sleep(10 * tentativa)
                continue
            raise ErroVoz(f"Google Text-to-Speech recusou ({erro.code}): {erro.read().decode()[:500]}") from erro
        except (urllib.error.URLError, TimeoutError, ConnectionError) as erro:
            if tentativa == tentativas:
                raise ErroVoz(f"sem conexão com o Google Text-to-Speech: {erro}") from erro
            time.sleep(10 * tentativa)
    raise ErroVoz("Google Text-to-Speech não respondeu")


def juntar_mp3(partes: list[Path], destino: Path) -> Path:
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in partes), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
                    "-c:a", "libmp3lame", "-b:a", "128k", str(destino)], check=True)
    lista.unlink()
    return destino


def narrar_google(texto: str, voz: str, chave: str, destino: Path, idioma: str = "pt-BR") -> Path:
    """Narra um texto de qualquer tamanho com uma voz do Google e salva um MP3 só."""
    partes = []
    for i, pedaco in enumerate(dividir_texto(texto)):
        resp = google("text:synthesize", chave, {
            "input": {"text": pedaco},
            "voice": {"languageCode": idioma, "name": voz},
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 24000},
        })
        parte = destino.parent / f"_{destino.stem}_{i:03d}.mp3"
        parte.write_bytes(base64.b64decode(resp["audioContent"]))
        partes.append(parte)
    juntar_mp3(partes, destino)
    for p in partes:
        p.unlink()
    return destino
