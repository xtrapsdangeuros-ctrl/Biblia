from PIL import Image

import arte_pavao
from comum import carregar_config
from video import gerar_arte


def _cores(**extra):
    return {**carregar_config()["video"], "estilo": "pavao", **extra}


def _capa(tmp_path):
    capa = tmp_path / "capa.jpg"
    Image.new("RGB", (345, 500), "#7a3b2e").save(capa)
    return capa


def test_rotulos_da_miniatura():
    assert arte_pavao.adaptar_rotulo("Capítulo 3", "Da Estrada") == ("Cap. 3", "Da Estrada")
    assert arte_pavao.adaptar_rotulo("Parte 2", "Caps. 5 a 9") == ("Parte 2", "Caps. 5 a 9")
    assert arte_pavao.adaptar_rotulo("Prólogo", "") == ("Prólogo", "")
    assert arte_pavao.adaptar_rotulo("Audiolivro Completo – Parte 2 de 3", "") == \
        ("Parte 2", "Audiolivro completo · parte 2 de 3")
    assert arte_pavao.adaptar_rotulo("Audiolivro Completo", "") == ("Completo", "Audiolivro completo")


def test_titulo_curto():
    assert arte_pavao.titulo_curto("Noite de Vigília: o retorno") == "Noite de Vigília"
    assert arte_pavao.titulo_curto("Noite de Vigília (Vol. 2)") == "Noite de Vigília"
    assert arte_pavao.titulo_curto("Fogo – Livro Um") == "Fogo"


def test_miniatura_e_arte_do_video_no_estilo_do_canal(tmp_path):
    capa = _capa(tmp_path)
    mini = gerar_arte(capa, tmp_path / "mini.jpg", "Noite de Vigília", "Aurélio Vasconcelos", "Capítulo 3",
                      "Da Estrada", 1280, 720, _cores(), miniatura=True)
    arte = gerar_arte(capa, tmp_path / "arte.png", "Noite de Vigília", "Aurélio Vasconcelos", "Capítulo 3",
                      "Um título bem comprido para testar a quebra de linhas", 1920, 1080, _cores())
    assert Image.open(mini).size == (1280, 720) and mini.stat().st_size < 2_000_000
    assert Image.open(arte).size == (1920, 1080)
    # o dourado do número do capítulo aparece (o estilo novo foi usado, não o antigo)
    dourado = arte_pavao.rgb(arte_pavao.DOURADO, None)
    pixels = Image.open(mini).convert("RGB").resize((320, 180)).getdata()
    assert sum(1 for p in pixels if all(abs(p[i] - dourado[i]) < 40 for i in range(3))) > 50


def test_todas_as_variantes_e_titulo_longo(tmp_path):
    capa = _capa(tmp_path)
    longo = "As Extraordinárias Aventuras do Cavaleiro Andante das Terras do Norte e do Sul"
    for v in arte_pavao.VARIANTES:
        mini = arte_pavao.miniatura(capa, tmp_path / f"{v}.jpg", longo, "Lauro Bastos", "Cap. 123", "Detalhe",
                                    variante=v)
        assert Image.open(mini).size == (1280, 720)


def test_sem_capa_usa_a_arte_do_canal(tmp_path):
    mini = gerar_arte(None, tmp_path / "mini.jpg", "Noite de Vigília", "", "Capítulo 1", "", 1280, 720,
                      _cores(), miniatura=True)
    assert Image.open(mini).size == (1280, 720)


def test_outros_canais_continuam_com_a_arte_antiga(tmp_path, monkeypatch):
    chamou = []
    monkeypatch.setattr(arte_pavao, "arte", lambda *a, **k: chamou.append(1))
    gerar_arte(_capa(tmp_path), tmp_path / "mini.jpg", "Livro", "Autor", "Capítulo 1", "", 1280, 720,
               carregar_config()["video"], miniatura=True)
    assert not chamou


def test_capa_quadrada(tmp_path):
    for capa in (_capa(tmp_path), None):
        img = arte_pavao.capa_quadrada(capa, tmp_path / "q.jpg", "Noite de Vigília", "Aurélio Vasconcelos")
        assert Image.open(img).size == (1400, 1400)
