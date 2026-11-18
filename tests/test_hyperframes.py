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
    # os cenários viram PNG; a pessoa (Golias) é desenhada em SVG, com cabeça que mexe
    arquivos = {p.name for p in (tmp_path / "proj" / "assets").iterdir()}
    assert {"cenario_0.png", "cenario_1.png"} <= arquivos
    assert 'class="cabeca"' in pagina and 'class="sobrancelhas"' in pagina
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
    monkeypatch.setattr(A, "renderizar", lambda rot, destino, chave, musica=None: usado.append("antigo") or destino)
    animar.fazer_video(A.ler_roteiro(ROTEIRO), tmp_path / "v.mp4")
    assert usado == ["antigo"]


def test_comeca_falando(tmp_path):
    rot, _, pagina = _montar(tmp_path)
    primeira = rot.cenas[0].falas[0]
    assert primeira.gancho and primeira.texto == ROTEIRO["gancho"] and primeira.inicio < 0.3
    # o gancho aparece grande, sem legenda repetida
    assert pagina.count(">20</span>") == 0


def test_corta_gravacao_longa_em_trechos(tmp_path):
    import subprocess
    import musica as M
    # 3 "músicas" separadas por silêncio: 30 s fraca, 200 s média (vira 2+ trechos), 60 s forte
    gravacao = tmp_path / "banda.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error",
                    "-f", "lavfi", "-i", "sine=f=220:d=30", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
                    "-f", "lavfi", "-i", "sine=f=330:d=200", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono:d=3",
                    "-f", "lavfi", "-i", "sine=f=440:d=60",
                    "-filter_complex", "[0]volume=0.1,aresample=44100[a];[1]aresample=44100[b];"
                    "[2]volume=0.4,aresample=44100[c];[3]aresample=44100[d];[4]volume=1,aresample=44100[e];"
                    "[a][b][c][d][e]concat=n=5:v=0:a=1", str(gravacao)], check=True)
    trechos = M.cortar(gravacao, tmp_path / "t")
    assert len(trechos) >= 4
    assert all(M.MENOR_TRECHO <= t["duracao"] <= M.MAXIMO + 1 for t in trechos)
    assert trechos[0]["clima"] == "calma" and trechos[-1]["clima"] == "epica"
    assert all((tmp_path / "t" / t["arquivo"]).exists() for t in trechos)
    # escolha: o menos usado do clima pedido
    usos = {trechos[-1]["arquivo"]: 3}
    assert M.escolher(trechos, "calma", 40, usos)["clima"] == "calma"
    assert M.escolher(trechos, "inexistente", 40, {})["arquivo"]


def test_elenco_elevenlabs_sem_repetir_voz():
    import elevenlabs as E
    vozes = [{"voice_id": f"id{i}", "name": n, "labels": {"gender": g}} for i, (n, g) in enumerate(
        [("Brian", "male"), ("Liam", "male"), ("Sarah", "female"), ("Callum", "male"), ("Roger", "male"), ("Alice", "female")])]
    rot = A.ler_roteiro({**ROTEIRO, "elenco": {**ROTEIRO["elenco"],
                                               "maria": {"tipo": "pessoa", "rotulo": "Maria", "voz": "pt-BR-Chirp3-HD-Kore"}},
                         "cenas": ROTEIRO["cenas"] + [{"cenario": "campo", "personagens": ["maria"],
                                                       "falas": [["maria", "Oi."]]}]})
    elenco = E.escolher_elenco(rot, vozes)
    assert elenco["narrador"] == "id0"                       # Brian narra
    assert {elenco["dra_berinjela"], elenco["maria"]} == {"id2", "id5"}   # vozes femininas para as duas
    assert len(set(elenco.values())) == len(elenco)          # ninguém com a mesma voz
    assert E.escolher_elenco(rot, vozes, {"narrador": "Roger"})["narrador"] == "id4"
    # voz fixa de um personagem não é sorteada para outro
    fixo = E.escolher_elenco(rot, vozes, {"seu_repolho": "Brian"})
    assert fixo["seu_repolho"] == "id0" and fixo["narrador"] != "id0"


def test_efeito_divino_no_narrador(tmp_path):
    import subprocess
    voz = tmp_path / "v.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=200:d=1.5", str(voz)], check=True)
    saida = A.efeito_de_voz(voz, "divino", tmp_path / "v_fx.wav")
    assert saida.exists() and A._duracao(saida) >= 1.5        # o eco deixa um rastro no fim
    assert A.efeito_de_voz(voz, "nenhum", tmp_path / "x.wav") == voz
    rot = A.ler_roteiro({**ROTEIRO, "efeito_narrador": "divino"})
    assert rot.efeito_narrador == "divino"


def test_sem_credito_no_elevenlabs_usa_o_google(tmp_path, monkeypatch):
    import elevenlabs as E
    chamadas = []

    def falso(rot, destino, motor="hyperframes", musica=None):
        chamadas.append(rot.narrador)
        if rot.narrador.startswith("eleven:"):
            raise E.ErroElevenLabs("ElevenLabs recusou (401): quota_exceeded")
        return destino

    class Drive:
        def pasta(self, *a): return "p"
        def ler_json(self, *a): return {"videos": {}, "dias": {}}
        def listar(self, *a): return []
        def achar(self, *a): return None
        def enviar(self, *a): return "x"
        def gravar_json(self, *a): pass
        def mover(self, *a): pass

    class YT:
        def enviar_video(self, *a): return "vid"

    monkeypatch.setattr(animar, "fazer_video", falso)
    monkeypatch.setattr(animar, "_roteiros", lambda d, p: [({"id": "r", "name": "01_x.yaml"}, ROTEIRO)])
    monkeypatch.setattr(animar, "usar_vozes", lambda rot, conf: setattr(rot, "narrador", "eleven:abc@0.5"))
    assert animar.rodar(Drive(), YT(), "raiz", {"animacao": {"ativo": True}}, pedido="01_") == 0
    assert chamadas[0].startswith("eleven:") and not chamadas[1].startswith("eleven:")


def test_meditacao_longa_tem_ritmo_calmo(tmp_path):
    curto = A.ler_roteiro(ROTEIRO)
    longo = A.ler_roteiro({**ROTEIRO, "formato": "longo"})
    t_curto = A.preparar_vozes(curto, tmp_path, None)
    (tmp_path / "l").mkdir()
    t_longo = A.preparar_vozes(longo, tmp_path / "l", None)
    assert t_longo > t_curto + 3          # respiros maiores entre falas e cenas
    (tmp_path / "x").mkdir()
    _, _, pagina = _montar(tmp_path / "x", {**ROTEIRO, "formato": "longo", "cenas": [
        {"cenario": "campo", "personagens": [], "destaque": "Salmo 23", "falas": [["narrador", "Respira. [pausa] Eu estou aqui."]]}]})
    assert 'data-width="1920"' in pagina and "#fundo0 img" in pagina   # só cenário e narração, com zoom lento
