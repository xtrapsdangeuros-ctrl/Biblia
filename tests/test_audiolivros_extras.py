"""Audiolivros no canal da Bíblia (main.audiolivros_extras)."""

from types import SimpleNamespace

import main


class Drive:
    def __init__(self):
        self.chamadas = []

    def achar(self, raiz, nome):
        self.chamadas.append(nome)
        return {"id": "pasta-livros", "name": nome, "mimeType": "application/vnd.google-apps.folder"}

    @staticmethod
    def eh_pasta(item):
        return True


ARGS = SimpleNamespace(capitulo=None, quantos=None, livro="", dry_run=True)


def test_desligado_nao_faz_nada():
    d = Drive()
    assert main.audiolivros_extras(d, None, "raiz", {"audiolivros": {"ativo": False}}, ARGS) == 0
    assert d.chamadas == []


def test_so_nos_dias_da_semana_e_sem_o_modo_biblia(monkeypatch):
    usado = {}
    monkeypatch.setattr(main, "publicar_livros", lambda drive, yt, raiz, cfg, args: usado.update(raiz=raiz, cfg=cfg) or 0)
    cfg = {"modo": "biblia", "publicacao": {"idioma": "pt-BR"},
           "audiolivros": {"ativo": True, "dias_da_semana": [], "pasta": "Livros"}}
    assert main.audiolivros_extras(Drive(), None, "raiz", cfg, ARGS) == 0 and not usado   # nenhum dia
    cfg["audiolivros"]["dias_da_semana"] = list(range(7))
    main.audiolivros_extras(Drive(), None, "raiz", cfg, ARGS)
    assert usado["raiz"] == "pasta-livros" and "modo" not in usado["cfg"]
    assert usado["cfg"]["publicacao"]["videos_por_dia"] == 1 and usado["cfg"]["publicacao"]["modo"] == "sequencial"
