"""Extras do canal, depois dos capítulos do dia: livro completo, legendas e Shorts.

Ordem de prioridade (a cota diária do YouTube e o tempo da máquina são divididos assim):
  1. legendas dos capítulos já publicados (a transcrição de áudio longo é salva aos pedaços);
  2. Shorts (trecho de 35–55 s com legenda grande) dos capítulos já publicados;
  3. livro completo (vídeos de até ~11h com marcadores) para livros com todos os capítulos publicados.
Cada um tem um limite por dia no config.yaml (seção "extras"). Se o YouTube disser que acabou a cota,
o robô para e continua no dia seguinte, de onde parou.

Uso:
  python src/extras.py                  # GitHub Actions, todo dia
  python src/extras.py --dry-run        # só mostra o que faria
  python src/extras.py --livro "Despertar" --so shorts
"""

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

import discreto
from comum import carregar_config, configurar_log, log, normalizar, pausado


def _pronto_para_completo(livro, estado: dict) -> bool:
    return (len(livro.capitulos) >= 2 and not livro.incompleto and not livro.a_cortar and not livro.problemas
            and not any(c.problema for c in livro.capitulos)
            and all(str(c.numero) in estado["capitulos"] for c in livro.capitulos)
            and not estado.get("completo", {}).get("concluido"))


def _alternar(listas: list[list]) -> list:
    """[[a1,a2],[b1]] -> [a1,b1,a2]: um capítulo de cada livro por vez."""
    saida, i = [], 0
    while any(i < len(l) for l in listas):
        saida += [l[i] for l in listas if i < len(l)]
        i += 1
    return saida


PASTA_PREVIAS = "Prévias de Shorts"


def rodar_extras(drive, youtube, raiz: str, cfg: dict, livro_filtro: str | None = None, so: str | None = None,
                 dry_run: bool = False, quantos: int | None = None, previa: bool = False,
                 saida_previas: Path | None = None) -> int:
    """previa=True: só gera os Shorts e põe o MP4 no Drive (pasta "Prévias de Shorts"), sem YouTube e sem cota."""
    from completo import publicar_livro_completo
    from google_api import LimiteDiario, SemPermissao
    from legendas import enviar_legenda
    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros, pedido_casa, privacidade_do_livro
    from main import filtrar_fila
    from shorts import gerar_short, merece_short, publicar_short
    from cortar import Palavra
    from transcrever import TempoEsgotado, baixar_capitulo, palavras_do_capitulo

    ext = cfg.get("extras") or {}
    if ext.get("ativo") is False:
        log.info("Extras desligados no config.yaml.")
        return 0
    quer = lambda nome: so in (None, nome)  # noqa: E731
    partes_restantes = ext.get("partes_completo_por_dia", 2) if ext.get("livro_completo", True) and quer("completo") else 0
    legendas_restantes = ext.get("legendas_por_dia", 5) if quer("legendas") else 0
    shorts_restantes = ext.get("shorts_por_dia", 3) if quer("shorts") else 0
    if quantos is not None:   # pedido manual: o mesmo número para o que foi escolhido
        partes_restantes, legendas_restantes, shorts_restantes = (
            quantos if partes_restantes else 0, quantos if legendas_restantes else 0, quantos if shorts_restantes else 0)
    if previa:   # prévia = só Shorts, nada vai para o YouTube
        partes_restantes = legendas_restantes = 0
        pasta_previas = drive.pasta(raiz, PASTA_PREVIAS) if not dry_run else None
    prazo_total = time.monotonic() + ext.get("minutos_maximos", 150) * 60
    # legendas e Shorts têm um pedaço do tempo; o resto fica para o livro completo
    prazo = min(prazo_total, time.monotonic() + ext.get("minutos_legendas_shorts", 80) * 60)
    modelo = cfg["corte"]["modelo_whisper"]
    idioma = cfg["publicacao"]["idioma"]

    pastas = pastas_de_livros(drive, raiz)
    pastas = ([p for p in pastas if pedido_casa(livro_filtro, p["name"])] if livro_filtro
              else filtrar_fila(pastas, cfg["publicacao"].get("livros") or []))
    livros = []
    for pasta in pastas:
        livro = carregar_livro(drive, pasta)
        if not livro or livro.ficha.get("ativo") is False or pausado(cfg, pasta["name"]):
            continue
        privacidade = privacidade_do_livro(livro.ficha)
        if ext.get("apenas_publicos") and privacidade != "public":
            continue
        estado = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
        if estado["capitulos"]:
            livros.append((livro, estado, privacidade))

    feitos = {"partes": 0, "legendas": 0, "shorts": 0}
    try:
        # 1) e 2) Legendas e Shorts, capítulo por capítulo (alternando os livros)
        if legendas_restantes > 0 or shorts_restantes > 0:
            por_livro = []
            for livro, estado, privacidade in livros:
                itens = []
                for c in livro.capitulos:
                    reg = estado["capitulos"].get(str(c.numero))
                    if not reg:
                        continue
                    # vídeo com vários capítulos: uma legenda só, feita a partir do primeiro capítulo dele
                    falta_leg = not reg.get("legenda") and (not reg.get("parte") or reg.get("grupo") == c.numero)
                    falta_short = (previa or not reg.get("short")) and merece_short(c.numero, c.titulo)
                    if falta_leg or falta_short:
                        itens.append((livro, estado, privacidade, c, reg))
                por_livro.append(itens)

            for livro, estado, privacidade, cap, reg in _alternar(por_livro):
                fazer_leg = (legendas_restantes > 0 and not reg.get("legenda")
                             and (not reg.get("parte") or reg.get("grupo") == cap.numero))
                fazer_short = (shorts_restantes > 0 and (previa or not reg.get("short"))
                               and merece_short(cap.numero, cap.titulo))
                if not (fazer_leg or fazer_short):
                    continue
                if (legendas_restantes <= 0 and shorts_restantes <= 0) or time.monotonic() > prazo:
                    break
                log.info("Extras de '%s' – capítulo %d:%s%s", livro.nome, cap.numero,
                         " legenda" if fazer_leg else "", " short" if fazer_short else "")
                if dry_run:
                    legendas_restantes -= fazer_leg
                    shorts_restantes -= fazer_short
                    continue
                with tempfile.TemporaryDirectory() as tmp:
                    tmp = Path(tmp)
                    audio = baixar_capitulo(drive, cap, tmp)
                    try:
                        palavras = palavras_do_capitulo(drive, livro, cap, audio, modelo, prazo)
                    except TempoEsgotado as onde:
                        log.info("Tempo dos extras acabou no meio da transcrição (%s); continua amanhã.", onde)
                        break
                    if fazer_leg:
                        membros = [(c, estado["capitulos"][str(c.numero)]) for c in livro.capitulos
                                   if estado["capitulos"].get(str(c.numero), {}).get("video_id") == reg["video_id"]]
                        palavras_video = palavras
                        if len(membros) > 1:
                            palavras_video = []
                            for c, r in membros:
                                ps = palavras if c is cap else palavras_do_capitulo(
                                    drive, livro, c, baixar_capitulo(drive, c, tmp / f"m{c.numero}"), modelo, prazo)
                                ini = float(r.get("inicio", 0))
                                palavras_video += [Palavra(p.texto, p.inicio + ini, p.fim + ini) for p in ps]
                        try:
                            if enviar_legenda(youtube, cap, reg, palavras_video, tmp, idioma):
                                feitos["legendas"] += 1
                            legendas_restantes -= 1
                            for _, r in membros:
                                r["legenda"] = reg.get("legenda")
                        except SemPermissao:
                            log.warning("A autorização atual não permite enviar legendas. Autorize de novo "
                                        "(scripts/autorizar.py) e troque o segredo GOOGLE_REFRESH_TOKEN no GitHub. "
                                        "Legendas puladas hoje.")
                            legendas_restantes = 0
                        drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)
                    if fazer_short and previa:
                        capa = drive.baixar(livro.capa["id"], tmp / f"capa{Path(livro.capa['name']).suffix}") if livro.capa else None
                        video, duracao = gerar_short(livro, cap, audio, palavras, capa, cfg, tmp)
                        if video:
                            nome = f"{livro.ficha['titulo']} - Cap {cap.numero}.mp4".replace("/", "-")
                            existente = drive.achar(pasta_previas, nome)
                            if existente:
                                drive.lixeira(existente["id"])
                            drive.enviar(video, pasta_previas, nome=nome, mime="video/mp4")
                            if saida_previas:
                                saida_previas.mkdir(parents=True, exist_ok=True)
                                shutil.copy(video, saida_previas / nome)
                            log.info("  prévia no Drive: %s › %s (%.0f s)", PASTA_PREVIAS, nome, duracao)
                            feitos["shorts"] += 1
                        shorts_restantes -= 1
                        drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)   # guarda a transcrição feita
                    elif fazer_short:
                        capa = drive.baixar(livro.capa["id"], tmp / f"capa{Path(livro.capa['name']).suffix}") if livro.capa else None
                        if publicar_short(youtube, livro, cap, reg, estado, audio, palavras, capa, cfg, privacidade, tmp):
                            feitos["shorts"] += 1
                        shorts_restantes -= 1
                        drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)
        # 3) Livro completo (por último: leva mais de uma hora por parte e não pode atrasar as legendas)
        for livro, estado, privacidade in livros:
            if partes_restantes <= 0 or time.monotonic() > prazo_total:
                break
            if not _pronto_para_completo(livro, estado):
                continue
            if dry_run:
                log.info("[dry-run] faria o livro completo de '%s'.", livro.nome)
                continue
            n = publicar_livro_completo(drive, youtube, livro, estado, cfg, privacidade, partes_restantes)
            partes_restantes -= n
            feitos["partes"] += n

    except LimiteDiario as motivo:
        log.warning("Limite diário do YouTube (%s). Os extras continuam amanhã.", motivo)
        for livro, estado, _ in livros:
            drive.gravar_json(livro.pasta["id"], ARQ_PUBLICADOS, estado)

    log.info("Extras nesta execução: %d parte(s) de livro completo, %d legenda(s), %d Short(s).",
             feitos["partes"], feitos["legendas"], feitos["shorts"])
    return 0


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--livro", type=discreto.resolver, help="número do livro no log ou trecho do nome da pasta")
    parser.add_argument("--so", choices=["completo", "legendas", "shorts"])
    parser.add_argument("--quantos", type=int, help="quantos fazer agora (no lugar do limite diário)")
    parser.add_argument("--previa", action="store_true", help="Shorts só no Drive (Prévias de Shorts), sem YouTube")
    parser.add_argument("--saida-previas", type=Path, help="também copia as prévias para esta pasta local")
    args = parser.parse_args()

    from google_api import Drive, YouTube, credenciais_do_ambiente
    credenciais = credenciais_do_ambiente()
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    return rodar_extras(Drive(credenciais), YouTube(credenciais), raiz, carregar_config(), args.livro, args.so,
                        args.dry_run, args.quantos, args.previa, args.saida_previas)


if __name__ == "__main__":
    sys.exit(main())
