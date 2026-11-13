"""Correção de SEO dos vídeos já publicados: prévia sem mexer em nada, aprovação, limite por dia e proteções."""

import json

import pytest

import corrigir_seo
from corrigir_seo import ARQ_PLANO, aplicar, ficha_de_titulo_antigo, montar_plano, relatorio
from google_api import LimiteDiario, SemPermissao
from metadados import com_proximo
from test_fluxo import PASTA, DriveFalso

FICHA = "titulo: Aurélio Vasconcelos Noite de Vigília\nautor: Aurélio Vasconcelos\nlicenca: dominio_publico\nfonte_texto: x\n"
CFG = {"publicacao": {"categoria_id": "27", "idioma": "pt-BR"}, "cta": {"canal": "https://y/@canal"},
       "extras": {}, "seo": {"proteger_titulo_acima_de_views": 1000, "titulos_protegidos": ["OLD1"]}}


@pytest.fixture(autouse=True)
def sem_pausa(monkeypatch):
    monkeypatch.setattr(corrigir_seo, "PAUSA_SEG", 0)


def _video(vid, titulo, views=0, privacidade="public", tags=None, descricao="Descrição antiga"):
    return {"id": vid, "snippet": {"title": titulo, "description": descricao, "tags": tags or [],
                                   "categoryId": "27", "defaultAudioLanguage": "pt-BR"},
            "status": {"privacyStatus": privacidade}, "statistics": {"viewCount": str(views)},
            "contentDetails": {"duration": "PT1H"}}


class YouTubeFalso:
    def __init__(self, videos):
        self.no_ar = {v["id"]: v for v in videos}
        self.atualizados, self.playlists_mudadas, self.comentarios = [], [], []
        self.limite_depois = None
        self.sem_permissao_comentar = False

    def videos_do_canal(self):
        return list(self.no_ar.values())

    def ler_videos(self, ids):
        return [self.no_ar[i] for i in ids if i in self.no_ar]

    def ler_playlists(self, ids):
        return [{"id": i, "snippet": {"title": "Noite de Vigília – Audiolivro completo", "description": ""},
                 "status": {"privacyStatus": "private"}} for i in ids]

    def _gasta(self):
        if self.limite_depois is not None and len(self.atualizados) + len(self.comentarios) >= self.limite_depois:
            raise LimiteDiario("quotaExceeded")

    def atualizar_metadados(self, vid, snippet):
        self._gasta()
        self.atualizados.append((vid, snippet))
        self.no_ar[vid]["snippet"].update(snippet)

    def atualizar_playlist(self, pid, titulo, descricao, privacidade):
        self.playlists_mudadas.append((pid, titulo, privacidade))

    def comentar(self, vid, texto):
        if self.sem_permissao_comentar:
            raise SemPermissao("insufficientPermissions")
        self._gasta()
        self.comentarios.append((vid, texto))
        return f"C{len(self.comentarios)}"


@pytest.fixture
def canal(tmp_path):
    drive = DriveFalso(tmp_path)
    raiz = drive.novo("Audiolivros", None, PASTA)
    livro = drive.novo("Aurélio Vasconcelos Noite de Vigília", raiz, PASTA)
    drive.novo("ficha.txt", livro, "text/plain", texto=FICHA)
    for n, titulo in ((1, "Da chegada"), (2, "Da estrada"), (3, "Tadeu")):
        drive.novo(f"0{n} - {titulo}.mp3", livro)
    estado = {"playlist_id": "PL1", "capitulos": {
        "1": {"video_id": "VA", "short": "SH1"}, "2": {"video_id": "VB"}, "3": {"video_id": "VC"}}}
    drive.gravar_json(livro, "publicados.json", estado)
    youtube = YouTubeFalso([
        _video("VA", "Aurélio Vasconcelos Noite de Vigília – Cap. 1: Da chegada | Audiolivro", views=50),
        _video("VB", "Aurélio Vasconcelos Noite de Vigília – Cap. 2: Da estrada | Audiolivro", views=5000),
        _video("VC", "Aurélio Vasconcelos Noite de Vigília – Cap. 3: Tadeu | Audiolivro", privacidade="private"),
        _video("SH1", "Aurélio Vasconcelos Noite de Vigília – Cap. 1 #Shorts"),
        _video("OLD1", "Áudiolivro Lumenor PARTE 1 DE 3 (Ciclo do Despertar #3) - Ricrdo Montemor (Voz Humana HD)",
               views=17744),
        _video("LIVE", "Live de domingo"),
    ])
    return drive, youtube, raiz, livro


def _itens(plano, tipo=None, vid=None):
    return [i for i in plano["itens"] if (tipo is None or i["tipo"] == tipo) and (vid is None or i["id"] == vid)]


def test_previa_nao_muda_nada_e_respeita_as_protecoes(canal):
    drive, youtube, raiz, _ = canal
    plano = montar_plano(drive, youtube, raiz, CFG)
    assert not youtube.atualizados and not youtube.comentarios and not youtube.playlists_mudadas
    assert plano["aprovado"] is False

    va = _itens(plano, "video", "VA")[0]
    assert va["depois"]["title"] == "AUDIOLIVRO NOITE DE VIGÍLIA – CAP. 1: Da chegada | Aurélio Vasconcelos"
    assert va["depois"]["description"].startswith("Audiolivro Noite de Vigília, de Aurélio Vasconcelos – Capítulo 1")
    assert "youtu.be/VB" in va["depois"]["description"]          # link do próximo
    assert va["depois"]["categoryId"] == "27" and va["depois"]["defaultAudioLanguage"] == "pt-BR"

    vb = _itens(plano, "video", "VB")[0]                          # 5.000 views: título protegido
    assert vb["depois"]["title"] == vb["antes"]["title"] and "title" not in vb["campos"]

    old = _itens(plano, "video", "OLD1")[0]                       # antigo: só tags e hashtags
    assert old["depois"]["title"] == old["antes"]["title"]
    assert old["depois"]["description"].startswith("Descrição antiga\n\n#audiolivro")
    assert "Lumenor" in old["depois"]["tags"] and "Ricardo Montemor" in old["depois"]["tags"]
    assert not _itens(plano, vid="LIVE")

    sh = _itens(plano, "video", "SH1")[0]
    assert sh["depois"]["title"] == "NOITE DE VIGÍLIA, Aurélio Vasconcelos – CAP. 1 #audiolivro #shorts"
    assert sh["depois"]["description"].startswith("📚 Ouça o livro todo: https://www.youtube.com/playlist?list=PL1")

    pl = _itens(plano, "playlist")[0]                             # o livro tem vídeo público: playlist pública
    assert pl["depois"]["privacidade"] == "public"
    assert pl["depois"]["title"] == "AUDIOLIVRO NOITE DE VIGÍLIA – Aurélio Vasconcelos (completo)"

    comentarios = {i["id"] for i in _itens(plano, "comentario")}
    assert comentarios == {"VA", "VB"}                            # VC é privado: sem comentário
    assert plano["itens"][0]["tipo"] == "playlist"
    assert any("AUDIOLIVRO NOITE DE VIGÍLIA" in l for l in relatorio(plano, 40))


def test_so_aplica_depois_de_aprovar_e_no_limite_do_dia(canal):
    drive, youtube, raiz, _ = canal
    drive.gravar_json(raiz, ARQ_PLANO, montar_plano(drive, youtube, raiz, CFG))

    aplicar(drive, youtube, raiz, CFG, maximo=40, aprovar=False)          # execução diária: lista não aprovada
    assert not youtube.atualizados and not youtube.playlists_mudadas

    aplicar(drive, youtube, raiz, CFG, maximo=3, aprovar=True)            # aprovou: 3 hoje
    assert len(youtube.playlists_mudadas) + len(youtube.atualizados) == 3
    plano = drive.ler_json(raiz, ARQ_PLANO, {})
    assert plano["aprovado"] and sum(1 for i in plano["itens"] if i.get("feito")) == 3

    aplicar(drive, youtube, raiz, CFG, maximo=100, aprovar=False)         # dias seguintes: continua até acabar
    plano = drive.ler_json(raiz, ARQ_PLANO, {})
    assert all(i.get("feito") for i in plano["itens"])
    assert youtube.no_ar["OLD1"]["snippet"]["title"].startswith("Áudiolivro Lumenor")


def test_comentario_fica_anotado_e_nao_repete(canal):
    drive, youtube, raiz, livro = canal
    drive.gravar_json(raiz, ARQ_PLANO, montar_plano(drive, youtube, raiz, CFG))
    aplicar(drive, youtube, raiz, CFG, maximo=100, aprovar=True)
    assert len(youtube.comentarios) == 2 and "list=PL1" in youtube.comentarios[0][1]
    estado = drive.ler_json(livro, "publicados.json", {})
    assert estado["capitulos"]["1"]["comentario"] == "C1" or estado["capitulos"]["2"]["comentario"] == "C1"
    assert not _itens(montar_plano(drive, youtube, raiz, CFG), "comentario")   # nova prévia não comenta de novo


def test_pula_video_que_mudou_depois_da_previa(canal):
    drive, youtube, raiz, _ = canal
    drive.gravar_json(raiz, ARQ_PLANO, montar_plano(drive, youtube, raiz, CFG))
    youtube.no_ar["VA"]["snippet"]["title"] = "Título que o dono escreveu no Studio"
    aplicar(drive, youtube, raiz, CFG, maximo=100, aprovar=True)
    assert "VA" not in [v for v, _ in youtube.atualizados]
    item = _itens(drive.ler_json(raiz, ARQ_PLANO, {}), "video", "VA")[0]
    assert item["feito"].startswith("pulado")


def test_para_quando_a_cota_acaba_e_sem_permissao_de_comentar(canal):
    drive, youtube, raiz, _ = canal
    drive.gravar_json(raiz, ARQ_PLANO, montar_plano(drive, youtube, raiz, CFG))
    youtube.limite_depois = 2
    youtube.sem_permissao_comentar = True
    aplicar(drive, youtube, raiz, CFG, maximo=100, aprovar=True)
    plano = drive.ler_json(raiz, ARQ_PLANO, {})
    assert len(youtube.atualizados) == 2 and any(not i.get("feito") for i in plano["itens"])


@pytest.mark.parametrize("titulo, esperado", [
    ("Áudiolivro Lumenor PARTE 1 DE 3 (Ciclo do Despertar #3) - Ricrdo Montemor (Voz Humana HD)",
     {"titulo": "Lumenor", "serie": "Ciclo do Despertar", "volume": 3, "autor": "Ricardo Montemor"}),
    ("Áudiolivro Manual dos andarilhos das estrelas Vol.4  - Diogo arantes (Voz Humana HD)",
     {"titulo": "Manual dos andarilhos das estrelas", "serie": "", "volume": 4, "autor": "Diogo arantes"}),
    ("A Disputa das Coroas 1/3 Livro 1  | DISPUTA DAS COROAS | DDC | As Crônicas de Sal e Cinza",
     {"titulo": "A Disputa das Coroas", "serie": "As Crônicas de Sal e Cinza", "volume": 1,
      "autor": "Gustavo R. R. Moraes"}),
])
def test_entende_titulos_antigos(titulo, esperado):
    assert ficha_de_titulo_antigo(titulo) == esperado


def test_titulo_no_padrao_novo_nao_e_tratado_como_antigo():
    assert ficha_de_titulo_antigo("AUDIOLIVRO DESPERTAR – CAP. 3 | Ricardo Montemor") is None


def test_link_do_proximo_entra_no_topo_sem_mexer_no_resto():
    nova = com_proximo("Audiolivro X.\n▶ Ouça o livro todo: L\n\nResto", "P2")
    assert nova == "Audiolivro X.\n▶ Ouça o livro todo: L\n⏭ Próximo: https://youtu.be/P2\n\nResto"
    assert com_proximo(nova, "P2") == nova
    assert com_proximo("Título antigo\n\nTexto", "P3").splitlines()[1] == "⏭ Próximo: https://youtu.be/P3"


def test_plano_cabe_em_json(canal):
    drive, youtube, raiz, _ = canal
    json.dumps(montar_plano(drive, youtube, raiz, CFG), ensure_ascii=False)
    assert corrigir_seo.CUSTO == 50


class _Resp(dict):
    def __init__(self, status):
        super().__init__(status=str(status))
        self.status, self.reason = status, "x"


def _erro(status, motivo="SERVICE_UNAVAILABLE"):
    from googleapiclient.errors import HttpError
    corpo = json.dumps({"error": {"errors": [{"reason": motivo}], "message": "Resource has been exhausted"}})
    return HttpError(_Resp(status), corpo.encode())


class _Pedido:
    def __init__(self, respostas):
        self.respostas = list(respostas)

    def execute(self, num_retries=0):
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_youtube_pede_para_ir_devagar_espera_e_continua(monkeypatch):
    import google_api
    esperas = []
    monkeypatch.setattr(google_api.time, "sleep", esperas.append)
    yt = google_api.YouTube.__new__(google_api.YouTube)
    assert yt._executar(_Pedido([_erro(429), _erro(429), {"ok": 1}])) == {"ok": 1}
    assert esperas == [10, 30]
    with pytest.raises(LimiteDiario):      # se continuar pedindo, para o dia sem derrubar o robô
        yt._executar(_Pedido([_erro(429)] * 4))
    with pytest.raises(LimiteDiario):
        yt._executar(_Pedido([_erro(403, "quotaExceeded")]))
