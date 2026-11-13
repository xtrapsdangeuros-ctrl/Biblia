"""Roda o robô com dados falsos e o modo discreto ligado, como no GitHub Actions (usado por test_discreto.py).

Uso: python tests/aux_fluxo_discreto.py PASTA_TEMPORARIA
Os nomes falsos vêm da variável NOMES_FALSOS (JSON). O teste confere que nenhum deles aparece na tela.
"""

import json
import logging
import os
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "src"))
sys.path.insert(0, str(AQUI))

from PIL import Image  # noqa: E402

import comum  # noqa: E402
import discreto  # noqa: E402

comum.configurar_log()   # liga o modo discreto antes de tudo (captura a saída do processo)

import cortar  # noqa: E402
import google_api  # noqa: E402
import livro as _livro  # noqa: E402,F401
import main  # noqa: E402
from cortar import CapituloCortado  # noqa: E402
from test_fluxo import PASTA, DriveFalso  # noqa: E402

N = json.loads(os.environ["NOMES_FALSOS"])
tmp = Path(sys.argv[1])


class YouTubeFalso:
    def __init__(self):
        self.n = 0

    def enviar_video(self, video, snippet, status):
        self.n += 1
        return discreto.registrar(N["videos"][self.n - 1], "vídeo") and N["videos"][self.n - 1]   # como o real

    def definir_miniatura(self, video_id, imagem):
        pass

    def criar_playlist(self, titulo, descricao, privacidade="private"):
        discreto.registrar(N["playlist"], "playlist")
        return N["playlist"]

    def adicionar_na_playlist(self, playlist_id, video_id):
        pass

    def ler_videos(self, ids):
        return []


class DriveQueRegistra(DriveFalso):
    """Como o Drive de verdade (google_api.Drive.listar): tudo o que é listado fica registrado como sensível."""

    def listar(self, pasta_id):
        itens = super().listar(pasta_id)
        for item in itens:
            discreto.registrar_item_drive(item)
        return itens


drive, youtube = DriveQueRegistra(tmp), YouTubeFalso()
raiz = drive.novo("Audiolivros", None, PASTA)
pasta_livro = drive.novo(N["pasta"], raiz, PASTA)
capa = tmp / "capa.jpg"
Image.new("RGB", (400, 600), "#335").save(capa)
audio = tmp / N["arquivo"]
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "9", "-i", "sine=frequency=440",
                "-c:a", "libmp3lame", str(audio)], check=True)
drive.novo("ficha.txt", pasta_livro, "text/plain",
           texto=f"titulo: {N['titulo']}\nautor: {N['autor']}\nlicenca: dominio_publico\nfonte_texto: x\n")
drive.novo("capa.jpg", pasta_livro, "image/jpeg", local=capa)
drive.novo(audio.name, pasta_livro, local=audio)

os.environ["DRIVE_PASTA_RAIZ"] = raiz
google_api.credenciais_do_ambiente = lambda: None
google_api.Drive = lambda cred: drive
google_api.YouTube = lambda cred: youtube
cortar.detectar = lambda a, c: ([CapituloCortado(1, N["capitulo"], 0, 3), CapituloCortado(2, "", 3, 6),
                                 CapituloCortado(3, "", 6, 9)], "teste")

cfg = comum.carregar_config()
cfg["cta"] = {"canal": N["link_canal"], "topo": N["texto_canal"], "fim": []}
cfg["video"]["cta"] = ""
cfg["publicacao"]["minutos_por_video"] = 0
comum.aplicar_canal(cfg)

assert cortar.processar_drive(cfg["corte"]) == 0
for _ in range(2):
    main.rodar_drive(Namespace(dry_run=False, livro=None, capitulo=None, quantos=None), cfg)

# Saídas que não passam pelo log do robô:
print(f"Arquivo do dia: {N['arquivo']} em {N['pasta']}")                                  # print comum
subprocess.run(["ffmpeg", "-v", "error", "-i", str(tmp / N["pasta"] / "nao existe.mp3")])  # erro do ffmpeg
logging.getLogger("biblioteca").warning("Processando %s", N["arquivo"])                     # log de biblioteca
comum.log.warning("Falhou: %s", Exception(f"erro com {N['titulo']} em {N['link_video']}"))  # erro com nome
comum.log.info("Mensagem escrita com f-string: %s / " + N["link_video"], N["autor"])
raise RuntimeError(f"Falha final em {N['pasta']} ({N['videos'][0]})")                       # traceback
