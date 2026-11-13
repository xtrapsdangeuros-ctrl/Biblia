"""Publica o(s) próximo(s) capítulo(s) da fila no YouTube.

Uso:
  python src/main.py                     # publica o capítulo do dia (GitHub Actions)
  python src/main.py --dry-run           # gera vídeo, miniatura e textos sem enviar nada
  python src/main.py --livro "01 - Noite de Vigília" --capitulo 3
  python src/main.py --teste-local capa.jpg audio.mp3 --ficha livro.yaml   # testa sem Google
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

import discreto
from comum import carregar_config, configurar_log, ler_nome_capitulo, log, normalizar, pausado
from metadados import descricao_playlist, intervalo, livro_e_autor, rotulo_e_titulo, snippet_video, titulo_playlist
from video import duracao_audio, gerar_arte, gerar_video


def produzir_miniatura(capa: Path | None, ficha: dict, numero: int, titulo_cap: str, destino: Path, cfg: dict) -> Path:
    rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
    return gerar_arte(capa, destino, ficha["titulo"], ficha.get("autor") or "", rotulo, titulo,
                      1280, 720, cfg["video"], miniatura=True)


def produzir(capa: Path | None, audios: list[Path], ficha: dict, numero: int, titulo_cap: str, pasta: Path, cfg: dict) -> tuple[Path, Path]:
    rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
    cores = cfg["video"]
    autor = ficha.get("autor") or ""
    arte = gerar_arte(capa, pasta / "arte.png", ficha["titulo"], autor, rotulo, titulo,
                      cores["largura"], cores["altura"], cores)
    miniatura = produzir_miniatura(capa, ficha, numero, titulo_cap, pasta / "miniatura.jpg", cfg)
    log.info("Renderizando vídeo...")
    return gerar_video(arte, audios, pasta / "video.mp4", cores.get("copiar_audio", True)), miniatura


def publicar_capitulo(drive, youtube, livro, capitulo, estado: dict, cfg: dict, dry_run: bool) -> None:
    publicar_grupo(drive, youtube, livro, [capitulo], estado, cfg, dry_run, minutos_alvo=0)


def publicar_grupo(drive, youtube, livro, capitulos: list, estado: dict, cfg: dict, dry_run: bool,
                   minutos_alvo: float = 0) -> list:
    """Publica um vídeo com um ou mais capítulos seguidos do livro.

    Com minutos_alvo > 0, junta capítulos da lista (em ordem) enquanto a soma couber no alvo; um capítulo nunca é
    cortado no meio, e o primeiro entra mesmo se for mais longo. Devolve os capítulos que entraram no vídeo."""
    from livro import ARQ_PUBLICADOS, privacidade_do_livro

    pub = cfg["publicacao"]
    cta = cfg.get("cta") or {}
    privacidade = privacidade_do_livro(livro.ficha)
    ficha = livro.ficha
    if estado.get("playlist_id") and not dry_run:
        feitos = set()
        for numero, reg in sorted(estado["capitulos"].items(), key=lambda kv: int(kv[0])):
            if reg.get("playlist"):
                feitos.add(reg["video_id"])
            elif reg["video_id"] in feitos:   # vídeo com vários capítulos: já foi colocado
                reg["playlist"] = True
            else:
                try:
                    youtube.adicionar_na_playlist(estado["playlist_id"], reg["video_id"])
                    reg["playlist"] = True
                    feitos.add(reg["video_id"])
                    log.info("Capítulo %s colocado na playlist (tinha ficado de fora).", numero)
                except Exception as erro:
                    log.warning("Capítulo %s ainda fora da playlist: %s", numero, erro)
    anteriores = [v for k, v in sorted(estado["capitulos"].items(), key=lambda kv: int(kv[0]))
                  if int(k) < capitulos[0].numero]
    anterior_id = anteriores[-1]["video_id"] if anteriores else None

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        capa = drive.baixar(livro.capa["id"], tmp / livro.capa["name"]) if livro.capa else None

        # baixa capítulo por capítulo até completar o tempo do vídeo
        usados, audios, inicios, total = [], [], [], 0.0
        for i, cap in enumerate(capitulos):
            arquivos = [drive.baixar(a["id"], tmp / "partes" / f"{i:03d}_{j:02d}_{a['name']}")
                        for j, a in enumerate(cap.arquivos)]
            duracao = sum(duracao_audio(a) for a in arquivos)
            if usados and (not minutos_alvo or total + duracao > minutos_alvo * 60):
                break
            usados.append(cap)
            audios += arquivos
            inicios.append(total)
            total += duracao
            if not minutos_alvo:
                break

        grupo = len(usados) > 1
        parte = None
        if grupo:
            parte = 1 + len({r["video_id"] for r in estado["capitulos"].values() if r.get("parte")})
        capitulos_tempo = [(c.numero, c.titulo, ini) for c, ini in zip(usados, inicios)]
        snippet = snippet_video(ficha, capitulos_tempo, parte, estado.get("playlist_id"), anterior_id, pub, cta, total)

        if grupo:
            rotulo, titulo = f"Parte {parte}", intervalo([(c.numero, c.titulo) for c in usados])
        else:
            rotulo, titulo = rotulo_e_titulo(usados[0].numero, usados[0].titulo)
        cores = cfg["video"]
        nome_livro, nome_autor = livro_e_autor(ficha)   # a capa mostra "Despertar", não "Ricardo Montemor Despertar"
        arte = gerar_arte(capa, tmp / "arte.png", nome_livro, nome_autor, rotulo, titulo,
                          cores["largura"], cores["altura"], cores)
        miniatura = gerar_arte(capa, tmp / "miniatura.jpg", nome_livro, nome_autor, rotulo,
                               titulo, 1280, 720, cores, miniatura=True)
        status = {
            "privacyStatus": privacidade,
            "selfDeclaredMadeForKids": bool(ficha.get("para_criancas", False)),
            "containsSyntheticMedia": bool(ficha.get("voz_sintetica", False)),
        }
        log.info("Título: %s (%s, %d capítulo(s), %.0f min)", snippet["title"], privacidade, len(usados), total / 60)
        if dry_run:
            log.info("[dry-run] nada foi enviado. Descrição:\n%s", snippet["description"])
            return usados

        log.info("Renderizando vídeo...")
        video = gerar_video(arte, audios, tmp / "video.mp4", cfg["video"].get("copiar_audio", True))
        video_id = youtube.enviar_video(video, snippet, status)
        log.info("Vídeo enviado: %s", video_id)
        # Grava logo após o envio: se algo abaixo falhar, os capítulos não são enviados de novo amanhã.
        agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
        registros = []
        for cap, ini in zip(usados, inicios):
            registro = {"video_id": video_id, "arquivos": [a["name"] for a in cap.arquivos], "data": agora}
            if grupo:
                registro.update(inicio=round(ini, 1), parte=parte, grupo=usados[0].numero,
                                duracao_total=round(total, 1))
            estado["capitulos"][str(cap.numero)] = registro
            registros.append(registro)
        drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)

        try:
            youtube.definir_miniatura(video_id, miniatura)
        except Exception as erro:  # canal não verificado não aceita miniatura personalizada
            log.warning("Não consegui definir a miniatura (o canal está verificado?): %s", erro)

        try:
            if not estado.get("playlist_id"):
                estado["playlist_id"] = youtube.criar_playlist(
                    titulo_playlist(ficha), descricao_playlist(ficha), privacidade)
            youtube.adicionar_na_playlist(estado["playlist_id"], video_id)
            for registro in registros:
                registro["playlist"] = True
        except Exception as erro:
            log.warning("Não consegui adicionar à playlist: %s", erro)
        divulgar(youtube, cfg, estado, registros, video_id, anterior_id, privacidade)
        drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)
    return usados


def divulgar(youtube, cfg: dict, estado: dict, registros: list[dict], video_id: str, anterior_id: str | None,
             privacidade: str) -> None:
    """Depois do envio: link 'Próximo' no vídeo anterior e comentário com o link da playlist (50 unidades cada).
    Nada disso pode impedir a publicação: qualquer erro só fica registrado no log."""
    from corrigir_seo import snippet_atual, texto_comentario
    from google_api import SemPermissao
    from metadados import com_proximo

    if anterior_id:
        try:
            anterior = youtube.ler_videos([anterior_id])
            if anterior:
                atual = snippet_atual(anterior[0])
                nova = com_proximo(atual["description"], video_id)
                if nova != atual["description"]:
                    youtube.atualizar_metadados(anterior_id, {**atual, "description": nova})
                    log.info("Link do próximo vídeo colocado em %s", anterior_id)
        except Exception as erro:
            log.warning("Não consegui pôr o link do próximo vídeo no anterior: %s", erro)
    seo = cfg.get("seo") or {}
    if privacidade == "public" and estado.get("playlist_id") and seo.get("comentar_playlist", True):
        try:
            comentario = youtube.comentar(video_id, texto_comentario(estado["playlist_id"], cfg.get("cta") or {}))
            for registro in registros:
                registro["comentario"] = comentario
        except SemPermissao:
            log.info("Comentário com a playlist pulado: a autorização atual não permite comentar.")
        except Exception as erro:
            log.warning("Não consegui comentar o link da playlist: %s", erro)


def avisar_actions(nome: str, valor: str) -> None:
    """Passa um valor para os próximos passos do GitHub Actions (steps.<id>.outputs.<nome>)."""
    saida = os.environ.get("GITHUB_OUTPUT")
    if saida:
        with open(saida, "a", encoding="utf-8") as f:
            f.write(f"{nome}={valor}\n")


def filtrar_fila(pastas: list[dict], livros: list[str]) -> list[dict]:
    """Se config.publicacao.livros tiver nomes, só esses livros entram, na ordem da lista."""
    if not livros:
        return pastas
    fila = []
    for trecho in livros:
        achadas = [p for p in pastas if normalizar(trecho) in normalizar(p["name"]) and p not in fila]
        if not achadas:
            log.warning("Nenhuma pasta do Drive tem '%s' no nome (config.yaml > publicacao > livros).", trecho)
        fila += achadas
    return fila


def rodar_drive(args, cfg: dict) -> int:
    from google_api import Drive, YouTube, credenciais_do_ambiente
    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros, pedido_casa

    credenciais = credenciais_do_ambiente()
    drive, youtube = Drive(credenciais), YouTube(credenciais)
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    import biblia
    if biblia.ligado(cfg):   # canal da Bíblia: um dia do plano por vídeo (o campo "capítulo" vira o dia)
        return biblia.rodar(drive, youtube, raiz, cfg, args.dry_run, args.capitulo, args.quantos)

    from google_api import LimiteDiario

    if args.capitulo is not None:
        restantes = 1
    elif args.quantos is not None:
        restantes = args.quantos if args.quantos > 0 else 10**6   # 0 = todos os pendentes
    else:
        restantes = cfg["publicacao"].get("videos_por_dia") or cfg["publicacao"]["capitulos_por_dia"]
    publicados_agora = 0
    problemas_graves = False

    pastas = pastas_de_livros(drive, raiz)
    if not args.livro:
        pastas = filtrar_fila(pastas, cfg["publicacao"].get("livros") or [])

    # 1) Quais livros têm o que publicar agora
    filas = []   # (livro, estado, pendentes)
    estados = []
    for pasta in pastas:
        if args.livro and not pedido_casa(args.livro, pasta["name"], exato=True):
            continue
        livro = carregar_livro(drive, pasta)
        if not livro:
            continue
        if livro.ficha.get("ativo") is False or pausado(cfg, pasta["name"]):
            log.info("'%s' está pausado (ativo: false).", livro.nome)
            continue
        estado = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
        estados.append(estado)
        pendentes = [c for c in livro.capitulos if str(c.numero) not in estado["capitulos"]]
        if args.capitulo is not None:
            pendentes = [c for c in livro.capitulos if c.numero == args.capitulo]
        if not pendentes:
            continue
        if livro.problemas:
            log.error("'%s' não pode ser publicado:\n%s", livro.nome, "\n".join(f"  - {p}" for p in livro.problemas))
            problemas_graves = True
            continue
        if args.capitulo is None and livro.a_cortar:
            log.info("'%s' ainda tem arquivo(s) esperando o corte (%s); aguardando para não publicar fora de ordem.",
                     livro.nome, ", ".join(i["name"] for i in livro.a_cortar))
            continue
        if args.capitulo is None and livro.incompleto:
            log.info("'%s' ainda não está completo: %s.", livro.nome, livro.incompleto)
            continue
        filas.append([livro, estado, pendentes])

    # Execução automática repetida no mesmo dia (o GitHub às vezes atrasa ou dispara de novo): desconta o que
    # já saiu hoje, para não publicar o dobro.
    if not args.livro and args.capitulo is None and args.quantos is None and not args.dry_run:
        hoje = datetime.now(timezone.utc).date().isoformat()
        ja_hoje = {r["video_id"] for e in estados for r in e["capitulos"].values()
                   if str(r.get("data", "")).startswith(hoje)}
        if ja_hoje:
            log.info("Já saíram %d vídeo(s) hoje; o limite do dia é %d.", len(ja_hoje), restantes)
            restantes -= len(ja_hoje)
            if restantes <= 0:
                avisar_actions("ja_feito", "true")   # execução de reserva: o dia já foi feito, pula o resto

    # 2) Ordem de publicação: um livro por vez, ou um capítulo de cada livro por vez
    alternado = cfg["publicacao"].get("modo") == "alternado" and not args.livro
    if alternado and filas:
        log.info("Publicando alternado entre %d livro(s): %s", len(filas), "; ".join(f[0].nome for f in filas))

    # Vídeos longos: junta capítulos seguidos até ~minutos_por_video (0 = um capítulo por vídeo).
    minutos_alvo = 0 if args.capitulo is not None else float(cfg["publicacao"].get("minutos_por_video") or 0)
    while restantes > 0 and filas:
        fila = filas[0]
        livro, estado, pendentes = fila
        capitulo = pendentes[0]
        if capitulo.problema:
            log.error("'%s' parou no capítulo %d: %s. Corrija no Drive; o robô continua dali.",
                      livro.nome, capitulo.numero, capitulo.problema)
            problemas_graves = True
            filas.pop(0)
            continue
        candidatos = []
        for c in pendentes:
            if c.problema:
                break
            candidatos.append(c)
        log.info("Publicando '%s' a partir do capítulo %d", livro.nome, capitulo.numero)
        for c in candidatos[:1] if not minutos_alvo else candidatos:
            if c.aviso:
                log.warning("Capítulo %d: %s", c.numero, c.aviso)
        try:
            usados = publicar_grupo(drive, youtube, livro, candidatos, estado, cfg, args.dry_run, minutos_alvo)
            del pendentes[:len(usados)]
        except LimiteDiario as motivo:
            log.warning("O YouTube atingiu o limite diário de envios (%s) depois de %d vídeo(s) nesta execução. "
                        "O restante continua amanhã.", motivo, publicados_agora)
            return 1 if problemas_graves else 0
        restantes -= 1
        publicados_agora += 1
        filas.pop(0)
        if pendentes:
            # alternado: o livro vai para o fim da fila; sequencial: continua na frente
            filas.append(fila) if alternado else filas.insert(0, fila)

    log.info("Vídeos publicados nesta execução: %d", publicados_agora)
    if restantes > 0 and not problemas_graves:
        log.info("Nada mais para publicar hoje.")
    return 1 if problemas_graves else 0


def rodar_local(args, cfg: dict) -> int:
    """Gera vídeo e textos a partir de arquivos locais, sem acessar o Google."""
    capa, audio = args.teste_local
    capa = capa if str(capa) not in ("", ".") else None   # "" = sem capa (fundo liso)
    ficha = yaml.safe_load(args.ficha.read_text(encoding="utf-8")) if args.ficha else {
        "titulo": "Livro de Teste", "autor": "Autor de Teste", "licenca": "proprio"}
    numero, titulo = ler_nome_capitulo(audio.name) or (1, "")
    saida = args.saida or Path("saida_teste")
    saida.mkdir(parents=True, exist_ok=True)
    video, miniatura = produzir(capa, [audio], ficha, numero, titulo, saida, cfg)
    pub = cfg["publicacao"]
    print("Título:   ", titulo_video(ficha, numero, titulo))
    print("Tags:     ", tags_video(ficha))
    print("Descrição:\n" + descricao_video(ficha, numero, titulo, "PLAYLIST_ID", "VIDEO_ANTERIOR"))
    print(f"\nArquivos: {video}  {miniatura}  {saida / 'arte.png'}")
    return 0


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="gera tudo mas não envia nada")
    parser.add_argument("--livro", type=discreto.resolver, help="número do livro no log ou nome exato da pasta")
    parser.add_argument("--capitulo", type=int, help="número do capítulo (republica mesmo que já tenha ido)")
    parser.add_argument("--quantos", type=int, help="quantos capítulos publicar agora (0 = todos os pendentes)")
    parser.add_argument("--teste-local", nargs=2, type=Path, metavar=("CAPA", "AUDIO"))
    parser.add_argument("--ficha", type=Path, help="ficha YAML para o teste local")
    parser.add_argument("--saida", type=Path, help="pasta de saída do teste local")
    args = parser.parse_args()
    cfg = carregar_config()
    if args.capitulo is not None and not args.livro and not str(cfg.get("modo") or "") == "biblia":
        parser.error("--capitulo precisa de --livro")
    return rodar_local(args, cfg) if args.teste_local else rodar_drive(args, cfg)


if __name__ == "__main__":
    sys.exit(main())
