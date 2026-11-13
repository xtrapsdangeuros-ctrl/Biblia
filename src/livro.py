"""Lê a pasta de um livro no Drive: ficha, capa, capítulos prontos e arquivos que ainda precisam de corte."""

import re
import unicodedata
from dataclasses import dataclass, field

import yaml

from datetime import datetime, timedelta, timezone

import discreto
from comum import (FATOR_FAIXA, eh_audio, eh_imagem, ler_nome_capitulo, ler_nome_cd, ler_nome_faixa,
                   ler_nome_faixa_simples, ler_nome_parte, limpar_titulo, normalizar)
from google_api import Drive

NOMES_FICHA = {"livro.yaml", "livro.yml", "ficha.yaml", "ficha.yml", "ficha.txt", "ficha", "livro"}
GOOGLE_DOC = "application/vnd.google-apps.document"
PASTA_CAPITULOS = "capitulos"
# Arquivo de "Parte" maior que isso é a parte inteira do livro, e não só o anúncio dela: vai para o corte.
TAMANHO_PARTE_PARA_CORTE = 20 * 1024 * 1024
HORAS_ESPERA_UPLOAD = 6
PASTA_ORIGINAIS = "originais"
ARQ_PUBLICADOS = "publicados.json"
ARQ_CORTES = "cortes.json"
# Pastas da raiz que não são livros (o robô não publica nem corta nada delas)
PASTAS_IGNORADAS = {"testes de voz", "previas de shorts", "criticas", "relatorios do robo"}
LICENCAS = {"uso_pessoal", "dominio_publico", "proprio"}
PRIVACIDADES = {"private", "unlisted", "public"}
# Só obra em domínio público ou com direitos do próprio canal pode sair do modo privado.
LICENCAS_QUE_PODEM_SER_PUBLICAS = {"dominio_publico", "proprio"}
# "Ricardo Montemor Valtor (Ciclo do Despertar Vol. 1)" -> série "Ciclo do Despertar", volume 1
_SERIE_VOLUME = re.compile(r"\((?P<serie>[^()]*?)\s*[,-]?\s*vol(?:ume)?\.?\s*(?P<vol>\d+)\s*\)", re.IGNORECASE)


@dataclass
class Capitulo:
    numero: int
    titulo: str
    arquivos: list[dict]   # em ordem; mais de um quando o capítulo vem em partes (A, B...)
    problema: str = ""     # se preenchido, o capítulo não é publicado (e a fila do livro para nele)
    aviso: str = ""        # só registrado no log; o capítulo é publicado assim mesmo


@dataclass
class Livro:
    pasta: dict
    ficha: dict
    capa: dict | None
    capitulos: list[Capitulo] = field(default_factory=list)
    a_cortar: list[dict] = field(default_factory=list)
    problemas: list[str] = field(default_factory=list)
    incompleto: str = ""   # motivo para esperar (o livro ainda está subindo); vazio = pronto

    @property
    def nome(self) -> str:
        return self.pasta["name"]


def validar_ficha(ficha: dict) -> list[str]:
    problemas = []
    if not ficha.get("titulo"):
        problemas.append("a ficha não tem o campo 'titulo'")
    licenca = ficha.get("licenca")
    if licenca not in LICENCAS:
        problemas.append(f"licenca deve ser uma de {sorted(LICENCAS)} (está '{licenca}')")
    privacidade = ficha.get("privacidade", "private")
    if privacidade not in PRIVACIDADES:
        problemas.append(f"privacidade deve ser uma de {sorted(PRIVACIDADES)} (está '{privacidade}')")
    elif privacidade != "private" and licenca not in LICENCAS_QUE_PODEM_SER_PUBLICAS:
        problemas.append(
            f"privacidade '{privacidade}' só é permitida para licenca dominio_publico ou proprio "
            f"(este livro está como '{licenca}', então fica privado)"
        )
    if licenca == "dominio_publico" and not ficha.get("fonte_texto"):
        problemas.append("livro em domínio público precisa do campo 'fonte_texto' (de onde veio o texto/tradução)")
    return problemas


def _ler_ficha(drive: Drive, item: dict) -> dict:
    texto = drive.ler_texto(item["id"], google_doc=item["mimeType"] == GOOGLE_DOC)
    dados = yaml.safe_load(texto) or {}
    if not isinstance(dados, dict):
        raise ValueError("a ficha não está no formato 'campo: valor'")
    return dados


def carregar_livro(drive: Drive, pasta: dict) -> Livro | None:
    """Retorna None se a pasta não tiver nenhum áudio nem subpasta (não é uma pasta de livro)."""
    itens = drive.listar(pasta["id"])
    if not any(eh_audio(i["name"]) or Drive.eh_pasta(i) for i in itens):
        return None

    # A ficha é opcional: sem ela, o título vem do nome da pasta e o uso é pessoal.
    nome_pasta = unicodedata.normalize("NFC", pasta["name"])
    titulo_pasta = _SERIE_VOLUME.sub("", nome_pasta).strip() or nome_pasta
    ficha, problemas = {"titulo": titulo_pasta, "licenca": "uso_pessoal"}, []
    serie_pasta = _SERIE_VOLUME.search(nome_pasta)
    if serie_pasta:
        ficha.update(serie=serie_pasta.group("serie").strip(), volume=int(serie_pasta.group("vol")))
    item_ficha = next((i for i in itens if normalizar(i["name"]) in NOMES_FICHA), None)
    if item_ficha:
        try:
            ficha.update(_ler_ficha(drive, item_ficha))
            problemas = validar_ficha(ficha)
        except (yaml.YAMLError, ValueError) as erro:
            problemas = [f"não consegui ler a ficha: {erro}"]

    # Capa opcional: "capa.jpg" ou, na falta, a primeira imagem da pasta.
    imagens = [i for i in itens if eh_imagem(i["name"])]
    capa = next((i for i in imagens if normalizar(i["name"]).startswith("capa")), imagens[0] if imagens else None)

    livro = Livro(pasta=pasta, ficha=ficha, capa=capa, problemas=problemas)
    discreto.registrar_ficha(pasta["name"], ficha)

    partes: dict[int, list[tuple[tuple[int, str], str, dict]]] = {}
    numeros_origem: list[int] = []   # numeração do jeito que veio (para achar buracos)
    discos: list[tuple[int, int, str, dict]] = []   # "cd02_003-...": (disco, faixa, título, arquivo)
    vistos = set()
    for item in itens:
        if Drive.eh_pasta(item) or not eh_audio(item["name"]):
            continue
        # o mesmo arquivo enviado duas vezes (mesmo nome e tamanho): usa só um
        chave = (unicodedata.normalize("NFC", item["name"]), item.get("size"))
        if chave in vistos:
            continue
        vistos.add(chave)
        if cd := ler_nome_cd(item["name"]):
            discos.append((*cd, item))
            continue
        if parte := ler_nome_parte(item["name"]):
            numero, ordem, titulo = parte
            partes.setdefault(numero, []).append((ordem, titulo, item))
            numeros_origem.append(numero)
        elif faixa := ler_nome_faixa(item["name"]):
            numero, secao = faixa
            numeros_origem.append(numero)
            if normalizar(secao).startswith("parte ") and int(item.get("size") or 0) > TAMANHO_PARTE_PARA_CORTE:
                livro.a_cortar.append(item)
            else:
                livro.capitulos.append(Capitulo(numero * FATOR_FAIXA, _titulo_util(secao, livro), [item]))
        elif simples := ler_nome_faixa_simples(item["name"]):
            numero, titulo = simples
            numeros_origem.append(numero)
            titulo = "Abertura" if numero == 0 else _titulo_util(limpar_titulo(titulo), livro)
            livro.capitulos.append(Capitulo(numero * FATOR_FAIXA, titulo, [item]))
        elif lido := ler_nome_capitulo(item["name"]):
            numeros_origem.append(lido[0])
            livro.capitulos.append(Capitulo(lido[0], _titulo_util(lido[1], livro), [item]))
        else:
            livro.a_cortar.append(item)

    # CDs: se a numeração das faixas recomeça em cada disco, a ordem é (disco, faixa)
    faixas = [f for _, f, _, _ in discos]
    por_disco = len(set(faixas)) != len(faixas)
    for disco, faixa, titulo, item in sorted(discos, key=lambda d: (d[0], d[1])):
        numeros_origem.append(faixa)
        if por_disco:
            numero = (disco + 1) * FATOR_FAIXA + faixa
            titulo = "Abertura" if (disco, faixa) == (0, 0) else limpar_titulo(titulo)
        else:
            numero, titulo = faixa, "Abertura" if faixa == 0 else titulo
        livro.capitulos.append(Capitulo(numero, titulo, [item]))

    for numero, lista in partes.items():
        lista.sort(key=lambda p: p[0])
        nomes = [p[2]["name"] for p in lista]
        numeros_partes = [p[0][0] for p in lista]
        letras = {p[0][1] for p in lista}
        problema = aviso = ""
        if len(set(p[0] for p in lista)) != len(lista):
            problema = f"partes repetidas: {nomes}"
        # Numeração com buraco (ex.: só existe a _002) costuma ser só nome diferente: publica e avisa.
        elif sorted(set(numeros_partes)) != list(range(1, max(numeros_partes) + 1)):
            faltando = sorted(set(range(1, max(numeros_partes) + 1)) - set(numeros_partes))
            aviso = f"numeração das partes pula {faltando}; publicando só: {nomes}"
        titulos = {normalizar(p[1]) for p in lista}
        titulo = "Abertura" if numero == 0 and len(titulos) > 1 else lista[0][1]
        livro.capitulos.append(Capitulo(numero, titulo, [p[2] for p in lista], problema, aviso))

    pasta_caps = next((i for i in itens if Drive.eh_pasta(i) and i["name"] == PASTA_CAPITULOS), None)
    if pasta_caps:
        for item in drive.listar(pasta_caps["id"]):
            lido = ler_nome_capitulo(item["name"]) if eh_audio(item["name"]) else None
            if lido:
                livro.capitulos.append(Capitulo(lido[0], lido[1], [item]))

    livro.capitulos.sort(key=lambda c: c.numero)
    livro.capitulos = _juntar_continuacoes(livro.capitulos)
    # faixa sem título próprio (só repetia o nome do livro): "Capítulo 1", "Capítulo 2"... pela ordem
    sem_titulo = [c for c in livro.capitulos if c.numero >= FATOR_FAIXA and not c.titulo]
    for ordem, c in enumerate(sem_titulo, start=1):
        c.titulo = "Completo" if len(sem_titulo) == 1 else f"Capítulo {ordem}"
    numeros = [c.numero for c in livro.capitulos]
    repetidos = sorted({n for n in numeros if numeros.count(n) > 1})
    if repetidos:
        livro.problemas.append(f"há mais de um arquivo para o(s) capítulo(s) {repetidos}")
    # livro narrado pelo robô: os capítulos chegam em ordem, um por vez; não precisa esperar "terminar de subir"
    if not ficha.get("completo") and not ficha.get("narrar"):
        livro.incompleto = _motivo_incompleto(itens, numeros_origem)
    return livro


_CONTINUACAO = re.compile(r"^(cont\.|cont\s|continua[cç][aã]o\b)", re.IGNORECASE)


def _juntar_continuacoes(capitulos: list[Capitulo]) -> list[Capitulo]:
    """Nas faixas numeradas pela ordem (1000+), 'Cont. cadeia' ou duas faixas seguidas 'Cap. 5' são o mesmo
    capítulo em partes: viram um vídeo só, com o título da primeira."""
    saida: list[Capitulo] = []
    for c in capitulos:
        anterior = saida[-1] if saida else None
        if (anterior and c.numero >= FATOR_FAIXA and anterior.numero >= FATOR_FAIXA and c.titulo
                and (_CONTINUACAO.match(c.titulo) or normalizar(c.titulo) == normalizar(anterior.titulo))):
            anterior.arquivos = anterior.arquivos + c.arquivos
            continue
        saida.append(c)
    return saida


def _titulo_util(titulo: str, livro: "Livro") -> str:
    """'Cronicas Esparsas - Aurélio Vasconcelos(1)' ou 'Vigília - Gervásio Ramalho - 01' só repetem o livro: sem título."""
    palavras = set(re.findall(r"[a-z]+", normalizar(livro.nome + " " + str(livro.ficha.get("titulo", "")) + " "
                                                   + str(livro.ficha.get("autor", "")))))
    resto = re.findall(r"[a-z]+", normalizar(re.sub(r"\(\d+\)|\d+", " ", titulo)))
    if resto and all(p in palavras for p in resto) and (len(resto) >= 2 or normalizar(livro.nome).endswith(resto[0])):
        return ""
    return titulo


def _motivo_incompleto(itens: list[dict], numeros: list[int]) -> str:
    """Um livro ainda subindo tem buracos na numeração ou arquivos que acabaram de chegar."""
    if numeros:
        unicos = sorted(set(numeros))
        faltando = sorted(set(range(unicos[0], unicos[-1] + 1)) - set(unicos))
        if faltando:
            amostra = ", ".join(map(str, faltando[:8])) + ("..." if len(faltando) > 8 else "")
            return f"faltam os números {amostra} (o livro ainda está subindo?)"
    limite = datetime.now(timezone.utc) - timedelta(hours=HORAS_ESPERA_UPLOAD)
    recentes = [i for i in itens if i.get("createdTime") and
                datetime.fromisoformat(i["createdTime"].replace("Z", "+00:00")) > limite]
    if recentes:
        return f"{len(recentes)} arquivo(s) chegaram nas últimas {HORAS_ESPERA_UPLOAD} h (esperando terminar de subir)"
    return ""


def privacidade_do_livro(ficha: dict) -> str:
    """Privado, a não ser que a ficha peça outra coisa E a licença permita."""
    pedida = ficha.get("privacidade", "private")
    if pedida in PRIVACIDADES and ficha.get("licenca") in LICENCAS_QUE_PODEM_SER_PUBLICAS:
        return pedida
    return "private"


def ordem_da_pasta(nome: str) -> tuple:
    """Livros da mesma série ficam juntos e em ordem de volume; o resto, por nome."""
    m = _SERIE_VOLUME.search(nome)
    if m:
        return (normalizar(m.group("serie")), int(m.group("vol")), normalizar(nome))
    return (normalizar(nome), 0, "")


def pastas_de_livros(drive: Drive, raiz_id: str) -> list[dict]:
    pastas = [i for i in drive.listar(raiz_id) if Drive.eh_pasta(i) and normalizar(i["name"]) not in PASTAS_IGNORADAS]
    discreto.registrar_livros(pastas)   # no log, cada livro aparece como "livro N"
    return sorted(pastas, key=lambda p: ordem_da_pasta(p["name"]))


def pedido_casa(pedido: str, nome_pasta: str, exato: bool = False) -> bool:
    """O livro pedido (no Run workflow ou na linha de comando) é esta pasta? Aceita o número que aparece no log
    ("3" ou "livro 3"), o nome exato da pasta ou, se exato=False, um trecho do nome."""
    if discreto.numero_do_livro(pedido) is not None:
        return discreto.casa_livro(pedido, nome_pasta)
    if exato:
        return normalizar(nome_pasta) == normalizar(pedido)
    return normalizar(pedido) in normalizar(nome_pasta)
