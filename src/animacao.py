"""Vídeos animados por código a partir de um roteiro (YAML): personagens, cenários, falas com voz, legenda grande e
música de fundo. Serve para Shorts (vertical, 1080x1920) e vídeos longos (horizontal, 1920x1080).

Roteiro (exemplo):
  formato: short            # short | longo
  titulo: "FICA 20 MINUTOS A MAIS TODO DIA? ISSO É HORA EXTRA"
  gancho: "20 MINUTOS A MAIS?"          # texto grande no começo
  musica: alegre                        # alegre | calma | epica (ou nome de um arquivo da pasta Músicas)
  elenco: {davi: {tipo: pessoa, rotulo: Davi, roupa: [90,130,190], funda: true}}   # além do elenco pronto
  cenas:
    - cenario: escritorio
      personagens: [tomatinho, seu_repolho]
      destaque: "CLT, art. 58"          # opcional: cartão de texto que entra no começo da cena
      falas:
        - [narrador, "O Tomatinho bate o ponto às seis..."]
        - [seu_repolho, "Termina esse relatório antes de sair!"]
"""

import base64
import math
import os
import random
import re
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

import arte_biblia
import personagens as P

FPS = 24
VOZ_NARRADOR = "pt-BR-Chirp3-HD-Charon"
PAUSA = 0.3


@dataclass
class Fala:
    quem: str
    texto: str
    inicio: float = 0.0
    duracao: float = 0.0
    audio: Path | None = None
    gancho: bool = False      # a fala do gancho: o texto já aparece grande na tela, sem legenda
    emocao: str = ""          # o texto com as marcas de emoção ([triste], [sussurrando]...) para o ElevenLabs


@dataclass
class Cena:
    cenario: str
    personagens: list[str]
    falas: list[Fala]
    destaque: str = ""
    inicio: float = 0.0
    fim: float = 0.0


@dataclass
class Roteiro:
    formato: str
    titulo: str
    cenas: list[Cena]
    gancho: str = ""
    musica: str = "calma"
    elenco: dict = field(default_factory=dict)
    narrador: str = VOZ_NARRADOR

    @property
    def tamanho(self) -> tuple[int, int]:
        return (1080, 1920) if self.formato == "short" else (1920, 1080)


# Marcas de emoção no texto da fala, entre colchetes: valem no ElevenLabs (modelo v3) e somem da legenda e do Google.
EMOCOES = {"triste": "sad", "sussurrando": "whispers", "sussurro": "whispers", "animado": "excited",
           "empolgado": "excited", "suspiro": "sighs", "suspirando": "sighs", "chorando": "crying",
           "choro": "crying", "rindo": "laughs", "risada": "laughs", "gritando": "shouts", "grito": "shouts",
           "bravo": "angry", "com raiva": "angry", "medo": "scared", "com medo": "scared", "pausa": "pause",
           "emocionado": "emotional", "calmo": "calm", "sério": "serious", "surpreso": "surprised",
           "esperançoso": "hopeful", "firme": "determined", "voz embargada": "voice breaking"}


def _emocao(texto: str) -> tuple[str, str]:
    """("texto limpo", "texto com as marcas em inglês") — o ElevenLabs entende as marcas em inglês."""
    def trocar(m):
        chave = m.group(1).strip().lower()
        return f"[{EMOCOES.get(chave, chave)}]"
    marcado = re.sub(r"\[([^\]]+)\]", trocar, texto)
    limpo = " ".join(re.sub(r"\[[^\]]*\]", " ", texto).split())
    return limpo, marcado


def ler_roteiro(dados: dict) -> Roteiro:
    elenco = dict(P.ELENCO)
    for nome, spec in (dados.get("elenco") or {}).items():
        spec = dict(spec)
        tipo = spec.pop("tipo", "pessoa")
        rotulo = spec.pop("rotulo", nome.title())
        voz = spec.pop("voz", VOZ_NARRADOR)
        spec = {k: tuple(v) if isinstance(v, list) else v for k, v in spec.items()}
        if tipo == "pessoa":
            elenco[nome] = P.pessoa(nome, rotulo, voz, **spec)
        else:
            base = P.ELENCO.get(tipo) or P.Personagem(nome, rotulo, tipo)
            elenco[nome] = P.Personagem(nome, rotulo, base.tipo, voz or base.voz, spec.pop("cor", base.cor),
                                        {**base.extras, **spec})
    cenas = []
    for c in dados.get("cenas") or []:
        falas = []
        for f in c.get("falas") or []:
            quem, texto = (str(f[0]), str(f[1])) if isinstance(f, (list, tuple)) else (f.get("quem", "narrador"),
                                                                                       str(f["texto"]))
            limpo, marcado = _emocao(texto)
            falas.append(Fala(quem, limpo, emocao=marcado))
        cenas.append(Cena(c.get("cenario", "neutro"), list(c.get("personagens") or []), falas, c.get("destaque", "")))
    # O vídeo sempre começa com alguém falando: o narrador lê o gancho (ou "gancho_fala", se vier) no quadro 0.
    gancho = str(dados.get("gancho") or "")
    if gancho and cenas and dados.get("gancho_falado", True):
        quem = str(dados.get("gancho_quem") or "narrador")
        limpo, marcado = _emocao(str(dados.get("gancho_fala") or gancho))
        cenas[0].falas.insert(0, Fala(quem, limpo, gancho=True, emocao=marcado))
    return Roteiro(dados.get("formato", "short"), dados.get("titulo", ""), cenas, dados.get("gancho", ""),
                   dados.get("musica", "calma"), elenco, dados.get("narrador", VOZ_NARRADOR))


# ---------------------------------------------------------------- voz

def _voz_de(rot: Roteiro, quem: str) -> str:
    return rot.narrador if quem == "narrador" or quem not in rot.elenco else rot.elenco[quem].voz


def sintetizar(texto: str, voz: str, destino: Path, chave: str | None) -> Path:
    """MP3 da fala. Sem chave do Google (testes), gera silêncio do tamanho aproximado da fala.
    Voz "eleven:<id>" usa o ElevenLabs (chave no segredo ELEVENLABS_API_KEY)."""
    if voz.startswith("eleven:"):
        import elevenlabs
        if elevenlabs.chave():
            return elevenlabs.sintetizar(texto, voz.split(":", 1)[1], destino, elevenlabs.chave())
        chave = None
    if chave:
        from vozes import google
        resp = google("text:synthesize", chave, {
            "input": {"text": texto}, "voice": {"languageCode": "pt-BR", "name": voz},
            "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 24000}})
        destino.write_bytes(base64.b64decode(resp["audioContent"]))
    else:
        segundos = max(0.8, len(texto) * 0.065)
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{segundos:.2f}", "-i",
                        "anullsrc=r=24000:cl=mono", "-c:a", "libmp3lame", str(destino)], check=True)
    return destino


def _duracao(audio: Path) -> float:
    saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                            str(audio)], capture_output=True, text=True, check=True).stdout
    return float(saida.strip())


def preparar_vozes(rot: Roteiro, pasta: Path, chave: str | None) -> float:
    """Gera o áudio de cada fala e marca o tempo de cada fala e cena. Devolve a duração total."""
    t = 0.15   # a voz entra logo no começo: vídeo mudo no primeiro segundo faz a pessoa passar direto
    n = 0
    for cena in rot.cenas:
        cena.inicio = t
        for fala in cena.falas:
            n += 1
            voz = _voz_de(rot, fala.quem)
            texto = (fala.emocao or fala.texto) if voz.startswith("eleven:") else fala.texto
            fala.audio = sintetizar(texto, voz, pasta / f"fala_{n:03d}.mp3", chave)
            fala.duracao = _duracao(fala.audio)
            fala.inicio = t
            t += fala.duracao + PAUSA
        cena.fim = t
        t += 0.2
    return t + 1.0


# ---------------------------------------------------------------- música de fundo (feita por código)

def musica_gerada(estilo: str, segundos: float, destino: Path, semente: int = 7) -> Path:
    """Trilha sem direitos autorais, sintetizada aqui: acordes suaves (calma), dedilhado com batida leve (alegre)
    ou tambores e acordes graves (epica)."""
    import numpy as np
    sr = 22050
    n = int(segundos * sr)
    t = np.arange(n) / sr
    rng = random.Random(semente)
    progressoes = {"calma": [(60, 64, 67), (57, 60, 64), (65, 69, 72), (67, 71, 74)],
                   "alegre": [(60, 64, 67), (67, 71, 74), (69, 72, 76), (65, 69, 72)],
                   "epica": [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]}
    prog = progressoes.get(estilo, progressoes["calma"])
    hz = lambda m: 440 * 2 ** ((m - 69) / 12)
    som = np.zeros(n)
    compasso = {"calma": 4.0, "alegre": 2.0, "epica": 3.0}.get(estilo, 4.0)
    for k in range(int(segundos / compasso) + 1):
        acorde = prog[k % len(prog)]
        i0, i1 = int(k * compasso * sr), min(n, int((k + 1) * compasso * sr) + sr)
        if i0 >= n:
            break
        tt = t[i0:i1] - t[i0]
        env = np.minimum(1, tt / 0.8) * np.exp(-tt / (compasso * 1.2))
        for m in acorde:   # pad
            som[i0:i1] += 0.12 * env * (np.sin(2 * np.pi * hz(m - 12) * tt) + 0.3 * np.sin(2 * np.pi * hz(m) * tt))
        if estilo == "alegre":   # dedilhado (pluck) em colcheias
            passo = compasso / 8
            for j in range(8):
                a0 = i0 + int(j * passo * sr)
                if a0 >= n:
                    break
                nota = acorde[j % 3] + (12 if j % 4 == 3 else 0)
                dur = min(n - a0, int(0.6 * sr))
                ta = np.arange(dur) / sr
                som[a0:a0 + dur] += 0.18 * np.exp(-ta * 6) * np.sign(np.sin(2 * np.pi * hz(nota) * ta)) * 0.5
            for j in (0, 4):   # batida leve
                a0 = i0 + int(j * passo * sr)
                dur = min(n - a0, int(0.15 * sr))
                if dur > 0:
                    ta = np.arange(dur) / sr
                    som[a0:a0 + dur] += 0.35 * np.exp(-ta * 30) * np.sin(2 * np.pi * 60 * ta)
        if estilo == "epica":
            for j in range(3):
                a0 = i0 + int(j * compasso / 3 * sr)
                dur = min(n - a0, int(0.4 * sr))
                if dur > 0:
                    ta = np.arange(dur) / sr
                    som[a0:a0 + dur] += 0.5 * np.exp(-ta * 9) * np.sin(2 * np.pi * (55 - 20 * ta) * ta)
    fade = np.minimum(1, np.minimum(t / 1.5, (segundos - t) / 2.5))
    som = som * np.clip(fade, 0, 1)
    som = som / (np.abs(som).max() or 1) * 0.6
    with wave.open(str(destino), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((som * 32767).astype("<i2").tobytes())
    return destino


# ---------------------------------------------------------------- cenários

PALETAS = {
    "escritorio": ((236, 228, 210), (205, 190, 165)), "fabrica": ((210, 214, 220), (150, 155, 165)),
    "rua": ((170, 215, 245), (140, 140, 145)), "tribunal": ((240, 232, 215), (170, 120, 80)),
    "casa": ((250, 235, 205), (190, 140, 100)), "deserto": ((250, 215, 150), (225, 180, 110)),
    "campo": ((170, 215, 245), (120, 180, 90)), "mar": ((160, 210, 240), (60, 120, 180)),
    "noite": ((25, 30, 70), (60, 55, 80)), "templo": ((245, 230, 200), (205, 175, 130)),
    "cidade_antiga": ((245, 215, 170), (200, 165, 120)), "neutro": ((240, 232, 214), (215, 200, 175)),
}


def cenario(nome: str, w: int, h: int) -> Image.Image:
    """Fundo da cena desenhado por código (2x e reduzido)."""
    s = 2
    W, H = w * s, h * s
    ceu, chao = PALETAS.get(nome, PALETAS["neutro"])
    img = Image.new("RGB", (W, H), ceu)
    d = ImageDraw.Draw(img)
    for y in range(0, int(H * 0.72), 4):   # degradê do céu/parede
        f = y / (H * 0.72)
        d.rectangle((0, y, W, y + 4), fill=tuple(int(c * (1 - 0.12 * f)) for c in ceu))
    linha = int(H * 0.72)
    d.rectangle((0, linha, W, H), fill=chao)
    rng = random.Random(nome)
    if nome in ("campo", "rua", "mar", "deserto", "cidade_antiga"):
        d.ellipse((W * 0.75, H * 0.08, W * 0.75 + 180 * s, H * 0.08 + 180 * s), fill=(255, 225, 120))
        for _ in range(3):
            x, y = rng.uniform(0, W), rng.uniform(H * 0.05, H * 0.3)
            for k in range(4):
                d.ellipse((x + k * 60 * s, y - (k % 2) * 30 * s, x + k * 60 * s + 140 * s, y + 80 * s),
                          fill=(255, 255, 255))
    if nome == "noite":
        for _ in range(120):
            x, y = rng.uniform(0, W), rng.uniform(0, linha)
            r = rng.uniform(1.5, 4) * s
            d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 250, 220))
        d.ellipse((W * 0.7, H * 0.1, W * 0.7 + 160 * s, H * 0.1 + 160 * s), fill=(250, 245, 220))
    if nome == "deserto":
        for k in range(3):
            d.ellipse((-W * 0.3 + k * W * 0.5, linha - 120 * s, W * 0.5 + k * W * 0.5, linha + 200 * s),
                      fill=tuple(int(c * (0.95 - 0.04 * k)) for c in chao))
    if nome == "campo":
        for k in range(3):
            d.ellipse((-W * 0.4 + k * W * 0.6, linha - 160 * s, W * 0.6 + k * W * 0.6, linha + 300 * s),
                      fill=(100 + 15 * k, 170, 80))
    if nome == "mar":
        for k in range(6):
            y = linha + k * 70 * s
            for x in range(0, W, 120 * s):
                d.arc((x, y, x + 120 * s, y + 50 * s), 200, 340, fill=(220, 240, 255), width=4 * s)
    if nome in ("escritorio", "casa"):
        jx, jy = W * 0.62, H * 0.12
        d.rectangle((jx, jy, jx + W * 0.28, jy + H * 0.22), fill=(180, 220, 245), outline=(120, 90, 60), width=10 * s)
        d.line((jx + W * 0.14, jy, jx + W * 0.14, jy + H * 0.22), fill=(120, 90, 60), width=8 * s)
        d.rectangle((0, linha - 8 * s, W, linha), fill=(150, 110, 80))
        if nome == "escritorio":
            d.rectangle((W * 0.08, H * 0.15, W * 0.08 + 120 * s, H * 0.15 + 150 * s), fill=(250, 250, 250),
                        outline=(90, 90, 90), width=4 * s)
            for k in range(5):
                d.line((W * 0.08 + 15 * s, H * 0.15 + (25 + 25 * k) * s, W * 0.08 + 105 * s,
                        H * 0.15 + (25 + 25 * k) * s), fill=(160, 160, 160), width=3 * s)
            d.ellipse((W * 0.4, H * 0.08, W * 0.4 + 110 * s, H * 0.08 + 110 * s), fill=(255, 255, 255),
                      outline=(60, 60, 60), width=6 * s)   # relógio
            cxr, cyr = W * 0.4 + 55 * s, H * 0.08 + 55 * s
            d.line((cxr, cyr, cxr, cyr - 38 * s), fill=(40, 40, 40), width=5 * s)
            d.line((cxr, cyr, cxr + 28 * s, cyr + 10 * s), fill=(40, 40, 40), width=5 * s)
    if nome == "fabrica":
        for k in range(4):
            x = W * (0.05 + 0.25 * k)
            d.rectangle((x, H * 0.25, x + W * 0.18, linha), fill=(120, 125, 135), outline=(80, 80, 90), width=6 * s)
            d.rectangle((x + W * 0.03, H * 0.32, x + W * 0.15, H * 0.42), fill=(200, 220, 235))
    if nome in ("tribunal", "templo"):
        for k in range(5):
            x = W * (0.08 + 0.2 * k)
            d.rectangle((x, H * 0.18, x + 60 * s, linha), fill=(250, 245, 235), outline=(180, 170, 150), width=4 * s)
        d.polygon([(W * 0.03, H * 0.18), (W * 0.97, H * 0.18), (W * 0.5, H * 0.05)], fill=(235, 225, 205),
                  outline=(180, 170, 150))
    if nome == "cidade_antiga":
        for k in range(5):
            x = W * (0.02 + 0.2 * k)
            alt = rng.uniform(0.18, 0.3) * H
            d.rectangle((x, linha - alt, x + W * 0.16, linha), fill=(225, 190, 140), outline=(170, 130, 90), width=4 * s)
            d.rectangle((x + W * 0.06, linha - alt * 0.45, x + W * 0.1, linha), fill=(120, 80, 50))
    if nome == "rua":
        d.rectangle((0, linha + 60 * s, W, linha + 100 * s), fill=(200, 200, 200))
        for k in range(4):
            x = W * (0.02 + 0.26 * k)
            alt = rng.uniform(0.25, 0.4) * H
            d.rectangle((x, linha - alt, x + W * 0.2, linha), fill=rng.choice([(235, 200, 160), (200, 220, 230),
                                                                              (240, 225, 200)]),
                        outline=(120, 110, 100), width=4 * s)
    return img.resize((w, h), Image.LANCZOS).filter(ImageFilter.GaussianBlur(1.2))


# ---------------------------------------------------------------- texto na tela

def _quebrar(d, texto, fonte, largura):
    linhas, atual = [], ""
    for p in texto.split():
        teste = f"{atual} {p}".strip()
        if d.textlength(teste, font=fonte) <= largura or not atual:
            atual = teste
        else:
            linhas.append(atual)
            atual = p
    return linhas + ([atual] if atual else [])


def _texto_contorno(d, xy, texto, fonte, cor, contorno=(30, 20, 15), largura=6, anchor="mm"):
    d.text(xy, texto, font=fonte, fill=cor, anchor=anchor, stroke_width=largura, stroke_fill=contorno)


def legenda_atual(fala: Fala, t: float, por_tela: int = 4) -> tuple[str, int]:
    """Pedaço da fala que está sendo dito agora (e índice da palavra em destaque), pelo tempo proporcional."""
    palavras = fala.texto.split()
    if not palavras:
        return "", 0
    pesos = [len(p) + 2 for p in palavras]
    total = sum(pesos)
    progresso = min(0.999, max(0.0, (t - fala.inicio) / max(fala.duracao, 0.1)))
    alvo, acc, idx = progresso * total, 0, 0
    for i, pw in enumerate(pesos):
        acc += pw
        if acc >= alvo:
            idx = i
            break
    ini = (idx // por_tela) * por_tela
    return " ".join(palavras[ini:ini + por_tela]), idx - ini


# ---------------------------------------------------------------- render

def _posicoes(n: int, w: int, h: int, short: bool) -> list[float]:
    if n <= 0:
        return []
    if short:
        return [w * (0.5 if n == 1 else 0.28 + 0.44 * i / (n - 1)) for i in range(n)]
    return [w * (0.5 if n == 1 else 0.25 + 0.5 * i / (n - 1)) for i in range(n)]


def mixar_audio(rot: Roteiro, tmp: Path, total: float, musica: Path | None = None) -> Path:
    """Falas no tempo certo + música baixinha, que abaixa sozinha quando alguém fala. Devolve um .m4a."""
    voz = tmp / "voz.wav"
    filtros, entradas = [], []
    falas = [f for c in rot.cenas for f in c.falas]
    for i, f in enumerate(falas):
        entradas += ["-i", str(f.audio)]
        filtros.append(f"[{i}:a]adelay={int(f.inicio * 1000)}|{int(f.inicio * 1000)},aresample=44100[a{i}]")
    mix = "".join(f"[a{i}]" for i in range(len(falas)))
    subprocess.run(["ffmpeg", "-y", "-v", "error", *entradas, "-filter_complex",
                    ";".join(filtros) + f";{mix}amix=inputs={len(falas)}:normalize=0,apad=whole_dur={total:.2f}"
                    f",atrim=0:{total:.2f}[v]", "-map", "[v]", "-ac", "1", str(voz)], check=True)
    trilha = musica or musica_gerada(rot.musica, total, tmp / "musica.wav")
    volume = 0.16 if musica else 0.22   # gravação de verdade (com voz cantada) fica um pouco mais baixa
    audio = tmp / "audio.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(voz), "-stream_loop", "-1", "-i", str(trilha),
                    "-filter_complex",
                    f"[1:a]volume={volume},atrim=0:{total:.2f},afade=t=out:st={max(total - 2.5, 0):.2f}:d=2.5[m];"
                    "[m][0:a]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=400[md];"
                    "[0:a][md]amix=inputs=2:normalize=0[o]",
                    "-map", "[o]", "-t", f"{total:.2f}", "-c:a", "aac", "-b:a", "160k", str(audio)], check=True)

    return audio


def renderizar(rot: Roteiro, destino: Path, chave_tts: str | None = None, musica: Path | None = None,
               cor_destaque=(242, 184, 75)) -> Path:
    w, h = rot.tamanho
    short = rot.formato == "short"
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        total = preparar_vozes(rot, tmp, chave_tts)
        alt_personagem = int(h * (0.30 if short else 0.42))
        # "tamanho" no elenco: Golias 1.6, criança 0.7 (o resto é 1)
        sprites = {n: P.poses(p, int(alt_personagem * float(p.extras.get("tamanho", 1))))
                   for n, p in rot.elenco.items() if any(n in c.personagens for c in rot.cenas)}
        fundos = {c.cenario: cenario(c.cenario, w, h) for c in rot.cenas}
        f_legenda = arte_biblia.lora(int(w * (0.085 if short else 0.05)))
        f_destaque = arte_biblia.titulo_fonte(int(w * (0.1 if short else 0.065)))
        f_nome = arte_biblia.lora(int(w * (0.035 if short else 0.022)))
        chao = int(h * 0.84) if short else int(h * 0.88)

        audio = mixar_audio(rot, tmp, total, musica)

        enc = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}",
                                "-r", str(FPS), "-i", "-", "-i", str(audio), "-map", "0:v", "-map", "1:a",
                                "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
                                "-c:a", "copy", "-shortest", "-movflags", "+faststart", str(destino)],
                               stdin=subprocess.PIPE)
        quadros = int(total * FPS)
        for q in range(quadros):
            t = q / FPS
            cena = next((c for c in rot.cenas if c.inicio - 0.2 <= t < c.fim + 0.2), rot.cenas[-1] if t > 1 else
                        rot.cenas[0])
            tela = fundos[cena.cenario].copy()
            d = ImageDraw.Draw(tela)
            fala = next((f for f in cena.falas if f.inicio <= t < f.inicio + f.duracao), None)
            fim_gancho = next((f.inicio + f.duracao for f in cena.falas if f.gancho), 0.0)
            xs = _posicoes(len(cena.personagens), w, h, short)
            for i, (nome, x) in enumerate(zip(cena.personagens, xs)):
                if nome not in sprites:
                    continue
                falando = bool(fala and fala.quem == nome)
                boca = falando and int(t * 9) % 2 == 0
                olhos = (t + i * 1.3) % 3.7 > 0.15
                img = sprites[nome][(boca, olhos)]
                entrada = min(1.0, (t - cena.inicio + 0.2) / 0.5)
                pulo = abs(math.sin(t * 7)) * (14 if falando else 0) + math.sin(t * 2 + i) * 4
                deslocx = (1 - entrada) * (-w * 0.4 if x < w / 2 else w * 0.4)
                if img.width > w * 0.48:
                    img = img.resize((int(w * 0.48), int(img.height * w * 0.48 / img.width)))
                px = int(x - img.width / 2 + deslocx)
                py = int(chao - img.height - pulo)
                sombra = Image.new("RGBA", (img.width, 40), (0, 0, 0, 0))
                ImageDraw.Draw(sombra).ellipse((img.width * 0.15, 5, img.width * 0.85, 35), fill=(0, 0, 0, 60))
                tela.paste(sombra, (px, chao - 20), sombra)
                tela.paste(img, (px, py), img)
                if falando:
                    _texto_contorno(d, (px + img.width / 2, py - 35), rot.elenco[nome].rotulo, f_nome, (255, 255, 255),
                                    largura=4)
            # gancho no começo (texto grande)
            if rot.gancho and t < max(fim_gancho, 1.5) + 0.2:
                escala = min(1.0, t / 0.25)
                f = arte_biblia.titulo_fonte(max(10, int(f_destaque.size * (0.6 + 0.4 * escala))))
                for k, linha in enumerate(_quebrar(d, rot.gancho.upper(), f, w * 0.88)):
                    _texto_contorno(d, (w / 2, h * (0.18 if short else 0.2) + k * f.size * 1.1), linha, f,
                                    cor_destaque, largura=8)
            # cartão de destaque da cena
            if cena.destaque and cena.inicio <= t < cena.inicio + 3.5 and not (rot.gancho and t < max(fim_gancho, 1.5) + 0.2):
                pop = min(1.0, (t - cena.inicio) / 0.2)
                f = arte_biblia.titulo_fonte(max(10, int(f_destaque.size * 0.8 * (0.7 + 0.3 * pop))))
                linhas = _quebrar(d, cena.destaque, f, w * 0.8)
                alt = len(linhas) * f.size * 1.15 + 50
                y0 = h * (0.2 if short else 0.15)
                d.rounded_rectangle((w * 0.06, y0, w * 0.94, y0 + alt), radius=30, fill=(255, 250, 235),
                                    outline=(60, 40, 25), width=6)
                for k, linha in enumerate(linhas):
                    d.text((w / 2, y0 + 25 + f.size * 0.55 + k * f.size * 1.15), linha, font=f, fill=(60, 36, 21),
                           anchor="mm")
            # legenda (karaokê: a palavra falada fica em destaque)
            if fala and not fala.gancho:
                trecho, ativa = legenda_atual(fala, t)
                palavras = trecho.split()
                y = h * 0.32 if short else h * 0.93   # Short: acima dos personagens (até o Golias)
                larguras = [d.textlength(p + " ", font=f_legenda) for p in palavras]
                x = w / 2 - sum(larguras) / 2
                if sum(larguras) > w * 0.92:   # não cabe: duas linhas
                    meio = len(palavras) // 2
                    for parte, dy, base_idx in ((palavras[:meio], -0.6, 0), (palavras[meio:], 0.6, meio)):
                        lw = [d.textlength(p + " ", font=f_legenda) for p in parte]
                        xx = w / 2 - sum(lw) / 2
                        for j, (p, lp) in enumerate(zip(parte, lw)):
                            cor = cor_destaque if base_idx + j == ativa else (255, 255, 255)
                            _texto_contorno(d, (xx, y + dy * f_legenda.size * 1.1), p, f_legenda, cor, anchor="lm")
                            xx += lp
                else:
                    for j, (p, lp) in enumerate(zip(palavras, larguras)):
                        _texto_contorno(d, (x, y), p, f_legenda, cor_destaque if j == ativa else (255, 255, 255),
                                        anchor="lm")
                        x += lp
            # transição: escurece e clareia entre cenas
            if t < cena.inicio + 0.25 or t > cena.fim - 0.05:
                f = 0.0 if t < cena.inicio else min(1, (t - cena.inicio) / 0.25)
                if t < cena.inicio + 0.25 and cena is not rot.cenas[0]:
                    tela = Image.blend(Image.new("RGB", (w, h), (0, 0, 0)), tela, max(0.3, f))
            enc.stdin.write(tela.tobytes())
        enc.stdin.close()
        if enc.wait() != 0:
            raise RuntimeError("ffmpeg falhou ao montar o vídeo animado")
    return destino


def chave_tts() -> str | None:
    return (os.environ.get("GOOGLE_TTS_API_KEY") or "").strip() or None


def caracteres(rot: Roteiro) -> int:
    """Quanto o roteiro gasta da cota de voz do Google."""
    return sum(len(f.texto) for c in rot.cenas for f in c.falas)


def slug(texto: str) -> str:
    return re.sub(r"[^\w]+", "-", texto.lower()).strip("-")[:60]
