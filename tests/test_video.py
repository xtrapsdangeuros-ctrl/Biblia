import subprocess

from PIL import Image

from comum import carregar_config
from video import duracao_audio, gerar_arte, gerar_video


def test_arte_miniatura_e_video(tmp_path):
    cfg = carregar_config()["video"]
    capa = tmp_path / "capa.jpg"
    Image.new("RGB", (600, 900), "#7a3b2e").save(capa)
    audio = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "4", "-i", "sine=frequency=440",
                    "-c:a", "libmp3lame", str(audio)], check=True)

    arte = gerar_arte(capa, tmp_path / "arte.png", "Noite de Vigília", "Aurélio Vasconcelos", "Capítulo 3",
                      "Um título bem comprido para testar a quebra de linhas", 1920, 1080, cfg)
    mini = gerar_arte(capa, tmp_path / "mini.jpg", "Noite de Vigília", "Aurélio Vasconcelos", "Capítulo 3", "",
                      1280, 720, cfg, miniatura=True)
    assert Image.open(arte).size == (1920, 1080)
    assert Image.open(mini).size == (1280, 720) and mini.stat().st_size < 2_000_000

    video = gerar_video(arte, [audio], tmp_path / "v.mp4")
    assert abs(duracao_audio(video) - 4) < 0.5
    juntas = gerar_video(arte, [audio, audio], tmp_path / "v2.mp4")   # partes A + B
    assert abs(duracao_audio(juntas) - 8) < 0.5


def _codec_audio(arquivo):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_name",
                           "-of", "csv=p=0", str(arquivo)], check=True, capture_output=True, text=True).stdout.strip()


def test_video_copia_o_som_quando_da_e_converte_quando_nao(tmp_path):
    from PIL import Image as Img
    arte = tmp_path / "arte.png"
    Img.new("RGB", (320, 180), "#14161c").save(arte)

    def gerar(nome, *codec):
        destino = tmp_path / nome
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "3", "-i", "sine=frequency=440",
                        "-ar", "44100", *codec, str(destino)], check=True)
        return destino

    a, b = gerar("it's a.mp3", "-c:a", "libmp3lame"), gerar("b.mp3", "-c:a", "libmp3lame")
    m4a = gerar("c.m4a", "-c:a", "aac")

    copiado = gerar_video(arte, [a, b], tmp_path / "copiado.mp4")       # mesmo formato: copia (rápido)
    assert _codec_audio(copiado) == "mp3"
    assert abs(duracao_audio(copiado) - 6) < 0.5

    misturado = gerar_video(arte, [a, m4a], tmp_path / "misturado.mp4")  # formatos diferentes: converte
    assert _codec_audio(misturado) == "aac"
    assert abs(duracao_audio(misturado) - 6) < 0.5

    desligado = gerar_video(arte, [a], tmp_path / "desligado.mp4", copiar_audio=False)
    assert _codec_audio(desligado) == "aac"
