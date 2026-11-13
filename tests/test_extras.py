"""Extras: livro completo, legendas e Shorts (com Drive e YouTube falsos)."""

import subprocess

import pytest

import extras
import google_api
import main
import transcrever as tr
from completo import descricao_parte, dividir_em_partes, marcadores, titulo_parte
from cortar import Palavra
from shorts import escolher_trecho, gerar_ass, merece_short, titulo_short
from test_fluxo import FICHA, PASTA, _args, ambiente, carregar_config_teste  # noqa: F401
from transcrever import gerar_srt
from video import duracao_audio


def _palavras(duracao: float, passo: float = 0.5, por_frase: int = 8) -> list[Palavra]:
    saida, t, i = [], 0.0, 0
    while t + passo <= duracao:
        i += 1
        saida.append(Palavra(f" palavra{i}" + ("." if i % por_frase == 0 else ""), t, t + passo * 0.9))
        t += passo
    return saida


# ---------------------------------------------------------------- partes e marcadores

def test_divide_em_partes_sem_quebrar_capitulo():
    h = 3600
    assert dividir_em_partes([4 * h, 4 * h, 4 * h, 1 * h], 11 * h) == [[0, 1], [2, 3]]
    assert dividir_em_partes([12 * h, 1 * h], 11 * h) == [[0], [1]]   # capítulo gigante vai sozinho
    assert dividir_em_partes([60, 60], 11 * h) == [[0, 1]]


def test_marcadores_comecam_em_zero():
    linhas = marcadores(["Abertura", "Cap. 1", "Cap. 2"], [75.4, 3600, 10])
    assert linhas == ["00:00 Abertura", "01:15 Cap. 1", "1:01:15 Cap. 2"]


def test_descricao_da_parte_prioriza_marcadores():
    ficha = {"titulo": "Despertar", "descricao": "x" * 6000, "licenca": "uso_pessoal"}
    linhas = [f"{i}:00:00 Cap. {i}" for i in range(80)]
    desc = descricao_parte(ficha, 1, 3, linhas, "PL1", {2: "VIDB"})
    assert len(desc) <= 5000 and "Cap. 79" in desc and "youtu.be/VIDB" in desc
    assert titulo_parte(ficha, 1, 3) == "AUDIOLIVRO COMPLETO DESPERTAR (1 DE 3)"
    assert titulo_parte(ficha, 1, 1) == "AUDIOLIVRO COMPLETO DESPERTAR"
    assert desc.startswith("Audiolivro Despertar – livro completo, parte 1 de 3.")


# ---------------------------------------------------------------- trecho, legenda e Short

def test_trecho_do_short_comeca_e_termina_em_frase():
    palavras = _palavras(300)
    trecho = escolher_trecho(palavras)
    dur = trecho[-1].fim - trecho[0].inicio
    assert 35 <= dur <= 55
    assert trecho[0].inicio >= 20 and trecho[-1].texto.endswith(".")
    anterior = palavras[palavras.index(trecho[0]) - 1]
    assert anterior.texto.endswith(".")


def test_trecho_sem_ponto_final_corta_no_maximo():
    trecho = escolher_trecho(_palavras(300, por_frase=10**6), pular=0)
    assert trecho[-1].fim - trecho[0].inicio <= 55


def test_ass_e_srt():
    trecho = _palavras(10, por_frase=4)
    ass = gerar_ass(trecho)
    assert "PlayResY: 1920" in ass and ass.count("Dialogue:") == 10 and "PALAVRA1" in ass
    srt = gerar_srt(trecho)
    assert srt.startswith("1\n00:00:00,000 --> ") and "palavra4." in srt


def test_quais_capitulos_viram_short():
    assert merece_short(3, "O fim")
    assert merece_short(0, "Prólogo")
    assert not merece_short(0, "Abertura") and not merece_short(80, "Glossário")
    assert titulo_short({"titulo": "Despertar"}, 3, "Capítulo 2 - A volta") == "DESPERTAR – CAP. 2 #audiolivro #shorts"


def test_renderiza_short_vertical(tmp_path):
    from comum import carregar_config
    from shorts import exemplo_local

    audio = tmp_path / "a.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "80", "-i", "sine=frequency=330",
                    "-c:a", "libmp3lame", str(audio)], check=True)
    video = exemplo_local(None, audio, _palavras(80), carregar_config(), tmp_path / "short.mp4")
    sonda = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout
    assert sonda.strip() == "1080,1920"
    assert 35 <= duracao_audio(video) <= 59


# ---------------------------------------------------------------- fluxo completo

@pytest.fixture
def publicado(ambiente, tmp_path, monkeypatch):  # noqa: F811
    """Livro com 3 capítulos já publicados (o 1º com 70 s, para caber um Short)."""
    drive, youtube, livro = ambiente
    curto = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    longo = tmp_path / "longo.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "70", "-i", "sine=frequency=500",
                    "-c:a", "libmp3lame", str(longo)], check=True)
    drive.novo("01 - Da chegada.mp3", livro, local=longo)
    drive.novo("02 - Da estrada.mp3", livro, local=curto)
    drive.novo("03 - O recado.mp3", livro, local=curto)
    cfg = carregar_config_teste()
    assert main.rodar_drive(_args(quantos=0), cfg) == 0 and len(youtube.videos) == 3

    youtube.legendas = []
    youtube.inserir_legenda = lambda vid, srt, idioma="pt-BR", nome="Português": youtube.legendas.append(
        (vid, srt.read_text()))
    transcritos = []

    def falso(audio, modelo):
        transcritos.append(audio.name)
        return _palavras(duracao_audio(audio))

    monkeypatch.setattr(tr, "transcrever", falso)
    youtube.transcritos = transcritos
    raiz = drive.itens[livro]["pai"]
    return drive, youtube, livro, raiz, cfg


def test_extras_fazem_completo_legendas_e_short(publicado):
    drive, youtube, livro, raiz, cfg = publicado
    assert extras.rodar_extras(drive, youtube, raiz, cfg) == 0

    # ordem nova: legendas e Shorts primeiro, livro completo por último
    novos = youtube.videos[3:]
    titulos = [s["title"] for s, _ in novos]
    assert titulos[0] == "NOITE DE VIGÍLIA, Aurélio Vasconcelos – CAP. 1 #audiolivro #shorts"   # os outros são curtos demais
    assert "youtu.be/VID1" in novos[0][0]["description"]
    assert titulos[1:] == ["AUDIOLIVRO COMPLETO NOITE DE VIGÍLIA | Aurélio Vasconcelos"]
    desc = novos[1][0]["description"]
    assert "00:00 Cap. 1: Da chegada" in desc and "01:10 Cap. 2: Da estrada" in desc
    assert all(st["privacyStatus"] == "private" for _, st in novos)   # a ficha não pediu público
    assert [v for v, _ in youtube.legendas] == ["VID1", "VID2", "VID3"]

    estado = drive.ler_json(livro, "publicados.json", {})
    assert estado["completo"]["concluido"] and estado["completo"]["partes"] == {"1": "VID5"}
    assert estado["capitulos"]["1"]["short"] == "VID4" and estado["capitulos"]["2"]["short"] == "pulado"
    assert all(estado["capitulos"][n]["legenda"] is True for n in "123")
    trans = drive.achar(livro, tr.PASTA_TRANSCRICOES)["id"]
    assert drive.nomes(trans) == ["1.json", "2.json", "3.json"]

    # No dia seguinte não repete nada (e não transcreve de novo).
    antes = (len(youtube.videos), len(youtube.legendas), len(youtube.transcritos))
    assert extras.rodar_extras(drive, youtube, raiz, cfg) == 0
    assert (len(youtube.videos), len(youtube.legendas), len(youtube.transcritos)) == antes


def test_sem_permissao_de_legenda_segue_com_shorts(publicado):
    drive, youtube, livro, raiz, cfg = publicado

    def nega(*a, **k):
        raise google_api.SemPermissao("insufficientPermissions")

    youtube.inserir_legenda = nega
    assert extras.rodar_extras(drive, youtube, raiz, cfg, so=None) == 0
    estado = drive.ler_json(livro, "publicados.json", {})
    assert not any(r.get("legenda") for r in estado["capitulos"].values())
    assert estado["capitulos"]["1"]["short"] == "VID4"


def test_limite_diario_para_os_extras(publicado, monkeypatch):
    drive, youtube, livro, raiz, cfg = publicado

    def limite(*a, **k):
        raise google_api.LimiteDiario("quotaExceeded")

    monkeypatch.setattr(youtube, "enviar_video", limite)
    assert extras.rodar_extras(drive, youtube, raiz, cfg) == 0
    estado = drive.ler_json(livro, "publicados.json", {})
    # a legenda do 1º capítulo sai antes do Short bater no limite; depois disso para tudo
    assert [v for v, _ in youtube.legendas] == ["VID1"]
    assert "short" not in estado["capitulos"]["1"] and not estado.get("completo", {}).get("partes")


def test_limites_diarios_respeitados(publicado):
    drive, youtube, livro, raiz, cfg = publicado
    cfg["extras"].update(legendas_por_dia=2, shorts_por_dia=0, livro_completo=False)
    extras.rodar_extras(drive, youtube, raiz, cfg)
    assert len(youtube.legendas) == 2 and len(youtube.videos) == 3


def test_previa_poe_short_no_drive_sem_youtube(publicado, tmp_path):
    drive, youtube, livro, raiz, cfg = publicado
    antes = len(youtube.videos)
    assert extras.rodar_extras(drive, youtube, raiz, cfg, so="shorts", quantos=3, previa=True,
                               saida_previas=tmp_path / "previas") == 0
    assert len(youtube.videos) == antes and youtube.legendas == []
    pasta = drive.achar(raiz, extras.PASTA_PREVIAS)["id"]
    assert drive.nomes(pasta) == ["Noite de Vigília - Cap 1.mp4"]       # os outros são curtos demais
    assert (tmp_path / "previas" / "Noite de Vigília - Cap 1.mp4").exists()
    estado = drive.ler_json(livro, "publicados.json", {})
    assert "short" not in estado["capitulos"]["1"]                   # o Short de verdade continua pendente
    # pode gerar a prévia de novo (substitui o arquivo, sem duplicar)
    extras.rodar_extras(drive, youtube, raiz, cfg, so="shorts", quantos=3, previa=True)
    assert drive.nomes(pasta) == ["Noite de Vigília - Cap 1.mp4"]
