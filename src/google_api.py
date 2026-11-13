"""Acesso ao Google Drive e ao YouTube com a credencial OAuth da conta do canal."""

import io
import json
import os
import ssl
import time
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

import discreto
from comum import log

ESCOPOS = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive",
    # legendas (captions.insert) só aceitam este escopo
    "https://www.googleapis.com/auth/youtube.force-ssl",
    # relatório de analytics (src/analytics.py)
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
PASTA_MIME = "application/vnd.google-apps.folder"
_ERROS_TEMPORARIOS = {500, 502, 503, 504}
PRIVACIDADES = {"private", "unlisted", "public"}
_MOTIVOS_LIMITE = {"quotaExceeded", "uploadLimitExceeded", "dailyLimitExceeded", "rateLimitExceeded"}


def _registrar_snippet(snippet: dict) -> None:
    """Título, descrição e tags de vídeo ou playlist: sensíveis no modo discreto."""
    if snippet.get("title"):
        discreto.registrar(snippet["title"], "título")
    discreto.registrar_texto(snippet.get("description"), "descrição")
    for tag in snippet.get("tags") or []:
        discreto.registrar(tag, "tag")


class SemPermissao(Exception):
    """A autorização atual não cobre esta operação (ex.: legendas precisam do escopo youtube.force-ssl)."""


class LimiteDiario(Exception):
    """O YouTube não aceita mais envios hoje (cota da API ou limite do canal)."""


def _motivo(erro: HttpError) -> str:
    try:
        return json.loads(erro.content)["error"]["errors"][0]["reason"]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


def credenciais_do_ambiente(token: str = "GOOGLE_REFRESH_TOKEN") -> Credentials:
    """Credencial da conta do canal. Com `token`, usa outra autorização (ex.: GOOGLE_REFRESH_TOKEN_DRIVE)."""
    faltando = [v for v in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", token) if not os.environ.get(v)]
    if faltando:
        raise SystemExit(f"Faltam variáveis de ambiente: {', '.join(faltando)}")
    return Credentials(
        token=None,
        refresh_token=os.environ[token],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GOOGLE_CLIENT_ID"],
        client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
        # sem "scopes": a renovação devolve só o que já foi autorizado (pedir um escopo novo daria erro)
        scopes=None,
    )


class Drive:
    def __init__(self, credenciais: Credentials):
        # Canal que é "conta de marca" não tem Drive: os arquivos ficam na conta pessoal, com autorização própria
        # (segredo GOOGLE_REFRESH_TOKEN_DRIVE, gerado com: python scripts/autorizar.py --parte drive).
        if os.environ.get("GOOGLE_REFRESH_TOKEN_DRIVE"):
            credenciais = credenciais_do_ambiente("GOOGLE_REFRESH_TOKEN_DRIVE")
        self.api = build("drive", "v3", credentials=credenciais, cache_discovery=False)

    def listar(self, pasta_id: str) -> list[dict]:
        itens, pagina = [], None
        while True:
            resp = self.api.files().list(
                q=f"'{pasta_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, size)",
                pageSize=1000,
                pageToken=pagina,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            ).execute(num_retries=5)
            itens += resp.get("files", [])
            for item in resp.get("files", []):
                discreto.registrar_item_drive(item)
            pagina = resp.get("nextPageToken")
            if not pagina:
                return sorted(itens, key=lambda i: i["name"])

    @staticmethod
    def eh_pasta(item: dict) -> bool:
        return item["mimeType"] == PASTA_MIME

    def achar(self, pasta_id: str, nome: str) -> dict | None:
        return next((i for i in self.listar(pasta_id) if i["name"] == nome), None)

    def pasta(self, pai_id: str, nome: str) -> str:
        """Devolve o ID da subpasta, criando se não existir."""
        existente = self.achar(pai_id, nome)
        if existente and self.eh_pasta(existente):
            return existente["id"]
        criada = self.api.files().create(
            body={"name": nome, "mimeType": PASTA_MIME, "parents": [pai_id]},
            fields="id", supportsAllDrives=True,
        ).execute(num_retries=5)
        discreto.registrar_item_drive({"id": criada["id"], "name": nome, "mimeType": PASTA_MIME})
        return criada["id"]

    def baixar(self, arquivo_id: str, destino: Path) -> Path:
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "wb") as f:
            pedido = self.api.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
            baixador = MediaIoBaseDownload(f, pedido, chunksize=50 * 1024 * 1024)
            concluido = False
            while not concluido:
                _, concluido = baixador.next_chunk(num_retries=5)
        return destino

    def ler_texto(self, arquivo_id: str, google_doc: bool = False) -> str:
        buffer = io.BytesIO()
        if google_doc:
            pedido = self.api.files().export_media(fileId=arquivo_id, mimeType="text/plain")
        else:
            pedido = self.api.files().get_media(fileId=arquivo_id, supportsAllDrives=True)
        baixador = MediaIoBaseDownload(buffer, pedido)
        concluido = False
        while not concluido:
            _, concluido = baixador.next_chunk(num_retries=5)
        return buffer.getvalue().decode("utf-8-sig")

    def enviar(self, origem: Path, pasta_id: str, nome: str | None = None, mime: str | None = None) -> str:
        midia = MediaFileUpload(str(origem), mimetype=mime, resumable=True)
        criado = self.api.files().create(
            body={"name": nome or origem.name, "parents": [pasta_id]},
            media_body=midia, fields="id", supportsAllDrives=True,
        ).execute(num_retries=5)
        discreto.registrar_item_drive({"id": criado["id"], "name": nome or origem.name})
        return criado["id"]

    def gravar_texto(self, pasta_id: str, nome: str, conteudo: str, mime: str = "text/plain") -> None:
        """Cria ou substitui um arquivo de texto pequeno."""
        caminho = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / f"_drive_{nome}"
        caminho.write_text(conteudo, encoding="utf-8")
        midia = MediaFileUpload(str(caminho), mimetype=mime, resumable=False)
        existente = self.achar(pasta_id, nome)
        if existente:
            self.api.files().update(fileId=existente["id"], media_body=midia, supportsAllDrives=True).execute(num_retries=5)
        else:
            self.api.files().create(
                body={"name": nome, "parents": [pasta_id]}, media_body=midia, supportsAllDrives=True,
            ).execute(num_retries=5)
        caminho.unlink(missing_ok=True)

    def ler_json(self, pasta_id: str, nome: str, padrao: dict) -> dict:
        item = self.achar(pasta_id, nome)
        dados = json.loads(self.ler_texto(item["id"])) if item else padrao
        discreto.registrar_dados(dados)
        return dados

    def gravar_json(self, pasta_id: str, nome: str, dados: dict) -> None:
        self.gravar_texto(pasta_id, nome, json.dumps(dados, ensure_ascii=False, indent=2), "application/json")

    def lixeira(self, arquivo_id: str) -> None:
        self.api.files().update(fileId=arquivo_id, body={"trashed": True}, supportsAllDrives=True).execute(num_retries=5)

    def mover(self, arquivo_id: str, de_pasta: str, para_pasta: str) -> None:
        self.api.files().update(
            fileId=arquivo_id, addParents=para_pasta, removeParents=de_pasta, supportsAllDrives=True,
        ).execute(num_retries=5)


class YouTube:
    def __init__(self, credenciais: Credentials):
        self.api = build("youtube", "v3", credentials=credenciais, cache_discovery=False)

    def enviar_video(self, video: Path, snippet: dict, status: dict) -> str:
        if status.get("privacyStatus") not in PRIVACIDADES:
            status = {**status, "privacyStatus": "private"}
        _registrar_snippet(snippet)
        midia = MediaFileUpload(str(video), mimetype="video/mp4", chunksize=64 * 1024 * 1024, resumable=True)
        pedido = self.api.videos().insert(part="snippet,status", body={"snippet": snippet, "status": status}, media_body=midia)
        resposta, tentativas = None, 0
        while resposta is None:
            try:
                progresso, resposta = pedido.next_chunk()
                if progresso:
                    log.info("Enviando vídeo: %d%%", int(progresso.progress() * 100))
            except HttpError as erro:
                if erro.resp.status in (400, 403, 429) and _motivo(erro) in _MOTIVOS_LIMITE:
                    raise LimiteDiario(_motivo(erro)) from erro
                if erro.resp.status not in _ERROS_TEMPORARIOS or tentativas >= 8:
                    raise
                tentativas += 1
                espera = 2 ** tentativas
                log.warning("Erro temporário do YouTube (%s); tentando de novo em %ds", erro.resp.status, espera)
                time.sleep(espera)
            except (ssl.SSLError, ConnectionError, TimeoutError, OSError) as erro:
                # queda de conexão no meio do envio (ex.: "EOF occurred in violation of protocol"):
                # o envio é retomável, então basta pedir o próximo pedaço de novo
                if tentativas >= 8:
                    raise
                tentativas += 1
                espera = 2 ** tentativas
                log.warning("Conexão caiu no envio (%s); retomando em %ds", erro, espera)
                time.sleep(espera)
        discreto.registrar(resposta["id"], "vídeo")
        return resposta["id"]

    def atualizar_metadados(self, video_id: str, snippet: dict, tentativas: int = 5) -> None:
        """Troca título, descrição e tags de um vídeo já publicado (custa ~50 unidades de cota)."""
        discreto.registrar(video_id, "vídeo")
        _registrar_snippet(snippet)
        self._executar(self.api.videos().update(part="snippet", body={"id": video_id, "snippet": snippet}),
                       esperas=tuple(10 * t for t in range(1, tentativas)))

    def inserir_legenda(self, video_id: str, srt: Path, idioma: str = "pt-BR", nome: str = "Português") -> None:
        """Envia uma legenda .srt para o vídeo (custa ~400 unidades de cota)."""
        try:
            self.api.captions().insert(
                part="snippet",
                body={"snippet": {"videoId": video_id, "language": idioma, "name": nome, "isDraft": False}},
                media_body=MediaFileUpload(str(srt), mimetype="application/octet-stream"),
            ).execute(num_retries=3)
        except HttpError as erro:
            motivo = _motivo(erro)
            if erro.resp.status in (400, 403, 429) and motivo in _MOTIVOS_LIMITE:
                raise LimiteDiario(motivo) from erro
            if erro.resp.status in (401, 403) and motivo in ("insufficientPermissions", "forbidden", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"):
                raise SemPermissao(motivo) from erro
            raise

    def definir_miniatura(self, video_id: str, imagem: Path) -> None:
        self.api.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(str(imagem), mimetype="image/jpeg")).execute(num_retries=3)

    def ler_videos(self, ids: list[str]) -> list[dict]:
        """snippet, status e statistics dos vídeos (1 unidade de cota a cada 50 vídeos)."""
        saida = []
        for i in range(0, len(ids), 50):
            saida += self.api.videos().list(part="snippet,status,statistics,contentDetails",
                                            id=",".join(ids[i:i + 50])).execute(num_retries=3).get("items", [])
        for video in saida:
            discreto.registrar(video.get("id"), "vídeo")
            _registrar_snippet(video.get("snippet") or {})
        return saida

    def videos_do_canal(self) -> list[dict]:
        canal = self.api.channels().list(part="contentDetails", mine=True).execute(num_retries=3)["items"][0]
        uploads, ids, pagina = canal["contentDetails"]["relatedPlaylists"]["uploads"], [], None
        discreto.registrar(canal.get("id"), "id")
        discreto.registrar(uploads, "playlist")
        while True:
            resp = self.api.playlistItems().list(part="contentDetails", playlistId=uploads, maxResults=50,
                                                 pageToken=pagina).execute(num_retries=3)
            ids += [i["contentDetails"]["videoId"] for i in resp.get("items", [])]
            pagina = resp.get("nextPageToken")
            if not pagina:
                return self.ler_videos(list(dict.fromkeys(ids)))

    def ler_playlists(self, ids: list[str]) -> list[dict]:
        saida = []
        for i in range(0, len(ids), 50):
            saida += self.api.playlists().list(part="snippet,status", id=",".join(ids[i:i + 50]),
                                               maxResults=50).execute(num_retries=3).get("items", [])
        for playlist in saida:
            discreto.registrar(playlist.get("id"), "playlist")
            _registrar_snippet(playlist.get("snippet") or {})
        return saida

    def _executar(self, pedido, permissao: bool = False, esperas: tuple = (10, 30, 90)):
        """Executa um pedido de escrita. Se o YouTube pedir para ir mais devagar (429), espera e tenta de novo;
        se continuar pedindo, para o dia (LimiteDiario) sem derrubar o robô."""
        for tentativa in range(len(esperas) + 1):
            try:
                return pedido.execute(num_retries=2)
            except HttpError as erro:
                motivo = _motivo(erro)
                if erro.resp.status in (400, 403, 429) and motivo in _MOTIVOS_LIMITE:
                    raise LimiteDiario(motivo) from erro
                if permissao and erro.resp.status in (401, 403) and motivo in (
                        "insufficientPermissions", "forbidden", "ACCESS_TOKEN_SCOPE_INSUFFICIENT"):
                    raise SemPermissao(motivo) from erro
                if erro.resp.status not in _ERROS_TEMPORARIOS | {429}:
                    raise
                if tentativa == len(esperas):
                    raise LimiteDiario(f"{erro.resp.status} {motivo}") from erro
                log.warning("YouTube pediu para ir mais devagar (%s); esperando %ds", erro.resp.status, esperas[tentativa])
                time.sleep(esperas[tentativa])

    def atualizar_playlist(self, playlist_id: str, titulo: str, descricao: str, privacidade: str) -> None:
        """Troca nome, descrição e privacidade de uma playlist (50 unidades)."""
        discreto.registrar(playlist_id, "playlist")
        _registrar_snippet({"title": titulo, "description": descricao})
        self._executar(self.api.playlists().update(part="snippet,status", body={
            "id": playlist_id, "snippet": {"title": titulo[:150], "description": descricao[:5000]},
            "status": {"privacyStatus": privacidade}}))

    def comentar(self, video_id: str, texto: str) -> str:
        """Escreve um comentário do canal no vídeo (50 unidades). O YouTube não deixa fixar pela API."""
        discreto.registrar_texto(texto)
        resp = self._executar(self.api.commentThreads().insert(part="snippet", body={"snippet": {
            "videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": texto}}}}), permissao=True)
        discreto.registrar(resp["id"], "id")
        return resp["id"]

    def criar_playlist(self, titulo: str, descricao: str, privacidade: str = "private") -> str:
        _registrar_snippet({"title": titulo, "description": descricao})
        resp = self.api.playlists().insert(
            part="snippet,status",
            body={"snippet": {"title": titulo[:150], "description": descricao[:5000]}, "status": {"privacyStatus": privacidade}},
        ).execute()
        discreto.registrar(resp["id"], "playlist")
        return resp["id"]

    def adicionar_na_playlist(self, playlist_id: str, video_id: str, tentativas: int = 5) -> None:
        # Logo depois do envio o YouTube às vezes responde 409/5xx ("SERVICE_UNAVAILABLE"); vale esperar e repetir.
        for tentativa in range(1, tentativas + 1):
            try:
                self.api.playlistItems().insert(
                    part="snippet",
                    body={"snippet": {"playlistId": playlist_id, "resourceId": {"kind": "youtube#video", "videoId": video_id}}},
                ).execute()
                return
            except HttpError as erro:
                if erro.resp.status not in _ERROS_TEMPORARIOS | {409} or tentativa == tentativas:
                    raise
                time.sleep(10 * tentativa)
