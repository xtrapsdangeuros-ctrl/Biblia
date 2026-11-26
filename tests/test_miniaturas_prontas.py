import miniaturas_prontas as mp


def _item(nome, i="x"):
    return {"id": i, "name": nome, "mimeType": "image/jpeg"}


def test_ler_capas_pelo_codigo():
    capas = mp.ler_capas([_item("P07 - Noite de Vigília.avif", "a"), _item("P10 - Outro.jpg", "b"),
                          _item("F01 - Na fila.png", "c"), _item("sem código.jpg"), _item("P08 - Texto.txt")])
    assert [c.codigo for c in capas] == ["P07", "P10", "F01"]
    assert capas[0].titulo == "Noite de Vigília" and capas[0].arquivo["id"] == "a"


def test_achar_pasta_prefere_nome_igual_e_a_que_tem_videos():
    pastas = [({"id": "1", "name": "Aurélio Vasconcelos Contos"}, "Contos"),
              ({"id": "2", "name": "Aurélio Vasconcelos 50 Contos"}, "50 Contos"),
              ({"id": "3", "name": "[Vasconcelos Aurélio] Noite de Vigília"}, "Noite de Vigília"),
              ({"id": "4", "name": "Aurélio Vasconcelos Noite de Vigília"}, "Noite de Vigília")]
    assert mp.achar_pasta("Contos", pastas, set())["id"] == "1"
    assert mp.achar_pasta("Noite de Vigília", pastas, {"4"})["id"] == "4"
    assert mp.achar_pasta("Livro que não existe", pastas, set()) is None


def test_um_video_por_grupo_e_rotulos():
    estado = {"capitulos": {
        "1": {"video_id": "a"}, "2": {"video_id": "b"},
        "3": {"video_id": "c", "parte": 1}, "4": {"video_id": "c", "parte": 1}},
        "completo": {"partes": {"1": "z"}}}
    vids = mp.videos_do_registro(estado, {1: "Da Estrada", 2: "", 3: "A", 4: "B"})
    assert [(v.video_id, v.rotulo, v.detalhe) for v in vids] == [
        ("a", "Cap. 1", "Da Estrada"), ("b", "Cap. 2", ""), ("c", "Parte 1", "Caps. 3 a 4"),
        ("z", "Parte 1", "Audiolivro completo")]


def test_videos_antigos_vao_para_o_livro_certo():
    livros = [mp.Livro(mp.Capa("P01", "Eragon", {}), None, nome="Eragon"),
              mp.Livro(mp.Capa("P02", "Eldest", {}), None, nome="Eldest"),
              mp.Livro(mp.Capa("P26", "Herança", {}), None, nome="Herança")]

    def v(i, titulo, dur="PT1H2M", quando="2015-01-01"):
        return {"id": i, "snippet": {"title": titulo, "publishedAt": quando}, "contentDetails": {"duration": dur}}

    canal = [v("e2", "Áudiolivro Eldest PARTE 2 DE 3 (Ciclo da Herança #2)", quando="2015-02"),
             v("e1", "Áudiolivro Eldest parte 1 (Ciclo da Herança #2)", quando="2015-03"),
             v("h1", "Áudiolivro Herança parte 1 (Ciclo da Herança #4)"),
             v("g", "Eragon 3/4"), v("s", "Eldest em 1 minuto", dur="PT59S"), v("r", "Eldest robô")]
    assert mp.distribuir_antigos(canal, livros, do_robo={"r"}) == 4
    assert [(x.video_id, x.rotulo) for x in livros[1].videos] == [("e1", "Parte 1"), ("e2", "Parte 2")]
    assert [(x.video_id, x.rotulo) for x in livros[0].videos] == [("g", "Parte 3")]
    assert [x.video_id for x in livros[2].videos] == ["h1"]


def test_nome_do_arquivo():
    assert mp.nome_arquivo(mp.Video("a", "Cap. 3", titulo_youtube="AUDIOLIVRO X – CAP. 3 | Autor")) == \
        "Cap 03 - AUDIOLIVRO X – CAP. 3 Autor.jpg"
    assert mp.nome_arquivo(mp.Video("a", "Parte 12", titulo_youtube="a/b")) == "Parte 12 - a b.jpg"
    assert mp.nome_arquivo(mp.Video("a", "Prólogo")) == "Prólogo.jpg"
    assert mp.segundos("PT1H2M3S") == 3723 and mp.segundos("") == 0


def test_lista_de_nomes():
    texto = "# comentário\n1abc => P35 - A Mão e a Luva.jpg\nfoto (2).jpeg => F01 - Excalibur.avif\n" \
            "x => sem codigo.jpg\ny => P36 - Casa Velha.txt\n\n"
    assert mp.ler_renomear(texto) == [("1abc", "P35 - A Mão e a Luva.jpg"), ("foto (2).jpeg", "F01 - Excalibur.avif")]


def test_troca_no_youtube_para_quando_a_cota_acaba():
    from googleapiclient.errors import HttpError

    class Resp(dict):
        status, reason = 403, "Forbidden"

    class YT:
        def __init__(self, erro=None):
            self.erro = erro

        def definir_miniatura(self, vid, img):
            if self.erro:
                raise self.erro

    assert mp._trocar_no_youtube(YT(), "a", None) == "ok"
    assert mp._trocar_no_youtube(YT(HttpError(Resp(), b'{"reason":"quotaExceeded"}')), "a", None) == "cota"
    assert mp._trocar_no_youtube(YT(HttpError(Resp(), b'{"reason":"forbidden"}')), "a", None) == "erro"
    lv = mp.Livro(mp.Capa("P06", "Livro", {}), None, nome="Livro")
    assert mp._linha(lv, "P06 - Livro", mp.Video("a", "Cap. 1"), {"a": "2026-11-26T10:00:00+00:00"})[-1] == \
        "trocada pelo robô em 2026-11-26"
