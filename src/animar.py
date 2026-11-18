"""Vídeos animados do canal: pega os roteiros (YAML) da pasta "Roteiros animados" do Drive, faz o vídeo (HyperFrames;
sem ele, o motor antigo do animacao.py) e publica no YouTube.

Ritmo (canal.yaml > animacao): shorts_por_dia (padrão 1) e longos nos dias da semana de "dias_longos"
(padrão terça e sexta = 2 por semana). Cada roteiro diz o próprio formato (short | longo). Roteiro publicado
vai para a subpasta "Publicados"; o estado fica em animacoes.json na pasta do canal.

Uso:
  python src/animar.py                         # GitHub Actions, todo dia (sai na hora se animacao.ativo = false)
  python src/animar.py --checar                # só diz (ativo=true/false) para o workflow decidir se instala o Node
  python src/animar.py --roteiro "@entrada:roteiro" --so-drive   # faz um roteiro e salva o MP4 no Drive (teste)
  python src/animar.py --local roteiro.yaml --saida video.mp4    # teste no computador, sem Drive nem YouTube
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import animacao as A
import discreto
import hyperframes as H
import musica as M
from comum import carregar_config, configurar_log, eh_audio, log

ARQ_ESTADO = "animacoes.json"
PADRAO = {
    "ativo": False,
    "pasta_roteiros": "Roteiros animados",
    "pasta_prontos": "Animações prontas",
    "shorts_por_dia": 1,
    "dias_longos": [1, 4],          # 0 = segunda ... 6 = domingo (terça e sexta)
    "privacidade": "public",
    "categoria_id": "27",
    "descricao": "{descricao}\n\n{hashtags}",
    "hashtags": "",
    "tags": [],
    "playlist_shorts": "",
    "playlist_longos": "",
    "motor": "hyperframes",          # hyperframes | antigo
    # Gravações longas (ex.: da banda) nesta pasta do Drive viram trechos de fundo; sem elas, música gerada.
    "pasta_musicas": "Músicas de fundo",
    "voz": "google",                 # google | elevenlabs (segredo ELEVENLABS_API_KEY)
    "elevenlabs": {},                # vozes: {narrador: "Nome ou ID", personagem: ...}
    "efeito_narrador": "",           # "divino": voz grave, aveludada, com eco de catedral (o roteiro pode trocar)
}


def config(cfg: dict) -> dict:
    return {**PADRAO, **(cfg.get("animacao") or {})}


def fazer_video(rot: A.Roteiro, destino: Path, motor: str = "hyperframes", musica: Path | None = None) -> Path:
    chave = A.chave_tts()
    if not chave:
        log.warning("Sem GOOGLE_TTS_API_KEY: o vídeo sai sem voz (só para teste).")
    if motor == "hyperframes" and H.disponivel():
        return H.renderizar(rot, destino, chave, musica)
    if motor == "hyperframes":
        log.warning("HyperFrames não instalado: usando o motor antigo.")
    return A.renderizar(rot, destino, chave, musica)


def usar_vozes(rot: A.Roteiro, conf: dict) -> None:
    """Com animacao.voz = elevenlabs (ou VOZ_ANIMACAO no teste), troca as vozes do Google pelas do ElevenLabs."""
    motor = (os.environ.get("VOZ_ANIMACAO") or conf.get("voz") or "google").strip().lower()
    if motor != "elevenlabs":
        return
    import elevenlabs
    if not elevenlabs.chave():
        log.warning("Voz ElevenLabs pedida, mas falta o segredo ELEVENLABS_API_KEY: usando o Google.")
        return
    escolhidas = elevenlabs.aplicar(rot, elevenlabs.chave(), (conf.get("elevenlabs") or {}).get("vozes"))
    log.info("Vozes do ElevenLabs: %s.", discreto.Seguro(", ".join(sorted(set(escolhidas.values())))))


def duracao_estimada(rot: A.Roteiro) -> float:
    falas = sum(len(c.falas) for c in rot.cenas)
    return A.caracteres(rot) / 14.5 + falas * A.PAUSA + 1.5


def trechos_de_musica(drive, raiz: str, conf: dict, tmp: Path) -> tuple[str | None, list[dict]]:
    """Corta (uma vez só) as gravações novas da pasta de músicas e devolve (pasta dos trechos, trechos)."""
    pasta = drive.achar(raiz, conf["pasta_musicas"])
    if not pasta or not drive.eh_pasta(pasta):
        return None, []
    pasta_trechos = drive.pasta(pasta["id"], "Trechos")
    indice = drive.ler_json(pasta_trechos, "trechos.json", {"gravacoes": {}, "trechos": []})
    for item in sorted(drive.listar(pasta["id"]), key=lambda i: i["name"]):
        if drive.eh_pasta(item) or not eh_audio(item["name"]) or item["id"] in indice["gravacoes"]:
            continue
        discreto.registrar_item_drive(item, "música")
        n = len(indice["gravacoes"]) + 1
        log.info("Cortando a gravação %d em trechos de música de fundo...", n)
        original = drive.baixar(item["id"], tmp / "gravacao" / f"g{n}{Path(item['name']).suffix}")
        novos = M.cortar(original, tmp / "trechos", prefixo=f"g{n:02d}")
        for t in novos:
            t["id"] = drive.enviar(tmp / "trechos" / t["arquivo"], pasta_trechos, t["arquivo"], "audio/mpeg")
            t["gravacao"] = n
        indice["gravacoes"][item["id"]] = {"numero": n, "trechos": len(novos)}
        indice["trechos"] += novos
        drive.gravar_json(pasta_trechos, "trechos.json", indice)
        original.unlink(missing_ok=True)
        log.info("Gravação %d: %d trechos (%s).", n, len(novos),
                 ", ".join(f"{c} {sum(1 for t in novos if t['clima'] == c)}" for c in ("calma", "alegre", "epica")))
    return pasta_trechos, indice["trechos"]


def musica_para(drive, rot: A.Roteiro, trechos: list[dict], estado: dict, tmp: Path) -> Path | None:
    escolhido = M.escolher(trechos, rot.musica, duracao_estimada(rot), estado.setdefault("musicas", {}))
    if not escolhido:
        return None
    estado["musicas"][escolhido["arquivo"]] = estado["musicas"].get(escolhido["arquivo"], 0) + 1
    log.info("Música de fundo: trecho %s (%s, %d s).", escolhido["arquivo"], escolhido["clima"],
             escolhido["duracao"])
    return drive.baixar(escolhido["id"], tmp / "musica" / escolhido["arquivo"])


def snippet(dados: dict, rot: A.Roteiro, conf: dict, idioma: str = "pt-BR") -> dict:
    valores = {"titulo": rot.titulo, "descricao": str(dados.get("descricao") or "").strip(),
               "hashtags": str(dados.get("hashtags") or conf.get("hashtags") or "").strip()}
    descricao = conf["descricao"]
    for k, v in valores.items():
        descricao = descricao.replace("{" + k + "}", v)
    tags = list(dados.get("tags") or []) + list(conf.get("tags") or [])
    if rot.formato == "short":
        tags.append("Shorts")
    return {"title": " ".join(rot.titulo.split())[:100], "description": descricao.strip()[:5000],
            "categoryId": str(conf.get("categoria_id") or "27"), "tags": tags[:30],
            "defaultLanguage": idioma, "defaultAudioLanguage": idioma}


def _hoje_brasil() -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=3)


def _roteiros(drive, pasta_id: str) -> list[tuple[dict, dict]]:
    """(arquivo, dados) de cada .yaml da pasta, em ordem de nome (01_..., 02_...)."""
    saida = []
    for item in sorted(drive.listar(pasta_id), key=lambda i: i["name"]):
        if drive.eh_pasta(item) or not item["name"].lower().endswith((".yaml", ".yml")):
            continue
        discreto.registrar_item_drive(item, "roteiro")
        try:
            dados = yaml.safe_load(drive.ler_texto(item["id"])) or {}
        except yaml.YAMLError as erro:
            log.warning("Roteiro com erro de formatação, pulado: %s (%s)", item["name"], erro)
            continue
        discreto.registrar_dados(dados, "roteiro")
        saida.append((item, dados))
    return saida


def rodar(drive, youtube, raiz: str, cfg: dict, pedido: str = "", so_drive: bool = False) -> int:
    from google_api import LimiteDiario

    conf = config(cfg)
    pasta = drive.pasta(raiz, conf["pasta_roteiros"])
    publicados_id = drive.pasta(pasta, "Publicados")
    estado = drive.ler_json(raiz, ARQ_ESTADO, {"videos": {}, "dias": {}})
    roteiros = _roteiros(drive, pasta)
    if pedido:
        escolhidos = [r for r in roteiros if pedido.lower() in r[0]["name"].lower()][:1]
        if not escolhidos:
            log.error("Nenhum roteiro com esse nome na pasta de roteiros.")
            return 1
    else:
        hoje = _hoje_brasil()
        feito_hoje = estado["dias"].get(hoje.strftime("%Y-%m-%d"), {})
        querer = {"short": int(conf["shorts_por_dia"]) - feito_hoje.get("short", 0),
                  "longo": (1 if hoje.weekday() in conf["dias_longos"] else 0) - feito_hoje.get("longo", 0)}
        escolhidos = []
        for item, dados in roteiros:
            formato = dados.get("formato", "short")
            if querer.get(formato, 0) > 0:
                escolhidos.append((item, dados))
                querer[formato] -= 1
        faltam = {f: sum(1 for _, d in roteiros if d.get("formato", "short") == f) for f in ("short", "longo")}
        log.info("Animações: %d roteiro(s) na fila (%d Shorts, %d longos); hoje: %d.",
                 len(roteiros), faltam["short"], faltam["longo"], len(escolhidos))
        if faltam["short"] < 7:
            log.warning("Faltam roteiros de Shorts para a próxima semana: hora de mandar mais para a pasta.")
    idioma = (cfg.get("publicacao") or {}).get("idioma", "pt-BR")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        _, trechos = trechos_de_musica(drive, raiz, conf, tmp) if escolhidos else (None, [])
        for n, (item, dados) in enumerate(escolhidos, start=1):
            rot = A.ler_roteiro(dados)
            log.info("Fazendo o vídeo animado %d (%s, %d caracteres de voz)...", n, rot.formato, A.caracteres(rot))
            usar_vozes(rot, conf)
            if not rot.efeito_narrador:
                rot.efeito_narrador = str(os.environ.get("EFEITO_NARRADOR") or conf.get("efeito_narrador") or "")
            trilha = musica_para(drive, rot, trechos, estado, tmp)
            video = fazer_video(rot, tmp / f"v{n}.mp4", conf["motor"], trilha)
            if so_drive:
                pronto = drive.pasta(raiz, conf["pasta_prontos"])
                drive.enviar(video, pronto, item["name"].rsplit(".", 1)[0] + ".mp4", "video/mp4")
                log.info("Vídeo salvo no Drive (pasta de animações prontas).")
                drive.gravar_json(raiz, ARQ_ESTADO, estado)
                continue
            try:
                vid = youtube.enviar_video(video, snippet(dados, rot, conf, idioma),
                                           {"privacyStatus": conf["privacidade"], "selfDeclaredMadeForKids": False})
            except LimiteDiario as motivo:
                log.warning("Limite diário do YouTube (%s); continua amanhã.", motivo)
                break
            log.info("Vídeo animado enviado: %s", vid)
            playlist = conf.get("playlist_shorts" if rot.formato == "short" else "playlist_longos")
            if playlist:
                try:
                    youtube.adicionar_na_playlist(playlist, vid)
                except Exception as erro:
                    log.warning("Vídeo fora da playlist: %s", erro)
            dia = _hoje_brasil().strftime("%Y-%m-%d")
            estado["dias"].setdefault(dia, {})
            estado["dias"][dia][rot.formato] = estado["dias"][dia].get(rot.formato, 0) + 1
            estado["videos"][item["name"]] = {"id": vid, "formato": rot.formato, "dia": dia}
            drive.mover(item["id"], pasta, publicados_id)
            drive.gravar_json(raiz, ARQ_ESTADO, estado)
    return 0


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checar", action="store_true", help="só diz se as animações estão ligadas no canal")
    parser.add_argument("--roteiro", type=discreto.resolver, default="", help="trecho do nome de um roteiro")
    parser.add_argument("--so-drive", action="store_true", help="salva o MP4 no Drive em vez de publicar")
    parser.add_argument("--local", type=Path, help="roteiro YAML no computador (teste)")
    parser.add_argument("--saida", type=Path, default=Path("animacao.mp4"))
    parser.add_argument("--musica", type=Path, help="teste local: trecho de música de fundo")
    args = parser.parse_args()

    if args.local:
        rot = A.ler_roteiro(yaml.safe_load(args.local.read_text(encoding="utf-8")))
        print(fazer_video(rot, args.saida, musica=args.musica))
        return 0
    cfg = carregar_config()
    conf = config(cfg)
    ligado = bool(conf.get("ativo")) or bool(args.roteiro)
    if args.checar:
        saida = os.environ.get("GITHUB_OUTPUT")
        if saida:
            with open(saida, "a") as f:
                f.write(f"ativo={'true' if ligado else 'false'}\n")
        print(f"ativo={'true' if ligado else 'false'}")
        return 0
    if not ligado:
        log.info("Animações desligadas neste canal (canal.yaml > animacao > ativo).")
        return 0
    from google_api import Drive, YouTube, credenciais_do_ambiente
    credenciais = credenciais_do_ambiente()
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    return rodar(Drive(credenciais), YouTube(credenciais), raiz, cfg, args.roteiro, args.so_drive)


if __name__ == "__main__":
    sys.exit(main())
