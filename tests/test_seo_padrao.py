"""Padrão de SEO aprovado em 03/11/2026: "AUDIOLIVRO" + NOME DO LIVRO no começo do título, autor no fim,
até 70 caracteres; 1ª linha da descrição com livro, autor e série; link da playlist logo em seguida."""

from metadados import (descricao_playlist, descricao_video, hashtags_video, livro_e_autor, snippet_video,
                       tags_video, titulo_completo, titulo_grupo, titulo_playlist, titulo_short, titulo_video)
from shorts import descricao_short

REI = {"titulo": "O Senhor das Marés (Henrique Saldanha)", "autor": "Henrique Saldanha", "licenca": "uso_pessoal",
       "serie": "As Crônicas de Tarso", "volume": 1}
DESPERTAR = {"titulo": "Ricardo Montemor Despertar", "autor": "Ricardo Montemor", "serie": "Cyclo do Despertar",
           "volume": 4}
PUB = {"categoria_id": "27", "idioma": "pt-BR"}


def test_separa_autor_do_nome_do_livro():
    assert livro_e_autor(REI) == ("O Senhor das Marés", "Henrique Saldanha")
    assert livro_e_autor(DESPERTAR) == ("Despertar", "Ricardo Montemor")
    # sem ficha: o autor vem grudado no nome da pasta
    assert livro_e_autor({"titulo": "B. K. Lemos O Homem no Telhado"}) == ("O Homem no Telhado", "B. K. Lemos")
    assert livro_e_autor({"titulo": "O Trono de Areia (G. R. R. Moraes)", "autor": "Gustavo R. R. Moraes"}) == \
        ("O Trono de Areia", "Gustavo R. R. Moraes")
    assert livro_e_autor({"titulo": "Noite de Vigília"}) == ("Noite de Vigília", "")


def test_titulos_dos_exemplos_aprovados():
    assert titulo_video(REI, 27, "") == "AUDIOLIVRO O SENHOR DAS MARÉS – CAP. 27 | Henrique Saldanha"
    # faixa de capítulos longa demais: sai do título (vai para a descrição)
    assert titulo_grupo(REI, 11, [(33, ""), (37, "Prévia: O guardião do farol")]) == \
        "AUDIOLIVRO O SENHOR DAS MARÉS – PARTE 11 | Henrique Saldanha"
    assert titulo_grupo({"titulo": "Aurélio Vasconcelos Contos"}, 2, [(1, ""), (4, "")]) == \
        "AUDIOLIVRO CONTOS – PARTE 2 (Caps. 1 a 4) | Aurélio Vasconcelos"
    assert titulo_completo(DESPERTAR, 2, 3) == "AUDIOLIVRO COMPLETO DESPERTAR (2 DE 3) | Ricardo Montemor"
    assert titulo_short({"titulo": "B. K. Lemos O Homem no Telhado"}, 6, "") == \
        "O HOMEM NO TELHADO, B. K. Lemos – CAP. 6 #audiolivro #shorts"


def test_titulo_nunca_passa_de_100_e_prefere_70():
    for ficha in (REI, DESPERTAR, {"titulo": "O Corvo, o Ferreiro e a Torre Esquecida", "autor": "C. T. Lorens"}):
        for n in range(1, 60):
            t = titulo_video(ficha, n, "Um título de capítulo bem comprido para testar o corte")
            assert t.startswith("AUDIOLIVRO ") and len(t) <= 70
    gigante = {"titulo": "Feiras e festejos ribeirinhos e outras crônicas de Lauro Bastos " * 2}
    assert len(titulo_video(gigante, 1, "")) <= 100


def test_descricao_comeca_com_palavra_chave_e_links():
    d = descricao_video(REI, 27, "", "PL1", "ANT", {"topo": "🔔 Inscreva-se"}, proximo_id="PROX")
    linhas = d.splitlines()
    assert linhas[0] == ("Audiolivro O Senhor das Marés, de Henrique Saldanha – Capítulo 27. Livro 1 de As Crônicas "
                         "de Tarso. Audiobook narrado em português.")
    assert linhas[1] == "▶ Ouça o livro todo, em ordem (playlist): https://www.youtube.com/playlist?list=PL1"
    assert linhas[2] == "⏭ Próximo: https://youtu.be/PROX" and linhas[3] == "⏮ Anterior: https://youtu.be/ANT"
    assert linhas[-1] == "#audiolivro #audiobook #OSenhorDasMarés #HenriqueSaldanha"


def test_serie_com_erro_de_digitacao_e_corrigida():
    assert "Livro 4 de Ciclo do Despertar" in descricao_video(DESPERTAR, 1, "", None, None)


def test_hashtags_da_ficha_vem_primeiro_e_no_maximo_5():
    tags = hashtags_video({**REI, "hashtags": ["rei tarso", "#fantasia", "audiolivro"]})
    assert tags == ["#ReiTarso", "#fantasia", "#audiolivro", "#audiobook", "#OSenhorDasMarés"]


def test_tags_cobrem_variacoes_de_busca():
    tags = tags_video(DESPERTAR)
    for t in ("audiolivro", "audiobook", "Despertar", "Despertar audiolivro", "Ricardo Montemor", "Ciclo do Despertar"):
        assert t in tags
    assert sum(len(t) + 1 + (2 if " " in t else 0) for t in tags_video({**DESPERTAR, "tags": ["x" * 90] * 9})) <= 450


def test_video_com_varios_capitulos():
    caps = [(1, "Da chegada", 0.0), (2, "Da estrada", 600.0), (3, "", 1300.0)]
    # livro de nome curto: o título com a faixa de capítulos cabe nos 70 caracteres
    s = snippet_video({"titulo": "Aurélio Vasconcelos O Farol"}, caps, 1, "PL", None, PUB, duracao_total=2000,
                      proximo_id="P2")
    assert s["title"] == "AUDIOLIVRO O FAROL – PARTE 1 (Caps. 1 a 3) | Aurélio Vasconcelos"
    assert s["description"].startswith("Audiolivro O Farol, de Aurélio Vasconcelos – Parte 1: Caps. 1 a 3.")
    assert "00:00 Cap. 1: Da chegada" in s["description"] and "youtu.be/P2" in s["description"]


def test_playlist_e_short_divulgam_o_livro_todo():
    assert titulo_playlist(REI) == "AUDIOLIVRO O SENHOR DAS MARÉS – Henrique Saldanha (completo)"
    assert descricao_playlist(REI).startswith("Audiolivro O Senhor das Marés, de Henrique Saldanha")
    d = descricao_short(REI, 3, "", "VID", "PL9")
    assert d.splitlines()[0] == "📚 Ouça o livro todo: https://www.youtube.com/playlist?list=PL9"
    assert "#Shorts" in d
