import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("testar_vozes", Path(__file__).parent.parent / "scripts" / "testar_vozes.py")
testar_vozes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(testar_vozes)


def test_filtra_vozes_brasileiras_das_melhores_para_as_piores():
    def voz(codigo, qualidade, base):
        return {"language": {"code": codigo}, "quality": qualidade,
                "files": {f"{base}.onnx": {}, f"{base}.onnx.json": {}, "MODEL_CARD": {}}}
    catalogo = {
        "pt_BR-edresson-low": voz("pt_BR", "low", "pt/pt_BR/edresson/low/pt_BR-edresson-low"),
        "pt_BR-faber-medium": voz("pt_BR", "medium", "pt/pt_BR/faber/medium/pt_BR-faber-medium"),
        "pt_PT-tugao-medium": voz("pt_PT", "medium", "pt/pt_PT/tugao/medium/pt_PT-tugao-medium"),
    }
    vozes = testar_vozes.vozes_do_idioma(catalogo)
    assert [v[0] for v in vozes] == ["pt_BR-faber-medium", "pt_BR-edresson-low"]
    assert vozes[0][1].endswith(".onnx") and vozes[0][2].endswith(".onnx.json")


def test_pasta_de_testes_de_voz_nao_e_livro():
    from livro import pastas_de_livros
    from test_fluxo import PASTA, DriveFalso
    drive = DriveFalso(Path("."))
    raiz = drive.novo("Audiolivros", None, PASTA)
    drive.novo("Testes de voz", raiz, PASTA)
    drive.novo("01 - Noite de Vigília", raiz, PASTA)
    assert [p["name"] for p in pastas_de_livros(drive, raiz)] == ["01 - Noite de Vigília"]


def test_divide_texto_para_o_google_sem_passar_do_limite():
    paragrafos = [("Frase número %d tem acentos: ação, coração. " % i) * 20 for i in range(30)]
    texto = "\n\n".join(paragrafos) + "\n\n" + "Parágrafo gigante sem quebra. " * 400
    pedacos = testar_vozes.dividir_texto(texto, 4500)
    assert all(len(p.encode()) <= 4500 for p in pedacos)
    junto = " ".join(" ".join(p.split()) for p in pedacos)
    assert junto.split() == texto.split()   # nada se perde nem se repete


def test_escolhe_uma_voz_feminina_e_uma_masculina_por_familia_do_google():
    vozes = [{"name": n, "ssmlGender": g, "languageCodes": ["pt-BR"]} for n, g in [
        ("pt-BR-Chirp3-HD-Aoede", "FEMALE"), ("pt-BR-Chirp3-HD-Charon", "MALE"), ("pt-BR-Chirp3-HD-Kore", "FEMALE"),
        ("pt-BR-Neural2-A", "FEMALE"), ("pt-BR-Neural2-B", "MALE"), ("pt-BR-Standard-A", "FEMALE"),
        ("pt-BR-Wavenet-C", "FEMALE")]]
    assert testar_vozes.escolher_vozes_google(vozes) == [
        "pt-BR-Chirp3-HD-Aoede", "pt-BR-Chirp3-HD-Charon", "pt-BR-Neural2-A", "pt-BR-Neural2-B", "pt-BR-Wavenet-C"]


def test_google_sem_chave_pula(monkeypatch, tmp_path):
    monkeypatch.delenv("GOOGLE_TTS_API_KEY", raising=False)
    assert testar_vozes.motor_google("Olá.", tmp_path, None) == []
