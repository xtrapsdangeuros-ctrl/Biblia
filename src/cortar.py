"""Corta arquivos de áudio que contêm vários capítulos.

Ordem de tentativa:
  1. marcações de capítulo embutidas no arquivo (.m4b e alguns MP3);
  2. reconhecimento de voz (faster-whisper): procura "Capítulo N" dito logo após uma pausa;
  3. cada corte é levado para o meio do silêncio mais próximo, para não cortar palavra.

Uso:
  python src/cortar.py --drive                 # processa a pasta do Drive (usado no GitHub Actions)
  python src/cortar.py arquivo.mp3 --dry-run   # só mostra os capítulos encontrados
  python src/cortar.py arquivo.mp3 --saida pasta/
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from comum import carregar_config, configurar_log, log, nome_arquivo_capitulo
from numeros import ler_numero, limpar_token
from video import duracao_audio

PROLOGOS = {"prologo", "prefacio", "introducao", "apresentacao"}
EPILOGOS = {"epilogo", "posfacio"}
_ROTULOS_ESPECIAIS = {
    "prologo": "Prólogo", "prefacio": "Prefácio", "introducao": "Introdução",
    "apresentacao": "Apresentação", "epilogo": "Epílogo", "posfacio": "Posfácio",
}
_FIM_DE_FRASE = (".", "!", "?", ":", "…")


@dataclass
class Palavra:
    texto: str
    inicio: float
    fim: float


@dataclass
class Marcador:
    inicio: float
    tipo: str            # capitulo | prologo | epilogo
    numero: int | None
    titulo: str


@dataclass
class CapituloCortado:
    numero: int
    titulo: str
    inicio: float
    fim: float
    tipo: str = "capitulo"

    @property
    def duracao(self) -> float:
        return self.fim - self.inicio


class ErroCorte(Exception):
    """Detecção duvidosa: o arquivo não deve ser publicado."""


# ---------------------------------------------------------------- detecção por voz

def _coletar_titulo(palavras: list[Palavra], i: int, max_palavras: int = 8, pausa_fim: float = 0.6) -> str:
    """Pega as palavras ditas logo depois do número, se forem seguidas de uma pausa (jeito de quem lê um título)."""
    if i >= len(palavras):
        return ""
    # Silêncio muito longo depois do número: o que vem já não é o título.
    if palavras[i].inicio - palavras[i - 1].fim > 4.0:
        return ""
    titulo = []
    for j in range(i, min(i + max_palavras + 1, len(palavras))):
        p = palavras[j]
        if j > i and p.inicio - palavras[j - 1].fim >= pausa_fim:
            break
        titulo.append(p.texto.strip())
        if p.texto.strip().endswith(_FIM_DE_FRASE):
            break
    else:
        return ""  # não houve pausa: provavelmente já é o texto do capítulo
    if len(titulo) > max_palavras:
        return ""
    texto = " ".join(titulo).strip(" .,;:!?…-–—")
    return texto[:1].upper() + texto[1:]


def encontrar_marcadores(palavras: list[Palavra], palavra_capitulo: str = "capitulo",
                         pausa_min: float = 1.5) -> list[Marcador]:
    alvo = limpar_token(palavra_capitulo)
    marcadores = []
    for i, p in enumerate(palavras):
        pausa = p.inicio - palavras[i - 1].fim if i else float("inf")
        if pausa < pausa_min:
            continue
        token = limpar_token(p.texto)
        if token == alvo:
            seguintes = [limpar_token(w.texto) for w in palavras[i + 1:i + 7]]
            lido = ler_numero(seguintes)
            if not lido:
                continue
            numero, usados = lido
            marcadores.append(Marcador(p.inicio, "capitulo", numero, _coletar_titulo(palavras, i + 1 + usados)))
        elif token in PROLOGOS:
            marcadores.append(Marcador(p.inicio, "prologo", 0, _ROTULOS_ESPECIAIS[token]))
        elif token in EPILOGOS:
            marcadores.append(Marcador(p.inicio, "epilogo", None, _ROTULOS_ESPECIAIS[token]))
    return marcadores


def transcrever(audio: Path, modelo: str) -> list[Palavra]:
    from faster_whisper import WhisperModel

    log.info("Transcrevendo %s com o modelo '%s' (pode levar um tempo)...", audio.name, modelo)
    whisper = WhisperModel(modelo, device="cpu", compute_type="int8")
    segmentos, info = whisper.transcribe(
        str(audio), language="pt", word_timestamps=True, vad_filter=True,
        beam_size=1, condition_on_previous_text=False,
    )
    palavras = []
    for seg in segmentos:
        palavras += [Palavra(w.word, w.start, w.end) for w in (seg.words or [])]
        if len(palavras) % 5000 < len(seg.words or []):
            log.info("  ... %.0f de %.0f min transcritos", seg.end / 60, info.duration / 60)
    return palavras


# ---------------------------------------------------------------- marcações embutidas e silêncio

def capitulos_embutidos(audio: Path) -> list[CapituloCortado]:
    saida = subprocess.run(
        ["ffprobe", "-v", "error", "-show_chapters", "-of", "json", str(audio)],
        check=True, capture_output=True, text=True,
    ).stdout
    capitulos = json.loads(saida).get("chapters", [])
    if len(capitulos) < 2:
        return []
    resultado = []
    for n, c in enumerate(capitulos, start=1):
        titulo = (c.get("tags") or {}).get("title", "").strip()
        resultado.append(CapituloCortado(n, titulo, float(c["start_time"]), float(c["end_time"])))
    return resultado


def detectar_silencios(audio: Path, ruido_db: int = -35, minimo: float = 0.4) -> list[tuple[float, float]]:
    saida = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(audio), "-af",
         f"silencedetect=noise={ruido_db}dB:d={minimo}", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    inicios = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", saida)]
    fins = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", saida)]
    return list(zip(inicios, fins))


def ajustar_ao_silencio(t: float, silencios: list[tuple[float, float]], janela: float = 5.0) -> float:
    """Leva o corte para o meio do silêncio que termina logo antes (ou perto) da fala do marcador."""
    candidatos = [(s, e) for s, e in silencios if t - janela <= e <= t + 0.3]
    if not candidatos:
        return max(0.0, t - 0.3)
    s, e = max(candidatos, key=lambda se: se[1])
    return max(0.0, (max(s, 0.0) + e) / 2)


# ---------------------------------------------------------------- montagem e travas de segurança

def montar_capitulos(marcadores: list[Marcador], duracao: float, silencios: list[tuple[float, float]]) -> list[CapituloCortado]:
    marcadores = sorted(marcadores, key=lambda m: m.inicio)
    capitulos = []
    for i, m in enumerate(marcadores):
        inicio = 0.0 if i == 0 else ajustar_ao_silencio(m.inicio, silencios)
        numero = m.numero
        if m.tipo == "epilogo":
            numero = (capitulos[-1].numero + 1) if capitulos else 1
        capitulos.append(CapituloCortado(numero, m.titulo, inicio, duracao, m.tipo))
        if i:
            capitulos[i - 1].fim = inicio
    return capitulos


def validar(marcadores: list[Marcador], capitulos: list[CapituloCortado], cfg: dict) -> list[str]:
    erros = []
    if not capitulos:
        return ["não encontrei nenhum 'Capítulo N' falado no áudio"]
    primeiro = min(m.inicio for m in marcadores) if marcadores else 0
    if primeiro > cfg["max_intro_seg"]:
        erros.append(
            f"o primeiro capítulo só aparece em {formatar_tempo(primeiro)}; "
            "o começo do arquivo pode ser continuação de outro capítulo"
        )
    tipos = [m.tipo for m in sorted(marcadores, key=lambda m: m.inicio)]
    if "prologo" in tipos[1:]:
        erros.append("encontrei um prólogo/introdução no meio do arquivo")
    if "epilogo" in tipos[:-1]:
        erros.append("encontrei um epílogo antes do fim do arquivo")

    numeros = [c.numero for c in capitulos if c.tipo == "capitulo"]
    for anterior, atual in zip(numeros, numeros[1:]):
        if atual != anterior + 1:
            erros.append(f"a sequência pulou ou repetiu: capítulo {anterior} seguido do {atual}")
    if tipos and tipos[0] == "prologo" and numeros and numeros[0] != 1:
        erros.append(f"depois do prólogo esperava o capítulo 1, veio o {numeros[0]}")

    for c in capitulos:
        if c.duracao < cfg["min_capitulo_seg"]:
            erros.append(
                f"o capítulo {c.numero} ficou com só {c.duracao:.0f}s "
                f"(em {formatar_tempo(c.inicio)}); pode ser uma citação de 'capítulo' no meio do texto"
            )
    return erros


def formatar_tempo(seg: float) -> str:
    h, resto = divmod(int(seg), 3600)
    m, s = divmod(resto, 60)
    return f"{h}:{m:02d}:{s:02d}"


# Palavras da última transcrição feita por detectar(); o corte guarda no Drive para as legendas.
ultimas_palavras: list[Palavra] = []
# Quando o corte roda pelo Drive: (drive, pasta das transcrições, nome do arquivo parcial, prazo). Com isso a
# transcrição de um arquivo enorme é salva aos pedaços e continua no dia seguinte, em vez de recomeçar do zero.
retomar: tuple | None = None


def palavras_de_cada_capitulo(palavras: list[Palavra], capitulos: list[CapituloCortado]) -> dict[int, list[Palavra]]:
    """Separa a transcrição do arquivo inteiro por capítulo, com o tempo contado do início de cada um."""
    saida = {}
    for c in capitulos:
        saida[c.numero] = [Palavra(p.texto, p.inicio - c.inicio, p.fim - c.inicio)
                           for p in palavras if c.inicio <= p.inicio < c.fim]
    return saida


def detectar(audio: Path, cfg: dict) -> tuple[list[CapituloCortado], str]:
    """Retorna (capítulos, método). Levanta ErroCorte se a detecção não passar nas travas."""
    embutidos = capitulos_embutidos(audio)
    if embutidos:
        return embutidos, "marcações do arquivo"

    duracao = duracao_audio(audio)
    if retomar:
        from transcrever import transcrever_retomavel
        drive, pasta, nome_parcial, prazo = retomar
        palavras = transcrever_retomavel(drive, pasta, nome_parcial, audio, cfg["modelo_whisper"],
                                         f"'{audio.name}' para o corte", prazo)
    else:
        palavras = transcrever(audio, cfg["modelo_whisper"])
    ultimas_palavras[:] = palavras   # reaproveitadas nas legendas (não precisa transcrever de novo)
    marcadores = encontrar_marcadores(palavras, cfg["palavra_capitulo"], cfg["pausa_antes_do_marcador_seg"])
    capitulos = montar_capitulos(marcadores, duracao, detectar_silencios(audio))
    erros = validar(marcadores, capitulos, cfg)
    if erros:
        raise ErroCorte(erros, capitulos)
    return capitulos, "reconhecimento de voz"


def cortar(audio: Path, capitulos: list[CapituloCortado], pasta_saida: Path) -> list[Path]:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    ext = audio.suffix.lower()
    copia_direta = ext in (".mp3", ".m4a", ".m4b", ".aac")
    ext_saida = ".m4a" if ext in (".m4a", ".m4b", ".aac") else ".mp3"
    largura = max(2, len(str(max(c.numero for c in capitulos))))
    arquivos = []
    for c in capitulos:
        destino = pasta_saida / nome_arquivo_capitulo(c.numero, c.titulo, ext_saida, largura)
        codec = ["-c", "copy"] if copia_direta else ["-c:a", "libmp3lame", "-q:a", "2"]
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{c.inicio:.3f}", "-i", str(audio),
             "-t", f"{c.duracao:.3f}", "-map", "0:a:0", "-map_chapters", "-1", "-map_metadata", "-1",
             *codec, str(destino)],
            check=True,
        )
        arquivos.append(destino)
    return arquivos


def resumo(capitulos: list[CapituloCortado]) -> str:
    return "\n".join(
        f"  {c.numero:>3}  {formatar_tempo(c.inicio)} → {formatar_tempo(c.fim)}  {c.titulo}" for c in capitulos
    )


# ---------------------------------------------------------------- integração com o Drive

def _relatorio_erro(nome: str, erros: list[str], capitulos: list[CapituloCortado]) -> str:
    linhas = [
        f"O robô NÃO publicou o arquivo '{nome}' porque o corte por capítulos pareceu errado:",
        "",
        *(f"- {e}" for e in erros),
        "",
        "O que você pode fazer:",
        "- cortar o arquivo você mesmo e enviar como '01 - Título.mp3', '02 - Título.mp3'...; ou",
        "- corrigir o áudio e enviar de novo (substituindo o arquivo, o robô tenta outra vez).",
        "",
        "Capítulos que o robô encontrou:",
        resumo(capitulos) if capitulos else "  (nenhum)",
    ]
    return "\n".join(linhas)


def processar_drive(cfg_corte: dict) -> int:
    global retomar
    try:
        return _processar_drive(cfg_corte)
    finally:
        retomar = None


def _processar_drive(cfg_corte: dict) -> int:
    from google_api import Drive, credenciais_do_ambiente
    from livro import ARQ_CORTES, PASTA_CAPITULOS, Capitulo, PASTA_ORIGINAIS, carregar_livro, pastas_de_livros

    global retomar
    from transcrever import PASTA_TRANSCRICOES, TempoEsgotado

    drive = Drive(credenciais_do_ambiente())
    raiz = os.environ["DRIVE_PASTA_RAIZ"]
    processados, falhas = 0, 0
    # o passo do corte tem 120 min no GitHub; para antes, salvando o que já transcreveu
    prazo = time.monotonic() + cfg_corte.get("minutos_maximos", 95) * 60

    for pasta in pastas_de_livros(drive, raiz):
        livro = carregar_livro(drive, pasta)
        if not livro or not livro.a_cortar:
            continue
        if livro.incompleto and "chegaram" in livro.incompleto:
            log.info("'%s': esperando terminar de subir antes de cortar (%s).", livro.nome, livro.incompleto)
            continue
        estado = drive.ler_json(pasta["id"], ARQ_CORTES, {})
        for item in livro.a_cortar:
            if processados >= cfg_corte["max_arquivos_por_execucao"]:
                log.info("Limite de arquivos por execução atingido; o resto fica para amanhã.")
                return 1 if falhas else 0
            anterior = estado.get(item["id"])
            if anterior and anterior.get("status") == "erro" and anterior.get("modificado") == item["modifiedTime"]:
                log.warning("'%s/%s' já falhou antes e não mudou; pulando (veja o arquivo de ERRO na pasta).",
                            livro.nome, item["name"])
                continue

            processados += 1
            log.info("Cortando '%s/%s'", livro.nome, item["name"])
            with tempfile.TemporaryDirectory() as tmp:
                local = drive.baixar(item["id"], Path(tmp) / item["name"])
                ultimas_palavras.clear()
                retomar = (drive, drive.pasta(pasta["id"], PASTA_TRANSCRICOES), f"corte_{item['id']}.parcial.json", prazo)
                try:
                    capitulos, metodo = detectar(local, cfg_corte)
                    capitulos = numerar_para_o_livro(capitulos, item["name"])
                    erros = _conferir_com_livro(capitulos, livro, len(livro.a_cortar))
                    if erros:
                        raise ErroCorte(erros, capitulos)
                except TempoEsgotado as onde:
                    log.info("Tempo do corte acabou (%s); o que foi transcrito está salvo e continua amanhã.", onde)
                    return 1 if falhas else 0
                except ErroCorte as erro:
                    erros, capitulos = erro.args
                    falhas += 1
                    log.error("Corte barrado em '%s':\n%s", item["name"], "\n".join(f"  - {e}" for e in erros))
                    drive.gravar_texto(pasta["id"], f"ERRO - {Path(item['name']).stem}.txt",
                                       _relatorio_erro(item["name"], erros, capitulos))
                    estado[item["id"]] = {"arquivo": item["name"], "modificado": item["modifiedTime"],
                                          "status": "erro", "motivos": erros}
                    drive.gravar_json(pasta["id"], ARQ_CORTES, estado)
                    continue

                log.info("Encontrados %d capítulos por %s:\n%s", len(capitulos), metodo, resumo(capitulos))
                pasta_caps = drive.pasta(pasta["id"], PASTA_CAPITULOS)
                for arquivo in cortar(local, capitulos, Path(tmp) / "saida"):
                    drive.enviar(arquivo, pasta_caps)
                drive.mover(item["id"], pasta["id"], drive.pasta(pasta["id"], PASTA_ORIGINAIS))
                estado[item["id"]] = {"arquivo": item["name"], "modificado": item["modifiedTime"], "status": "ok",
                                      "metodo": metodo, "capitulos": [asdict(c) for c in capitulos]}
                drive.gravar_json(pasta["id"], ARQ_CORTES, estado)
                if ultimas_palavras:
                    from transcrever import salvar_transcricao
                    for numero, ps in palavras_de_cada_capitulo(ultimas_palavras, capitulos).items():
                        if ps:
                            salvar_transcricao(drive, pasta["id"], numero, ps)
                    log.info("Transcrição guardada para as legendas (%d capítulos).", len(capitulos))
                livro.capitulos += [Capitulo(c.numero, c.titulo, []) for c in capitulos]
                erro_antigo = drive.achar(pasta["id"], f"ERRO - {Path(item['name']).stem}.txt")
                if erro_antigo:
                    drive.lixeira(erro_antigo["id"])
    return 1 if falhas else 0


def numerar_para_o_livro(capitulos: list[CapituloCortado], nome_original: str) -> list[CapituloCortado]:
    """Capítulos cortados de uma faixa ("002. Lâmina Rubra ... - 2 - Parte 1 ...") ganham números 2001, 2002...,
    para ficarem na ordem certa entre as outras faixas do livro. O número do capítulo vai no título."""
    from comum import ler_nome_faixa
    from livro import FATOR_FAIXA

    faixa = ler_nome_faixa(nome_original)
    if not faixa:
        return capitulos
    base = faixa[0] * FATOR_FAIXA
    renumerados = []
    for c in capitulos:
        if c.tipo == "capitulo":
            titulo = f"Capítulo {c.numero}" + (f" – {c.titulo}" if c.titulo else "")
        else:
            titulo = c.titulo
        renumerados.append(CapituloCortado(base + (c.numero % FATOR_FAIXA), titulo, c.inicio, c.fim, c.tipo))
    return renumerados


def _numero_real(c: CapituloCortado) -> int:
    from livro import FATOR_FAIXA
    return c.numero % FATOR_FAIXA


def _conferir_com_livro(capitulos: list[CapituloCortado], livro, arquivos_a_cortar: int) -> list[str]:
    erros = []
    existentes = {c.numero for c in livro.capitulos}
    repetidos = sorted(existentes & {c.numero for c in capitulos})
    if repetidos:
        erros.append(f"o livro já tem arquivo(s) para o(s) capítulo(s) {repetidos}")
    total = livro.ficha.get("total_capitulos")
    if total:
        numerados = [_numero_real(c) for c in capitulos if c.tipo == "capitulo"]
        if numerados and max(numerados) > int(total):
            erros.append(f"encontrei o capítulo {max(numerados)}, mas a ficha diz que o livro tem {total}")
        if arquivos_a_cortar == 1 and not existentes and numerados == [c.numero for c in capitulos if c.tipo == "capitulo"]:
            contados = len(numerados)
            if contados != int(total):
                erros.append(f"encontrei {contados} capítulos, mas a ficha diz que o livro tem {total}")
    return erros


def main() -> int:
    configurar_log()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("arquivo", nargs="?", type=Path, help="arquivo de áudio local")
    parser.add_argument("--drive", action="store_true", help="processar a pasta do Google Drive")
    parser.add_argument("--dry-run", action="store_true", help="só mostrar os capítulos, sem cortar")
    parser.add_argument("--saida", type=Path, help="pasta onde salvar os capítulos (padrão: ao lado do arquivo)")
    args = parser.parse_args()
    cfg = carregar_config()["corte"]

    if args.drive:
        return processar_drive(cfg)
    if not args.arquivo:
        parser.error("informe um arquivo ou use --drive")

    try:
        capitulos, metodo = detectar(args.arquivo, cfg)
    except ErroCorte as erro:
        erros, capitulos = erro.args
        print("Corte BARRADO pelas travas de segurança:", *(f"  - {e}" for e in erros), sep="\n")
        print("Capítulos encontrados:\n" + resumo(capitulos))
        return 1
    print(f"{len(capitulos)} capítulos encontrados por {metodo}:\n{resumo(capitulos)}")
    if not args.dry_run:
        saida = args.saida or args.arquivo.with_suffix("")
        for arquivo in cortar(args.arquivo, capitulos, saida):
            print("  salvo:", arquivo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
