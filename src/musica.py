"""Música de fundo a partir de gravações longas (ex.: o áudio da banda): corta em trechos e escolhe um por vídeo.

Corte: primeiro nos silêncios (fim de uma música, começo de outra); depois, músicas longas viram trechos de
45 s a 150 s, cortados no ponto mais baixinho perto de 90 s (corte no meio de uma nota alta soa estranho).
Cada trecho ganha fade de entrada e saída e volume igualado. O "clima" (calma, alegre, epica) vem da energia
do trecho em relação aos outros da mesma gravação: o roteiro pede um clima e o robô escolhe um trecho dele.

Escolha: entre os trechos do clima pedido (ou de qualquer clima, se não houver), o menos usado até agora,
preferindo os que duram mais que o vídeo. Assim os vídeos seguidos não repetem a mesma parte.
"""

import subprocess
from pathlib import Path

import numpy as np

TAXA = 22050
JANELA = 0.5            # segundos por medida de volume
SILENCIO_DB = -38       # abaixo disto (em relação ao pico) é silêncio
SILENCIO_MIN = 1.5      # segundos de silêncio que separam duas músicas
MINIMO, ALVO, MAXIMO = 45.0, 90.0, 150.0
MENOR_TRECHO = 20.0


def _ler(audio: Path) -> np.ndarray:
    bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", str(audio), "-ac", "1", "-ar", str(TAXA), "-f", "f32le",
                            "-"], capture_output=True, check=True).stdout
    return np.frombuffer(bruto, dtype=np.float32)


def volumes(som: np.ndarray) -> np.ndarray:
    """Volume (dB em relação ao pico) de cada janela de meio segundo."""
    n = int(TAXA * JANELA)
    blocos = som[: len(som) // n * n].reshape(-1, n)
    rms = np.sqrt((blocos.astype(np.float64) ** 2).mean(axis=1)) + 1e-9
    return 20 * np.log10(rms / rms.max())


def _musicas(db: np.ndarray) -> list[tuple[int, int]]:
    """Trechos com som entre os silêncios (em janelas)."""
    som = db > SILENCIO_DB
    partes, ini, quietas = [], None, 0
    for i, tem in enumerate(som):
        if tem:
            if ini is None:
                ini = i
            quietas = 0
        elif ini is not None:
            quietas += 1
            if quietas * JANELA >= SILENCIO_MIN:
                partes.append((ini, i - quietas + 1))
                ini, quietas = None, 0
    if ini is not None:
        partes.append((ini, len(som) - quietas))
    return partes


def pontos_de_corte(db: np.ndarray) -> list[tuple[float, float]]:
    """(início, fim) em segundos de cada trecho."""
    saida = []
    for ini, fim in _musicas(db):
        while (fim - ini) * JANELA > MAXIMO:
            a, b = ini + int(MINIMO / JANELA), ini + int(MAXIMO / JANELA)
            # ponto mais baixo entre 45 s e 150 s, puxando para perto de 90 s
            janela = db[a:b] + np.abs(np.arange(a, b) - (ini + ALVO / JANELA)) * JANELA * 0.08
            corte = a + int(np.argmin(janela))
            if (fim - corte) * JANELA < MENOR_TRECHO:   # sobraria um pedacinho: deixa junto
                break
            saida.append((ini * JANELA, corte * JANELA))
            ini = corte
        if (fim - ini) * JANELA >= MENOR_TRECHO:
            saida.append((ini * JANELA, fim * JANELA))
    return saida


def cortar(audio: Path, pasta: Path, prefixo: str = "trecho") -> list[dict]:
    """Corta a gravação e devolve [{arquivo, inicio, duracao, energia, clima}]."""
    pasta.mkdir(parents=True, exist_ok=True)
    som = _ler(audio)
    db = volumes(som)
    trechos = []
    for n, (ini, fim) in enumerate(pontos_de_corte(db), start=1):
        dur = fim - ini
        arq = pasta / f"{prefixo}_{n:03d}.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", str(audio),
                        "-af", f"afade=t=in:d=1.5,afade=t=out:st={max(dur - 2.5, 0):.2f}:d=2.5,"
                        "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "44100", "-b:a", "192k", str(arq)], check=True)
        a, b = int(ini / JANELA), int(fim / JANELA)
        trechos.append({"arquivo": arq.name, "inicio": round(ini, 1), "duracao": round(dur, 1),
                        "energia": round(float(np.mean(db[a:b])), 2)})
    _climas(trechos)
    return trechos


def _climas(trechos: list[dict]) -> None:
    """Terço mais baixinho = calma, do meio = alegre, mais forte = epica."""
    if not trechos:
        return
    ordem = sorted(trechos, key=lambda t: t["energia"])
    for i, t in enumerate(ordem):
        t["clima"] = ("calma", "alegre", "epica")[min(2, i * 3 // len(ordem))]


def escolher(trechos: list[dict], clima: str, segundos: float, usos: dict) -> dict | None:
    if not trechos:
        return None
    candidatos = [t for t in trechos if t.get("clima") == clima] or trechos
    return min(candidatos, key=lambda t: (usos.get(t["arquivo"], 0), t["duracao"] < segundos, t["arquivo"]))
