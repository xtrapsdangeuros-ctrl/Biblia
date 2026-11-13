"""Críticas polêmicas (NotebookLM): sugestão, publicação e travas, com Drive e YouTube falsos."""

import json
import os
import subprocess

import cortar
import criticas
import main
from cortar import Palavra
from test_fluxo import FICHA, _args, _detectar_tres, ambiente, carregar_config_teste  # noqa: F401  (fixture)

NEUTRO = "Ele caminhou pela rua e olhou as casas, as árvores e o céu azul daquela manhã tranquila. " * 12
POLEMICO = ("Tadeu sentia um ciúme terrível de Lívia e desconfiava de traição com o amigo. "
            "Seria culpa dela ou apenas loucura dele? A morte do amigo trouxe mais segredo e mentira. ") * 8


def _palavras(texto, passo=0.4):
    return [Palavra(" " + w, i * passo, i * passo + passo * 0.8) for i, w in enumerate(texto.split())]


def _gravar_transcricoes(drive, livro, textos):
    pasta = drive.pasta(livro, "transcricoes")
    for numero, texto in textos.items():
        dados = [[p.texto, p.inicio, p.fim] for p in _palavras(texto)]
        drive.gravar_texto(pasta, f"{numero}.json", json.dumps(dados), "application/json")


def _publicar_os_tres(ambiente, monkeypatch, privacidade):
    drive, youtube, livro = ambiente
    ficha = drive.achar(livro, "ficha.txt")
    drive.itens[ficha["id"]]["texto"] = FICHA + f"privacidade: {privacidade}\n"
    cfg = carregar_config_teste()
    monkeypatch.setattr(cortar, "detectar", _detectar_tres)
    assert cortar.processar_drive(cfg["corte"]) == 0
    assert main.rodar_drive(_args(), cfg) == 0
    return drive, youtube, livro, cfg


def _cfg():
    cfg = carregar_config_teste()
    cfg["criticas"].update(ativo=True, sugestoes_por_execucao=3, publicar_por_dia=2, transcrever_por_execucao=0)
    return cfg


def test_vem_desligado_e_nao_mexe_em_nada(ambiente, monkeypatch):
    assert carregar_config_teste()["criticas"]["ativo"] is False
    drive, youtube, livro, cfg = _publicar_os_tres(ambiente, monkeypatch, "public")
    _gravar_transcricoes(drive, livro, {2: POLEMICO})
    antes, videos = len(drive.itens), len(youtube.videos)
    assert criticas.rodar(drive, youtube, _raiz(), cfg) == 0
    assert len(drive.itens) == antes and len(youtube.videos) == videos


def test_pasta_criticas_nao_vira_livro(ambiente):
    import livro as _livro
    drive, _, _ = ambiente
    drive.pasta(_raiz(), "Críticas")
    assert [p["name"] for p in _livro.pastas_de_livros(drive, _raiz())] == ["01 - Noite de Vigília"]


def _raiz():
    return os.environ["DRIVE_PASTA_RAIZ"]


def test_nota_polemica_separa_capitulo_quente_de_morno():
    nota_quente, temas = criticas.nota_polemica(POLEMICO)
    nota_morna, _ = criticas.nota_polemica(NEUTRO)
    assert nota_quente > 3 * max(nota_morna, 1)
    assert {"ciúme", "traição", "culpa", "morte", "loucura", "mentira"} <= set(temas)
    assert criticas.nota_polemica("curto demais")[0] == 0


def test_sugere_publica_e_nao_repete(ambiente, monkeypatch):
    drive, youtube, livro, _ = _publicar_os_tres(ambiente, monkeypatch, "public")
    _gravar_transcricoes(drive, livro, {1: NEUTRO, 2: POLEMICO, 3: NEUTRO})
    cfg = _cfg()

    assert criticas.rodar(drive, youtube, _raiz(), cfg, so="sugerir") == 0
    base = drive.achar(_raiz(), "Críticas")["id"]
    a_fazer = drive.achar(base, "A fazer")["id"]
    assert drive.nomes(a_fazer) == ["Noite de Vigília – Capítulo 2"]   # só o capítulo polêmico
    pasta = drive.achar(a_fazer, "Noite de Vigília – Capítulo 2")["id"]
    assert drive.nomes(pasta) == [criticas.ARQ_FONTE, criticas.ARQ_INSTRUCOES]
    instrucoes = drive.ler_texto(drive.achar(pasta, criticas.ARQ_INSTRUCOES)["id"])
    assert "Capítulo 2 – Da estrada" in instrucoes and "Noite de Vigília" in instrucoes and "ciúme" in instrucoes
    assert "{" not in instrucoes
    assert "Lívia" in drive.ler_texto(drive.achar(pasta, criticas.ARQ_FONTE)["id"])
    assert criticas.ARQ_COMO_FAZER in drive.nomes(base)

    # Sem áudio na pasta, nada é publicado; sugerir de novo não repete o capítulo.
    videos_antes = len(youtube.videos)
    assert criticas.rodar(drive, youtube, _raiz(), cfg) == 0
    assert len(youtube.videos) == videos_antes and drive.nomes(a_fazer) == ["Noite de Vigília – Capítulo 2"]

    # Você solta o áudio do NotebookLM na pasta: o robô publica e move a pasta.
    audio = drive.armazem / "notebooklm.m4a"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "6", "-i", "sine=frequency=300",
                    "-c:a", "aac", str(audio)], check=True)
    drive.novo("Noite de Vigília audio overview.m4a", pasta, "audio/mp4", local=audio)
    fala = _palavras("Um pombo pode ser síndico do prédio? Claro que não. E Lívia traiu Tadeu? Comenta aí!", 0.3)
    monkeypatch.setattr(cortar, "transcrever", lambda a, m: fala)
    assert criticas.rodar(drive, youtube, _raiz(), cfg, so="publicar") == 0

    snippet, status = youtube.videos[-1]
    assert snippet["title"] == "Um pombo pode ser síndico do prédio? | NOITE DE VIGÍLIA #audiolivro #shorts"
    assert "https://youtu.be/VID2" in snippet["description"] and "NotebookLM" in snippet["description"]
    assert "playlist?list=PL1" in snippet["description"].splitlines()[0]   # playlist logo na 1ª linha
    assert status == {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "containsSyntheticMedia": True}
    publicadas = drive.achar(base, "Publicadas")["id"]
    assert drive.nomes(a_fazer) == [] and drive.nomes(publicadas) == ["Noite de Vigília – Capítulo 2"]
    estado = drive.ler_json(base, "criticas.json", {})
    assert [r["video_id"] for r in estado["publicadas"].values()] == [f"VID{len(youtube.videos)}"]

    total = len(youtube.videos)
    assert criticas.rodar(drive, youtube, _raiz(), cfg) == 0
    assert len(youtube.videos) == total


def test_livro_privado_nao_recebe_sugestao(ambiente, monkeypatch):
    drive, youtube, livro, _ = _publicar_os_tres(ambiente, monkeypatch, "private")
    _gravar_transcricoes(drive, livro, {2: POLEMICO})
    assert criticas.rodar(drive, youtube, _raiz(), _cfg(), so="sugerir") == 0
    base = drive.achar(_raiz(), "Críticas")
    assert base is None or drive.achar(base["id"], "A fazer") is None   # livro privado não recebe sugestão


def test_recortar_termina_em_fim_de_frase():
    palavras = _palavras("Primeira frase longa aqui. Segunda frase também. Terceira que não termina", 10)
    trecho = criticas.recortar(palavras, 75)
    assert trecho[-1].texto.strip() == "também." and trecho[-1].fim <= 75


def test_titulo_sem_pergunta_usa_o_padrao():
    ficha = {"titulo": "Noite de Vigília"}
    assert criticas.titulo_critica(_palavras("Nada de pergunta aqui."), ficha, "Capítulo 2") == \
        "POLÊMICA EM NOITE DE VIGÍLIA (Capítulo 2): e você, concorda? #audiolivro #shorts"
    assert criticas.titulo_critica([], ficha, "Capítulo 2", "Lívia é inocente?\n") == \
        "Lívia é inocente? #audiolivro #shorts"
    # pergunta comprida demais para título: tenta a próxima
    fala = _palavras("Será que tudo isso que aconteceu naquele capítulo enorme faz algum sentido para alguém aqui hoje? "
                     "Lívia traiu?")
    assert criticas.titulo_critica(fala, {"titulo": "01 - Noite de Vigília"}, "Capítulo 2").startswith("Lívia traiu? | NOITE")


def test_dry_run_nao_cria_nada(ambiente, monkeypatch):
    drive, youtube, livro, _ = _publicar_os_tres(ambiente, monkeypatch, "public")
    _gravar_transcricoes(drive, livro, {2: POLEMICO})
    antes = len(drive.itens)
    assert criticas.rodar(drive, youtube, _raiz(), _cfg(), dry_run=True) == 0
    assert len(drive.itens) == antes and drive.achar(_raiz(), "Críticas") is None


def test_audio_longo_e_cortado_no_fim_de_frase(tmp_path, monkeypatch):
    import subprocess as sp
    audio = tmp_path / "longo.wav"
    sp.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", "12", "-i", "sine=frequency=300", str(audio)], check=True)
    fala = _palavras("Primeira frase aqui. Segunda frase bem aqui. Terceira frase que passa do limite e continua", 0.5)
    cfg = carregar_config_teste()
    cfg["criticas"]["limite_segundos"] = 6
    video, trecho, duracao = criticas.montar_video(audio, None, {"titulo": "Teste"}, "Capítulo 1", cfg, tmp_path, fala)
    assert video.exists() and trecho[-1].texto.strip() == "aqui." and duracao <= 6


def test_titulo_pula_a_abertura_absurda():
    fala = _palavras("O pombo quer ser síndico do prédio? Quer sim. " + "bla " * 30 +
                     "Então a pergunta é: e se o vilão for o narrador? Pensa comigo.", 0.4)
    titulo = criticas.titulo_critica(fala, {"titulo": "Noite de Vigília"}, "Capítulo 62")
    assert titulo == "E se o vilão for o narrador? | NOITE DE VIGÍLIA #audiolivro #shorts"


def test_hashtags_sem_cerquilha_dobrada():
    texto = criticas.descricao_critica({"titulo": "Noite de Vigília", "autor": "Aurélio Vasconcelos"}, "Capítulo 1",
                                       None, None, {})
    assert "##" not in texto and "#Shorts" in texto


def test_instrucoes_dao_a_briga_pronta():
    cfg = carregar_config_teste()
    texto = criticas.instrucoes(cfg["criticas"]["prompt"], "Noite de Vigília", "Aurélio Vasconcelos", "Capítulo 2",
                                ["ciúme"], ["Tadeu", "Lívia"])
    assert "{" not in texto
    assert criticas.BRIGAS["ciúme"][0] in texto and criticas.BRIGAS["ciúme"][1] in texto
    assert criticas.BRIGAS["ciúme"][2] in texto and "Tadeu, Lívia" in texto and "derrapar até ciúme" in texto
    # sem tema conhecido: briga padrão "quem é o verdadeiro vilão"
    assert criticas.BRIGA_PADRAO[2] in criticas.instrucoes(cfg["criticas"]["prompt"], "L", "", "Capítulo 1", [])


def test_personagens_ignora_comeco_de_frase():
    texto = ("Tadeu viu Lívia. Ela sorriu para Valério e Lívia riu. Depois disse Lívia que sim. "
             "Então Valério saiu, e Valério voltou com Valério pai. Deus sabe.")
    assert criticas.personagens(texto) == ["Valério", "Lívia"]
