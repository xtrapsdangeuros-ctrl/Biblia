"""Críticas polêmicas em vídeo vertical, com o áudio gerado no NotebookLM (fluxo semiautomático).

1. sugerir: o robô dá uma nota de "potencial de polêmica" aos capítulos já publicados (pela transcrição) e cria,
   para os melhores, uma pasta em Audiolivros/Críticas/A fazer/ com o texto do capítulo e as instruções prontas
   para colar no NotebookLM (abertura absurda + pergunta polêmica + embate + pergunta para o público).
2. Você gera a visão geral em áudio no NotebookLM e solta o arquivo baixado na mesma pasta.
3. publicar: o robô transcreve o áudio, monta o vídeo vertical (capa + legenda grande) e publica.
   A pasta vai para Críticas/Publicadas. Não gostou de uma sugestão? Apague a pasta: ela não volta.

Desligado por padrão (config.yaml > criticas > ativo: false). Ligado, roda como um passo curto da publicação
diária (sem máquina extra no GitHub Actions) e só usa transcrições que as legendas já salvaram.

Uso:
  python src/criticas.py                 # sugerir + publicar (passo da publicação diária)
  python src/criticas.py --so sugerir
  python src/criticas.py --so publicar --dry-run
  python src/criticas.py --montar audio.wav --capa capa.jpg --livro "Noite de Vigília" --capitulo 2 --saida teste.mp4
      # teste local: monta o vídeo vertical de um áudio do NotebookLM, sem Drive e sem YouTube
"""

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from comum import carregar_config, configurar_log, eh_audio, log, normalizar, pausado, so_audiolivro
from cortar import Palavra

PASTA_CRITICAS = "Críticas"
PASTA_A_FAZER = "A fazer"
PASTA_PUBLICADAS = "Publicadas"
ARQ_ESTADO = "criticas.json"
ARQ_COMO_FAZER = "COMO FAZER.txt"
ARQ_FONTE = "1 - fonte (envie ao NotebookLM).txt"
ARQ_INSTRUCOES = "2 - instruções (cole na personalização).txt"
ARQ_TITULO = "titulo.txt"
_FIM_DE_FRASE = (".", "!", "?", "…")

# Palavras (radicais, sem acento) que costumam render discussão. A nota é por mil palavras, mais um bônus
# por tema diferente: um capítulo com ciúme, morte e culpa ganha de um que só repete "morte".
TEMAS = {
    "ciúme": ("ciume", "ciumento", "ciumenta"),
    "traição": ("trai", "traicao", "traidor", "adulter", "amante", "infiel", "infidelidade"),
    "morte": ("morte", "morreu", "morrer", "morto", "morta", "matou", "matar", "assassin", "cadaver", "enterro"),
    "culpa": ("culpa", "culpado", "remorso", "arrepend", "pecado", "confess"),
    "vingança": ("vinganca", "vingar", "vingou", "revanche"),
    "mentira": ("mentira", "mentiu", "mentir", "engano", "enganou", "fingiu", "fingir", "segredo"),
    "ódio e inveja": ("odio", "odeia", "odiava", "inveja", "rancor", "despeito"),
    "violência": ("sangue", "golpe", "espada", "faca", "veneno", "guerra", "batalha", "violencia", "surra"),
    "loucura": ("loucura", "louco", "louca", "delirio", "insano", "hospicio"),
    "injustiça": ("injust", "castigo", "escrav", "crime", "criminoso", "preso", "prisao", "julgamento", "condenad"),
    "poder e dinheiro": ("heranca", "dinheiro", "fortuna", "ambicao", "ganancia", "trono", "dote"),
    "amor proibido": ("paixao", "beijo", "proibid", "casamento", "noivado", "seduz"),
}


def _radical(palavra: str) -> str:
    return re.sub(r"[^a-z]", "", normalizar(palavra))


def nota_polemica(texto: str) -> tuple[float, list[str]]:
    """(nota, temas encontrados, do mais citado ao menos)."""
    palavras = [_radical(p) for p in texto.split()]
    palavras = [p for p in palavras if p]
    if len(palavras) < 150:
        return 0.0, []
    contagem = {}
    for tema, radicais in TEMAS.items():
        n = sum(1 for p in palavras if p.startswith(radicais))
        if n:
            contagem[tema] = n
    por_mil = sum(contagem.values()) * 1000 / len(palavras)
    perguntas = texto.count("?") * 1000 / len(palavras)
    nota = por_mil + 2.0 * len(contagem) + 0.5 * perguntas
    return round(nota, 2), sorted(contagem, key=lambda t: -contagem[t])


def texto_corrido(palavras: list[Palavra], pausa_paragrafo: float = 1.2) -> str:
    """Junta as palavras da transcrição em parágrafos (quebra em pausa longa depois de fim de frase)."""
    paragrafos, atual = [], []
    for i, p in enumerate(palavras):
        atual.append(p.texto.strip())
        prox = palavras[i + 1] if i + 1 < len(palavras) else None
        if prox is None or (p.texto.strip().endswith(_FIM_DE_FRASE) and
                            (prox.inicio - p.fim > pausa_paragrafo or len(atual) > 160)):
            paragrafos.append(" ".join(w for w in atual if w))
            atual = []
    return "\n\n".join(paragrafos)


# Para cada tema, uma briga já escolhida: lado A, lado B e a pergunta final. O NotebookLM, quando precisa inventar
# a polêmica sozinho, faz um resumo educado e termina em "os dois têm razão". Com os lados prontos, ele briga.
# Os lados falam do papel ("quem sente ciúme"), não de um nome: o NotebookLM lê o capítulo e sabe quem é.
BRIGAS = {
    "ciúme": ("Quem sente ciúme nesse capítulo tem motivo de sobra: é lucidez, não doença.",
              "O ciúme inventou o problema inteiro: o ciumento é o verdadeiro vilão do capítulo.",
              "O ciumento estava certo ou é o vilão dessa história?"),
    "traição": ("Quem trai não tem desculpa nenhuma, ponto.",
                "A traição foi empurrada: quem foi traído plantou isso.",
                "Traição pode ter justificativa?"),
    "morte": ("Essa morte era inevitável e, no fundo, foi o melhor que podia acontecer.",
              "Essa morte tem culpado, e dá para apontar o dedo para alguém do capítulo.",
              "Essa morte tinha culpado? Quem?"),
    "culpa": ("Quem carrega a culpa nesse capítulo é culpado mesmo e não merece perdão.",
              "É vítima das circunstâncias: pôr a culpa só nessa pessoa é preguiça de quem lê.",
              "Merece perdão ou não?"),
    "vingança": ("A vingança é justa: qualquer um faria igual.",
                 "A vingança transforma quem se vinga exatamente no vilão que diz combater.",
                 "Você se vingaria?"),
    "mentira": ("A mentira foi necessária: a verdade destruiria todo mundo.",
                "Quem mente nesse capítulo mente por egoísmo, e isso é imperdoável.",
                "Mentir, nesse caso, foi certo?"),
    "ódio e inveja": ("A inveja é compreensível: o mundo desse capítulo é injusto com quem sente.",
                      "Quem sente inveja aqui é simplesmente uma pessoa ruim, sem desculpa.",
                      "É vítima ou é ruim mesmo?"),
    "violência": ("A violência era a única saída possível nesse capítulo.",
                  "Havia outra saída: a violência foi escolha, não necessidade.",
                  "Tinha outra saída?"),
    "loucura": ("Quem parece louco nesse capítulo é o único que enxerga a verdade.",
                "Perdeu o juízo mesmo, e quem acredita nessa pessoa é cúmplice.",
                "É loucura ou é a única pessoa lúcida?"),
    "injustiça": ("O castigo foi justo: quem sofreu pediu por isso.",
                  "Foi uma injustiça, e quem lê e aplaude é cúmplice.",
                  "Foi justiça ou injustiça?"),
    "poder e dinheiro": ("Ambição não é defeito: quem busca poder aqui faz o que precisa ser feito.",
                         "Vendeu a alma por dinheiro e poder, e o capítulo prova isso.",
                         "Ambição: defeito ou virtude?"),
    "amor proibido": ("Esse amor vale qualquer escândalo: quem atrapalha é o vilão.",
                      "Esse amor é egoísmo disfarçado e vai destruir todo mundo em volta.",
                      "Esse amor vale o estrago?"),
}
BRIGA_PADRAO = ("A personagem que todo mundo defende nesse capítulo é a verdadeira vilã, só que o livro disfarça.",
                "Não tem vilão disfarçado nenhum: quem parece culpado é culpado mesmo.",
                "Quem é o verdadeiro vilão desse capítulo?")


def escolher_briga(temas: list[str], capitulo: str) -> tuple[str, tuple[str, str, str]]:
    """(tema, briga) de um dos dois temas mais fortes, alternando entre capítulos para não repetir sempre."""
    opcoes = [t for t in temas[:2] if t in BRIGAS]
    if not opcoes:
        return (temas[0] if temas else "o conflito central do capítulo"), BRIGA_PADRAO
    tema = opcoes[sum(map(ord, capitulo)) % len(opcoes)]
    return tema, BRIGAS[tema]


# Palavras que aparecem com maiúscula no meio da frase mas não são personagens.
_NAO_PERSONAGEM = {"deus", "senhor", "senhora", "dona", "dom", "capitulo", "livro", "rua", "rio", "sao", "santa",
                   "santo", "nossa", "virgem", "cristo", "jesus", "igreja", "rei", "rainha", "eu", "voce"}
_PONTUACAO = ".,;:!?…\"'()«»“”—–-"


def personagens(texto: str, quantos: int = 3) -> list[str]:
    """Os nomes mais citados: palavras com maiúscula que não começam frase (a transcrição já põe maiúscula em nomes)."""
    contagem, nomes = {}, {}
    anterior = "."
    for bruta in texto.split():
        palavra = bruta.strip(_PONTUACAO)
        comeca_frase = anterior.rstrip("\"'”»)").endswith((".", "!", "?", "…", ":", "—", "–", "-"))
        if (palavra[:1].isupper() and len(palavra) >= 3 and not comeca_frase
                and normalizar(palavra) not in _NAO_PERSONAGEM):
            chave = normalizar(palavra)
            contagem[chave] = contagem.get(chave, 0) + 1
            nomes.setdefault(chave, palavra)
        anterior = bruta
    return [nomes[k] for k in sorted(contagem, key=lambda k: -contagem[k]) if contagem[k] >= 3][:quantos]


def instrucoes(modelo: str, livro: str, autor: str, capitulo: str, temas: list[str],
               nomes: list[str] | None = None) -> str:
    nomes = nomes or []
    tema, (lado_a, lado_b, pergunta) = escolher_briga(temas, capitulo)
    valores = {"livro": livro, "autor": autor or "autor desconhecido", "capitulo": capitulo,
               "temas": ", ".join(temas[:4]) or "os conflitos do capítulo",
               "tema": tema,
               "personagens": ", ".join(nomes) or "as personagens do capítulo",
               "lado_a": lado_a, "lado_b": lado_b, "pergunta": pergunta}
    texto = modelo
    for chave, valor in valores.items():
        texto = texto.replace("{" + chave + "}", valor)
    return texto.strip() + "\n"


COMO_FAZER = """COMO TRANSFORMAR UMA SUGESTÃO EM VÍDEO (uns 3 minutos seus)

Cada pasta em "A fazer" é um capítulo que o robô achou bom para uma crítica polêmica.
Não gostou da sugestão? Apague a pasta. Ela não volta.

1. Abra https://notebooklm.google.com e crie um notebook novo.
2. Em "Adicionar fontes", envie o arquivo "1 - fonte (envie ao NotebookLM).txt" da pasta.
3. No painel "Estúdio", clique no lápis de "Visão geral em áudio" (personalizar):
   - Formato: Debate (o formato Crítica é feito para revisar redação e sai morno);
   - Idioma: português (Brasil);
   - Cole TODO o texto do arquivo "2 - instruções (cole na personalização).txt".
4. Gere, ouça e, se gostar, baixe o áudio (menu ⋮ > Baixar).
5. Arraste o arquivo baixado para dentro da MESMA pasta do capítulo, aqui no Drive.

Pronto: na próxima execução o robô monta o vídeo vertical com capa e legenda e publica.
Opcional: crie na pasta um "titulo.txt" com o título que você quer; sem ele, o robô usa a primeira
pergunta do áudio.
"""


# ---------------------------------------------------------------- estado

def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _chave(pasta_livro_id: str, numero: int) -> str:
    return f"{pasta_livro_id}:{numero}"


def _pastas(drive, raiz: str) -> tuple[str, str, str]:
    base = drive.pasta(raiz, PASTA_CRITICAS)
    return base, drive.pasta(base, PASTA_A_FAZER), drive.pasta(base, PASTA_PUBLICADAS)


def _transcricao_salva(drive, livro, numero: int) -> list[Palavra] | None:
    from transcrever import PASTA_TRANSCRICOES

    pasta = drive.achar(livro.pasta["id"], PASTA_TRANSCRICOES)
    salvo = drive.achar(pasta["id"], f"{numero}.json") if pasta else None
    if not salvo:
        return None
    return [Palavra(*p) for p in json.loads(drive.ler_texto(salvo["id"]))]


# ---------------------------------------------------------------- 1) sugerir

def sugerir(drive, raiz: str, cfg: dict, estado: dict, dry_run: bool = False) -> int:
    from livro import ARQ_PUBLICADOS, carregar_livro, pastas_de_livros, privacidade_do_livro
    from main import filtrar_fila
    from metadados import rotulo_e_titulo
    from shorts import merece_short
    from transcrever import baixar_capitulo, palavras_do_capitulo

    conf = cfg["criticas"]
    prazo = time.monotonic() + conf.get("minutos_maximos", 10) * 60
    transcrever_restantes = conf.get("transcrever_por_execucao", 0)
    candidatos = []   # (nota, temas, livro, capitulo, palavras)
    pastas = filtrar_fila(pastas_de_livros(drive, raiz), cfg["publicacao"].get("livros") or [])
    for pasta in pastas:
        livro = carregar_livro(drive, pasta)
        if not livro or livro.ficha.get("ativo") is False or pausado(cfg, pasta["name"]):
            continue
        if conf.get("apenas_publicos", True) and privacidade_do_livro(livro.ficha) == "private":
            continue
        publicados = drive.ler_json(pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})["capitulos"]
        for cap in livro.capitulos:
            if (str(cap.numero) not in publicados or _chave(pasta["id"], cap.numero) in estado["sugeridas"]
                    or not merece_short(cap.numero, cap.titulo)):
                continue
            palavras = _transcricao_salva(drive, livro, cap.numero)
            if palavras is None:
                if dry_run or transcrever_restantes <= 0 or time.monotonic() > prazo:
                    continue
                transcrever_restantes -= 1
                with tempfile.TemporaryDirectory() as tmp:
                    audio = baixar_capitulo(drive, cap, Path(tmp))
                    palavras = palavras_do_capitulo(drive, livro, cap, audio, cfg["corte"]["modelo_whisper"])
            nota, temas = nota_polemica(" ".join(p.texto for p in palavras))
            if nota >= conf.get("nota_minima", 8):
                candidatos.append((nota, temas, livro, cap, palavras))

    # os melhores, no máximo um por livro em cada execução (variedade)
    escolhidos, livros_usados = [], set()
    for item in sorted(candidatos, key=lambda c: -c[0]):
        if item[2].pasta["id"] in livros_usados:
            continue
        escolhidos.append(item)
        livros_usados.add(item[2].pasta["id"])
        if len(escolhidos) >= conf.get("sugestoes_por_execucao", 3):
            break

    if not escolhidos:
        log.info("Críticas: nenhum capítulo novo com potencial de polêmica (nota mínima %s).", conf.get("nota_minima", 8))
        return 0
    base, a_fazer, _ = (None, None, None) if dry_run else _pastas(drive, raiz)
    if base and not drive.achar(base, ARQ_COMO_FAZER):
        drive.gravar_texto(base, ARQ_COMO_FAZER, COMO_FAZER)
    for nota, temas, livro, cap, palavras in escolhidos:
        rotulo, titulo = rotulo_e_titulo(cap.numero, cap.titulo)
        nome_cap = f"{rotulo}" + (f" – {titulo}" if titulo else "")
        nome_pasta = f"{livro.ficha['titulo']} – {rotulo}".replace("/", "-")
        log.info("Críticas: sugerido '%s' (nota %.1f; %s)", nome_pasta, nota, ", ".join(temas[:4]))
        if dry_run:
            continue
        pasta = drive.pasta(a_fazer, nome_pasta)
        cabecalho = f"{livro.ficha['titulo']}" + (f", de {livro.ficha['autor']}" if livro.ficha.get("autor") else "")
        drive.gravar_texto(pasta, ARQ_FONTE, f"{cabecalho}\n{nome_cap}\n\n{texto_corrido(palavras)}\n")
        drive.gravar_texto(pasta, ARQ_INSTRUCOES, instrucoes(conf["prompt"], livro.ficha["titulo"],
                                                             livro.ficha.get("autor") or "", nome_cap, temas,
                                                             personagens(" ".join(p.texto for p in palavras))))
        estado["sugeridas"][_chave(livro.pasta["id"], cap.numero)] = {
            "livro": livro.nome, "pasta_livro": livro.pasta["id"], "capitulo": cap.numero, "pasta": pasta,
            "nota": nota, "temas": temas[:4], "data": _agora(),
        }
    return len(escolhidos)


# ---------------------------------------------------------------- 2) publicar

def recortar(palavras: list[Palavra], limite: float) -> list[Palavra]:
    """Palavras até o último fim de frase que cabe no limite (ou até a última palavra que cabe)."""
    cabem = [p for p in palavras if p.fim <= limite]
    for i in range(len(cabem) - 1, -1, -1):
        if cabem[i].texto.strip().endswith(_FIM_DE_FRASE) and cabem[i].fim >= limite * 0.6:
            return cabem[:i + 1]
    return cabem


# As instruções pedem uma abertura absurda nos primeiros 10 s: a pergunta do título vem depois dela.
ABERTURA_SEG = 12.0


def primeira_pergunta(palavras: list[Palavra], depois_de: float = 0.0, minimo: int = 12,
                      maximo: int = 70) -> str:
    """A primeira pergunta de tamanho bom para título, começando depois de `depois_de` segundos.
    'Então a pergunta é: e se ele for o vilão?' -> 'E se ele for o vilão?'."""
    frase = []
    for p in palavras:
        texto = p.texto.strip()
        frase.append(p)
        if texto.endswith("?"):
            pergunta = " ".join(w.texto.strip() for w in frase if w.texto.strip())
            if frase[0].inicio >= depois_de and minimo <= len(pergunta) <= maximo:
                return pergunta[:1].upper() + pergunta[1:]
            frase = []
        elif texto.endswith((".", "!", "…", ":")):   # depois de ":" começa a pergunta de verdade
            frase = []
    return ""


def titulo_critica(palavras: list[Palavra], ficha: dict, rotulo: str, manual: str = "") -> str:
    """A primeira pergunta do áudio (o gancho) + o nome do livro: 'E se Lívia for inocente? | NOITE DE VIGÍLIA #shorts'."""
    from metadados import _limpar, livro_e_autor

    livro = livro_e_autor(ficha)[0] or ficha["titulo"]
    sufixo = " #audiolivro #shorts"
    base = manual.strip().splitlines()[0].strip() if manual.strip() else ""
    if not base:
        pergunta = primeira_pergunta(palavras, depois_de=ABERTURA_SEG) or primeira_pergunta(palavras)
        if pergunta:
            base = f"{pergunta} | {livro.upper()}"
    if not base:
        base = f"POLÊMICA EM {livro.upper()} ({rotulo}): e você, concorda?"
    base = _limpar(base)
    limite = 100 - len(sufixo)
    return (base[: limite - 1].rstrip() + "…" if len(base) > limite else base) + sufixo


def descricao_critica(ficha: dict, nome_cap: str, video_capitulo: str | None, playlist_id: str | None,
                      cta: dict) -> str:
    from metadados import _limpar, hashtags_video, link_playlist, livro_e_autor

    livro, autor = livro_e_autor(ficha)
    linhas = []
    if playlist_id:   # o link da playlist vem primeiro: é o que aparece sem abrir a descrição
        linhas.append(f"📚 Ouça o livro todo: {link_playlist(playlist_id)}")
    if video_capitulo:
        linhas.append(f"▶ Este capítulo inteiro: https://youtu.be/{video_capitulo}")
    linhas += ["", f"Uma leitura polêmica do audiolivro {livro}" + (f", de {autor}" if autor else "")
               + f" – {nome_cap}. E você, concorda? Conta nos comentários! 👇"]
    if cta.get("canal"):
        linhas += ["", f"🔔 Inscreva-se: {cta['canal']}"]
    linhas += ["", "Conversa gerada com IA (NotebookLM) a partir do texto do capítulo: é uma provocação para "
                   "debate, não a opinião do autor do livro."]
    linhas += ["", " ".join("#" + h.lstrip("#") for h in hashtags_video(ficha, ["Shorts"]))]
    return _limpar("\n".join(linhas))[:5000]


def montar_video(audio: Path, capa: Path | None, ficha: dict, rotulo: str, cfg: dict, pasta: Path,
                 palavras: list[Palavra] | None = None) -> tuple[Path, list[Palavra], float]:
    """Monta o vídeo vertical (capa + legenda grande) a partir do áudio do NotebookLM.
    Retorna (vídeo, palavras usadas, duração)."""
    from cortar import transcrever
    from metadados import livro_e_autor
    from shorts import gerar_arte_vertical, gerar_ass, renderizar_short
    from video import duracao_audio

    conf = cfg["criticas"]
    if palavras is None:
        palavras = transcrever(audio, cfg["corte"]["modelo_whisper"])
    if not palavras:
        raise ValueError(f"não ouvi fala nenhuma em {audio.name}")
    total = duracao_audio(audio)
    limite = float(conf.get("limite_segundos", 175))
    if total > limite and conf.get("acima_do_limite", "cortar") == "cortar":
        trecho = recortar(palavras, limite - 1)
        log.warning("Críticas: o áudio tem %.0f s; cortado em %.0f s (fim de frase) para caber no Shorts.",
                    total, trecho[-1].fim)
    else:
        trecho = palavras
    inicio = max(trecho[0].inicio - 0.15, 0)
    duracao = min(trecho[-1].fim - inicio + 0.6, total - inicio)
    arte = gerar_arte_vertical(capa, pasta / "arte.png", livro_e_autor(ficha)[0] or ficha["titulo"],
                               f"Polêmica • {rotulo.replace('Capítulo', 'Cap.')}", cfg["video"])
    video = renderizar_short(arte, audio, inicio, duracao,
                             gerar_ass(trecho, cor_destaque=cfg["video"]["cor_destaque"]), pasta / "critica.mp4")
    return video, trecho, duracao


def publicar(drive, youtube, raiz: str, cfg: dict, estado: dict, dry_run: bool = False) -> int:
    from google_api import LimiteDiario
    from livro import ARQ_PUBLICADOS, carregar_livro, privacidade_do_livro
    from metadados import rotulo_e_titulo, tags_video

    conf = cfg["criticas"]
    restantes = conf.get("publicar_por_dia", 2)
    hoje = datetime.now(timezone.utc).date().isoformat()
    restantes -= sum(1 for r in estado["publicadas"].values() if str(r.get("data", "")).startswith(hoje))
    if restantes <= 0:
        log.info("Críticas: o limite de hoje já foi publicado.")
        return 0
    if dry_run:   # só lê: não cria pastas
        base = drive.achar(raiz, PASTA_CRITICAS)
        achada = drive.achar(base["id"], PASTA_A_FAZER) if base else None
        if not achada:
            return 0
        a_fazer, publicadas = achada["id"], None
    else:
        _, a_fazer, publicadas = _pastas(drive, raiz)
    prazo = time.monotonic() + conf.get("minutos_maximos", 10) * 60
    por_pasta = {s["pasta"]: k for k, s in estado["sugeridas"].items()}
    feitas = 0
    for pasta in sorted((p for p in drive.listar(a_fazer) if drive.eh_pasta(p)), key=lambda p: p["name"]):
        if restantes <= 0 or time.monotonic() > prazo:
            break
        arquivos = drive.listar(pasta["id"])
        audios = [a for a in arquivos if eh_audio(a["name"]) or a["name"].lower().endswith(".mp4")]
        if not audios:
            continue
        chave = por_pasta.get(pasta["id"])
        if not chave:
            log.warning("Críticas: a pasta '%s' não foi criada pelo robô; não sei de que capítulo é.", pasta["name"])
            continue
        sug = estado["sugeridas"][chave]
        livro = carregar_livro(drive, {"id": sug["pasta_livro"], "name": sug["livro"]})
        cap = next((c for c in livro.capitulos if c.numero == sug["capitulo"]), None) if livro else None
        if not cap:
            log.warning("Críticas: não achei mais o capítulo de '%s'; pulando.", pasta["name"])
            continue
        audio_drive = max(audios, key=lambda a: a.get("modifiedTime", ""))
        titulo_manual = next((a for a in arquivos if a["name"].lower() == ARQ_TITULO), None)
        rotulo, titulo_cap = rotulo_e_titulo(cap.numero, cap.titulo)
        nome_cap = rotulo + (f" – {titulo_cap}" if titulo_cap else "")
        log.info("Críticas: montando '%s' a partir de %s", pasta["name"], audio_drive["name"])
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            audio = drive.baixar(audio_drive["id"], tmp / f"critica{Path(audio_drive['name']).suffix}")
            capa = drive.baixar(livro.capa["id"], tmp / f"capa{Path(livro.capa['name']).suffix}") if livro.capa else None
            try:
                video, trecho, duracao = montar_video(audio, capa, livro.ficha, rotulo, cfg, tmp)
            except ValueError as erro:
                log.warning("Críticas: %s; pulando.", erro)
                continue
            publicados = drive.ler_json(livro.pasta["id"], ARQ_PUBLICADOS, {"capitulos": {}})
            reg = publicados["capitulos"].get(str(cap.numero)) or {}
            privacidade = privacidade_do_livro(livro.ficha)
            link = None
            if reg.get("video_id") and privacidade != "private":
                link = reg["video_id"] + (f"?t={int(reg['inicio'])}" if reg.get("inicio") else "")
            pub = cfg["publicacao"]
            snippet = {
                "title": titulo_critica(trecho, livro.ficha, rotulo,
                                        drive.ler_texto(titulo_manual["id"]) if titulo_manual else ""),
                "description": descricao_critica(livro.ficha, nome_cap, link, publicados.get("playlist_id"),
                                                 cfg.get("cta") or {}),
                "tags": tags_video(livro.ficha, ["shorts", "crítica literária", "polêmica"]),
                "categoryId": str(pub["categoria_id"]),
                "defaultLanguage": pub["idioma"],
                "defaultAudioLanguage": pub["idioma"],
            }
            status = {"privacyStatus": privacidade, "selfDeclaredMadeForKids": False,
                      "containsSyntheticMedia": True}   # vozes do NotebookLM são sintéticas
            log.info("Críticas: título '%s' (%.0f s, %s)", snippet["title"], duracao, privacidade)
            if dry_run:
                continue
            try:
                video_id = youtube.enviar_video(video, snippet, status)
            except LimiteDiario as motivo:
                log.warning("Críticas: limite diário do YouTube (%s); continua amanhã.", motivo)
                break
        log.info("Críticas: publicado %s", video_id)
        estado["publicadas"][chave] = {"video_id": video_id, "data": _agora(), "titulo": snippet["title"]}
        drive.mover(pasta["id"], a_fazer, publicadas)
        restantes -= 1
        feitas += 1
    return feitas


# ---------------------------------------------------------------- execução

def rodar(drive, youtube, raiz: str, cfg: dict, so: str | None = None, dry_run: bool = False) -> int:
    conf = cfg.get("criticas") or {}
    if not conf.get("ativo"):
        log.info("Críticas desligadas no config.yaml.")
        return 0
    if dry_run:   # só lê o que existe; não cria nem grava nada
        achada = drive.achar(raiz, PASTA_CRITICAS)
        estado = drive.ler_json(achada["id"], ARQ_ESTADO, {}) if achada else {}
        base = None
    else:
        base = drive.pasta(raiz, PASTA_CRITICAS)
        estado = drive.ler_json(base, ARQ_ESTADO, {})
    estado.setdefault("sugeridas", {})
    estado.setdefault("publicadas", {})
    try:
        if so in (None, "publicar"):
            n = publicar(drive, youtube, raiz, cfg, estado, dry_run)
            log.info("Críticas publicadas nesta execução: %d", n)
        if so in (None, "sugerir"):
            n = sugerir(drive, raiz, cfg, estado, dry_run)
            log.info("Críticas sugeridas nesta execução: %d", n)
    finally:
        if base:
            drive.gravar_json(base, ARQ_ESTADO, estado)
    return 0


def montar_local(args) -> int:
    """Teste local: monta o vídeo de um áudio do NotebookLM sem Drive e sem YouTube, e mostra o título."""
    import shutil
    from metadados import rotulo_e_titulo

    cfg = carregar_config()
    cfg.setdefault("criticas", {})
    ficha = {"titulo": args.livro, "autor": args.autor or ""}
    rotulo, titulo_cap = rotulo_e_titulo(args.capitulo, "")
    with tempfile.TemporaryDirectory() as tmp:
        video, trecho, duracao = montar_video(Path(args.montar), Path(args.capa) if args.capa else None, ficha,
                                              rotulo, cfg, Path(tmp))
        destino = Path(args.saida)
        shutil.copy(video, destino)
    print(f"Vídeo: {destino} ({duracao:.0f} s)")
    print(f"Título: {titulo_critica(trecho, ficha, rotulo)}")
    print("Descrição:\n" + descricao_critica(ficha, rotulo, "ID_DO_CAPITULO", "ID_DA_PLAYLIST", cfg.get("cta") or {}))
    return 0


def main() -> int:
    configurar_log()
    if so_audiolivro("Críticas"):
        return 0
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--so", choices=["sugerir", "publicar"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--montar", help="teste local: áudio do NotebookLM")
    parser.add_argument("--capa")
    parser.add_argument("--livro", default="Livro de teste")
    parser.add_argument("--autor")
    parser.add_argument("--capitulo", type=int, default=1)
    parser.add_argument("--saida", default="critica.mp4")
    args = parser.parse_args()
    if args.montar:
        return montar_local(args)

    from google_api import Drive, YouTube, credenciais_do_ambiente
    cfg = carregar_config()
    if not (cfg.get("criticas") or {}).get("ativo"):   # sai antes de conectar: não gasta nada
        log.info("Críticas desligadas no config.yaml.")
        return 0
    credenciais = credenciais_do_ambiente()
    raiz = os.environ.get("DRIVE_PASTA_RAIZ") or sys.exit("Falta a variável DRIVE_PASTA_RAIZ")
    return rodar(Drive(credenciais), YouTube(credenciais), raiz, cfg, args.so, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
