"""Fluxo completo com Drive e YouTube falsos (sem rede)."""

import json
import shutil
import subprocess
from argparse import Namespace
from pathlib import Path

import pytest
from PIL import Image

import cortar
import google_api
import livro as _livro  # noqa: F401  (importar antes de trocar google_api.Drive pelo falso)
import main
from comum import carregar_config
from cortar import CapituloCortado

PASTA = google_api.PASTA_MIME


class DriveFalso:
    def __init__(self, armazem: Path):
        self.itens = {}   # id -> {id, name, mimeType, modifiedTime, pai, local}
        self.seq = 0
        self.armazem = armazem

    def novo(self, nome, pai, mime="audio/mpeg", local=None, texto=None):
        self.seq += 1
        item = {"id": f"id{self.seq}", "name": nome, "mimeType": mime, "modifiedTime": "t1", "pai": pai,
                "local": local, "texto": texto}
        self.itens[item["id"]] = item
        return item["id"]

    def listar(self, pasta_id):
        return sorted((dict(i) for i in self.itens.values() if i["pai"] == pasta_id), key=lambda i: i["name"])

    eh_pasta = staticmethod(google_api.Drive.eh_pasta)

    def achar(self, pasta_id, nome):
        return next((i for i in self.listar(pasta_id) if i["name"] == nome), None)

    def pasta(self, pai_id, nome):
        achado = self.achar(pai_id, nome)
        return achado["id"] if achado else self.novo(nome, pai_id, PASTA)

    def baixar(self, arquivo_id, destino):
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.itens[arquivo_id]["local"], destino)
        return destino

    def ler_texto(self, arquivo_id, google_doc=False):
        return self.itens[arquivo_id]["texto"]

    def enviar(self, origem, pasta_id, nome=None, mime=None):
        guardado = self.armazem / f"{self.seq}_{origem.name}"
        shutil.copy(origem, guardado)
        return self.novo(nome or origem.name, pasta_id, local=guardado)

    def gravar_texto(self, pasta_id, nome, conteudo, mime="text/plain"):
        existente = self.achar(pasta_id, nome)
        if existente:
            self.itens[existente["id"]]["texto"] = conteudo
        else:
            self.novo(nome, pasta_id, mime, texto=conteudo)

    def ler_json(self, pasta_id, nome, padrao):
        item = self.achar(pasta_id, nome)
        return json.loads(item["texto"]) if item else padrao

    def gravar_json(self, pasta_id, nome, dados):
        self.gravar_texto(pasta_id, nome, json.dumps(dados))

    def mover(self, arquivo_id, de_pasta, para_pasta):
        self.itens[arquivo_id]["pai"] = para_pasta

    def lixeira(self, arquivo_id):
        del self.itens[arquivo_id]

    def nomes(self, pasta_id):
        return [i["name"] for i in self.listar(pasta_id)]


class YouTubeFalso:
    def __init__(self):
        self.videos = []

    def enviar_video(self, video, snippet, status):
        assert video.exists() and video.stat().st_size > 0
        self.videos.append((snippet, status))
        return f"VID{len(self.videos)}"

    def definir_miniatura(self, video_id, imagem):
        assert imagem.exists()

    def criar_playlist(self, titulo, descricao, privacidade="private"):
        return "PL1"

    def adicionar_na_playlist(self, playlist_id, video_id):
        pass


FICHA = """titulo: Noite de Vigília
autor: Aurélio Vasconcelos
licenca: dominio_publico
fonte_texto: edição de 1907
total_capitulos: 3
"""


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    drive, youtube = DriveFalso(tmp_path), YouTubeFalso()
    raiz = drive.novo("Audiolivros", None, PASTA)
    livro = drive.novo("01 - Noite de Vigília", raiz, PASTA)
    capa = tmp_path / "capa.jpg"
    Image.new("RGB", (400, 600), "#335").save(capa)
    audio = tmp_path / "livro completo.mp3"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "9", "-i", "sine=frequency=440",
                    "-c:a", "libmp3lame", str(audio)], check=True)
    drive.novo("ficha.txt", livro, "text/plain", texto=FICHA)
    drive.novo("capa.jpg", livro, "image/jpeg", local=capa)
    drive.novo(audio.name, livro, local=audio)

    monkeypatch.setenv("DRIVE_PASTA_RAIZ", raiz)
    monkeypatch.setattr(google_api, "credenciais_do_ambiente", lambda: None)
    monkeypatch.setattr(google_api, "Drive", lambda cred: drive)
    monkeypatch.setattr(google_api, "YouTube", lambda cred: youtube)
    return drive, youtube, livro


def _detectar_tres(audio, cfg):
    return [CapituloCortado(1, "Da chegada", 0, 3), CapituloCortado(2, "Da estrada", 3, 6),
            CapituloCortado(3, "", 6, 9)], "teste"


def carregar_config_teste():
    cfg = carregar_config()
    cfg["publicacao"]["livros"] = []
    cfg["publicacao"]["minutos_por_video"] = 0   # testes antigos: um capítulo por vídeo
    cfg["cta"] = {}
    cfg["video"]["cta"] = ""
    return cfg


def _args(**kw):
    return Namespace(**{"dry_run": False, "livro": None, "capitulo": None, "quantos": None, **kw})


def test_corta_e_publica_um_por_dia(ambiente, monkeypatch):
    drive, youtube, livro = ambiente
    cfg = carregar_config_teste()
    monkeypatch.setattr(cortar, "detectar", _detectar_tres)

    # Antes do corte, nada é publicado (evita publicar fora de ordem).
    assert main.rodar_drive(_args(), cfg) == 0 and youtube.videos == []

    assert cortar.processar_drive(cfg["corte"]) == 0
    assert "livro completo.mp3" not in drive.nomes(livro)
    caps = drive.achar(livro, "capitulos")["id"]
    assert drive.nomes(caps) == ["01 - Da chegada.mp3", "02 - Da estrada.mp3", "03.mp3"]
    assert drive.nomes(drive.achar(livro, "originais")["id"]) == ["livro completo.mp3"]

    for _ in range(4):
        assert main.rodar_drive(_args(), cfg) == 0
    titulos = [s["title"] for s, _ in youtube.videos]
    assert titulos == ["AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 1: Da chegada | Aurélio Vasconcelos",
                       "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 2: Da estrada | Aurélio Vasconcelos",
                       "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 3 | Aurélio Vasconcelos"]
    assert "youtu.be/VID1" in youtube.videos[1][0]["description"]
    assert all(status["privacyStatus"] == "private" for _, status in youtube.videos)
    estado = drive.ler_json(livro, "publicados.json", {})
    assert estado["playlist_id"] == "PL1" and set(estado["capitulos"]) == {"1", "2", "3"}


def test_corte_barrado_nao_publica_e_avisa(ambiente, monkeypatch):
    drive, youtube, livro = ambiente
    cfg = carregar_config_teste()
    monkeypatch.setattr(cortar, "detectar", lambda a, c: ([CapituloCortado(1, "", 0, 4), CapituloCortado(2, "", 4, 9)], "teste"))

    assert cortar.processar_drive(cfg["corte"]) == 1  # ficha diz 3 capítulos, achou 2
    erro = drive.achar(livro, "ERRO - livro completo.txt")
    assert erro and "a ficha diz que o livro tem 3" in erro["texto"]
    assert "livro completo.mp3" in drive.nomes(livro)

    # No dia seguinte o mesmo arquivo não é reprocessado e nada é publicado.
    assert cortar.processar_drive(cfg["corte"]) == 0
    assert main.rodar_drive(_args(), cfg) == 0 and youtube.videos == []


def test_ficha_sem_fonte_bloqueia(ambiente):
    drive, youtube, livro = ambiente
    ficha = drive.achar(livro, "ficha.txt")
    drive.itens[ficha["id"]]["texto"] = FICHA.replace("fonte_texto: edição de 1907\n", "")
    audio = drive.achar(livro, "livro completo.mp3")
    drive.itens[audio["id"]]["name"] = "01 - Começo.mp3"
    assert main.rodar_drive(_args(), carregar_config_teste()) == 1
    assert youtube.videos == []


def test_partes_a_b_viram_um_video(ambiente, tmp_path):
    drive, youtube, livro = ambiente
    original = drive.achar(livro, "livro completo.mp3")
    for nome in ["Pasta02_001-Segundo.mp3", "Pasta01_002-Primeiro B.mp3", "Pasta01_001-Primeiro A.mp3"]:
        drive.novo(nome, livro, local=drive.itens[original["id"]]["local"])
    drive.lixeira(original["id"])
    ficha = drive.achar(livro, "ficha.txt")
    drive.lixeira(ficha["id"])   # sem ficha: título vem do nome da pasta

    cfg = carregar_config_teste()
    assert main.rodar_drive(_args(), cfg) == 0
    snippet, status = youtube.videos[0]
    assert snippet["title"] == "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 1: Primeiro"   # sem o "01 - " da pasta
    assert "Cópia privada para uso pessoal" in snippet["description"] and status["privacyStatus"] == "private"
    estado = drive.ler_json(livro, "publicados.json", {})
    assert estado["capitulos"]["1"]["arquivos"] == ["Pasta01_001-Primeiro A.mp3", "Pasta01_002-Primeiro B.mp3"]


def test_livro_dominio_publico_sai_publico(ambiente, monkeypatch):
    drive, youtube, livro = ambiente
    ficha = drive.achar(livro, "ficha.txt")
    drive.itens[ficha["id"]]["texto"] = FICHA + "privacidade: public\n"
    audio = drive.achar(livro, "livro completo.mp3")
    drive.itens[audio["id"]]["name"] = "01 - Começo.mp3"
    assert main.rodar_drive(_args(), carregar_config_teste()) == 0
    assert youtube.videos[0][1]["privacyStatus"] == "public"


def test_para_limpo_no_limite_diario(ambiente, monkeypatch):
    from googleapiclient.errors import HttpError

    drive, youtube, livro = ambiente
    audio = drive.achar(livro, "livro completo.mp3")
    for n in (1, 2, 3, 4):
        drive.novo(f"0{n} - Cap {n}.mp3", livro, local=drive.itens[audio["id"]]["local"])
    drive.lixeira(audio["id"])
    original = youtube.enviar_video

    def enviar(video, snippet, status):
        if len(youtube.videos) == 2:
            resp = type("R", (), {"status": 403, "reason": "Forbidden"})()
            erro = HttpError(resp, b'{"error":{"errors":[{"reason":"uploadLimitExceeded"}]}}')
            if erro.resp.status in (400, 403, 429):
                raise google_api.LimiteDiario("uploadLimitExceeded") from erro
        return original(video, snippet, status)

    monkeypatch.setattr(youtube, "enviar_video", enviar)
    assert main.rodar_drive(_args(quantos=0), carregar_config_teste()) == 0
    assert len(youtube.videos) == 2
    assert set(drive.ler_json(livro, "publicados.json", {})["capitulos"]) == {"1", "2"}


def test_alternado_entre_livros(ambiente):
    drive, youtube, livro = ambiente
    raiz = drive.itens[livro]["pai"]
    local = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    for n in (1, 2, 3):
        drive.novo(f"0{n} - A{n}.mp3", livro, local=local)
    outro = drive.novo("02 - Outro Livro", raiz, PASTA)
    for n in (1, 2):
        drive.novo(f"0{n} - B{n}.mp3", outro, local=local)
    incompleto = drive.novo("03 - Subindo", raiz, PASTA)
    for n in (1, 3):
        drive.novo(f"0{n} - C{n}.mp3", incompleto, local=local)

    cfg = carregar_config_teste()
    cfg["publicacao"].update(modo="alternado", capitulos_por_dia=4)
    assert main.rodar_drive(_args(), cfg) == 0
    titulos = [s["title"].split(" | ")[0] for s, _ in youtube.videos]
    assert titulos == ["AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 1: A1", "AUDIOLIVRO OUTRO LIVRO – CAP. 1: B1",
                       "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 2: A2", "AUDIOLIVRO OUTRO LIVRO – CAP. 2: B2"]


def test_reaplica_ficha_nos_videos_publicados(ambiente):
    import atualizar

    drive, youtube, livro = ambiente
    local = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    for n in (1, 2, 3):
        drive.novo(f"0{n} - Cap {n}.mp3", livro, local=local)
    cfg = carregar_config_teste()
    assert main.rodar_drive(_args(quantos=0), cfg) == 0

    ficha = drive.achar(livro, "ficha.txt")
    drive.itens[ficha["id"]]["texto"] = FICHA + "descricao: Sinopse nova e caprichada.\ntags: [tadeu, lívia]\n"
    youtube.atualizados = []
    youtube.atualizar_metadados = lambda vid, snip: youtube.atualizados.append((vid, snip))

    pasta = {"id": livro, "name": drive.itens[livro]["name"]}
    assert atualizar.atualizar_livro(drive, youtube, pasta, cfg, dry_run=False, forcar=False) == 0
    assert [v for v, _ in youtube.atualizados] == ["VID1", "VID2", "VID3"]
    snip = youtube.atualizados[1][1]
    assert "Sinopse nova e caprichada." in snip["description"] and "youtu.be/VID1" in snip["description"]
    assert "lívia" in snip["tags"] and snip["categoryId"]

    youtube.atualizados.clear()   # segunda vez não repete...
    atualizar.atualizar_livro(drive, youtube, pasta, cfg, dry_run=False, forcar=False)
    assert youtube.atualizados == []
    atualizar.atualizar_livro(drive, youtube, pasta, cfg, dry_run=False, forcar=True)   # ...a não ser forçando
    assert len(youtube.atualizados) == 3


def test_livro_pausado_no_config_nao_publica(ambiente):
    drive, youtube, livro = ambiente
    local = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    drive.novo("01 - Cap 1.mp3", livro, local=local)
    cfg = carregar_config_teste()
    cfg["publicacao"]["pausados"] = ["noite de vigília"]
    assert main.rodar_drive(_args(), cfg) == 0 and youtube.videos == []



def test_video_longo_junta_capitulos_com_tempos(ambiente):
    """Vários capítulos curtos viram um vídeo só, com os tempos de cada um na descrição."""
    drive, youtube, livro = ambiente
    curto = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    for nome in ("01 - Da chegada.mp3", "02 - Da estrada.mp3", "03 - O recado.mp3"):
        drive.novo(nome, livro, local=curto)
    ficha = drive.achar(livro, "ficha.txt")   # livro de nome curto: a faixa de capítulos cabe nos 70 caracteres
    drive.itens[ficha["id"]]["texto"] = FICHA.replace("titulo: Noite de Vigília", "titulo: O Farol")
    cfg = carregar_config_teste()
    cfg["publicacao"]["minutos_por_video"] = 120
    cfg["cta"] = {"topo": "Inscreva-se!", "fim": ["Canal: {canal}"], "canal": "https://y/@c"}
    assert main.rodar_drive(_args(), cfg) == 0
    assert len(youtube.videos) == 1
    snippet, status = youtube.videos[0]
    assert snippet["title"] == "AUDIOLIVRO O FAROL – PARTE 1 (Caps. 1 a 3) | Aurélio Vasconcelos"
    desc = snippet["description"]
    assert "Capítulos neste vídeo:\n00:00 Cap. 1: Da chegada\n" in desc and "Cap. 3: O recado" in desc
    assert "Inscreva-se!" in desc and "Canal: https://y/@c" in desc
    estado = drive.ler_json(livro, "publicados.json", {})
    regs = [estado["capitulos"][n] for n in "123"]
    assert len({r["video_id"] for r in regs}) == 1 and [r["parte"] for r in regs] == [1, 1, 1]
    assert regs[0]["inicio"] == 0 and 0 < regs[1]["inicio"] < regs[2]["inicio"]
    # segunda execução no mesmo dia não publica mais nada (não há pendentes) nem repete
    assert main.rodar_drive(_args(), cfg) == 0 and len(youtube.videos) == 1


def test_capitulo_longo_vai_sozinho(ambiente):
    drive, youtube, livro = ambiente
    curto = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    for nome in ("01 - Da chegada.mp3", "02 - Da estrada.mp3"):
        drive.novo(nome, livro, local=curto)
    cfg = carregar_config_teste()
    cfg["publicacao"]["minutos_por_video"] = 0.001   # menor que qualquer capítulo
    assert main.rodar_drive(_args(quantos=0), cfg) == 0
    assert [s["title"] for s, _ in youtube.videos] == ["AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 1: Da chegada | Aurélio Vasconcelos",
                                                       "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 2: Da estrada | Aurélio Vasconcelos"]


def test_reaplica_ficha_em_video_longo(ambiente):
    import atualizar
    drive, youtube, livro = ambiente
    curto = drive.itens[drive.achar(livro, "livro completo.mp3")["id"]]["local"]
    drive.lixeira(drive.achar(livro, "livro completo.mp3")["id"])
    for nome in ("01 - Da chegada.mp3", "02 - Da estrada.mp3"):
        drive.novo(nome, livro, local=curto)
    cfg = carregar_config_teste()
    cfg["publicacao"]["minutos_por_video"] = 120
    main.rodar_drive(_args(), cfg)
    atualizados = []
    youtube.atualizar_metadados = lambda vid, sn: atualizados.append((vid, sn))
    pasta = {"id": livro, "name": drive.itens[livro]["name"]}
    assert atualizar.atualizar_livro(drive, youtube, pasta, cfg, False, True) == 0
    assert len(atualizados) == 1 and "PARTE 1" in atualizados[0][1]["title"]
    assert "Capítulos neste vídeo:" in atualizados[0][1]["description"]


def test_execucao_de_reserva_avisa_que_o_dia_ja_foi_feito(ambiente, monkeypatch, tmp_path):
    drive, youtube, livro = ambiente
    monkeypatch.setattr(cortar, "detectar", _detectar_tres)
    cortar.processar_drive(carregar_config_teste()["corte"])
    cfg = carregar_config_teste()
    cfg["publicacao"]["capitulos_por_dia"] = 1
    saida = tmp_path / "saida_actions"
    monkeypatch.setenv("GITHUB_OUTPUT", str(saida))
    assert main.rodar_drive(_args(), cfg) == 0 and len(youtube.videos) == 1
    assert not saida.exists()                                   # 1ª execução: trabalhou normalmente
    assert main.rodar_drive(_args(), cfg) == 0 and len(youtube.videos) == 1
    assert saida.read_text() == "ja_feito=true\n"               # reserva: pula os passos pesados
