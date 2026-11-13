"""Legendas mais rápidas: transcrição longa em pedaços (com progresso salvo) e reaproveitamento do corte."""

import json
import subprocess
from types import SimpleNamespace

import pytest

import transcrever as tr
from cortar import CapituloCortado, Palavra, palavras_de_cada_capitulo
from test_fluxo import PASTA, DriveFalso, ambiente  # noqa: F401  (ambiente é fixture)


@pytest.fixture
def livro_com_audio(tmp_path, monkeypatch):
    drive = DriveFalso(tmp_path)
    pasta = drive.novo("Livro", None, PASTA)
    audio = tmp_path / "cap.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "50", "-i", "anullsrc", "-c:a", "aac",
                    str(audio)], check=True)
    monkeypatch.setattr(tr, "PEDACO_SEG", 20)   # pedaços de 20 s no lugar de 20 min
    feitos = []

    def falso(arquivo, modelo):
        feitos.append(arquivo.name)
        return [Palavra("oi", 1.0, 1.5)]

    monkeypatch.setattr(tr, "transcrever", falso)
    livro = SimpleNamespace(pasta={"id": pasta}, nome="Livro")
    return drive, livro, SimpleNamespace(numero=7), audio, feitos


def test_audio_longo_vai_em_pedacos_e_soma_os_tempos(livro_com_audio):
    drive, livro, cap, audio, feitos = livro_com_audio
    palavras = tr.palavras_do_capitulo(drive, livro, cap, audio, "small")
    assert len(feitos) == 3                                   # 50 s em pedaços de 20 s
    assert [p.inicio for p in palavras] == [1.0, 21.0, 41.0]
    pasta = drive.achar(livro.pasta["id"], tr.PASTA_TRANSCRICOES)["id"]
    assert drive.nomes(pasta) == ["7.json"]                   # o parcial some quando termina
    tr.palavras_do_capitulo(drive, livro, cap, audio, "small")
    assert len(feitos) == 3                                   # da segunda vez lê do Drive


def test_para_no_prazo_e_continua_de_onde_parou(livro_com_audio):
    drive, livro, cap, audio, feitos = livro_com_audio
    with pytest.raises(tr.TempoEsgotado):
        tr.palavras_do_capitulo(drive, livro, cap, audio, "small", prazo=0.001)   # prazo já passou
    assert len(feitos) == 1
    pasta = drive.achar(livro.pasta["id"], tr.PASTA_TRANSCRICOES)["id"]
    parcial = json.loads(drive.ler_texto(drive.achar(pasta, "7.parcial.json")["id"]))
    assert parcial["ate"] == 20

    palavras = tr.palavras_do_capitulo(drive, livro, cap, audio, "small")      # dia seguinte
    assert len(feitos) == 3 and [p.inicio for p in palavras] == [1.0, 21.0, 41.0]


def test_transcricao_do_corte_e_separada_por_capitulo():
    palavras = [Palavra("Capítulo", 0.5, 1.0), Palavra("um", 1.0, 1.2), Palavra("Capítulo", 60.5, 61.0),
                Palavra("dois", 61.0, 61.4), Palavra("fim", 90.0, 90.5)]
    caps = [CapituloCortado(2001, "Capítulo 1", 0.0, 60.0), CapituloCortado(2002, "Capítulo 2", 60.0, 100.0)]
    separadas = palavras_de_cada_capitulo(palavras, caps)
    assert [p.texto for p in separadas[2001]] == ["Capítulo", "um"]
    assert [(p.texto, p.inicio) for p in separadas[2002]] == [("Capítulo", 0.5), ("dois", 1.0), ("fim", 30.0)]


def test_salvar_transcricao_no_formato_das_legendas(tmp_path):
    drive = DriveFalso(tmp_path)
    pasta = drive.novo("Livro", None, PASTA)
    tr.salvar_transcricao(drive, pasta, 3, [Palavra("oi", 1.234, 2.0)])
    sub = drive.achar(pasta, tr.PASTA_TRANSCRICOES)["id"]
    assert json.loads(drive.ler_texto(drive.achar(sub, "3.json")["id"])) == [["oi", 1.23, 2.0]]


def test_corte_guarda_a_transcricao_de_cada_capitulo(ambiente, monkeypatch):
    import cortar

    drive, _youtube, livro = ambiente

    def detecta(audio, cfg):
        cortar.ultimas_palavras[:] = [Palavra("um", 1.0, 1.2), Palavra("dois", 4.0, 4.3), Palavra("três", 7.5, 7.9)]
        return [CapituloCortado(1, "", 0, 3), CapituloCortado(2, "", 3, 6), CapituloCortado(3, "", 6, 9)], "teste"

    monkeypatch.setattr(cortar, "detectar", detecta)
    assert cortar.processar_drive(cortar.carregar_config()["corte"]) == 0
    pasta = drive.achar(livro, tr.PASTA_TRANSCRICOES)["id"]
    assert drive.nomes(pasta) == ["1.json", "2.json", "3.json"]
    assert json.loads(drive.ler_texto(drive.achar(pasta, "3.json")["id"])) == [["três", 1.5, 1.9]]


def test_corte_de_arquivo_enorme_continua_no_dia_seguinte(ambiente, monkeypatch):
    """O arquivo é transcrito em pedaços; se o tempo do corte acaba, o progresso fica salvo e nada é cortado."""
    import cortar
    import time

    drive, _youtube, livro = ambiente
    monkeypatch.setattr(tr, "PEDACO_SEG", 3)          # o áudio de teste tem 9 s: 3 pedaços
    pedacos = []

    def falso(arquivo, modelo):
        pedacos.append(arquivo.name)
        return [Palavra("capítulo", 0.5, 1.0)]

    monkeypatch.setattr(tr, "transcrever", falso)
    cfg = {**cortar.carregar_config()["corte"], "minutos_maximos": 0}   # o prazo acaba logo no 1º pedaço
    assert cortar.processar_drive(cfg) == 0
    assert len(pedacos) == 1 and cortar.retomar is None
    pasta = drive.achar(livro, tr.PASTA_TRANSCRICOES)["id"]
    parcial = [n for n in drive.nomes(pasta) if n.startswith("corte_")]
    assert len(parcial) == 1 and json.loads(drive.ler_texto(drive.achar(pasta, parcial[0])["id"]))["ate"] == 3
    assert not drive.achar(livro, "capitulos")                         # nada foi cortado ainda

    monkeypatch.setattr(time, "monotonic", lambda: 0.0)                # dia seguinte: tempo de sobra
    cfg["minutos_maximos"] = 95
    cortar.processar_drive(cfg)                                        # continua do 2º pedaço
    assert len(pedacos) == 3
    assert not [n for n in drive.nomes(pasta) if n.startswith("corte_")]
