"""Modo Bíblia (src/biblia.py): plano de leitura, títulos e o fluxo com Drive e YouTube falsos."""

import subprocess
import unicodedata

import pytest

import biblia
from biblia import Capitulo, dividir, numero_do_arquivo, ordem_e_nome, referencia
from test_fluxo import PASTA, DriveFalso


def _caps(livro, ordem, numeros, tamanho=100):
    return [Capitulo(livro, ordem, n, {"id": f"{livro}{n}", "name": f"{n}.mp3", "size": str(tamanho)})
            for n in numeros]


def test_nomes_de_pasta_e_arquivo():
    assert ordem_e_nome("01 Gênesis") == (1, "Gênesis")
    assert ordem_e_nome("49 - Efésios") == (49, "Efésios")
    assert ordem_e_nome("34  Naum") == (34, "Naum")
    assert ordem_e_nome("09 1 Samuel") == (9, "1 Samuel")
    assert ordem_e_nome("Artes") is None
    assert numero_do_arquivo("01ge01.mp3") == 1
    assert numero_do_arquivo("19sl150.mp3") == 150
    assert numero_do_arquivo("Gênesis 12.mp3") == 12
    assert numero_do_arquivo("sem numero.mp3") is None


def test_referencia_segue_as_regras_do_titulo():
    assert referencia(_caps("Gênesis", 1, [1, 2, 3])) == "Gênesis 1, 2 e 3"
    assert referencia(_caps("Gênesis", 1, [4, 5])) == "Gênesis 4 e 5"
    assert referencia(_caps("Salmos", 19, [23])) == "Salmo 23"
    assert referencia(_caps("Salmos", 19, [23, 24, 25, 26, 27])) == "Salmos 23 a 27"
    assert referencia(_caps("Rute", 8, [4]) + _caps("1 Samuel", 9, [1, 2])) == "Rute 4 e 1 Samuel 1 e 2"


def test_divisao_equilibrada_e_em_ordem():
    caps = _caps("A", 1, range(1, 11), 100) + _caps("B", 2, range(1, 11), 300)
    dias = dividir(caps, 5)
    assert len(dias) == 5 and [c for d in dias for c in d] == caps   # nada some nem muda de ordem
    pesos = [sum(c.tamanho for c in d) for d in dias]
    assert max(pesos) - min(pesos) <= 300                            # o livro de capítulos grandes rende menos por dia
    assert dividir(caps[:3], 365) == [[c] for c in caps[:3]]          # menos capítulos que dias


def test_titulo_longo_usa_o_modelo_curto():
    conf = biblia.config({})
    caps = _caps("Rute", 8, [4]) + _caps("1 Samuel", 9, [1, 2])
    valores = biblia.campos(conf, 70, 365, caps, None, {})
    assert biblia.titulo(conf, valores) == "Rute 4 e 1 Samuel 1 e 2 | Bíblia em Áudio | Dia 70 de 365"
    longo = _caps("1 Tessalonicenses", 52, [1, 2, 3, 4, 5]) + _caps("2 Tessalonicenses", 53, [1, 2, 3])
    valores = biblia.campos(conf, 330, 365, longo, None, {})
    assert biblia.titulo(conf, valores) == "1 Tessalonicenses 1 a 5 e 2 Tessalonicenses 1, 2 e 3 | Dia 330 de 365"


def test_minutagem_so_com_tres_capitulos_ou_mais():
    conf = biblia.config({"biblia": {"credito": "Tradução X"}})
    tres = biblia.campos(conf, 1, 365, _caps("Gênesis", 1, [1, 2, 3]), [0, 300.4, 3725], {})
    texto = biblia.descricao(conf, tres)
    assert "00:00 Gênesis 1\n05:00 Gênesis 2\n1:02:05 Gênesis 3" in texto and "Texto bíblico: Tradução X" in texto
    assert "#BíbliaEmÁudio #Gênesis #BíbliaEm1Ano" in texto
    dois = biblia.campos(conf, 2, 365, _caps("Gênesis", 1, [4, 5]), [0, 300], {})
    assert "00:00" not in biblia.descricao(conf, dois)


class YouTubeFalso:
    def __init__(self):
        self.videos, self.playlists, self.itens, self.atualizados = [], {}, [], []

    def enviar_video(self, video, snippet, status):
        assert video.exists() and video.stat().st_size > 0
        self.videos.append((snippet, status))
        return f"V{len(self.videos)}"

    def definir_miniatura(self, video_id, imagem):
        assert imagem.exists()

    def criar_playlist(self, titulo, descricao, privacidade="private"):
        pid = f"PL{len(self.playlists) + 1}"
        self.playlists[pid] = (titulo, privacidade)
        return pid

    def adicionar_na_playlist(self, playlist_id, video_id):
        self.itens.append((playlist_id, video_id))

    def atualizar_metadados(self, video_id, snippet):
        self.atualizados.append((video_id, snippet))


@pytest.fixture
def biblia_falsa(tmp_path):
    drive, youtube = DriveFalso(tmp_path), YouTubeFalso()
    raiz = drive.novo("Canal", None, PASTA)
    audios = drive.novo("Áudios", raiz, PASTA)
    for ordem, livro, n in ((1, "01 Gênesis", 4), (40, "40 Mateus", 2)):
        pasta = drive.novo(livro, audios, PASTA)
        for c in range(1, n + 1):
            mp3 = tmp_path / f"{ordem}_{c}.mp3"
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "2", "-i", "sine=frequency=440",
                            "-c:a", "libmp3lame", str(mp3)], check=True)
            drive.novo(f"{ordem:02d}xx{c:02d}.mp3", pasta, local=mp3)
    cfg = {"modo": "biblia", "video": {"largura": 640, "altura": 360, "cor_fundo": "#111111", "cor_texto": "#ffffff",
                                         "cor_destaque": "#ffcc00", "copiar_audio": True},
           "publicacao": {"idioma": "pt-BR"}, "cta": {"canal": "https://y/@c"},
           "biblia": {"dias": 3, "credito": "Tradução Livre", "privacidade": "public"}}
    return drive, youtube, raiz, cfg


def test_fluxo_publica_um_dia_por_vez(biblia_falsa):
    drive, youtube, raiz, cfg = biblia_falsa
    assert biblia.rodar(drive, youtube, raiz, cfg) == 0
    assert biblia.rodar(drive, youtube, raiz, cfg) == 0   # mesmo dia: não publica de novo
    assert len(youtube.videos) == 1
    snippet, status = youtube.videos[0]
    assert snippet["title"].startswith("Gênesis 1") and snippet["title"].endswith("Dia 1 de 3")
    assert status["privacyStatus"] == "public"
    assert "https://www.youtube.com/playlist?list=PL1" in snippet["description"]   # links já no 1º envio
    # dia 1 entra no plano, no Antigo Testamento e no livro
    assert {youtube.playlists[p][0] for p, v in youtube.itens if v == "V1"} == {
        "Bíblia em 1 Ano – Leitura Diária (Dia 1 ao 3)", "Antigo Testamento em Áudio – Bíblia Completa",
        "Gênesis Completo em Áudio – Bíblia Sagrada"}

    estado = drive.ler_json(raiz, biblia.ARQ_ESTADO, {})
    estado["dias"]["1"]["data"] = "2000-01-01"            # finge que o dia 1 saiu ontem
    drive.gravar_json(raiz, biblia.ARQ_ESTADO, estado)
    assert biblia.rodar(drive, youtube, raiz, cfg) == 0
    assert len(youtube.videos) == 2 and "Dia 2 de 3" in youtube.videos[1][0]["title"]
    # o vídeo de ontem ganhou o link do de hoje
    assert youtube.atualizados[-1][0] == "V1" and "https://youtu.be/V2" in youtube.atualizados[-1][1]["description"]
    assert "Texto bíblico: Tradução Livre" in youtube.videos[1][0]["description"]


def test_dia_pedido_e_dry_run(biblia_falsa):
    drive, youtube, raiz, cfg = biblia_falsa
    assert biblia.rodar(drive, youtube, raiz, cfg, dry_run=True) == 0 and youtube.videos == []
    assert biblia.rodar(drive, youtube, raiz, cfg, dia_pedido=3) == 0
    assert "Mateus" in youtube.videos[0][0]["title"] and "Dia 3 de 3" in youtube.videos[0][0]["title"]
    assert any(youtube.playlists[p][0].startswith("Novo Testamento") for p, _ in youtube.itens)


def test_etapas_de_audiolivro_pulam_no_modo_biblia(monkeypatch):
    import comum
    monkeypatch.setattr(comum, "carregar_config", lambda *a, **k: {"modo": "biblia"})
    assert comum.so_audiolivro("Extras") is True
    monkeypatch.setattr(comum, "carregar_config", lambda *a, **k: {})
    assert comum.so_audiolivro("Extras") is False


def test_acha_a_pasta_com_acento_do_mac(biblia_falsa):
    drive, youtube, raiz, cfg = biblia_falsa
    pasta = drive.achar(raiz, "Áudios")
    drive.itens[pasta["id"]]["name"] = unicodedata.normalize("NFD", "Áudios ")   # como o Mac envia
    assert biblia.rodar(drive, youtube, raiz, cfg, dry_run=True) == 0


def test_usa_as_artes_do_canal_e_a_tela_final(biblia_falsa, tmp_path):
    from PIL import Image
    from video import duracao_audio
    drive, youtube, raiz, cfg = biblia_falsa
    artes = drive.novo("Artes", raiz, PASTA)
    for nome, tam in (("fundo.png", (1920, 1080)), ("mini.png", (1280, 720)), ("tela.png", (1920, 1080))):
        arq = tmp_path / nome
        Image.new("RGB", tam, "#e8d9b5").save(arq)
        drive.novo(nome, artes, "image/png", local=arq)
    cfg["biblia"].update(fundo_video="Artes/fundo.png", tela_final="Artes/tela.png", tela_final_segundos=3,
                         miniatura={"fundo": "Artes/mini.png", "linha1": "Leitura em {total_dias} dias"})
    enviados = []
    original = youtube.enviar_video

    def enviar(video, snippet, status):
        enviados.append(duracao_audio(video))
        return original(video, snippet, status)
    youtube.enviar_video = enviar
    miniaturas = []
    youtube.definir_miniatura = lambda vid, img: miniaturas.append((vid, Image.open(img).size))
    assert biblia.rodar(drive, youtube, raiz, cfg) == 0
    assert enviados[0] >= 3 + 2 * 2 - 0.5          # leitura (2 capítulos de 2 s) + 3 s de tela final
    assert miniaturas == [("V1", (1280, 720))]

    # mudou o modelo da miniatura: o dia já publicado ganha a nova, sem reenviar o vídeo
    cfg["biblia"]["miniatura"]["linha2"] = "Canal de teste"
    estado = drive.ler_json(raiz, biblia.ARQ_ESTADO, {})
    estado["dias"]["1"]["data"] = "2000-01-01"
    drive.gravar_json(raiz, biblia.ARQ_ESTADO, estado)
    biblia.rodar(drive, youtube, raiz, cfg, dry_run=False, quantos=0)
    assert miniaturas[-1][0] == "V1" and len(youtube.videos) == 1


def test_textos_da_miniatura():
    import arte_biblia
    assert arte_biblia.textos_do_dia([("Gênesis", 1), ("Gênesis", 2), ("Gênesis", 3)]) == ("Gênesis", "Capítulos 1 a 3")
    assert arte_biblia.textos_do_dia([("Salmos", 23)]) == ("Salmos", "Salmo 23")
    assert arte_biblia.textos_do_dia([("Rute", 4), ("1 Samuel", 1), ("1 Samuel", 2)]) == (
        "Rute · 1 Samuel", "Rute 4 · 1 Samuel 1 e 2")


def test_divide_capitulo_em_partes_no_fim_da_frase():
    from cortar import Palavra
    from shorts_biblia import dividir_partes
    palavras, t = [], 0.0
    for i in range(120):   # 120 frases de 4 s (3 palavras + ponto final): 480 s
        for j, w in enumerate(["um", "dois", "tres."]):
            palavras.append(Palavra(w, t, t + 1.2))
            t += 1.333
    partes = dividir_partes(palavras, t, 175)
    assert len(partes) == 3 and partes[0][0] == 0 and abs(partes[-1][1] - t) < 0.01
    assert all(fim - ini <= 175 for ini, fim in partes)
    assert max(f - i for i, f in partes) - min(f - i for i, f in partes) < 20   # tamanhos parecidos
    fins_de_frase = [p.fim for p in palavras if p.texto.endswith(".")]
    assert all(any(f <= corte <= f + 0.2 for f in fins_de_frase) for _, corte in partes[:-1])
    assert dividir_partes(palavras[:10], 13.3, 175) == [(0.0, 13.3)]


def test_shorts_do_dia(biblia_falsa, tmp_path):
    from cortar import Palavra
    import shorts_biblia
    drive, youtube, raiz, cfg = biblia_falsa
    assert biblia.rodar(drive, youtube, raiz, cfg) == 0   # publica o dia 1
    cfg["biblia"]["shorts"] = {"ativo": True, "max_segundos": 1.5, "linha_rodape": "Canal"}
    falas = lambda cap, audio: [Palavra("Primeira.", 0.1, 0.9), Palavra("Segunda.", 1.0, 1.9)]
    estado = drive.ler_json(raiz, biblia.ARQ_ESTADO, {})
    conf = biblia.config(cfg)
    caps, _ = biblia.capitulos_da_biblia(drive, drive.achar(raiz, "Áudios")["id"])
    plano = [[c for c in caps if (c.livro, c.numero) in {tuple(x) for x in dia}] for dia in estado["plano"]]
    n = shorts_biblia.publicar_shorts(drive, youtube, raiz, cfg, conf, plano, estado, transcrever_fn=falas)
    assert n == 2 * len(plano[0])                                      # 2 partes por capítulo (2 s cada, máx. 1,5 s)
    shorts = [s for s, _ in youtube.videos if "Bíblia em Áudio" in s["title"] and "–" in s["title"]]
    assert shorts and "parte 1 de 2" in shorts[0]["title"] and "https://youtu.be/V1" in shorts[0]["description"]
    assert estado["shorts"]["1"]["completo"] is True
    assert shorts_biblia.publicar_shorts(drive, youtube, raiz, cfg, conf, plano, estado, transcrever_fn=falas) == 0


def test_arte_vertical(tmp_path):
    from PIL import Image
    from shorts_biblia import arte_vertical
    mini = tmp_path / "mini.png"
    Image.new("RGB", (1280, 720), "#e8d9b5").save(mini)
    arte = arte_vertical(mini, None, tmp_path / "v.png", 12, "Salmos", 23, 2, 3, "Canal")
    assert Image.open(arte).size == (1080, 1920)


def test_minutagem_com_encerramento_e_link_do_testamento():
    conf = biblia.config({})
    estado = {"playlists": {"at": "PLAT"}}
    v = biblia.campos(conf, 1, 365, _caps("Gênesis", 1, [1, 2, 3]), [0, 60, 120], estado, encerramento=200)
    assert "02:00 Gênesis 3\n03:20 Encerramento" in v["minutagem"]
    assert v["testamento"] == "Antigo Testamento" and v["link_testamento"].endswith("PLAT")


def test_arte_do_audiolivro_no_estilo_do_canal(tmp_path):
    from PIL import Image
    import arte_biblia
    fundo, capa = tmp_path / "fundo.png", tmp_path / "capa.jpg"
    Image.new("RGB", (1280, 720), "#efe3c8").save(fundo)
    Image.new("RGB", (600, 900), "#7fb8b0").save(capa)
    for (w, h), nome in (((1280, 720), "m.jpg"), ((1920, 1080), "a.png")):
        saida = arte_biblia.arte_audiolivro(fundo, capa, tmp_path / nome, "Um título bem comprido para quebrar linhas",
                                            "Autor", "Parte 1 · Caps. 1 a 5", w, h, rodape="Rodapé")
        assert Image.open(saida).size == (w, h)
    # sem capa também funciona (texto ocupa mais largura)
    assert arte_biblia.arte_audiolivro(fundo, None, tmp_path / "s.jpg", "Título", "", "").exists()
