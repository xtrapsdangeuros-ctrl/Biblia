"""Modo discreto (src/discreto.py) e configuração do canal fora do código (canal.yaml)."""

import json
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import comum
import discreto

RAIZ = Path(__file__).resolve().parent.parent

# Tudo inventado: se qualquer um destes aparecer na tela, o modo discreto falhou.
NOMES_FALSOS = {
    "pasta": "Zumbarato Ferrolho Quelvim Ortiga (Saga do Vento Pardo Vol. 2)",
    "titulo": "Quelvim Ortiga",
    "autor": "Zumbarato Ferrolho",
    "arquivo": "Quelvim completo narrado.mp3",
    "capitulo": "Xeropântano Sombrio",
    "videos": ["VIDzq9Kx31a", "VIDzq9Kx31b", "VIDzq9Kx31c", "VIDzq9Kx31d"],
    "playlist": "PLfalsoQwertyAsdf",
    "link_canal": "https://www.youtube.com/@canalFalsoXyzzy?sub_confirmation=1",
    "texto_canal": "Canal Falso Xyzzy: histórias inventadas todo dia",
    "link_video": "https://youtu.be/VIDzq9Kx31a",
}


@pytest.fixture
def modo(monkeypatch):
    monkeypatch.setenv("ROBO_DISCRETO", "1")
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    discreto._reg.limpar()
    yield
    discreto._reg.limpar()


def _registro(msg, *args, exc_info=None):
    return logging.LogRecord("audiolivro", logging.INFO, __file__, 1, msg, args, exc_info)


# ---------------------------------------------------------------- filtro do log

def test_valores_viram_rotulos_e_o_resto_fica_oculto(modo):
    discreto.registrar_livros([{"name": "Livro Secreto Um", "id": "idPastaSecreta1", "createdTime": "1"},
                               {"name": "Livro Secreto Dois", "id": "idPastaSecreta2", "createdTime": "2"}])
    discreto.registrar("VIDsecreto01", "vídeo")
    texto = discreto.mensagem_neutra(_registro("'%s' capítulo %d: %s (%s, %s)", "Livro Secreto Dois", 12,
                                               "VIDsecreto01", "Um título qualquer", "private"))
    assert texto == "livro 2 capítulo 12: vídeo 1 (‹…›, private)"


def test_links_canais_e_erros_nao_aparecem(modo):
    erro = ValueError("arquivo 'Livro Secreto.mp3' não existe")
    texto = discreto.mensagem_neutra(_registro("Veja https://youtu.be/abc e @meuCanal: %s", erro))
    assert texto == "Veja ‹link› e ‹canal›: ValueError"
    try:
        raise RuntimeError("Livro Secreto")
    except RuntimeError:
        com_tb = discreto.mensagem_neutra(_registro("deu ruim", exc_info=sys.exc_info()))
    assert "Livro Secreto" not in com_tb and "RuntimeError" in com_tb and "relatório" in com_tb


def test_ficha_registra_titulo_e_autor_sozinhos(modo):
    discreto.registrar_livros([{"name": "Zumbarato Ferrolho Quelvim Ortiga", "id": "x" * 20}])
    discreto.registrar_ficha("Zumbarato Ferrolho Quelvim Ortiga",
                             {"titulo": "Quelvim Ortiga", "autor": "Zumbarato Ferrolho", "licenca": "proprio"})
    texto = discreto.limpar("Quelvim Ortiga, de Zumbarato Ferrolho (proprio)")
    assert texto == "título do livro 1, de autor do livro 1 (proprio)"


def test_palavras_tecnicas_nao_sao_escondidas(modo):
    """'public' ou 'dominio_publico' na ficha não podem virar máscara (o log inteiro ficaria cheio de ***)."""
    discreto.registrar_dados({"privacidade": "public", "licenca": "dominio_publico", "capa": "capa.jpg"})
    assert discreto._reg.rotulos == {}


def test_fora_do_github_mostra_tudo(monkeypatch):
    monkeypatch.delenv("ROBO_DISCRETO", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert not discreto.ativo()
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert discreto.ativo()
    monkeypatch.setenv("ROBO_DISCRETO", "0")
    assert not discreto.ativo()


def test_mascara_do_github_para_valores_sensiveis(modo, monkeypatch, capfd):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    discreto.registrar("Nome Secreto do Livro", "livro")
    discreto.registrar("Nome Secreto do Livro", "livro")   # uma vez só
    assert capfd.readouterr().out.count("::add-mask::Nome Secreto do Livro\n") == 1


def test_entrada_do_run_workflow_e_numero_do_livro(modo, monkeypatch, tmp_path):
    evento = tmp_path / "evento.json"
    evento.write_text(json.dumps({"inputs": {"livro": "3", "atualizar_livro": "Livro Secreto"}}))
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(evento))
    assert discreto.resolver("@entrada:livro") == "3"
    assert discreto.resolver("@entrada:nao_existe") == ""
    assert discreto.resolver("texto normal") == "texto normal"
    assert discreto.resolver("@entrada:atualizar_livro") == "Livro Secreto"
    assert discreto.limpar("Livro Secreto") != "Livro Secreto"   # o que foi digitado também fica escondido

    from livro import pedido_casa
    pastas = [{"name": f"Livro {c}", "id": f"id{c}" * 5, "createdTime": str(i)} for i, c in enumerate("ABC")]
    discreto.registrar_livros(pastas)
    assert [pedido_casa("3", p["name"]) for p in pastas] == [False, False, True]
    assert [pedido_casa("livro 1", p["name"]) for p in pastas] == [True, False, False]
    assert [pedido_casa("Livro B", p["name"], exato=True) for p in pastas] == [False, True, False]


def test_relatorio_tem_os_nomes_e_a_legenda(modo):
    discreto.registrar_livros([{"name": "Livro Secreto Um", "id": "idPastaSecreta1"}])
    discreto.anexar("Analytics", "linha com Livro Secreto Um")
    texto = discreto.texto_relatorio()
    assert "livro 1: Livro Secreto Um" in texto and "linha com Livro Secreto Um" in texto
    discreto._rel.secoes.clear()


# ---------------------------------------------------------------- fluxo completo com dados falsos

def test_fluxo_completo_nao_mostra_nenhum_nome_falso(tmp_path):
    relatorio = tmp_path / "relatorio.txt"
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST", "GITHUB_", "DRIVE_", "GOOGLE_"))}
    env.update(ROBO_DISCRETO="1", GITHUB_ACTIONS="true", ROBO_RELATORIO_ARQUIVO=str(relatorio),
               ROBO_SEM_CANAL_LOCAL="1", NOMES_FALSOS=json.dumps(NOMES_FALSOS), PYTHONIOENCODING="utf-8")
    pasta = tmp_path / "dados"
    pasta.mkdir()
    feito = subprocess.run([sys.executable, str(RAIZ / "tests" / "aux_fluxo_discreto.py"), str(pasta)],
                           capture_output=True, text=True, env=env, timeout=300)
    saida = feito.stdout + feito.stderr
    mascaras = [l for l in saida.splitlines() if l.startswith("::add-mask::")]
    tela = "\n".join(l for l in saida.splitlines() if not l.startswith("::add-mask::"))   # o GitHub não mostra

    assert feito.returncode == 1, saida   # o erro final (de propósito) termina com falha
    sensiveis = [NOMES_FALSOS[k] for k in ("pasta", "titulo", "autor", "arquivo", "capitulo", "playlist",
                                           "link_canal", "texto_canal", "link_video")] + NOMES_FALSOS["videos"]
    sensiveis += ["Quelvim", "Zumbarato", "Xeropântano", "canalFalsoXyzzy", "VIDzq9Kx31"]
    vazou = [s for s in sensiveis if s in tela]
    assert not vazou, f"apareceu na tela: {vazou}\n{tela}"

    # A tela continua útil: diz o que aconteceu, com rótulos neutros.
    assert "Publicando livro 1 a partir do capítulo 1" in tela
    assert "Vídeo enviado: vídeo 1" in tela
    assert "Erro: RuntimeError" in tela and "relatório" in tela
    assert "Traceback" not in tela
    # O GitHub recebe as máscaras dos valores sensíveis (proteção extra).
    assert f"::add-mask::{NOMES_FALSOS['pasta']}" in mascaras

    # O relatório (que no GitHub vai para o Drive) tem tudo, com a legenda dos rótulos.
    completo = relatorio.read_text(encoding="utf-8")
    assert f"livro 1: {NOMES_FALSOS['pasta']}" in completo
    assert "Traceback" in completo and f"Falha final em {NOMES_FALSOS['pasta']}" in completo
    assert "nao existe.mp3" in completo   # erro do ffmpeg
    assert f"Arquivo do dia: {NOMES_FALSOS['arquivo']}" in completo


# ---------------------------------------------------------------- canal.yaml por cima do config.yaml

def test_mesclar_dicionarios_e_trocar_listas():
    base = {"cta": {}, "video": {"cta": "", "largura": 1920}, "publicacao": {"pausados": ["a"], "modo": "x"}}
    canal = {"cta": {"canal": "c"}, "video": {"cta": "Frase"}, "publicacao": {"pausados": ["b"]}}
    assert comum.mesclar(base, canal) == {"cta": {"canal": "c"}, "video": {"cta": "Frase", "largura": 1920},
                                          "publicacao": {"pausados": ["b"], "modo": "x"}}
    assert base["video"]["cta"] == ""   # não mexe no original


def test_config_do_repositorio_e_generico():
    cfg = comum.carregar_config(canal=False)
    assert cfg["cta"] == {} and cfg["video"]["cta"] == ""
    assert cfg["publicacao"]["pausados"] == [] and cfg["publicacao"]["livros"] == []
    assert cfg["seo"]["titulos_protegidos"] == []
    texto = (RAIZ / "config.yaml").read_text(encoding="utf-8")
    assert "youtube.com/@" not in texto and "youtu.be" not in texto


def test_sem_canal_yaml_funciona_como_antes(monkeypatch):
    monkeypatch.setenv("ROBO_SEM_CANAL_LOCAL", "1")
    monkeypatch.setattr(comum, "canal_do_drive", lambda: None)
    monkeypatch.delenv("ROBO_CANAL", raising=False)
    cfg = comum.carregar_config()
    assert cfg["publicacao"]["capitulos_por_dia"] > 0 and cfg["cta"] == {}


def test_canal_yaml_local_e_do_drive(monkeypatch, tmp_path, modo):
    monkeypatch.setenv("ROBO_SEM_CANAL_LOCAL", "1")
    local = tmp_path / "canal.yaml"
    local.write_text(yaml.safe_dump({"cta": {"canal": "https://y/@local"}, "publicacao": {"pausados": ["P1"]},
                                     "video": {"cta": "Frase local"}}), encoding="utf-8")
    monkeypatch.setenv("ROBO_CANAL", str(local))
    monkeypatch.setattr(comum, "canal_do_drive", lambda: {"video": {"cta": "Frase do Drive"},
                                                         "seo": {"titulos_protegidos": ["VIDprotegid"]},
                                                         "metadados": {"autores_conhecidos": ["Autora Inventada"]}})
    import metadados
    antes = metadados.AUTORES_CONHECIDOS
    try:
        cfg = comum.carregar_config()
        assert cfg["video"]["cta"] == "Frase do Drive"             # o Drive vale por último
        assert cfg["cta"]["canal"] == "https://y/@local"
        assert cfg["publicacao"]["pausados"] == ["P1"]
        assert cfg["video"]["largura"] == 1920                     # o resto do config.yaml continua
        assert metadados.AUTORES_CONHECIDOS == ("Autora Inventada",)
        assert re.fullmatch(r"vídeo 1 / texto do canal \d+", discreto.limpar("VIDprotegid / Frase do Drive"))
    finally:
        metadados.AUTORES_CONHECIDOS = antes


def test_canal_do_drive_e_lido_da_pasta_raiz(monkeypatch):
    class DriveFalso:
        def __init__(self, cred):
            pass

        def achar(self, pasta, nome):
            return {"id": "c1"} if (pasta, nome) == ("RAIZ", "canal.yaml") else None

        def ler_texto(self, arquivo_id):
            return "cta:\n  canal: https://y/@drive\n"

    import google_api
    monkeypatch.setenv("DRIVE_PASTA_RAIZ", "RAIZ")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "x")
    monkeypatch.setattr(google_api, "Drive", DriveFalso)
    monkeypatch.setattr(google_api, "credenciais_do_ambiente", lambda: None)
    monkeypatch.setattr(comum, "_cache_canal", {})
    assert comum.canal_do_drive() == {"cta": {"canal": "https://y/@drive"}}


def test_canal_yaml_quebrado_para_o_robo(monkeypatch, tmp_path):
    local = tmp_path / "canal.yaml"
    local.write_text("cta: [sem fechar", encoding="utf-8")
    monkeypatch.setenv("ROBO_CANAL", str(local))
    monkeypatch.setattr(comum, "canal_do_drive", lambda: None)
    with pytest.raises(SystemExit):
        comum.carregar_config()


# ---------------------------------------------------------------- workflows

def _workflows():
    return {p.name: (p.read_text(encoding="utf-8"), yaml.safe_load(p.read_text(encoding="utf-8")))
            for p in (RAIZ / ".github" / "workflows").glob("*.yml")}


def test_workflows_nao_guardam_nada_do_canal():
    for nome, (texto, wf) in _workflows().items():
        assert "upload-artifact" not in texto, nome                 # artifact fica baixável por qualquer um
        assert "pull_request_target" not in texto, nome
        assert "GITHUB_STEP_SUMMARY" not in texto, nome
        assert wf.get("permissions"), f"{nome}: falta 'permissions'"
        for job in wf["jobs"].values():
            for passo in job.get("steps", []):
                if str(passo.get("uses", "")).startswith("actions/cache"):
                    assert "huggingface" in str(passo["with"]["path"]), nome   # só o modelo de voz público
                # nomes de livro digitados no Run workflow nunca entram no texto do passo nem no env
                bloco = json.dumps({k: passo.get(k) for k in ("run", "env", "with")}, ensure_ascii=False)
                assert not re.search(r"inputs\.(livro|atualizar_livro)", bloco), f"{nome}: {passo.get('name')}"


def test_workflow_de_limpeza_apaga_execucoes_antigas():
    texto, wf = _workflows()["limpar-execucoes.yml"]
    assert wf["permissions"]["actions"] == "write"
    assert wf[True]["workflow_dispatch"]["inputs"]["dias"]["default"] == "3"   # o YAML lê "on" como True
    assert "DELETE" in texto and "status=completed" in texto
