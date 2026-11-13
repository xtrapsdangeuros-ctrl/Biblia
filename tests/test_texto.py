import pytest

from comum import ler_nome_capitulo, nome_arquivo_capitulo
from livro import validar_ficha
from metadados import descricao_video, rotulo_e_titulo, tags_video, titulo_video
from numeros import ler_numero, limpar_token


@pytest.mark.parametrize("texto, esperado", [
    ("12", (12, 1)),
    ("XII", (12, 1)),
    ("iv", (4, 1)),
    ("doze", (12, 1)),
    ("vinte e um", (21, 3)),
    ("cento e dois", (102, 3)),
    ("primeiro", (1, 1)),
    ("décimo primeiro", (11, 2)),
    ("vigésima terceira", (23, 2)),
    ("três", (3, 1)),
])
def test_ler_numero(texto, esperado):
    tokens = [limpar_token(t) for t in texto.split()] + ["o", "menino"]
    assert ler_numero(tokens) == esperado


@pytest.mark.parametrize("texto", ["menino", "", "e"])
def test_ler_numero_sem_numero(texto):
    assert ler_numero([limpar_token(texto)]) is None


def test_limpar_token():
    assert limpar_token(" Capítulo,") == "capitulo"
    assert limpar_token("3.") == "3"


@pytest.mark.parametrize("nome, esperado", [
    ("01 - Da chegada.mp3", (1, "Da chegada")),
    ("3_Fim.m4a", (3, "Fim")),
    ("07.mp3", (7, "")),
    ("livro completo.mp3", None),
    ("parte-1.mp3", None),
])
def test_ler_nome_capitulo(nome, esperado):
    assert ler_nome_capitulo(nome) == esperado


def test_nome_arquivo_capitulo():
    assert nome_arquivo_capitulo(3, "Um: título/estranho?", ".mp3") == "03 - Um título estranho.mp3"
    assert nome_arquivo_capitulo(3, "", ".mp3", largura=3) == "003.mp3"


FICHA = {"titulo": "Noite de Vigília", "autor": "Aurélio Vasconcelos", "licenca": "dominio_publico",
         "fonte_texto": "edição de 1907", "narrador": "Fulana", "tags": ["literatura brasileira"]}


def test_validar_ficha():
    assert validar_ficha(FICHA) == []
    sem_fonte = {**FICHA, "fonte_texto": ""}
    assert any("fonte_texto" in p for p in validar_ficha(sem_fonte))
    assert any("licenca" in p for p in validar_ficha({**FICHA, "licenca": "outra"}))


def test_rotulo_e_titulo():
    assert rotulo_e_titulo(3, "Da Estrada") == ("Capítulo 3", "Da Estrada")
    assert rotulo_e_titulo(0, "Prólogo") == ("Prólogo", "")
    assert rotulo_e_titulo(5, "") == ("Capítulo 5", "")
    assert rotulo_e_titulo(5, "Capítulo 5") == ("Capítulo 5", "")


def test_titulo_video():
    assert titulo_video(FICHA, 3, "Da Estrada") == "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 3: Da Estrada | Aurélio Vasconcelos"
    # nome do capítulo comprido: sai o nome, ficam livro, número e autor
    assert titulo_video(FICHA, 3, "palavra " * 30) == "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 3 | Aurélio Vasconcelos"


def test_descricao_licencas():
    pd = descricao_video(FICHA, 2, "", "PL123", "VID1")
    assert "domínio público" in pd and "edição de 1907" in pd
    assert "list=PL123" in pd and "youtu.be/VID1" in pd
    proprio = descricao_video({**FICHA, "licenca": "proprio", "titulo": "A <b>"}, 1, "", None, None)
    assert "Todos os direitos reservados" in proprio and "<" not in proprio


def test_tags():
    tags = tags_video(FICHA)
    assert tags[0] == "literatura brasileira" and "audiolivro" in tags and "Aurélio Vasconcelos" in tags


@pytest.mark.parametrize("nome, esperado", [
    ("Pasta49_002-Os dois lados de um rio B.mp3", (49, (2, "B"), "Os dois lados de um rio")),
    ("Pasta36_001-Dorvan.mp3", (36, (1, ""), "Dorvan")),
    ("Pasta01_001-Prólogo A.mp3", (1, (1, "A"), "Prólogo")),
    ("01 - Da chegada.mp3", None),
])
def test_ler_nome_parte(nome, esperado):
    from comum import ler_nome_parte
    assert ler_nome_parte(nome) == esperado


def test_nomes_do_despertar():
    import unicodedata
    from comum import ler_nome_parte
    decomposto = unicodedata.normalize("NFD", "Pasta57_001 - Capítulo 57 A.mp3")
    assert ler_nome_parte(decomposto) == (57, (1, "A"), "Capítulo 57")
    assert ler_nome_parte("Pasta75_003 - Capítulo 74 C.mp3") == (74, (3, "C"), "Capítulo 74")
    assert ler_nome_parte("Pasta62_001- Capitulo 62 A.mp3") == (62, (1, "A"), "Capitulo 62")
    assert rotulo_e_titulo(46, "Capótulo 46") == ("Capítulo 46", "")
    assert rotulo_e_titulo(80, "Glossário") == ("Glossário", "")
    assert rotulo_e_titulo(0, "Abertura") == ("Abertura", "")


def test_filtrar_fila():
    from main import filtrar_fila
    pastas = [{"name": n} for n in ["Henrique Saldanha Lâmina Rubra (Vol. 3)", "Ricardo Montemor Despertar (Cyclo do Despertar Vol. 4)",
                                   "Ricardo Montemor Valtor (Cyclo do Despertar Vol. 1)"]]
    assert [p["name"][:24] for p in filtrar_fila(pastas, ["Montemor Despertar"])] == ["Ricardo Montemor Despert"]
    assert len(filtrar_fila(pastas, [])) == 3


def test_privacidade_por_livro():
    from livro import privacidade_do_livro
    assert privacidade_do_livro({"licenca": "dominio_publico", "privacidade": "public"}) == "public"
    assert privacidade_do_livro({"licenca": "proprio", "privacidade": "unlisted"}) == "unlisted"
    assert privacidade_do_livro({"licenca": "dominio_publico"}) == "private"
    assert privacidade_do_livro({"licenca": "uso_pessoal", "privacidade": "public"}) == "private"
    assert privacidade_do_livro({"privacidade": "public"}) == "private"
    problemas = validar_ficha({**FICHA, "licenca": "uso_pessoal", "privacidade": "public"})
    assert any("só é permitida" in p for p in problemas)


def test_faixas_do_saldanha():
    from comum import ler_nome_faixa
    assert ler_nome_faixa("003. O senhor das marés_ As crônicas de Tarso, Livro 1 - 03 - Capítulo 1.mp3") == (3, "Capítulo 1")
    assert ler_nome_faixa("002. O senhor das marés_ As crônicas de Tarso, Livro 1 - 02 - Parte 1_ Um Batismo No Outono.mp3") \
        == (2, "Parte 1: Um Batismo No Outono")
    assert ler_nome_faixa("Pasta01_001 - Capítulo 1.mp3") is None
    assert rotulo_e_titulo(3000, "Capítulo 1") == ("Capítulo 1", "")
    assert rotulo_e_titulo(2016, "Capítulo 16 – A batalha") == ("Capítulo 16", "A batalha")
    assert rotulo_e_titulo(2000, "Parte 1: Um Batismo No Outono") == ("Parte 1: Um Batismo No Outono", "")
    assert rotulo_e_titulo(1000, "Créditos Iniciais") == ("Créditos Iniciais", "")
    assert rotulo_e_titulo(5, "Da Estrada") == ("Capítulo 5", "Da Estrada")


def test_livro_incompleto():
    from datetime import datetime, timedelta, timezone
    from livro import _motivo_incompleto
    antigo = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    novo = datetime.now(timezone.utc).isoformat()
    assert "faltam os números 2, 3" in _motivo_incompleto([], [0, 1, 4, 4])
    assert _motivo_incompleto([{"createdTime": antigo}], [0, 1, 2]) == ""
    assert "chegaram" in _motivo_incompleto([{"createdTime": novo}], [0, 1, 2])


def test_numerar_cortes_de_faixa():
    from cortar import CapituloCortado, numerar_para_o_livro
    caps = [CapituloCortado(16, "", 0, 10), CapituloCortado(17, "A batalha", 10, 20)]
    nome = "003. Lâmina Rubra_ As crônicas de Tarso, Livro 3 - 3 - Parte 2 - Monte Corvo.mp3"
    novos = numerar_para_o_livro(caps, nome)
    assert [(c.numero, c.titulo) for c in novos] == [(3016, "Capítulo 16"), (3017, "Capítulo 17 – A batalha")]
    assert numerar_para_o_livro(caps, "livro completo.mp3") == caps


def test_capas(monkeypatch):
    import io, json
    from PIL import Image
    import capas

    assert capas.termos_de_busca("Ricardo Montemor Despertar (Cyclo do Despertar Vol. 4)") == "Ricardo Montemor Despertar"
    assert capas.termos_de_busca("Gustavo R. R. Moraes As Crônicas de Sal e Cinza Vol. 1 A Disputa das Coroas") \
        == "Gustavo R. R. Moraes As Crônicas de Sal e Cinza A Disputa das Coroas"

    def jpg(w, h):
        b = io.BytesIO(); Image.new("RGB", (w, h), "#345").save(b, "JPEG"); return b.getvalue()

    respostas = {
        "googleapis": json.dumps({"items": [{"volumeInfo": {"imageLinks": {"thumbnail": "http://x/pequena?zoom=1&edge=curl"}}}]}).encode(),
        "https://x/pequena?zoom=0": jpg(80, 120),      # pequena demais: descartada
        "https://x/pequena?zoom=1": jpg(80, 120),
        "openlibrary.org/search": json.dumps({"docs": [{"cover_i": 7}]}).encode(),
        "covers.openlibrary.org/b/id/7": jpg(400, 600),
    }

    def falso(url, timeout=30):
        for chave, dados in respostas.items():
            if chave in url:
                return dados
        raise OSError("sem rede")

    monkeypatch.setattr(capas, "_baixar", falso)
    dados, url = capas.buscar_capa("Ricardo Montemor Despertar (Cyclo do Despertar Vol. 4)")
    assert "openlibrary" in url and Image.open(io.BytesIO(dados)).size == (400, 600)


def test_numero_seguido_so_de_espaco():
    from comum import ler_nome_capitulo
    assert ler_nome_capitulo("001 Abertura.mp3") == (1, "Abertura")
    assert ler_nome_capitulo("045 A janela da frente.mp3") == (45, "A janela da frente")
    assert ler_nome_capitulo("2 - Dois.mp3") == (2, "Dois")
    assert ler_nome_capitulo("livro completo.mp3") is None


def test_nomes_de_cd():
    from comum import ler_nome_capitulo
    from metadados import rotulo_e_titulo
    assert ler_nome_capitulo("CD01_000-OAprendizDoVento.mp3") == (0, "Abertura")
    assert ler_nome_capitulo("CD03_000.mp3") == (0, "Abertura")
    assert ler_nome_capitulo("CD02_005-cap.04.mp3") == (5, "cap.04")
    assert rotulo_e_titulo(5, "cap.04") == ("Capítulo 4", "")
    assert ler_nome_capitulo("CD01_001-Cap.01.mp3") == (1, "Cap.01")


# ---------------------------------------------------------------- formatos de nome dos livros novos

def _livro_falso(nome_pasta, nomes):
    from livro import carregar_livro

    class DriveFalso:
        def listar(self, _id):
            return [{"id": str(i), "name": n, "size": "1000", "mimeType": "audio/mpeg"} for i, n in enumerate(nomes)]

    return carregar_livro(DriveFalso(), {"id": "p", "name": nome_pasta})


def _titulos(livro):
    # o que importa aqui é o rótulo de cada capítulo, não o formato do título no YouTube
    from metadados import rotulo_e_titulo
    saida = []
    for c in livro.capitulos:
        rotulo, titulo = rotulo_e_titulo(c.numero, c.titulo)
        saida.append(f"{livro.ficha['titulo']} – {rotulo.replace('Capítulo', 'Cap.')}" + (f": {titulo}" if titulo else ""))
    return saida


def test_cds_com_faixa_que_recomeca_em_cada_disco():
    livro = _livro_falso("Aurélio Vasconcelos O Relojoeiro", [
        "cd00_001-Inicio.mp3", "cd01-001-Cap.01.mp3", "cd02_001-Cap.02.mp3", "cd05_001-Cap.05.mp3", "cd05_002-Cap.05.mp3"])
    assert not livro.problemas and not livro.a_cortar
    assert _titulos(livro) == ["Aurélio Vasconcelos O Relojoeiro – Inicio", "Aurélio Vasconcelos O Relojoeiro – Cap. 1",
                               "Aurélio Vasconcelos O Relojoeiro – Cap. 2", "Aurélio Vasconcelos O Relojoeiro – Cap. 5"]
    assert len(livro.capitulos[-1].arquivos) == 2   # as duas faixas do cap. 5 viram um vídeo


def test_cds_com_faixa_continua_mantem_numero():
    livro = _livro_falso("Valdória", ["CD01_000-abertura.mp3", "CD01_001-cap.01.mp3", "CD02_002-cap.02.mp3"])
    assert [c.numero for c in livro.capitulos] == [0, 1, 2]   # igual a antes: os já publicados não mudam


def test_faixas_simples_e_continuacao():
    livro = _livro_falso("Gervásio Ramalho Terra Rachada", [
        "faixa00_Abertura.mp3", "faixa01_andança(1).mp3", "faixa03_feira.mp3", "faixa04_cont.feira.mp3",
        "faixa06_FilhoDoMeio(1).mp3"])
    assert _titulos(livro) == ["Gervásio Ramalho Terra Rachada – Abertura", "Gervásio Ramalho Terra Rachada – Andança",
                               "Gervásio Ramalho Terra Rachada – Feira", "Gervásio Ramalho Terra Rachada – Filho Do Meio"]
    assert len(livro.capitulos[2].arquivos) == 2


def test_titulo_que_so_repete_o_livro():
    livro = _livro_falso("Aurélio Vasconcelos Crônicas Esparsas", [
        "001. Cronicas Esparsas - Aurélio Vasconcelos(1).mp3", "002. Cronicas Esparsas - Aurélio Vasconcelos(2).mp3"])
    assert _titulos(livro) == ["Aurélio Vasconcelos Crônicas Esparsas – Cap. 1", "Aurélio Vasconcelos Crônicas Esparsas – Cap. 2"]
    unico = _livro_falso("Lauro Bastos Sino de Natal", ["001. Sino de Natal - 1 - Sino de Natal.mp3"])
    assert _titulos(unico) == ["Lauro Bastos Sino de Natal – Completo"]
    conto = _livro_falso("Gervásio Ramalho Três anéis", [
        "Três anéis - 0001 - Créditos Iniciais.mp3", "Três anéis - 0002 - Três anéis.mp3"])
    assert _titulos(conto) == ["Gervásio Ramalho Três anéis – Créditos Iniciais", "Gervásio Ramalho Três anéis – Completo"]


def test_arquivo_enviado_duas_vezes_conta_uma_vez():
    livro = _livro_falso("Toledo", ["019. A Caravana_ Livro 1 - 19 - Capítulo 19.mp3"] * 2)
    assert not livro.problemas and len(livro.capitulos) == 1


def test_capitulo_zero_sem_rotulo():
    from metadados import titulo_video
    assert titulo_video({"titulo": "Obra"}, 0, "Crédito inicial") == "AUDIOLIVRO OBRA – Crédito inicial"
    assert titulo_video({"titulo": "Obra"}, 3, "Da estrada") == "AUDIOLIVRO OBRA – CAP. 3: Da estrada"


def test_miniatura_so_troca_video_publicado_antes_da_capa():
    from miniaturas import precisa_trocar
    capa = {"createdTime": "2026-10-17T15:00:00.000Z"}
    assert precisa_trocar({"data": "2026-10-17T13:30:00+00:00"}, capa)
    assert not precisa_trocar({"data": "2026-10-18T12:00:00+00:00"}, capa)       # já saiu com a capa
    assert not precisa_trocar({"data": "2026-10-17T13:30:00+00:00", "video_id": "V"}, capa, {"V": "feito"})


def test_capa_da_wikipedia_so_do_artigo_do_livro(monkeypatch):
    import capas
    resposta = {"query": {"pages": {
        "1": {"index": 1, "title": "Henrique Saldanha", "thumbnail": {"source": "https://x/autor.jpg"}},
        "2": {"index": 2, "title": "O Senhor das Marés", "thumbnail": {"source": "https://x/capa.jpg"}},
        "3": {"index": 3, "title": "Brasão", "original": {"source": "https://x/b.svg"}}}}}
    monkeypatch.setattr(capas, "_json", lambda url: resposta)
    assert capas.candidatos_wikipedia("Henrique Saldanha O Senhor das Marés") == ["https://x/capa.jpg"]


def test_capa_do_google_precisa_ser_do_mesmo_livro():
    from capas import titulo_combina
    assert not titulo_combina("Gervásio Ramalho Marcelina", "Conversa entre mestres e aprendizes", "Ana Maria")
    assert not titulo_combina("Aurélio Vasconcelos O Engano", "The Contradictions of Science in Aurélio Vasconcelos", "Rosana")
    assert titulo_combina("Henrique Saldanha O Senhor das Marés", "O senhor das marés", "Henrique Saldanha")
    assert titulo_combina("Lauro Bastos Feiras e festejos ribeirinhos e outras crônicas de Lauro Bastos",
                          "Feiras e festejos ribeirinhos e outras crônicas de Lauro Bastos", "Lauro Bastos")
