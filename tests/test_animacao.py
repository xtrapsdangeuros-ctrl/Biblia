"""Vídeos animados por código (src/animacao.py e src/personagens.py)."""

import subprocess

import animacao as A
import personagens as P


def test_todos_os_personagens_tem_as_quatro_poses():
    for p in list(P.ELENCO.values()) + [P.pessoa("moises", "Moisés", barba=(230, 230, 230), cajado=True)]:
        poses = P.poses(p, 200)
        assert len(poses) == 4 and all(img.height == 200 for img in poses.values())


def test_legenda_acompanha_a_fala():
    fala = A.Fala("narrador", "um dois tres quatro cinco seis sete oito", inicio=10, duracao=8)
    assert A.legenda_atual(fala, 10.1) == ("um dois tres quatro", 0)
    assert A.legenda_atual(fala, 17.9)[0] == "cinco seis sete oito"


def test_roteiro_vira_video(tmp_path):
    rot = A.ler_roteiro({
        "formato": "short", "titulo": "Teste", "gancho": "Pergunta?", "musica": "alegre",
        "elenco": {"davi": {"tipo": "pessoa", "rotulo": "Davi", "funda": True, "tamanho": 0.8}},
        "cenas": [{"cenario": "campo", "personagens": ["tomatinho", "davi"], "destaque": "Art. 1º",
                   "falas": [["narrador", "Era uma vez."], ["davi", "Oi!"]]}]})
    assert A.caracteres(rot) == len("Era uma vez.") + len("Oi!")
    video = A.renderizar(rot, tmp_path / "v.mp4")
    saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=width,height,codec_type",
                            "-of", "csv=p=0", str(video)], capture_output=True, text=True).stdout
    assert "1080,1920,video" in saida.replace("video,1080,1920", "1080,1920,video") or "1080,1920" in saida
    assert "audio" in saida


def test_musica_gerada(tmp_path):
    for estilo in ("calma", "alegre", "epica"):
        arq = A.musica_gerada(estilo, 5, tmp_path / f"{estilo}.wav")
        assert arq.stat().st_size > 50_000
