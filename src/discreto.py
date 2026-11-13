"""Modo discreto: o log do GitHub Actions não mostra nada do canal.

Num repositório público, qualquer pessoa lê o log das execuções. Por isso, quando o robô roda no GitHub Actions
(ou com ROBO_DISCRETO=1), tudo o que vai para a tela passa por aqui:

- Mensagens do log: cada valor "%s" vira um rótulo neutro ("livro 3", "vídeo 12") se for conhecido, ou "‹…›" se
  não for. Números ficam. Erros viram só o tipo do erro ("HttpError 403"). Assim, uma mensagem nova que alguém
  escrever no código também sai protegida, sem precisar revisar cada uma.
- Tudo o que o robô lê do Drive e do YouTube (nomes de pasta e arquivo, IDs, títulos, descrições) é registrado
  como sensível: o texto é trocado pelo rótulo onde quer que apareça, e o GitHub recebe um "::add-mask::" para
  esconder o valor com *** se ele escapar por outro caminho.
- O que programas de fora escrevem (ffmpeg, whisper, bibliotecas) e os erros completos (traceback) não vão para
  a tela: ficam só no relatório.
- No fim, o relatório completo (com os nomes de verdade e a legenda dos rótulos) é salvo no Drive, na pasta
  "Relatórios do robô". Nada disso vai para o log nem para artifacts do GitHub.

Fora do GitHub Actions (no seu computador), nada muda: o log mostra tudo, como sempre.
"""

import atexit
import json
import logging
import os
import re
import sys
import threading
import traceback
import unicodedata
from datetime import datetime, timedelta, timezone

PASTA_RELATORIOS = "Relatórios do robô"
OCULTO = "‹…›"
# Nomes que o próprio robô cria: não dizem nada sobre o canal e aparecem em todo lugar.
GENERICOS = {
    "capitulos", "originais", "publicados.json", "cortes.json", "narracao.json", "miniaturas.json",
    "ficha.txt", "ficha.yaml", "ficha.yml", "livro.yaml", "livro.yml", "ficha", "livro", "capa.jpg", "capa.png",
    "canal.yaml", "transcricoes", "a fazer", "feitas", "criticas", "previas de shorts", "testes de voz",
    "relatorios do robo", "audiolivros", "plano_seo.json",
}
_URL = re.compile(r"https?://(?:www\.|m\.)?(?:youtu\.be|youtube\.com|drive\.google\.com|docs\.google\.com)\S*",
                  re.IGNORECASE)
_HANDLE = re.compile(r"(?<![\w.])@[A-Za-z0-9_.-]{3,}")
# Valor de "%s" que pode aparecer como está: número, palavra técnica minúscula ("private", "quotaExceeded").
_NUMERICO = re.compile(r"[\d\s.,:%/+-]*")
_PALAVRA_TECNICA = re.compile(r"[a-z][a-zA-Z_-]{0,23}")


class Seguro(str):
    """Texto que o programador garante não ter nada do canal (aparece no log como está)."""


def ativo() -> bool:
    valor = os.environ.get("ROBO_DISCRETO", "").strip().lower()
    if valor in ("1", "true", "sim", "on"):
        return True
    if valor in ("0", "false", "nao", "não", "off"):
        return False
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


# ---------------------------------------------------------------- registro de valores sensíveis

class _Registro:
    def __init__(self):
        self.rotulos: dict[str, str] = {}     # valor -> rótulo
        self.contagem: dict[str, int] = {}
        self._regex = None
        self._trava = threading.Lock()
        self.mascarados: set[str] = set()

    def limpar(self):
        with self._trava:
            self.rotulos.clear()
            self.contagem.clear()
            self.mascarados.clear()
            self._regex = None

    def _novo_rotulo(self, tipo: str) -> str:
        self.contagem[tipo] = self.contagem.get(tipo, 0) + 1
        return f"{tipo} {self.contagem[tipo]}"

    def registrar(self, valor, tipo: str = "texto", rotulo: str | None = None) -> str:
        """Marca o valor como sensível e devolve o rótulo neutro que aparece no lugar dele."""
        if valor is None:
            return OCULTO
        valor = str(valor).strip()
        if not rotulo and _PALAVRA_TECNICA.fullmatch(valor):   # "public", "dominio_publico": não é do canal
            return valor
        if not _vale_registrar(valor):
            return valor if valor else OCULTO
        with self._trava:
            atual = self.rotulos.get(valor)
            if atual and not rotulo:
                return atual
            novo = rotulo or self._novo_rotulo(tipo)
            for forma in {valor, unicodedata.normalize("NFC", valor), unicodedata.normalize("NFD", valor)}:
                self.rotulos[forma] = novo
            self._regex = None
        _mascarar(valor)
        return novo

    def rotulo(self, valor) -> str | None:
        return self.rotulos.get(str(valor).strip()) if valor is not None else None

    def trocar(self, texto: str) -> str:
        if not self.rotulos:
            return texto
        with self._trava:
            if self._regex is None:
                valores = sorted(self.rotulos, key=len, reverse=True)
                self._regex = re.compile("|".join(re.escape(v) for v in valores))
            regex, rotulos = self._regex, dict(self.rotulos)
        texto = regex.sub(lambda m: rotulos[m.group(0)], texto)
        # "'livro 3'" fica "livro 3"
        return re.sub(r"'((?:[a-zçãéíóú]+ )*[a-zçãéíóú]+ \d+)'", r"\1", texto)


def _vale_registrar(valor: str) -> bool:
    if len(valor) < 4:
        return False
    sem_ext = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", valor)
    if not re.search(r"[^\W\d_]", sem_ext) and len(sem_ext) < 8:   # "01.mp3", "2026"
        return False
    return _norm(valor) not in GENERICOS


_reg = _Registro()


def registrar(valor, tipo: str = "texto", rotulo: str | None = None) -> str:
    return _reg.registrar(valor, tipo, rotulo)


def registrar_texto(texto, tipo: str = "texto") -> None:
    """Texto longo (descrição, ficha): registra o texto inteiro e cada linha com conteúdo."""
    if not texto:
        return
    texto = str(texto)
    for linha in texto.splitlines():
        if len(linha.strip()) >= 8:
            _reg.registrar(linha, tipo)
    if "\n" not in texto.strip():
        _reg.registrar(texto, tipo)


def registrar_dados(dados, tipo: str = "texto") -> None:
    """Registra todos os textos de um dicionário/lista (ex.: o bloco do canal no config, um JSON do Drive)."""
    if isinstance(dados, dict):
        for chave, valor in dados.items():
            if isinstance(valor, str):
                chave = str(chave)
                if chave == "video_id" or chave.endswith("video"):
                    registrar(valor, "vídeo")
                elif "playlist" in chave:
                    registrar(valor, "playlist")
                elif chave == "id" or chave.endswith("_id") or chave == "comentario":
                    registrar(valor, "id")
                else:
                    registrar_texto(valor, tipo)
            else:
                registrar_dados(valor, tipo)
    elif isinstance(dados, (list, tuple, set)):
        for valor in dados:
            registrar_dados(valor, tipo) if not isinstance(valor, str) else registrar_texto(valor, tipo)
    elif isinstance(dados, str):
        registrar_texto(dados, tipo)


def registrar_item_drive(item: dict, tipo: str | None = None) -> None:
    if not isinstance(item, dict):
        return
    if item.get("id"):
        registrar(item["id"], "id")
    if item.get("name") and not _reg.rotulo(item["name"]):
        registrar(item["name"], tipo or ("pasta" if str(item.get("mimeType", "")).endswith("folder") else "arquivo"))


def registrar_livros(pastas: list[dict]) -> None:
    """As pastas de livro ganham número fixo pela ordem em que foram criadas no Drive ("livro 1", "livro 2"...).
    Livro novo entra no fim, e os números dos antigos não mudam."""
    ordem = sorted(pastas, key=lambda p: (str(p.get("createdTime") or ""), p.get("name", "")))
    for n, pasta in enumerate(ordem, start=1):
        registrar(pasta.get("name"), rotulo=f"livro {n}")
        if pasta.get("id"):
            registrar(pasta["id"], "id")


def registrar_ficha(nome_pasta: str, ficha: dict) -> None:
    """Título, autor, série e textos da ficha também são sensíveis (aparecem sozinhos nos títulos)."""
    base = _reg.rotulo(nome_pasta) or registrar(nome_pasta, "livro")
    for campo, nome in (("titulo", "título"), ("autor", "autor"), ("serie", "série"), ("narrador", "narrador")):
        if isinstance(ficha.get(campo), str):
            valor = ficha[campo].strip()
            if _vale_registrar(valor) and not _reg.rotulo(valor):
                registrar(valor, rotulo=f"{nome} do {base}")
    try:   # "Ricardo Montemor Despertar": o autor e o título sozinhos
        from metadados import livro_e_autor
        titulo, autor = livro_e_autor(ficha)
        for valor, nome in ((titulo, "título"), (autor, "autor")):
            if valor and _vale_registrar(valor) and not _reg.rotulo(valor):
                registrar(valor, rotulo=f"{nome} do {base}")
    except Exception:
        pass
    registrar_dados({k: v for k, v in ficha.items() if k not in ("titulo", "autor", "serie", "narrador")}, "texto")


def rotulo(valor) -> str:
    """O rótulo neutro do valor (para usar numa mensagem): 'livro 3'. Desconhecido: '‹…›'."""
    return Seguro(_reg.rotulo(valor) or OCULTO) if ativo() else Seguro(str(valor))


def limpar(texto: str) -> str:
    """Troca valores registrados por rótulos e esconde links do YouTube/Drive e @canais."""
    texto = _URL.sub("‹link›", str(texto))   # antes dos rótulos: "youtu.be/<id>" vira só ‹link›
    texto = _reg.trocar(texto)
    return _HANDLE.sub("‹canal›", texto)


def _mascarar(valor: str) -> None:
    if not (ativo() and os.environ.get("GITHUB_ACTIONS") == "true"):
        return
    for linha in str(valor).splitlines():
        linha = linha.strip()
        if len(linha) >= 4 and linha not in _reg.mascarados:
            _reg.mascarados.add(linha)
            _escrever_console(f"::add-mask::{linha}\n")


# ---------------------------------------------------------------- entradas do "Run workflow"

def entrada(nome: str) -> str:
    """Valor digitado em "Run workflow", lido do evento (e não do texto do passo, que aparece no log)."""
    caminho = os.environ.get("GITHUB_EVENT_PATH")
    valor = ""
    if caminho and os.path.exists(caminho):
        try:
            with open(caminho, encoding="utf-8") as f:
                valor = str(((json.load(f) or {}).get("inputs") or {}).get(nome) or "")
        except (OSError, ValueError):
            valor = ""
    valor = valor.strip()
    if valor:
        registrar(valor, "pedido")
    return valor


def resolver(valor: str) -> str:
    """Para argparse: "@entrada:livro" vira o que foi digitado no campo "livro" do Run workflow."""
    if isinstance(valor, str) and valor.startswith("@entrada:"):
        return entrada(valor.split(":", 1)[1])
    return valor


def numero_do_livro(pedido: str) -> int | None:
    """'3', 'livro 3', '#3' -> 3 (o número que aparece no log). Outro texto -> None."""
    m = re.fullmatch(r"\s*(?:livro\s*|#)?(\d{1,4})\s*", str(pedido or ""), re.IGNORECASE)
    return int(m.group(1)) if m else None


def casa_livro(pedido: str, nome_pasta: str) -> bool:
    """O pedido é o número do livro no log ("livro 3") e esta é a pasta dele."""
    numero = numero_do_livro(pedido)
    return numero is not None and _reg.rotulo(nome_pasta) == f"livro {numero}"


# ---------------------------------------------------------------- log da tela (neutro) e relatório (completo)

class _Relatorio:
    def __init__(self):
        self.log: list[str] = []
        self.saida: list[str] = []      # o que programas de fora escreveram (ffmpeg, whisper...)
        self.erros: list[str] = []      # tracebacks
        self.secoes: list[tuple[str, str]] = []
        self.inicio = datetime.now(timezone.utc)

    def vazio(self) -> bool:
        return not (self.log or self.saida or self.erros or self.secoes)


_rel = _Relatorio()


def anexar(titulo: str, texto: str) -> None:
    """Guarda um texto (relatório de SEO, analytics...) só no relatório do Drive."""
    _rel.secoes.append((titulo, str(texto)))


def mostrar_relatorio(titulo: str, texto: str) -> None:
    """No computador: mostra na tela e no resumo do GitHub. No modo discreto: só no relatório do Drive."""
    if ativo():
        anexar(titulo, texto)
        logging.getLogger("audiolivro").info("%s: salvo no relatório do Drive (pasta %s).", Seguro(titulo),
                                             Seguro(PASTA_RELATORIOS))
        return
    print(texto)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def resumo_erro(erro: BaseException) -> str:
    nome = type(erro).__name__
    status = getattr(getattr(erro, "resp", None), "status", None)
    if status:
        nome += f" {status}"
    texto = str(erro).strip()
    if texto and _seguro(texto):
        nome += f" ({texto})"
    else:   # códigos do Google que ajudam a achar o problema e não dizem nada do canal
        codigo = re.search(r"\b(invalid_grant|invalid_client|unauthorized_client|invalid_scope|access_denied)\b", texto)
        if codigo:
            nome += f" ({codigo.group(1)})"
    return nome


def _seguro(texto: str) -> bool:
    if isinstance(texto, Seguro):
        return True
    if _reg.rotulo(texto):
        return False
    if _NUMERICO.fullmatch(texto):
        return True
    return bool(_PALAVRA_TECNICA.fullmatch(texto)) and len(texto) != 11


def _arg_neutro(valor):
    if isinstance(valor, (bool, int, float)) or valor is None:
        return valor
    if isinstance(valor, BaseException):
        return resumo_erro(valor)
    if isinstance(valor, Seguro):
        return limpar(valor)
    if isinstance(valor, str):
        conhecido = _reg.rotulo(valor)
        if conhecido:
            return conhecido
        return valor if _seguro(valor) else OCULTO
    if isinstance(valor, (list, tuple, set, dict)):
        return OCULTO
    return OCULTO if not _seguro(str(valor)) else str(valor)


def mensagem_neutra(record: logging.LogRecord) -> str:
    msg = str(record.msg)
    if record.args:
        args = record.args
        if isinstance(args, dict):
            neutros = {k: _arg_neutro(v) for k, v in args.items()}
        else:
            neutros = tuple(_arg_neutro(a) for a in (args if isinstance(args, tuple) else (args,)))
        try:
            msg = msg % neutros
        except (TypeError, ValueError):
            msg = msg + " " + " ".join(str(a) for a in (neutros if isinstance(neutros, tuple) else neutros.values()))
    msg = limpar(msg)
    if record.exc_info:
        erro = record.exc_info[1]
        msg += f" [{resumo_erro(erro) if erro else 'erro'}; detalhes no relatório do Drive]"
    return msg


class FormatadorDiscreto(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        copia = logging.makeLogRecord(record.__dict__)
        copia.msg, copia.args = mensagem_neutra(record), None
        copia.exc_info = copia.exc_text = copia.stack_info = None
        return super().format(copia)


class _HandlerRelatorio(logging.Handler):
    def emit(self, record):
        try:
            _rel.log.append(self.format(record))
        except Exception:
            pass


# ---------------------------------------------------------------- captura da saída do processo

_estado = {"ativado": False, "console": None, "fds": None, "leitor": None, "linhas_externas": 0}


def _escrever_console(texto: str) -> None:
    console = _estado["console"]
    try:
        if console is not None:
            console.write(texto)
            console.flush()
        else:
            sys.__stdout__.write(texto)
            sys.__stdout__.flush()
    except Exception:
        pass


class _FluxoPython:
    """Substitui sys.stdout/sys.stderr: o texto do próprio robô (print, sys.exit("...")) aparece já limpo."""

    def __init__(self, destino):
        self.destino = destino
        self.buffer = ""
        self.encoding = "utf-8"

    def write(self, texto):
        self.buffer += str(texto)
        while "\n" in self.buffer:
            linha, self.buffer = self.buffer.split("\n", 1)
            self._linha(linha)
        return len(texto)

    def _linha(self, linha):
        _rel.saida.append(linha)
        if linha.startswith("::") and not linha.startswith(("::error", "::warning", "::notice")):
            return   # comandos do GitHub (ex.: ::set-output) não precisam aparecer; ::add-mask:: vai direto
        try:
            self.destino.write(limpar(linha) + "\n")
            self.destino.flush()
        except Exception:
            pass

    def flush(self):
        if self.buffer:
            linha, self.buffer = self.buffer, ""
            self._linha(linha)

    def isatty(self):
        return False

    def fileno(self):
        return self.destino.fileno()


def _ler_pipe(fd: int) -> None:
    resto = ""
    while True:
        try:
            bloco = os.read(fd, 65536)
        except OSError:
            break
        if not bloco:
            break
        resto += bloco.decode("utf-8", errors="replace")
        partes = re.split(r"[\r\n]", resto)
        resto = partes.pop()
        for linha in partes:
            if linha.strip():
                _rel.saida.append(linha)
                _estado["linhas_externas"] += 1
    if resto.strip():
        _rel.saida.append(resto)
        _estado["linhas_externas"] += 1
    os.close(fd)


def _excepthook(tipo, erro, tb):
    _rel.erros.append("".join(traceback.format_exception(tipo, erro, tb)))
    _escrever_console(f"Erro: {limpar(resumo_erro(erro))}. Detalhes no relatório do Drive ({PASTA_RELATORIOS}).\n")


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    _excepthook(args.exc_type, args.exc_value, args.exc_traceback)


def ativar(nome: str | None = None, capturar_fds: bool = True) -> None:
    """Liga o modo discreto neste processo (chamado por configurar_log). Sem efeito fora do modo discreto."""
    if _estado["ativado"] or not ativo():
        return
    _estado["ativado"] = True
    _rel.nome = nome or os.path.basename(sys.argv[0] or "robo")
    sys.stdout.flush()
    sys.stderr.flush()
    if capturar_fds and not os.environ.get("PYTEST_CURRENT_TEST"):
        # fd 1 e 2 passam a cair num cano lido aqui: ffmpeg, whisper e bibliotecas em C não chegam à tela.
        fd_out, fd_err = os.dup(1), os.dup(2)
        leitura, escrita = os.pipe()
        os.dup2(escrita, 1)
        os.dup2(escrita, 2)
        os.close(escrita)
        _estado["fds"] = (fd_out, fd_err)
        console = os.fdopen(fd_out, "w", encoding="utf-8", buffering=1, closefd=False)
        leitor = threading.Thread(target=_ler_pipe, args=(leitura,), daemon=True)
        leitor.start()
        _estado["leitor"] = leitor
    else:
        console = sys.__stdout__
    _estado["console"] = console
    sys.stdout = _FluxoPython(console)
    sys.stderr = _FluxoPython(console)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    atexit.register(encerrar)


def configurar_logging(nivel=logging.INFO) -> None:
    formato = "%(asctime)s %(levelname)s %(message)s"
    raiz = logging.getLogger()
    for h in list(raiz.handlers):
        raiz.removeHandler(h)
    console = logging.StreamHandler(_estado["console"] or sys.__stderr__)
    console.setFormatter(FormatadorDiscreto(formato))
    relatorio = _HandlerRelatorio()
    relatorio.setFormatter(logging.Formatter(formato))
    raiz.addHandler(console)
    raiz.addHandler(relatorio)
    raiz.setLevel(nivel)
    for barulhento in ("httpx", "httpx2", "httpcore", "httpcore2", "huggingface_hub", "faster_whisper", "urllib3"):
        logging.getLogger(barulhento).setLevel(logging.WARNING)   # só ruído no log


def texto_relatorio() -> str:
    agora = datetime.now(timezone.utc)
    linhas = [f"===== {getattr(_rel, 'nome', 'robo')} — {agora:%Y-%m-%d %H:%M} UTC ====="]
    rotulos = {}
    for valor, r in _reg.rotulos.items():
        if valor == unicodedata.normalize("NFC", valor):
            rotulos.setdefault(r, valor)
    if rotulos:
        linhas += ["", "--- Legenda dos rótulos do log ---"]
        linhas += [f"{r}: {v}" for r, v in sorted(rotulos.items(), key=lambda kv: _ordem_rotulo(kv[0]))]
    if _rel.log:
        linhas += ["", "--- Log completo ---", *_rel.log]
    for titulo, texto in _rel.secoes:
        linhas += ["", f"--- {titulo} ---", texto]
    if _rel.erros:
        linhas += ["", "--- Erros (completos) ---", *_rel.erros]
    if _rel.saida:
        linhas += ["", "--- Saída de programas (ffmpeg, whisper, print) ---", *_rel.saida]
    return "\n".join(linhas) + "\n"


def _ordem_rotulo(r: str):
    m = re.match(r"(.*?)(\d+)$", r)
    return (m.group(1), int(m.group(2))) if m else (r, 0)


def nome_relatorio() -> str:
    data = _rel.inicio.astimezone(timezone(timedelta(hours=-3)))
    fluxo = re.sub(r"[^\w .-]", "", os.environ.get("GITHUB_WORKFLOW", "robo")).strip() or "robo"
    execucao = os.environ.get("GITHUB_RUN_NUMBER")
    return f"{data:%Y-%m-%d %H-%M} {fluxo}" + (f" #{execucao}" if execucao else "") + ".txt"


def _salvar_relatorio(texto: str) -> str:
    local = os.environ.get("ROBO_RELATORIO_ARQUIVO")
    if local:
        with open(local, "a", encoding="utf-8") as f:
            f.write(texto)
        return "arquivo local"
    raiz = os.environ.get("DRIVE_PASTA_RAIZ")
    if not raiz or not os.environ.get("GOOGLE_REFRESH_TOKEN"):
        return ""
    from google_api import Drive, credenciais_do_ambiente
    drive = Drive(credenciais_do_ambiente())
    pasta = drive.pasta(raiz, PASTA_RELATORIOS)
    nome = nome_relatorio()
    existente = drive.achar(pasta, nome)
    anterior = drive.ler_texto(existente["id"]) + "\n" if existente else ""
    drive.gravar_texto(pasta, nome, anterior + texto)
    _apagar_relatorios_antigos(drive, pasta)
    return f"Drive › {PASTA_RELATORIOS}"


def _apagar_relatorios_antigos(drive, pasta: str) -> None:
    try:
        dias = int(os.environ.get("ROBO_RELATORIOS_DIAS", "60"))
    except ValueError:
        dias = 60
    if dias <= 0:
        return
    limite = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()
    for item in drive.listar(pasta):
        if str(item.get("modifiedTime") or "9999") < limite:
            drive.lixeira(item["id"])


def encerrar() -> None:
    """No fim do processo: fecha a captura e salva o relatório completo no Drive."""
    if not _estado["ativado"]:
        return
    _estado["ativado"] = False
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.flush()
        except Exception:
            pass
    if _estado["fds"]:
        fd_out, fd_err = _estado["fds"]
        try:
            os.dup2(fd_out, 1)
            os.dup2(fd_err, 2)
        except OSError:
            pass
        if _estado["leitor"]:
            _estado["leitor"].join(timeout=5)
        _estado["fds"] = None
    if _estado["linhas_externas"]:
        _escrever_console(f"({_estado['linhas_externas']} linha(s) de saída de programas, como ffmpeg e whisper, "
                          f"ficaram só no relatório.)\n")
    if _rel.vazio():
        return
    try:
        onde = _salvar_relatorio(texto_relatorio())
        if onde:
            _escrever_console(f"Relatório completo salvo ({onde}).\n")
    except Exception as erro:
        _escrever_console(f"Não consegui salvar o relatório no Drive ({limpar(resumo_erro(erro))}).\n")
