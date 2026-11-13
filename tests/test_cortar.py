import subprocess

import pytest

from cortar import (
    CapituloCortado, Palavra, ajustar_ao_silencio, capitulos_embutidos, cortar, detectar_silencios,
    encontrar_marcadores, montar_capitulos, validar,
)
from video import duracao_audio

CFG = {"min_capitulo_seg": 60, "max_intro_seg": 180}


def falas(*trechos):
    """trechos: (inicio, 'texto', segundos_por_palavra). Gera palavras com tempos."""
    palavras = []
    for inicio, texto, passo in trechos:
        t = inicio
        for w in texto.split():
            palavras.append(Palavra(" " + w, t, t + passo * 0.8))
            t += passo
    return palavras


def test_encontra_capitulos_com_titulo_e_ignora_citacao():
    palavras = falas(
        (0.0, "Noite de Vigília, de Aurélio Vasconcelos.", 0.4),
        (5.0, "Capítulo primeiro.", 0.4),
        (7.0, "Da chegada.", 0.4),
        (9.0, "Naquela manhã, voltando da feira pela estrada do rio", 0.3),
        (40.0, "como eu disse no capítulo dois", 0.3),          # citação: sem pausa antes
        (300.0, "Capítulo 2", 0.4),
        (302.0, "Da estrada.", 0.4),
        (304.0, "Agora que contei a chegada", 0.3),
        (600.0, "Capítulo III", 0.4),
        (603.0, "O recado", 0.4),
        (606.0, "Ia abrir a porta do quintal", 0.3),
    )
    marcadores = encontrar_marcadores(palavras, "Capítulo", 1.5)
    assert [(m.numero, m.titulo) for m in marcadores] == [(1, "Da chegada"), (2, "Da estrada"), (3, "O recado")]


def test_capitulo_sem_titulo():
    palavras = falas((0.0, "Capítulo 1", 0.4), (3.0, "Era uma vez um menino que morava longe daqui", 0.3))
    assert encontrar_marcadores(palavras)[0].titulo == ""


def test_prologo_e_epilogo():
    palavras = falas((0.0, "Prólogo", 0.4), (2.0, "texto", 0.3), (100.0, "Capítulo um", 0.4),
                     (103.0, "era uma vez um menino que morava muito longe daqui", 0.3), (200.0, "Epílogo", 0.4), (203.0, "fim", 0.3))
    marcadores = encontrar_marcadores(palavras)
    caps = montar_capitulos(marcadores, 400.0, [])
    assert [(c.numero, c.titulo, c.tipo) for c in caps] == [
        (0, "Prólogo", "prologo"), (1, "", "capitulo"), (2, "Epílogo", "epilogo")]
    assert validar(marcadores, caps, CFG) == []


def test_ajuste_ao_silencio():
    silencios = [(10.0, 12.0), (100.0, 101.6)]
    assert ajustar_ao_silencio(101.7, silencios) == pytest.approx(100.8)
    assert ajustar_ao_silencio(50.0, silencios) == pytest.approx(49.7)  # sem silêncio perto


def test_travas_de_seguranca():
    palavras = falas((10.0, "Capítulo 1", 0.4), (300.0, "Capítulo 3", 0.4), (330.0, "Capítulo 4", 0.4))
    marcadores = encontrar_marcadores(palavras)
    erros = validar(marcadores, montar_capitulos(marcadores, 1000.0, []), CFG)
    assert any("pulou" in e for e in erros)
    assert any("capítulo 3 ficou com só 30s" in e for e in erros)

    tarde = encontrar_marcadores(falas((900.0, "Capítulo 5", 0.4)))
    assert any("continuação" in e for e in validar(tarde, montar_capitulos(tarde, 2000.0, []), CFG))
    assert validar([], [], CFG) == ["não encontrei nenhum 'Capítulo N' falado no áudio"]


def _gerar_audio(caminho, trechos_seg, com_capitulos=False):
    """Tons de 440 Hz separados por 2 s de silêncio."""
    partes, filtros = [], []
    for i, dur in enumerate(trechos_seg):
        partes += ["-f", "lavfi", "-t", str(dur), "-i", f"sine=frequency={440 + i * 110}:sample_rate=44100"]
        partes += ["-f", "lavfi", "-t", "2", "-i", "anullsrc=r=44100:cl=mono"]
    n = len(trechos_seg) * 2
    filtros = "".join(f"[{i}:a]" for i in range(n)) + f"concat=n={n}:v=0:a=1[a]"
    cmd = ["ffmpeg", "-y", "-v", "error", *partes]
    if com_capitulos:
        meta = caminho.with_suffix(".txt")
        linhas, t = [";FFMETADATA1"], 0
        for i, dur in enumerate(trechos_seg, 1):
            linhas += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={t * 1000}", f"END={(t + dur + 2) * 1000}", f"title=Parte {i}"]
            t += dur + 2
        meta.write_text("\n".join(linhas) + "\n")
        cmd += ["-i", str(meta), "-map_metadata", str(n), "-map_chapters", str(n)]
    cmd += ["-filter_complex", filtros, "-map", "[a]", "-c:a", "aac" if caminho.suffix == ".m4a" else "libmp3lame", str(caminho)]
    subprocess.run(cmd, check=True)
    return caminho


def test_capitulos_embutidos_e_corte(tmp_path):
    audio = _gerar_audio(tmp_path / "livro.m4a", [5, 7, 4], com_capitulos=True)
    caps = capitulos_embutidos(audio)
    assert [c.titulo for c in caps] == ["Parte 1", "Parte 2", "Parte 3"]
    arquivos = cortar(audio, caps, tmp_path / "saida")
    assert [a.name for a in arquivos] == ["01 - Parte 1.m4a", "02 - Parte 2.m4a", "03 - Parte 3.m4a"]
    assert [round(duracao_audio(a)) for a in arquivos] == [7, 9, 6]


def test_sem_capitulos_embutidos_e_silencios(tmp_path):
    audio = _gerar_audio(tmp_path / "livro.mp3", [3, 3])
    assert capitulos_embutidos(audio) == []
    silencios = detectar_silencios(audio)
    assert [round(s) for s, _ in silencios[:2]] == [3, 8]


def test_corte_mp3_por_tempos(tmp_path):
    audio = _gerar_audio(tmp_path / "livro.mp3", [4, 4])
    caps = [CapituloCortado(1, "Um", 0, 6), CapituloCortado(2, "", 6, duracao_audio(audio))]
    nomes = [a.name for a in cortar(audio, caps, tmp_path / "s")]
    assert nomes == ["01 - Um.mp3", "02.mp3"]
