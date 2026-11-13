"""Narra o mesmo texto com vozes sintéticas de vários motores, para comparar e escolher uma.

Motores:
  piper   grátis, roda no GitHub (vozes cadu, faber, jeff)
  kokoro  grátis, roda no GitHub, licença permite uso comercial (vozes Dora, Alex, Santa)
  google  Google Cloud Text-to-Speech (cota grátis mensal; precisa do segredo GOOGLE_TTS_API_KEY)
  xtts    Coqui XTTS-v2, muito natural, mas a licença NÃO permite uso comercial (só para ouvir)

Os MP3 vão para a pasta "Testes de voz" dentro de Audiolivros no Drive (o robô de publicação ignora essa pasta).
O texto vem do texto.txt dessa pasta (ou de --texto).

Uso:
  python scripts/testar_vozes.py --motor kokoro
  python scripts/testar_vozes.py --motor piper --sem-drive --texto capitulo.txt --voz modelo.onnx
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

PASTA_DRIVE = "Testes de voz"
# Usado quando não há texto.txt na pasta "Testes de voz" do Drive.
TEXTO_PADRAO = ("Capítulo um. A chuva tinha parado pouco antes do amanhecer, e a cidade ainda dormia quando ela "
                "abriu a janela. — Hoje vai ser diferente — disse, baixinho, como quem faz uma promessa. Lá embaixo, "
                "o padeiro empurrava a carroça pela rua de pedras, assobiando uma música antiga. Será que alguém "
                "lembraria daquele dia? Talvez não. Mas ela lembraria, e isso bastava.")
URL_PIPER = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
URL_GOOGLE = "https://texttospeech.googleapis.com/v1/"
VOZES_KOKORO = ["pf_dora", "pm_alex", "pm_santa"]
# XTTS em CPU é lento: só o começo do capítulo (cerca de 6 minutos de fala)
MAX_CARACTERES_XTTS = 5000
VOZES_XTTS = ["Ana Florence", "Damien Black"]   # uma feminina e uma masculina, se existirem no modelo
# Google: as melhores famílias de voz, da mais natural para a mais simples
FAMILIAS_GOOGLE = ["Chirp3-HD", "Neural2", "Wavenet"]
LIMITE_BYTES_GOOGLE = 4500   # a API aceita até 5000 bytes por pedido


# ---------------------------------------------------------------- utilidades

def para_mp3(wav: Path, mp3: Path) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "128k", str(mp3)],
                   check=True)
    wav.unlink(missing_ok=True)
    return mp3


def juntar_mp3(partes: list[Path], destino: Path) -> Path:
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(f"file '{p.resolve()}'\n" for p in partes), encoding="utf-8")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
                    "-c:a", "libmp3lame", "-b:a", "128k", str(destino)], check=True)
    lista.unlink()
    return destino


def dividir_texto(texto: str, limite_bytes: int) -> list[str]:
    """Pedaços de até limite_bytes, cortando entre parágrafos (ou frases, se um parágrafo for enorme)."""
    unidades = []
    for paragrafo in [p.strip() for p in re.split(r"\n\s*\n", texto) if p.strip()]:
        if len(paragrafo.encode()) <= limite_bytes:
            unidades.append(paragrafo)
        else:
            unidades += [f.strip() for f in re.split(r"(?<=[.!?…])\s+", paragrafo) if f.strip()]
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


def baixar(url: str, destino: Path) -> Path:
    if not destino.exists():
        destino.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, destino)
    return destino


# ---------------------------------------------------------------- Piper

def vozes_do_idioma(catalogo: dict, idioma: str = "pt_BR", com_baixa_qualidade: bool = True) -> list[tuple[str, str, str]]:
    """(nome, caminho do .onnx, caminho do .onnx.json) de cada voz do idioma, das melhores para as piores."""
    ordem = {"high": 0, "medium": 1, "low": 2, "x_low": 3}
    saida = []
    for nome, voz in catalogo.items():
        if voz.get("language", {}).get("code") != idioma:
            continue
        if not com_baixa_qualidade and voz.get("quality") in ("low", "x_low"):
            continue
        arquivos = list(voz.get("files", {}))
        onnx = next((f for f in arquivos if f.endswith(".onnx")), None)
        if onnx and onnx + ".json" in arquivos:
            saida.append((nome, onnx, onnx + ".json", ordem.get(voz.get("quality"), 9)))
    return [(n, o, j) for n, o, j, _ in sorted(saida, key=lambda v: (v[3], v[0]))]


def motor_piper(texto: str, saida: Path, args) -> list[Path]:
    modelos = list(args.voz or [])
    if not modelos:
        catalogo = json.load(urllib.request.urlopen(URL_PIPER + "voices.json"))
        vozes = vozes_do_idioma(catalogo, com_baixa_qualidade=False)
        print(f"Piper: {', '.join(v[0] for v in vozes)}")
        for _, onnx, cfg in vozes:
            baixar(URL_PIPER + cfg, saida / "_modelos" / Path(cfg).name)
            modelos.append(baixar(URL_PIPER + onnx, saida / "_modelos" / Path(onnx).name))
    feitos = []
    for modelo in modelos:
        nome = modelo.name.removesuffix(".onnx")
        for ritmo, velocidade, pausa in (("normal", 1.0, 0.4), ("calma", 1.15, 0.8)):
            print(f"Piper {nome} ({ritmo})...")
            wav = saida / f"{nome}-{ritmo}.wav"
            subprocess.run([sys.executable, "-m", "piper", "-m", str(modelo), "-f", str(wav),
                            "--length-scale", str(velocidade), "--sentence-silence", str(pausa)],
                           input=texto, text=True, check=True)
            feitos.append(para_mp3(wav, saida / f"voz - piper - {nome} - {ritmo}.mp3"))
    return feitos


# ---------------------------------------------------------------- Kokoro

def motor_kokoro(texto: str, saida: Path, args) -> list[Path]:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    pipeline = KPipeline(lang_code="p")   # p = português do Brasil
    feitos = []
    for voz in VOZES_KOKORO:
        for ritmo, velocidade in (("normal", 1.0), ("calma", 0.9)):
            print(f"Kokoro {voz} ({ritmo})...")
            pausa = np.zeros(int(24000 * 0.35), dtype=np.float32)
            trechos = []
            for _, _, audio in pipeline(texto, voice=voz, speed=velocidade, split_pattern=r"\n+"):
                if audio is not None:
                    trechos += [np.asarray(audio, dtype=np.float32), pausa]
            wav = saida / f"{voz}-{ritmo}.wav"
            sf.write(wav, np.concatenate(trechos), 24000)
            feitos.append(para_mp3(wav, saida / f"voz - kokoro - {voz} - {ritmo}.mp3"))
    return feitos


# ---------------------------------------------------------------- Google Cloud

def _google(caminho: str, chave: str, corpo: dict | None = None) -> dict:
    url = URL_GOOGLE + caminho + ("&" if "?" in caminho else "?") + urllib.parse.urlencode({"key": chave})
    dados = json.dumps(corpo).encode() if corpo is not None else None
    pedido = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(pedido, timeout=120))
    except urllib.error.HTTPError as erro:
        raise SystemExit(f"Google Text-to-Speech recusou ({erro.code}): {erro.read().decode()[:500]}") from erro


def escolher_vozes_google(vozes: list[dict]) -> list[str]:
    """Uma voz feminina e uma masculina de cada família (Chirp3-HD, Neural2, Wavenet)."""
    escolhidas = []
    for familia in FAMILIAS_GOOGLE:
        for genero in ("FEMALE", "MALE"):
            nomes = sorted(v["name"] for v in vozes if f"-{familia}-" in v["name"]
                           and v.get("ssmlGender") == genero and "pt-BR" in v.get("languageCodes", []))
            if nomes:
                escolhidas.append(nomes[0])
    return escolhidas


def motor_google(texto: str, saida: Path, args) -> list[Path]:
    chave = os.environ.get("GOOGLE_TTS_API_KEY")
    if not chave:
        print("Google: falta o segredo GOOGLE_TTS_API_KEY no GitHub. Pulando (veja o README, 'Voz sintética').")
        return []
    vozes = escolher_vozes_google(_google("voices?languageCode=pt-BR", chave).get("voices", []))
    pedacos = dividir_texto(texto, LIMITE_BYTES_GOOGLE)
    print(f"Google: {', '.join(vozes)} — {len(texto) * len(vozes):,} caracteres no total (desconta da cota grátis)")
    feitos = []
    for voz in vozes:
        print(f"Google {voz}...")
        partes = []
        for i, pedaco in enumerate(pedacos):
            resp = _google("text:synthesize", chave, {
                "input": {"text": pedaco},
                "voice": {"languageCode": "pt-BR", "name": voz},
                "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 24000},
            })
            parte = saida / f"_{voz}_{i:03d}.mp3"
            parte.write_bytes(base64.b64decode(resp["audioContent"]))
            partes.append(parte)
        feitos.append(juntar_mp3(partes, saida / f"voz - google - {voz}.mp3"))
        for p in partes:
            p.unlink()
    return feitos


# ---------------------------------------------------------------- XTTS

def motor_xtts(texto: str, saida: Path, args) -> list[Path]:
    os.environ.setdefault("COQUI_TOS_AGREED", "1")   # licença não comercial da Coqui (CPML)
    from TTS.api import TTS

    trecho = texto[:MAX_CARACTERES_XTTS]
    if len(texto) > MAX_CARACTERES_XTTS:
        trecho = trecho[: max(trecho.rfind("\n\n"), trecho.rfind(". ") + 1)]
    print(f"XTTS: só os primeiros {len(trecho)} caracteres (em CPU é lento).")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2")
    disponiveis = list(getattr(tts, "speakers", None) or [])
    vozes = [v for v in VOZES_XTTS if v in disponiveis] or disponiveis[:2]
    feitos = []
    for voz in vozes:
        print(f"XTTS {voz}...")
        wav = saida / f"xtts-{voz}.wav"
        tts.tts_to_file(text=trecho, language="pt", speaker=voz, file_path=str(wav), split_sentences=True)
        feitos.append(para_mp3(wav, saida / f"voz - xtts - {voz} (trecho, uso não comercial).mp3"))
    return feitos


MOTORES = {"piper": motor_piper, "kokoro": motor_kokoro, "google": motor_google, "xtts": motor_xtts}


# ---------------------------------------------------------------- principal

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--motor", choices=list(MOTORES), default="piper")
    parser.add_argument("--texto", type=Path, help="padrão: texto.txt da pasta Testes de voz no Drive")
    parser.add_argument("--saida", type=Path, default=Path("testes_de_voz"))
    parser.add_argument("--voz", type=Path, action="append", help="Piper: usar este .onnx em vez de baixar")
    parser.add_argument("--sem-drive", action="store_true", help="só salvar no disco")
    args = parser.parse_args()
    from comum import configurar_log
    configurar_log()   # no GitHub Actions: modo discreto (nada do canal no log)

    drive = pasta_drive = None
    if not args.sem_drive:
        from google_api import Drive, credenciais_do_ambiente
        drive = Drive(credenciais_do_ambiente())
        pasta_drive = drive.pasta(os.environ["DRIVE_PASTA_RAIZ"], PASTA_DRIVE)
    if args.texto:
        texto = args.texto.read_text(encoding="utf-8")
    elif drive and drive.achar(pasta_drive, "texto.txt"):
        texto = drive.ler_texto(drive.achar(pasta_drive, "texto.txt")["id"])
        print("Usando o texto.txt da pasta Testes de voz.")
    elif (RAIZ / "exemplos" / "teste_voz.txt").exists():
        texto = (RAIZ / "exemplos" / "teste_voz.txt").read_text(encoding="utf-8")
    else:
        texto = TEXTO_PADRAO
    print(f"Texto com {len(texto)} caracteres.")

    args.saida.mkdir(parents=True, exist_ok=True)
    feitos = MOTORES[args.motor](texto, args.saida, args)

    if drive and feitos:
        for mp3 in feitos:
            existente = drive.achar(pasta_drive, mp3.name)
            if existente:
                drive.lixeira(existente["id"])
            drive.enviar(mp3, pasta_drive, mime="audio/mpeg")
        print(f"{len(feitos)} arquivo(s) enviados para Audiolivros › {PASTA_DRIVE} no Drive.")
    print("Pronto:", ", ".join(m.name for m in feitos) or "nada")
    return 0


if __name__ == "__main__":
    sys.exit(main())
