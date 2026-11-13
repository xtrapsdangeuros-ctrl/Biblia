"""Monta título, descrição e tags do vídeo de cada capítulo."""

import re

from comum import FATOR_FAIXA, normalizar

_ESPECIAIS = (
    "prologo", "prefacio", "introducao", "apresentacao", "epilogo", "posfacio", "nota", "abertura",
    "glossario", "agradecimentos", "guia de pronuncia", "sinopse", "sumario", "apendice", "credito",
    "dedicatoria", "a lingua", "parte ", "previa", "orelha", "contra", "preludio", "interludio",
    "nota final", "livro ", "leitura", "indice", "texto critico", "sobre o", "o autor", "palavras do editor",
    "roteiro", "vida e obra", "perfil biografico", "completo",
)
_ESPECIAIS_BASE = _ESPECIAIS   # o canal.yaml pode acrescentar outras (metadados > secoes_especiais)
# "Capítulo 16", "Capitulo 16 – A batalha", "Capótulo 46" (erro de digitação)
_CAPITULO_NO_TITULO = re.compile(r"^cap\w*\.?\s*(\d+)\s*(?:[-–—:.]\s*)?(.*)$", re.IGNORECASE)
LIMITE_TITULO = 100
LIMITE_DESCRICAO = 5000
LIMITE_TAGS = 450  # o YouTube aceita 500 caracteres no total; deixamos folga


def _limpar(texto: str) -> str:
    # O YouTube recusa "<" e ">" no título e na descrição.
    return str(texto).replace("<", "‹").replace(">", "›").strip()


def rotulo_e_titulo(numero: int, titulo: str) -> tuple[str, str]:
    """(3, 'Da Estrada') -> ('Capítulo 3', 'Da Estrada'); (0, 'Prólogo') -> ('Prólogo', '')."""
    titulo = (titulo or "").strip()
    norm = normalizar(titulo)
    if norm.startswith(_ESPECIAIS):
        return titulo, ""
    if not norm:
        return f"Capítulo {numero}", ""
    no_titulo = _CAPITULO_NO_TITULO.match(titulo)
    if no_titulo:
        # o número escrito no título manda (nas faixas do Saldanha a faixa 3 é o "Capítulo 1")
        return f"Capítulo {int(no_titulo.group(1))}", no_titulo.group(2).strip()
    if numero == 0 or numero >= FATOR_FAIXA:
        # número da faixa, não do capítulo ("Cap. 1000: Sino de Natal" não faz sentido): fica só o título
        return titulo, ""
    return f"Capítulo {numero}", titulo


# Autores que costumam vir grudados no nome da pasta ("Autor Exemplo Livro Exemplo") e erros de digitação conhecidos
# nos nomes das pastas. São do canal: vêm do canal.yaml (bloco "metadados"), via configurar().
AUTORES_CONHECIDOS: tuple = ()
_CORRECOES: dict = {}
# Autor de séries que aparecem nos títulos antigos sem o nome do autor (trecho do título em minúsculas: autor)
AUTOR_DA_SERIE: dict = {}
PALAVRA = "AUDIOLIVRO"
LIMITE_BOM = 70   # acima disso o título é cortado na busca do celular


def configurar(meta: dict | None) -> None:
    """canal.yaml > metadados: autores_conhecidos (lista), correcoes (errado: certo) e autor_da_serie (trecho: autor)."""
    global AUTORES_CONHECIDOS, _CORRECOES, AUTOR_DA_SERIE
    if meta is None:   # o canal não tem o bloco "metadados": fica como está
        return
    meta = meta or {}
    AUTOR_DA_SERIE = {str(k): str(v) for k, v in (meta.get("autor_da_serie") or {}).items()}
    global _ESPECIAIS
    _ESPECIAIS = _ESPECIAIS_BASE + tuple(normalizar(str(s)) for s in (meta.get("secoes_especiais") or []))
    AUTORES_CONHECIDOS = tuple(str(a) for a in (meta.get("autores_conhecidos") or []))
    _CORRECOES = {str(k): str(v) for k, v in (meta.get("correcoes") or {}).items()}


def _corrigir(texto: str) -> str:
    for errado, certo in _CORRECOES.items():
        texto = texto.replace(errado, certo)
    return texto


def livro_e_autor(ficha: dict) -> tuple[str, str]:
    """{'titulo': 'Ricardo Montemor Despertar', 'autor': 'Ricardo Montemor'} -> ('Despertar', 'Ricardo Montemor').
    Também tira '(Henrique Saldanha)' do fim e reconhece autores conhecidos quando a ficha não tem autor."""
    titulo = _corrigir(str(ficha.get("titulo") or "").strip())
    titulo = re.sub(r"^\d{1,3}\s*[-–.]\s+(?=\S)", "", titulo)   # "01 - Noite de Vigília" (número da pasta)
    autor = _corrigir(str(ficha.get("autor") or "").strip())
    for nome in ([autor] if autor else []) + list(AUTORES_CONHECIDOS):
        no_fim = re.search(r"\s*\(\s*" + re.escape(nome) + r"\s*\)\s*$", titulo, re.IGNORECASE)
        no_comeco = re.match(re.escape(nome) + r"\s+(?=\S)", titulo, re.IGNORECASE)
        if no_fim or no_comeco:
            resto = titulo[: no_fim.start()] if no_fim else titulo[no_comeco.end():]
            if len(resto.strip()) >= 2:
                return resto.strip(), autor or nome
    return titulo, autor


def serie_e_volume(ficha: dict) -> tuple[str, int | None]:
    serie = _corrigir(str(ficha.get("serie") or "").strip())
    try:
        volume = int(ficha["volume"]) if ficha.get("volume") not in (None, "") else None
    except (TypeError, ValueError):
        volume = None
    return serie, volume


def _escolher(candidatos: list[str]) -> str:
    """O primeiro que cabe em 70 caracteres; senão o primeiro que cabe em 100; senão o último, cortado."""
    candidatos = [_limpar(c) for c in dict.fromkeys(candidatos) if c]
    for limite in (LIMITE_BOM, LIMITE_TITULO):
        for c in candidatos:
            if len(c) <= limite:
                return c
    return candidatos[-1][: LIMITE_TITULO - 1].rstrip() + "…"


def _base(ficha: dict) -> tuple[str, str]:
    livro, autor = livro_e_autor(ficha)
    return f"{PALAVRA} {livro.upper()}", autor


def titulo_video(ficha: dict, numero: int, titulo_cap: str, sufixo: str = "") -> str:
    """'AUDIOLIVRO O SENHOR DAS MARÉS – CAP. 27 | Henrique Saldanha'. (`sufixo` ficou só por compatibilidade.)"""
    base, autor = _base(ficha)
    rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
    rotulo = rotulo.replace("Capítulo", "CAP.")
    com_titulo = f"{base} – {rotulo}: {titulo}" if titulo else ""
    sem_titulo = f"{base} – {rotulo}"
    por = f" | {autor}" if autor else ""
    return _escolher([com_titulo and com_titulo + por, sem_titulo + por, com_titulo, sem_titulo])


def titulo_grupo(ficha: dict, parte: int, capitulos: list[tuple[int, str]], sufixo: str = "") -> str:
    """'AUDIOLIVRO NOITE DE VIGÍLIA – PARTE 2 (Caps. 13 a 25) | Aurélio Vasconcelos'."""
    base, autor = _base(ficha)
    corpo = f"{base} – PARTE {parte}"
    faixa = f"{corpo} ({intervalo(capitulos)})"
    por = f" | {autor}" if autor else ""
    return _escolher([faixa + por, corpo + por, faixa, corpo])


def titulo_completo(ficha: dict, parte: int, total: int) -> str:
    """'AUDIOLIVRO COMPLETO DESPERTAR (2 DE 3) | Ricardo Montemor'."""
    livro, autor = livro_e_autor(ficha)
    corpo = f"{PALAVRA} COMPLETO {livro.upper()}" + (f" ({parte} DE {total})" if total > 1 else "")
    return _escolher([corpo + (f" | {autor}" if autor else ""), corpo])


def titulo_short(ficha: dict, numero: int, titulo_cap: str) -> str:
    """'O HOMEM NO TELHADO, B. K. Lemos – CAP. 6 #audiolivro #shorts'."""
    livro, autor = livro_e_autor(ficha)
    rotulo = rotulo_e_titulo(numero, titulo_cap)[0].replace("Capítulo", "CAP.")
    fim = f" – {rotulo} #audiolivro #shorts"
    return _escolher([f"{livro.upper()}, {autor}{fim}" if autor else "", f"{livro.upper()}{fim}"])


def titulo_playlist(ficha: dict) -> str:
    livro, autor = livro_e_autor(ficha)
    return _limpar(f"{PALAVRA} {livro.upper()}" + (f" – {autor}" if autor else "") + " (completo)")[:150]


def linha_principal(ficha: dict, detalhe: str = "") -> str:
    """Primeira linha da descrição (é o que aparece na busca):
    'Audiolivro O Senhor das Marés, de Henrique Saldanha – Capítulo 27. Livro 1 de As Crônicas de Tarso. ...'"""
    livro, autor = livro_e_autor(ficha)
    serie, volume = serie_e_volume(ficha)
    linha = f"Audiolivro {livro}" + (f", de {autor}" if autor else "") + (f" – {detalhe}" if detalhe else "") + "."
    if serie and volume:
        linha += f" Livro {volume} de {serie}."
    elif serie:
        linha += f" Da série {serie}."
    return linha + " Audiobook narrado em português."


def com_proximo(descricao: str, proximo_id: str) -> str:
    """Põe '⏭ Próximo: link' perto do topo de uma descrição que já está no ar (sem mexer no resto)."""
    link = f"https://youtu.be/{proximo_id}"
    if link in descricao:
        return descricao
    linhas = descricao.split("\n")
    pos = 1
    while pos < len(linhas) and linhas[pos].startswith(("▶", "📚")):
        pos += 1
    linhas.insert(pos, f"⏭ Próximo: {link}")
    return _limpar("\n".join(linhas))[:LIMITE_DESCRICAO]


def link_playlist(playlist_id: str) -> str:
    return f"https://www.youtube.com/playlist?list={playlist_id}"


def _camel(texto: str) -> str:
    return "".join(p[:1].upper() + p[1:] for p in re.findall(r"\w+", texto))


def hashtags_video(ficha: dict, extras: list[str] | None = None) -> list[str]:
    """Até 5 hashtags: as da ficha primeiro, depois #audiolivro #audiobook #NomeDoLivro #Autor."""
    livro, autor = livro_e_autor(ficha)
    saida, vistos = [], set()
    for h in [*(ficha.get("hashtags") or []), *(extras or []), "audiolivro", "audiobook", _camel(livro), _camel(autor)]:
        h = _camel(str(h).lstrip("#")) if " " in str(h) else str(h).lstrip("#").strip()
        if h and len(h) <= 30 and normalizar(h) not in vistos:
            vistos.add(normalizar(h))
            saida.append(f"#{h}")
    return saida[:5]


def descricao_video(ficha: dict, numero: int, titulo_cap: str, playlist_id: str | None, anterior_id: str | None,
                    cta: dict | None = None, cabecalho: str | None = None, marcadores: list[str] | None = None,
                    proximo_id: str | None = None) -> str:
    """Descrição de um vídeo. Num vídeo com vários capítulos, `cabecalho` é o detalhe da 1ª linha ("Parte 2: Caps.
    13 a 25") e `marcadores` são os tempos ("00:00 Abertura", "12:31 Cap. 1: …"), que viram capítulos clicáveis."""
    rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
    detalhe = cabecalho or (rotulo + (f": {titulo}" if titulo else ""))
    linhas = [linha_principal(ficha, detalhe)]
    if playlist_id:
        linhas.append(f"▶ Ouça o livro todo, em ordem (playlist): {link_playlist(playlist_id)}")
    if proximo_id:
        linhas.append(f"⏭ Próximo: https://youtu.be/{proximo_id}")
    if anterior_id:
        linhas.append(f"⏮ Anterior: https://youtu.be/{anterior_id}")
    linhas.append("")
    cta = cta or {}
    if cta.get("topo"):
        linhas += [str(cta["topo"]).strip(), ""]
    sinopse = str(ficha.get("descricao") or "").strip()
    if marcadores:
        # os marcadores não podem ser cortados: a sinopse encolhe se faltar espaço nos 5.000 caracteres
        bloco = ["Capítulos neste vídeo:", *marcadores, ""]
        sobra = LIMITE_DESCRICAO - len("\n".join(bloco)) - 1100
        if len(sinopse) > sobra:
            sinopse = sinopse[: max(0, sobra)].rsplit(" ", 1)[0] + "…" if sobra > 200 else ""
    if sinopse:
        linhas += [sinopse, ""]
    if marcadores:
        linhas += bloco
    livro, autor = livro_e_autor(ficha)
    if autor:
        linhas.append(f"Autor: {autor}")
    if ficha.get("narrador"):
        linhas.append(f"Narração: {ficha['narrador']}")
    if ficha.get("voz_sintetica"):
        linhas.append("Narração gerada com voz sintética (inteligência artificial).")
    if linhas[-1]:
        linhas.append("")
    for linha in cta.get("fim") or []:
        linhas.append(str(linha).replace("{canal}", cta.get("canal", "")))
    if cta.get("fim"):
        linhas.append("")
    linhas.append(_licenca(ficha))
    linhas += ["", " ".join(hashtags_video(ficha))]
    return _limpar("\n".join(linhas))[:LIMITE_DESCRICAO]


def _licenca(ficha: dict) -> str:
    if ficha.get("licenca", "uso_pessoal") == "uso_pessoal":
        return "Cópia privada para uso pessoal."
    if ficha.get("licenca") == "dominio_publico":
        return f"Obra em domínio público. Fonte do texto: {ficha.get('fonte_texto', '')}."
    detentor = ficha.get("detentor_direitos") or ficha.get("autor") or livro_e_autor(ficha)[1]
    return f"© {detentor}. Todos os direitos reservados. Publicado pelo detentor dos direitos."


def rotulo_curto(numero: int, titulo_cap: str) -> str:
    """'Capítulo 3' -> 'Cap. 3'; 'Prólogo' fica 'Prólogo'."""
    return rotulo_e_titulo(numero, titulo_cap)[0].replace("Capítulo", "Cap.")


def intervalo(capitulos: list[tuple[int, str]]) -> str:
    """[(1,'A'), ..., (12,'B')] -> 'Caps. 1 a 12'; [(0,'Abertura'), (5,'X')] -> 'Abertura a Cap. 5'."""
    primeiro, ultimo = rotulo_curto(*capitulos[0]), rotulo_curto(*capitulos[-1])
    a, b = re.match(r"^Cap\. (\d+)$", primeiro), re.match(r"^Cap\. (\d+)$", ultimo)
    if a and b:
        return f"Caps. {a.group(1)} a {b.group(1)}"
    return f"{primeiro} a {ultimo}"


def tempo(segundos: float) -> str:
    s = int(segundos)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def marcadores_grupo(capitulos: list[tuple[int, str, float]], longo: bool) -> list[str]:
    """[(numero, título, início em segundos)] -> ['00:00 Abertura', '12:31 Cap. 1: Da chegada', ...]."""
    linhas = []
    for numero, titulo_cap, inicio in capitulos:
        rotulo, titulo = rotulo_e_titulo(numero, titulo_cap)
        texto = rotulo.replace("Capítulo", "Cap.") + (f": {titulo}" if titulo else "")
        marca = tempo(inicio)
        if longo and inicio < 3600:
            marca = "0:" + marca      # mesmo formato em todas as linhas (0:12:31) quando o vídeo passa de 1 hora
        linhas.append(_limpar(f"{marca} {texto}"))
    return linhas


def snippet_video(ficha: dict, capitulos: list[tuple[int, str, float]], parte: int | None, playlist_id: str | None,
                  anterior_id: str | None, pub: dict, cta: dict | None = None, duracao_total: float = 0,
                  proximo_id: str | None = None) -> dict:
    """Título, descrição e tags de um vídeo com um capítulo (parte None) ou vários (marcadores de tempo)."""
    numero, titulo_cap, _ = capitulos[0]
    if parte is None or len(capitulos) == 1:
        titulo = titulo_video(ficha, numero, titulo_cap)
        descricao = descricao_video(ficha, numero, titulo_cap, playlist_id, anterior_id, cta, proximo_id=proximo_id)
    else:
        pares = [(n, t) for n, t, _ in capitulos]
        titulo = titulo_grupo(ficha, parte, pares)
        descricao = descricao_video(ficha, numero, titulo_cap, playlist_id, anterior_id, cta,
                                    f"Parte {parte}: {intervalo(pares)}",
                                    marcadores_grupo(capitulos, duracao_total >= 3600), proximo_id)
    return {
        "title": titulo,
        "description": descricao,
        "tags": tags_video(ficha),
        "categoryId": str(pub["categoria_id"]),
        "defaultLanguage": pub["idioma"],
        "defaultAudioLanguage": pub["idioma"],
    }


def tags_video(ficha: dict, extras: list[str] | None = None) -> list[str]:
    """Tags da ficha + variações de busca (livro, autor, série, audiolivro/audiobook), até ~450 caracteres."""
    livro, autor = livro_e_autor(ficha)
    serie, _ = serie_e_volume(ficha)
    candidatas = [*(ficha.get("tags") or []), *(extras or []), "audiolivro", "audiobook", livro,
                  f"{livro} audiolivro", f"{livro} audiobook", autor, autor and f"{autor} audiolivro", serie,
                  "audiolivro completo", "livro narrado", "audiolivro em português", "audiobook em português"]
    tags, total = [], 0
    for tag in candidatas:
        tag = _limpar(tag or "").replace(",", " ")[:100]
        custo = len(tag) + (2 if " " in tag else 0) + 1
        if tag and tag.lower() not in (t.lower() for t in tags) and total + custo <= LIMITE_TAGS:
            tags.append(tag)
            total += custo
    return tags


def descricao_playlist(ficha: dict) -> str:
    partes = [linha_principal(ficha, "todos os capítulos, em ordem")]
    if ficha.get("descricao"):
        partes.append(str(ficha["descricao"]).strip())
    partes.append(" ".join(hashtags_video(ficha)))
    return _limpar("\n\n".join(partes))[:5000]
