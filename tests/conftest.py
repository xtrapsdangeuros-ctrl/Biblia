import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import metadados  # noqa: E402

# Configuração de metadados de um canal FICTÍCIO (nomes inventados), igual ao bloco "metadados" do canal.yaml.
METADADOS_TESTE = {
    "autores_conhecidos": [
        "Aurélio Vasconcelos", "Gervásio Ramalho", "Lauro Bastos", "C. T. Lorens", "J. R. R. Toledo",
        "Gustavo R. R. Moraes", "G. R. R. Moraes", "Henrique Saldanha", "Ricardo Montemor", "B. K. Lemos",
        "Lúcio Carvalhal", "Bruno Salles", "Diogo Arantes", "Josué de Alcântara", "Afonso Azambuja",
        "Elói de Queluz", "Moreira Lobão",
    ],
    "correcoes": {"Cyclo do Despertar": "Ciclo do Despertar", "Ricrdo Montemor": "Ricardo Montemor"},
    "autor_da_serie": {"sal e cinza": "Gustavo R. R. Moraes", "despertar": "Ricardo Montemor",
                       "andarilho": "Diogo Arantes"},
}


@pytest.fixture(autouse=True)
def canal_ficticio(monkeypatch):
    """Os testes não dependem do canal.yaml (privado) da raiz: usam só a configuração fictícia acima."""
    monkeypatch.setenv("ROBO_SEM_CANAL_LOCAL", "1")
    antes = (metadados.AUTORES_CONHECIDOS, metadados._CORRECOES, metadados.AUTOR_DA_SERIE)
    metadados.configurar(METADADOS_TESTE)
    yield
    metadados.AUTORES_CONHECIDOS, metadados._CORRECOES, metadados.AUTOR_DA_SERIE = antes
