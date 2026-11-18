"""Vozes do ElevenLabs para os vídeos animados (opcional; o padrão é o Google).

Liga com canal.yaml > animacao > voz: elevenlabs (ou, num teste, o campo "voz" do workflow Vídeos animados).
Precisa do segredo ELEVENLABS_API_KEY no ambiente do canal (GitHub > Settings > Environments).

Elenco automático: o robô lê as vozes da sua conta e escolhe uma para cada personagem, pelo gênero da voz do
Google que o personagem já tem (Kore, Aoede e Leda são femininas) e pela idade, sem repetir voz no mesmo vídeo.
Para escolher à mão: canal.yaml > animacao > elevenlabs > vozes: {narrador: "Nome ou ID", davi: "..."}.
"""

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("audiolivro")

URL = "https://api.elevenlabs.io/v1/"
MODELO = "eleven_v3"            # o mais expressivo (entende [sad], [whispers]...)
RESERVA = "eleven_multilingual_v2"
ESTAB_NARRADOR, ESTAB_PERSONAGEM = 0.5, 0.0
PREFIXO = "eleven:"
FEMININAS = {"Kore", "Aoede", "Leda", "Zephyr", "Callirrhoe", "Despina", "Erinome", "Laomedeia", "Pulcherrima",
             "Vindemiatrix", "Achernar", "Autonoe", "Gacrux", "Sulafat"}
# preferência por nome entre as vozes prontas do ElevenLabs (as que existirem na conta)
PREFERIDAS = {
    "narrador": ["Brian", "George", "Daniel", "Adam", "Bill", "Eric"],
    "masculina": ["Liam", "Will", "Chris", "Charlie", "Callum", "Roger", "Eric", "Josh"],
    "jovem": ["Chris", "Charlie", "Liam", "Will", "Josh"],
    "feminina": ["Sarah", "Charlotte", "Matilda", "Alice", "Lily", "Jessica", "Laura", "Aria"],
}


class ErroElevenLabs(RuntimeError):
    pass


def chave() -> str | None:
    return (os.environ.get("ELEVENLABS_API_KEY") or "").strip() or None


def _pedido(caminho: str, chave_api: str, corpo: dict | None = None, tentativas: int = 4):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(URL + caminho, data=dados, headers={
            "xi-api-key": chave_api, "Content-Type": "application/json",
            "Accept": "audio/mpeg" if corpo is not None else "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return resp.read()
        except urllib.error.HTTPError as erro:
            if erro.code in (429, 500, 502, 503) and tentativa < tentativas:
                time.sleep(8 * tentativa)
                continue
            raise ErroElevenLabs(f"ElevenLabs recusou ({erro.code}): {erro.read().decode(errors='replace')[:400]}") from erro
        except (urllib.error.URLError, TimeoutError) as erro:
            if tentativa == tentativas:
                raise ErroElevenLabs(f"sem conexão com o ElevenLabs: {erro}") from erro
            time.sleep(8 * tentativa)


def vozes_da_conta(chave_api: str) -> list[dict]:
    return json.loads(_pedido("voices", chave_api)).get("voices") or []


def _genero(voz_google: str) -> str:
    return "feminina" if voz_google.rsplit("-", 1)[-1] in FEMININAS else "masculina"


def escolher_elenco(rot, vozes: list[dict], fixas: dict | None = None) -> dict[str, str]:
    """{quem: voice_id} para o narrador e cada personagem que fala no roteiro."""
    fixas = fixas or {}
    por_nome = {v["name"].split(" ")[0].lower(): v for v in vozes}
    por_id = {v["voice_id"]: v for v in vozes}
    usadas: set[str] = set()

    def achar(valor: str):
        return por_id.get(valor) or por_nome.get(str(valor).split(" ")[0].lower())

    def pegar(tipo: str) -> str:
        for nome in PREFERIDAS[tipo]:
            v = por_nome.get(nome.lower())
            if v and v["voice_id"] not in usadas:
                return v["voice_id"]
        genero = "female" if tipo == "feminina" else "male"
        for v in vozes:
            if (v.get("labels") or {}).get("gender") == genero and v["voice_id"] not in usadas:
                return v["voice_id"]
        livres = [v for v in vozes if v["voice_id"] not in usadas] or vozes
        if not livres:
            raise ErroElevenLabs("a conta do ElevenLabs não tem nenhuma voz")
        return livres[0]["voice_id"]

    falantes = []
    for c in rot.cenas:
        for f in c.falas:
            if f.quem not in falantes:
                falantes.append(f.quem)
    if "narrador" in falantes:   # o narrador escolhe primeiro
        falantes.remove("narrador")
        falantes.insert(0, "narrador")
    # vozes escolhidas à mão ficam reservadas: o sorteio dos outros personagens não pode pegar
    for quem, valor in fixas.items():
        if quem in falantes and achar(valor):
            usadas.add(achar(valor)["voice_id"])
    elenco = {}
    for quem in falantes:
        if quem in fixas and achar(fixas[quem]):
            vid = achar(fixas[quem])["voice_id"]
        elif quem == "narrador" or quem not in rot.elenco:
            vid = pegar("narrador")
        else:
            p = rot.elenco[quem]
            tipo = _genero(p.voz)
            if tipo == "masculina" and float(p.extras.get("tamanho", 1)) < 0.9:
                tipo = "jovem"
            vid = pegar(tipo)
        usadas.add(vid)
        elenco[quem] = vid
    return elenco


def aplicar(rot, chave_api: str, fixas: dict | None = None) -> dict[str, str]:
    """Troca as vozes do roteiro pelas do ElevenLabs (prefixo "eleven:") e devolve {quem: nome da voz}."""
    vozes = vozes_da_conta(chave_api)
    elenco = escolher_elenco(rot, vozes, fixas)
    nomes = {v["voice_id"]: v["name"] for v in vozes}
    # estabilidade do v3: o narrador fica "natural" (0.5); os personagens, "criativos" (0), com mais garra e emoção
    for quem, vid in elenco.items():
        if quem == "narrador":
            rot.narrador = f"{PREFIXO}{vid}@{ESTAB_NARRADOR}"
        elif quem in rot.elenco:
            rot.elenco[quem].voz = f"{PREFIXO}{vid}@{ESTAB_PERSONAGEM}"
    if "narrador" not in elenco:
        rot.narrador = PREFIXO + pegar_qualquer(vozes)
    return {quem: nomes.get(vid, vid) for quem, vid in elenco.items()}


def pegar_qualquer(vozes: list[dict]) -> str:
    return vozes[0]["voice_id"]


def sintetizar(texto: str, voice_id: str, destino: Path, chave_api: str, modelo: str = MODELO) -> Path:
    """voice_id pode vir com a estabilidade: "abc123@0.0"."""
    voice_id, _, estab = voice_id.partition("@")
    if modelo == "eleven_v3":
        # v3: estabilidade 0 = "criativo" (mais emoção), 0.5 = natural, 1 = robusto
        ajustes = {"stability": float(estab or os.environ.get("ELEVENLABS_ESTABILIDADE") or 0.5)}
    else:
        ajustes = {"stability": 0.35, "similarity_boost": 0.8, "style": 0.45, "use_speaker_boost": True}
    try:
        audio = _pedido(f"text-to-speech/{voice_id}?output_format=mp3_44100_128", chave_api,
                        {"text": texto, "model_id": modelo, "voice_settings": ajustes})
    except ErroElevenLabs as erro:
        if modelo == RESERVA or "(4" not in str(erro) or "(401)" in str(erro):
            raise
        log.warning("ElevenLabs: modelo %s recusou (%s); usando o %s.", modelo, erro, RESERVA)
        limpo = " ".join(__import__("re").sub(r"\[[^\]]*\]", " ", texto).split())
        return sintetizar(limpo, f"{voice_id}@{estab}" if estab else voice_id, destino, chave_api, RESERVA)
    destino.write_bytes(audio)
    return destino


def provar(chave_api: str, texto: str, pasta: Path, quantas: int = 6, genero: str = "male",
           pular: tuple = ("Brian",)) -> list[Path]:
    """Lê o mesmo texto com várias vozes da conta (uma por arquivo, com o nome da voz) para escolher de ouvido."""
    pasta.mkdir(parents=True, exist_ok=True)
    vozes = [v for v in vozes_da_conta(chave_api) if (v.get("labels") or {}).get("gender") == genero
             and v["name"].split(" ")[0] not in pular][:quantas]
    saida = []
    for v in vozes:
        nome = v["name"].split(" ")[0]
        saida.append(sintetizar(texto, f"{v['voice_id']}@{ESTAB_PERSONAGEM}", pasta / f"{nome}.mp3", chave_api))
    return saida
