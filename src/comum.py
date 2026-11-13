"""Utilidades compartilhadas: configuração, nomes de arquivo e normalização de texto."""

import logging
import os
import re
import unicodedata
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parent.parent
EXT_AUDIO = {".mp3", ".m4a", ".m4b", ".wav", ".flac", ".ogg", ".opus", ".aac"}
EXT_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}

# "01 - Título.mp3", "01_Título.mp3", "01.mp3"
_PADRAO_CAPITULO = re.compile(r"^\s*(\d{1,6})(?:\s*[-–—_.]\s*(.*?)|\s+(\D.*?))?\s*$")
# "Pasta49_002-Os dois lados de um dilema B.mp3": capítulo 49, parte 2 (letra B)
_PADRAO_PARTE = re.compile(r"^\s*[Pp]asta\s*(\d{1,4})\s*[_-]\s*(\d{1,3})\s*[-–_]\s*(.*?)(?:\s+([A-Z]))?\s*$")
# "003. O senhor das marés_ As crônicas de Tarso, Livro 1 - 03 - Capítulo 1.mp3": faixa 3, seção "Capítulo 1"
_PADRAO_FAIXA = re.compile(r"^\s*(\d{1,4})\.\s+.+?\s-\s(\d{1,4})\s-\s(.+?)\s*$")
# "Capítulo 57", "Capitulo 57", "Capótulo 46" (erro de digitação), "Cap. 3"
_NUMERO_NO_TITULO = re.compile(r"^cap\w*\.?\s*(\d+)\s*$")
_CARACTERES_PROIBIDOS = re.compile(r'[\\/:*?"<>|]+')

log = logging.getLogger("audiolivro")


def configurar_log() -> None:
    """Log na tela. No GitHub Actions liga o modo discreto (src/discreto.py): nada do canal aparece no log."""
    import discreto
    if discreto.ativo():
        discreto.ativar()
        discreto.configurar_logging()
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


ARQ_CANAL = "canal.yaml"
# Partes do config que são do canal (e não do robô): vêm do canal.yaml e ficam escondidas no log.
BLOCOS_DO_CANAL = ("cta", "video.cta", "publicacao.pausados", "publicacao.livros", "seo.titulos_protegidos",
                   "metadados")
_cache_canal: dict = {}


def mesclar(base: dict, extra: dict) -> dict:
    """Junta dois configs: o que está em `extra` vale; dicionários são mesclados por dentro, listas são trocadas."""
    saida = dict(base or {})
    for chave, valor in (extra or {}).items():
        if isinstance(valor, dict) and isinstance(saida.get(chave), dict):
            saida[chave] = mesclar(saida[chave], valor)
        else:
            saida[chave] = valor
    return saida


def _ler_yaml(texto: str, origem: str) -> dict:
    try:
        dados = yaml.safe_load(texto) or {}
    except yaml.YAMLError as erro:
        raise SystemExit(f"O {origem} não está num formato válido ({type(erro).__name__}). Corrija e rode de novo.")
    if not isinstance(dados, dict):
        raise SystemExit(f"O {origem} precisa ter o formato 'campo: valor'.")
    return dados


def canal_do_drive() -> dict | None:
    """canal.yaml da pasta raiz do Drive (None se não houver Drive configurado ou o arquivo não existir)."""
    raiz = os.environ.get("DRIVE_PASTA_RAIZ")
    if not raiz or not os.environ.get("GOOGLE_REFRESH_TOKEN") or os.environ.get("ROBO_CANAL_DRIVE") == "0":
        return None
    if "drive" not in _cache_canal:
        from google_api import Drive, credenciais_do_ambiente
        drive = Drive(credenciais_do_ambiente())
        item = drive.achar(raiz, ARQ_CANAL)
        _cache_canal["drive"] = _ler_yaml(drive.ler_texto(item["id"]), f"{ARQ_CANAL} do Drive") if item else None
    return _cache_canal["drive"]


def carregar_config(caminho: Path | None = None, canal: bool = True) -> dict:
    """config.yaml (genérico, no repositório) + canal.yaml (o que é do canal) por cima.

    O canal.yaml é procurado, nesta ordem (o último vale): na pasta do projeto (uso no computador ou repositório
    privado), no caminho de ROBO_CANAL e na pasta raiz do Drive (DRIVE_PASTA_RAIZ)."""
    with open(caminho or RAIZ / "config.yaml", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not canal or caminho is not None:
        return cfg
    local = RAIZ / ARQ_CANAL if os.environ.get("ROBO_SEM_CANAL_LOCAL") != "1" else None
    for arquivo in (local, Path(os.environ["ROBO_CANAL"]) if os.environ.get("ROBO_CANAL") else None):
        if arquivo and arquivo.exists():
            cfg = mesclar(cfg, _ler_yaml(arquivo.read_text(encoding="utf-8"), arquivo.name))
    do_drive = canal_do_drive()
    if do_drive:
        cfg = mesclar(cfg, do_drive)
    aplicar_canal(cfg)
    return cfg


def so_audiolivro(nome: str) -> bool:
    """True (e um aviso no log) se o canal está no modo Bíblia: esta etapa é só dos audiolivros e não roda."""
    if str(carregar_config().get("modo") or "").strip().lower() == "biblia":
        import discreto
        log.info("%s: não se aplica ao modo Bíblia; pulando.", discreto.Seguro(nome))
        return True
    return False


def aplicar_canal(cfg: dict) -> None:
    """Marca os textos do canal como sensíveis (modo discreto) e passa listas do canal para os módulos."""
    import discreto
    for caminho in BLOCOS_DO_CANAL:
        valor = cfg
        for parte in caminho.split("."):
            valor = valor.get(parte) if isinstance(valor, dict) else None
        if caminho == "seo.titulos_protegidos":
            for vid in valor or []:
                discreto.registrar(vid, "vídeo")
        else:
            discreto.registrar_dados(valor, "texto do canal")
    import metadados
    metadados.configurar(cfg.get("metadados"))


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos, para comparar palavras."""
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def eh_audio(nome: str) -> bool:
    return Path(nome).suffix.lower() in EXT_AUDIO


def eh_imagem(nome: str) -> bool:
    return Path(nome).suffix.lower() in EXT_IMAGEM


# Faixas viram 1000, 2000, 3000... para que os capítulos cortados de uma faixa (2001, 2002...) caibam entre elas.
# Capítulo com número a partir disso foi numerado pela ordem das faixas: o vídeo mostra só o título.
FATOR_FAIXA = 1000

# "CD02_005-cap.04.mp3", "cd01-001-Cap.01.mp3", "CD01_faixa01_cap01(01).mp3": disco 2, faixa 5, título "cap.04"
_PADRAO_CD = re.compile(r"^\s*CD(\d{1,3})\s*[_ -]+\s*(?:faixa\s*)?(\d{1,4})(?:\s*[-–—_.]*\s*(.*?))?\s*$", re.IGNORECASE)
# "faixa01_mudança(1).mp3"
_PADRAO_FAIXA_SIMPLES = re.compile(r"^\s*faixa\s*(\d{1,4})\s*[-–—_. ]+\s*(.*?)\s*$", re.IGNORECASE)
# "O Farol - 0001 - Capítulo 1.mp3", "Três anéis - 0002 - Três anéis.mp3" (sem número no começo)
_PADRAO_LIVRO_FAIXA = re.compile(r"^\s*(\D.*?)\s+-\s+(\d{1,4})\s+-\s+(.+?)\s*$")


def ler_nome_cd(nome: str) -> tuple[int, int, str] | None:
    """'cd02_003-FreiSimao_Cap.III.mp3' -> (2, 3, 'FreiSimao_Cap.III'). None se não for nome de CD."""
    cd = _PADRAO_CD.match(unicodedata.normalize("NFC", Path(nome).stem))
    if not cd:
        return None
    return int(cd.group(1)), int(cd.group(2)), (cd.group(3) or "").strip()


def ler_nome_faixa_simples(nome: str) -> tuple[int, str] | None:
    """'faixa01_mudança(1).mp3' -> (1, 'mudança(1)'); 'O Engano - 0002 - Capítulo 2.mp3' -> (2, 'Capítulo 2')."""
    stem = unicodedata.normalize("NFC", Path(nome).stem)
    if m := _PADRAO_FAIXA_SIMPLES.match(stem):
        return int(m.group(1)), m.group(2)
    if m := _PADRAO_LIVRO_FAIXA.match(stem):
        return int(m.group(2)), m.group(3)
    return None


_CAPITULO_GRUDADO = re.compile(r"^(?:cap(?:itulo|ítulo)?|chapter)\s*\.?\s*0*(\d+)\s*(?:\(\d+\))?\s*$", re.IGNORECASE)


def limpar_titulo(titulo: str) -> str:
    """Deixa o título do arquivo legível: 'AsHistoriasSemData' -> 'As Historias Sem Data', 'cap01(01)' -> 'Capítulo 1',
    'Chapter 3' -> 'Capítulo 3', 'mudança(1)' -> 'Mudança', 'cont.cadeia' -> 'Cont. cadeia'."""
    t = (titulo or "").strip().lstrip("-–—_. ").strip()
    if m := _CAPITULO_GRUDADO.match(t):
        return f"Capítulo {int(m.group(1))}"
    t = re.sub(r"\s*\(\d+\)\s*$", "", t)                  # "(1)" no fim: cópia repetida do arquivo
    if " " not in t and re.search(r"[a-zà-ú][A-ZÀ-Ú]", t):     # tudo grudado em CamelCase
        t = re.sub(r"(?<=[a-zà-ú])(?=[A-ZÀ-Ú])", " ", t)
    t = t.replace("_", " ")
    t = re.sub(r"\b(cap|cont)\.(?=\S)", r"\1. ", t, flags=re.IGNORECASE)
    t = " ".join(t.split())
    if m := _CAPITULO_GRUDADO.match(t):
        return f"Capítulo {int(m.group(1))}"
    return t[:1].upper() + t[1:] if t[:1].islower() else t


def ler_nome_capitulo(nome: str) -> tuple[int, str] | None:
    """'03 - Da Estrada.mp3' -> (3, 'Da Estrada'). Retorna None se o nome não começar com número."""
    if cd := ler_nome_cd(nome):
        _, numero, titulo = cd
        return numero, "Abertura" if numero == 0 else titulo
    m = _PADRAO_CAPITULO.match(unicodedata.normalize("NFC", Path(nome).stem))
    if not m:
        return None
    return int(m.group(1)), (m.group(2) or m.group(3) or "").strip()


def titulo_generico(titulo: str) -> bool:
    """'Capitulo 57' não acrescenta nada além do número."""
    return bool(_NUMERO_NO_TITULO.match(normalizar(titulo)))


def ler_nome_parte(nome: str) -> tuple[int, tuple[int, str], str] | None:
    """'Pasta49_002-Os dois lados B.mp3' -> (49, (2, 'B'), 'Os dois lados'). None se não for desse formato."""
    m = _PADRAO_PARTE.match(unicodedata.normalize("NFC", Path(nome).stem))
    if not m:
        return None
    numero, titulo = int(m.group(1)), m.group(3).strip()
    # "Pasta75_003 - Capítulo 74 C": o título manda (arquivo guardado na pasta errada).
    no_titulo = _NUMERO_NO_TITULO.match(normalizar(titulo))
    if no_titulo:
        numero = int(no_titulo.group(1))
    return numero, (int(m.group(2)), m.group(4) or ""), titulo


def ler_nome_faixa(nome: str) -> tuple[int, str] | None:
    """'003. Livro_ Série - 03 - Parte 1_ Um Nascimento.mp3' -> (3, 'Parte 1: Um Nascimento')."""
    m = _PADRAO_FAIXA.match(unicodedata.normalize("NFC", Path(nome).stem))
    if not m:
        return None
    secao = re.sub(r"_\s", ": ", m.group(3)).strip()
    return int(m.group(1)), secao


def nome_arquivo_capitulo(numero: int, titulo: str, ext: str, largura: int = 2) -> str:
    titulo = " ".join(_CARACTERES_PROIBIDOS.sub(" ", titulo).split())
    base = f"{numero:0{largura}d}"
    return f"{base} - {titulo}{ext}" if titulo else f"{base}{ext}"


def pausado(cfg: dict, nome_pasta: str) -> bool:
    """config.yaml > publicacao > pausados: livros que o robô não publica (ex.: já postados antes do robô)."""
    return any(normalizar(t) in normalizar(nome_pasta) for t in (cfg.get("publicacao", {}).get("pausados") or []))
