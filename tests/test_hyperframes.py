"""Vídeos animados com HyperFrames (src/hyperframes.py) e a rotina diária (src/animar.py)."""

import re

import animacao as A
import animar
import hyperframes as H
import personagens as P

ROTEIRO = {
    "formato": "short", "titulo": "20 MINUTOS A MAIS? ISSO É HORA EXTRA", "gancho": "20 minutos a mais?",
    "descricao": "Entenda a regra.", "tags": ["hora extra"],
    "elenco": {"golias": {"tipo": "pessoa", "rotulo": "Golias", "tamanho": 1.6}},
    "cenas": [
        {"cenario": "escritorio", "personagens": ["tomatinho", "seu_repolho"], "destaque": "CLT, art. 58",
         "falas": [["narrador", "O Tomatinho fica sempre mais tempo."], ["seu_repolho", "Termina isso aí!"]]},
        {"cenario": "deserto", "personagens": ["golias", "dra_berinjela"],
         "falas": [["dra_berinjela", "Isso conta como hora extra."]]},
    ]}


def _montar(tmp_path, dados=ROTEIRO):
    rot = A.ler_roteiro(dados)
    total = A.preparar_vozes(rot, tmp_path, None)
    return rot, total, H.composicao(rot, total, tmp_path / "proj", "trilha.m4a")


def test_todos_os_vegetais_tem_desenho():
    for p in P.ELENCO.values():
        svg = H.svg_vegetal(p)
        assert H._tem_svg(p)
        for parte in ("olhos", "palpebras", "boca-aberta", "boca-fechada", "braco-e", "braco-d"):
            assert f'class="{parte}"' in svg


def test_composicao_segue_o_contrato(tmp_path):
    rot, total, pagina = _montar(tmp_path)
    assert f'data-duration="{total:.2f}"' in pagina
    assert 'window.__timelines["main"] = tl' in pagina
    assert "Math.random" not in pagina and "Date.now" not in pagina and "repeat: -1" not in pagina
    assert '<audio id="trilha"' in pagina
    # todo elemento com tempo tem class clip, início e duração
    for tag in re.findall(r"<[^>]*data-start[^>]*>", pagina):
        assert "data-duration" in tag and ("clip" in tag or "<audio" in tag or "data-composition-id" in tag)
    # a pessoa (Golias) vira desenho PNG; os cenários também
    arquivos = {p.name for p in (tmp_path / "proj" / "assets").iterdir()}
    assert {"cenario_0.png", "cenario_1.png", "golias_01.png", "golias_11.png", "golias_00.png"} <= arquivos
    # gancho some antes da primeira fala; a legenda tem todas as palavras
    assert 'id="gancho"' in pagina and "Termina" in pagina and "CLT, art. 58" in pagina


def test_golias_nao_cobre_a_legenda(tmp_path):
    _, _, pagina = _montar(tmp_path)
    topo_legenda = float(re.search(r"\.legenda \{[^}]*top: (\d+)px", pagina).group(1))
    for top in re.findall(r'class="clip personagem"[^>]*top:(-?\d+)px', pagina):
        assert float(top) > topo_legenda + 150


def test_formato_longo_horizontal(tmp_path):
    _, _, pagina = _montar(tmp_path, {**ROTEIRO, "formato": "longo"})
    assert 'data-width="1920" data-height="1080"' in pagina


def test_snippet_do_youtube():
    rot = A.ler_roteiro(ROTEIRO)
    conf = animar.config({"animacao": {"hashtags": "#direito", "tags": ["CLT"]}})
    s = animar.snippet(ROTEIRO, rot, conf)
    assert s["title"] == ROTEIRO["titulo"]
    assert s["description"] == "Entenda a regra.\n\n#direito"
    assert s["tags"] == ["hora extra", "CLT", "Shorts"]


def test_sem_hyperframes_usa_o_motor_antigo(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERFRAMES_CLI", raising=False)
    monkeypatch.setattr(H.shutil, "which", lambda _: None)
    usado = []
    monkeypatch.setattr(A, "renderizar", lambda rot, destino, chave: usado.append("antigo") or destino)
    animar.fazer_video(A.ler_roteiro(ROTEIRO), tmp_path / "v.mp4")
    assert usado == ["antigo"]
