"""Narração a partir de .epub (voz do Google trocada por um áudio de teste)."""

import shutil
import subprocess
import zipfile

import pytest

import main
import narrar
import vozes
from epub import ler_epub, texto_falado, titulo_arquivo
from test_fluxo import PASTA, _args, ambiente, carregar_config_teste  # noqa: F401

PARAGRAFO = "Tavian olhou para o campo de batalha e respirou fundo antes de correr. " * 30


def criar_epub(destino):
    capitulos = [("p0.html", "Créditos", "<p>Copyright 2010</p>"),
                 ("p1.html", "PARTE UM: ALÉM DA SERRA", "<p>PARTE UM</p>"),
                 ("p2.html", "1: Filho da neblina",
                  '<h1>1: Filho da neblina</h1><p><span class="cap">T</span>avian correu.</p>' + f"<p>{PARAGRAFO}</p>"),
                 ("p3.html", "I-1: Orrek", f"<p>{PARAGRAFO}</p>"),
                 ("p4.html", "Epílogo: Do último farol", f"<p>{PARAGRAFO}</p>")]
    with zipfile.ZipFile(destino, "w") as z:
        z.writestr("OEBPS/content.opf", "<package><manifest>" + "".join(
            f'<item id="i{n}" href="Text/{a}"/>' for n, (a, _, _) in enumerate(capitulos)) + "</manifest><spine>" +
            "".join(f'<itemref idref="i{n}"/>' for n in range(len(capitulos))) + "</spine></package>")
        z.writestr("OEBPS/toc.ncx", "<ncx>" + "".join(
            f'<navPoint><navLabel><text>{t}</text></navLabel><content src="Text/{a}"/></navPoint>'
            for a, t, _ in capitulos) + "</ncx>")
        for a, _, corpo in capitulos:
            z.writestr(f"OEBPS/Text/{a}", f"<html><head><style>p{{}}</style></head><body>{corpo}</body></html>")
    return destino


def test_le_epub_na_ordem_do_sumario(tmp_path):
    secoes = ler_epub(criar_epub(tmp_path / "l.epub"))
    assert [titulo_arquivo(s.titulo) for s in secoes] == [
        "Capítulo 1 - Filho da neblina", "Interlúdio I-1 - Orrek", "Epílogo - Do último farol"]
    falado = texto_falado(secoes[0])
    assert falado.startswith("Parte um: além da serra.\n\nCapítulo 1: Filho da neblina.\n\nTavian correu.")
    assert falado.count("Filho da neblina") == 1   # o título escrito no texto não é lido duas vezes


def test_divide_texto_gigante():
    pedacos = vozes.dividir_texto("palavra " * 5000)   # um parágrafo sem ponto final
    assert all(len(p.encode()) <= vozes.LIMITE_BYTES_GOOGLE for p in pedacos)
    assert " ".join(pedacos).split() == ["palavra"] * 5000


@pytest.fixture
def livro_narrado(ambiente, tmp_path, monkeypatch):  # noqa: F811
    drive, youtube, livro = ambiente
    raiz = drive.itens[livro]["pai"]
    pasta = drive.novo("Bruno Salles A Trilha dos Sábios", raiz, PASTA)
    drive.novo("ficha.txt", pasta, "text/plain", texto="titulo: A Trilha dos Sábios\nlicenca: uso_pessoal\n"
               "voz_sintetica: true\nnarrar: true\nvoz: pt-BR-Chirp3-HD-Achernar\n")
    drive.novo("livro.epub", pasta, "application/epub+zip", local=criar_epub(tmp_path / "livro.epub"))
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])   # o outro livro sai da frente
    som = tmp_path / "som.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "2", "-i", "sine", str(som)], check=True)
    pedidos = []

    def falsa(texto, voz, chave, destino, idioma="pt-BR"):
        pedidos.append((voz, texto))
        shutil.copy(som, destino)
        return destino

    monkeypatch.setattr(vozes, "narrar_google", falsa)
    monkeypatch.setenv("GOOGLE_TTS_API_KEY", "chave")
    return drive, youtube, raiz, pasta, pedidos


def test_narra_respeitando_a_cota_e_publica(livro_narrado):
    drive, youtube, raiz, pasta, pedidos = livro_narrado
    cfg = carregar_config_teste()
    cfg["narracao"]["caracteres_por_mes"] = 5000   # cabem 2 das 3 seções
    assert narrar.processar(drive, raiz, cfg) == 0
    caps = drive.achar(pasta, "capitulos")["id"]
    assert drive.nomes(caps) == ["001 - Capítulo 1 - Filho da neblina.mp3", "002 - Interlúdio I-1 - Orrek.mp3"]
    assert all(v == "pt-BR-Chirp3-HD-Achernar" for v, _ in pedidos)
    uso = drive.ler_json(raiz, narrar.ARQ_USO, {})["meses"][narrar.mes_atual()]
    assert 4000 < uso <= 5000

    assert narrar.processar(drive, raiz, cfg) == 0 and len(pedidos) == 2   # cota do mês acabou: não repete
    cfg["narracao"]["caracteres_por_mes"] = 10**6
    narrar.processar(drive, raiz, cfg)
    assert len(drive.nomes(caps)) == 3 and len(pedidos) == 3

    assert main.rodar_drive(_args(quantos=0), cfg) == 0
    titulos = [s["title"] for s, _ in youtube.videos]
    assert [t.split(" | ")[0] for t in titulos] == ["AUDIOLIVRO A TRILHA DOS SÁBIOS – CAP. 1: Filho da neblina",
                                                    "AUDIOLIVRO A TRILHA DOS SÁBIOS – Interlúdio I-1 - Orrek",
                                                    "AUDIOLIVRO A TRILHA DOS SÁBIOS – Epílogo - Do último farol"]
    assert all(st["privacyStatus"] == "private" and st["containsSyntheticMedia"] for _, st in youtube.videos)


def test_sem_chave_avisa(livro_narrado, monkeypatch):
    drive, youtube, raiz, pasta, pedidos = livro_narrado
    monkeypatch.delenv("GOOGLE_TTS_API_KEY")
    assert narrar.processar(drive, raiz, carregar_config_teste()) == 1 and pedidos == []
