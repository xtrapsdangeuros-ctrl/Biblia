"""Reels / Shorts de divulgação do Audiolivros Pavão (TESTE): roteiro próprio narrado pela ElevenLabs.

Cada roteiro é um arquivo em reels/ (codigo da capa, livro, autor, texto e legenda do post). O vídeo sai vertical
(1080x1920, até 60 s) no visual do Pavão (src/arte_pavao.py), com a capa, legenda grande sincronizada com a voz
(tempos de cada letra devolvidos pela ElevenLabs) e a marca do canal no fim. Nada é publicado: o MP4 e a legenda
do post vão para a pasta "Pavão - Reels" no Meu Drive (fora da pasta AudioLivros, que o robô lê como livros).

Créditos: cada caractere do texto gasta 1 crédito (v3 / multilingual v2; flash gasta metade). O áudio narrado fica
guardado no Drive (subpasta "_audio"): rodar de novo o mesmo texto com a mesma voz e modelo não gasta nada.

Uso (no GitHub Actions, workflow "Reels Pavão (teste)", só manual):
  python src/reels.py --saldo                          # saldo e vozes da conta (não gasta créditos)
  python src/reels.py --roteiro dom-casmurro --voz NOME --modelo eleven_v3
  python src/reels.py --previa --roteiro dom-casmurro  # local, sem ElevenLabs nem Drive (voz muda, tempos fictícios)
"""

import argparse
import base64
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import arte_pavao as ap  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
PASTA_ROTEIROS = RAIZ / "reels"
PASTA_DRIVE = "Pavão - Reels"
PASTA_CAPAS = "capas novas"
URL = "https://api.elevenlabs.io/v1/"
W, H, FPS = 1080, 1920, 30
DURACAO_MAX = 60.0
FIM_SEG = 3.0                 # cartão final com a marca do canal
LIMITE_CARACTERES = 1100      # trava: texto maior que isso não é narrado (passaria de 60 s e gastaria demais)
MARGEM_CREDITOS = 100
CUSTO = {"eleven_v3": 1.0, "eleven_multilingual_v2": 1.0, "eleven_flash_v2_5": 0.5, "eleven_turbo_v2_5": 0.5}


def log(msg: str) -> None:
    print(msg, flush=True)


# ---------------------------------------------------------------- ElevenLabs

def _chave() -> str:
    chave = (os.environ.get("ELEVENLABS_API_KEY") or "").strip()
    if not chave:
        raise SystemExit("Falta o segredo ELEVENLABS_API_KEY neste ambiente (GitHub > Settings > Environments).")
    return chave


def _api(caminho: str, corpo: dict | None = None, tentativas: int = 2) -> dict:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    for tentativa in range(1, tentativas + 1):
        req = urllib.request.Request(URL + caminho, data=dados, headers={
            "xi-api-key": _chave(), "Content-Type": "application/json", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as erro:
            texto = erro.read().decode(errors="replace")[:300]
            if erro.code in (429, 503) and tentativa < tentativas:
                time.sleep(15)
                continue
            raise SystemExit(f"ElevenLabs recusou ({erro.code}): {texto}") from erro


def saldo() -> dict:
    s = _api("user/subscription")
    usados, limite = int(s.get("character_count", 0)), int(s.get("character_limit", 0))
    return {"plano": s.get("tier"), "usados": usados, "limite": limite, "restam": limite - usados,
            "renova": s.get("next_character_count_reset_unix")}


def vozes() -> list[dict]:
    return _api("voices").get("voices") or []


def _eh_pt(v: dict) -> bool:
    rotulos = " ".join(str(x) for x in (v.get("labels") or {}).values()).lower()
    langs = " ".join(f"{l.get('language', '')} {l.get('accent', '')} {l.get('locale', '')}"
                     for l in (v.get("verified_languages") or [])).lower()
    return any(p in f"{rotulos} {langs}" for p in ("brazil", "portug", "pt-br", " pt "))


def achar_voz(lista: list[dict], pedido: str) -> dict:
    if pedido:
        for v in lista:
            if pedido in (v["voice_id"], v["name"]) or v["name"].split(" ")[0].lower() == pedido.split(" ")[0].lower():
                return v
        raise SystemExit(f"Voz '{pedido}' não está na conta. Rode o modo saldo para ver a lista.")
    pt = [v for v in lista if _eh_pt(v)]
    if not pt:
        raise SystemExit("Nenhuma voz em português na conta: escolha uma no campo 'voz' (veja o modo saldo).")
    masc = [v for v in pt if (v.get("labels") or {}).get("gender") == "male"]
    return (masc or pt)[0]


def narrar(texto: str, voice_id: str, modelo: str) -> tuple[bytes, dict]:
    """Uma única chamada com tempos: devolve (mp3, alinhamento por caractere)."""
    ajustes = {"stability": 0.5} if modelo == "eleven_v3" else \
        {"stability": 0.4, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}
    r = _api(f"text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
             {"text": texto, "model_id": modelo, "language_code": "pt", "voice_settings": ajustes}, tentativas=1)
    alinh = r.get("alignment") or r.get("normalized_alignment")
    if not alinh:
        raise SystemExit("A ElevenLabs não devolveu os tempos da fala.")
    return base64.b64decode(r["audio_base64"]), alinh


# ---------------------------------------------------------------- tempos das palavras

def palavras_do_alinhamento(alinh: dict) -> list[dict]:
    letras = alinh["characters"]
    ini, fim = alinh["character_start_times_seconds"], alinh["character_end_times_seconds"]
    saida, atual = [], None
    for c, a, b in zip(letras, ini, fim):
        if c.isspace():
            if atual:
                saida.append(atual)
            atual = None
            continue
        if atual is None:
            atual = {"texto": c, "inicio": a, "fim": b}
        else:
            atual["texto"] += c
            atual["fim"] = b
    if atual:
        saida.append(atual)
    return saida


def palavras_ficticias(texto: str) -> list[dict]:
    """Para a prévia local: ~15 caracteres por segundo, pausas em pontuação."""
    t, saida = 0.3, []
    for p in texto.split():
        dur = 0.06 * len(p) + 0.12
        saida.append({"texto": p, "inicio": t, "fim": t + dur})
        t += dur + (0.35 if p[-1] in ".?!" else 0.15 if p[-1] in ",;:" else 0.04)
    return saida


def grupos(palavras: list[dict], maximo: int = 3) -> list[list[dict]]:
    """Blocos de até 3 palavras, quebrando em vírgula e ponto (como no Short dos capítulos)."""
    saida, g = [], []
    for p in palavras:
        g.append(p)
        if len(g) >= maximo or re.search(r"[.,!?;:…]$", p["texto"].rstrip('"”')):
            saida.append(g)
            g = []
    if g:
        saida.append(g)
    return saida


# ---------------------------------------------------------------- arte

def fundo_base(capa: Image.Image | None, livro: str, autor: str) -> tuple[Image.Image, Image.Image, tuple]:
    """Fundo fixo (degradê, penas, marca, título) e a capa com moldura separada (para o zoom lento)."""
    img = ap.degrade(W, H, angulo=70).convert("RGBA")
    img.alpha_composite(ap.leque(W, H, (W * 1.05, H * 0.30), 900, n=11, abertura=(150, 260), alfa=38))
    img.alpha_composite(ap.leque(W, H, (-W * 0.05, H * 1.02), 760, n=9, abertura=(280, 350), alfa=30))
    d = ImageDraw.Draw(img)
    # marca no alto: selo + nome do canal
    selo = ap.selo(96)
    f = ap.fonte("sans", "Bold", 34)
    nome = "AUDIOLIVROS PAVÃO"
    larg = 96 + 22 + sum(d.textlength(c, font=f) + 4 for c in nome)
    x0 = int((W - larg) / 2)
    img.alpha_composite(selo, (x0, 92))
    cx = x0 + 96 + 22
    for c in nome:
        d.text((cx, 120), c, font=f, fill=ap.rgb(ap.DOURADO))
        cx += d.textlength(c, font=f) + 4
    # título e autor
    ft, linhas = ap._caber(d, ap.titulo_curto(livro), "serifa", "Bold", 92, 60, W - 160, 2)
    y = 228
    for linha in linhas:
        lw = d.textlength(linha, font=ft)
        d.text(((W - lw) / 2 + 3, y + 4), linha, font=ft, fill=(0, 0, 0, 140))
        d.text(((W - lw) / 2, y), linha, font=ft, fill=ap.rgb(ap.CREME))
        y += int(ft.size * 1.08)
    fa = ap.fonte("sans", "Medium", 38)
    aw = d.textlength(autor, font=fa)
    d.text(((W - aw) / 2, y + 8), autor, font=fa, fill=ap.rgb(ap.DOURADO))
    topo_capa = y + 80
    camada = None
    if capa is not None:
        camada, _m = ap._capa_com_moldura(capa, 700)
    return img, camada, (topo_capa,)


def cartao_final(base: Image.Image) -> Image.Image:
    img = ap.degrade(W, H, angulo=70).convert("RGBA")
    img.alpha_composite(ap.leque(W, H, (W / 2, H * 0.62), 980, n=13, abertura=(195, 345), alfa=55))
    d = ImageDraw.Draw(img)
    selo = ap.selo(360)
    img.alpha_composite(selo, ((W - 360) // 2, 470))
    linhas = [("Ouça o audiolivro completo", ap.fonte("sans", "SemiBold", 50), ap.CREME, 900),
              ("Audiolivros", ap.fonte("serifa", "Bold", 118), ap.DOURADO, 1000),
              ("Pavão", ap.fonte("serifa", "Bold", 118), ap.DOURADO, 1125),
              ("no YouTube  ·  link na bio", ap.fonte("sans", "SemiBold", 48), ap.CREME, 1290),
              ("@audiolivrospavao", ap.fonte("sans", "Bold", 52), ap.DOURADO, 1380)]
    for texto, f, cor, y in linhas:
        tw = d.textlength(texto, font=f)
        d.text(((W - tw) / 2 + 3, y + 4), texto, font=f, fill=(0, 0, 0, 140))
        d.text(((W - tw) / 2, y), texto, font=f, fill=ap.rgb(cor))
    return img


FONTE_LEGENDA = None


def desenhar_legenda(img: Image.Image, grupo: list[dict], atual: int, y_centro: int) -> None:
    global FONTE_LEGENDA
    if FONTE_LEGENDA is None:
        FONTE_LEGENDA = ap.fonte("sans", "ExtraBold", 92)
    f = FONTE_LEGENDA
    d = ImageDraw.Draw(img)
    textos = [p["texto"].upper() for p in grupo]
    espaco = d.textlength(" ", font=f)
    larguras = [d.textlength(t, font=f) for t in textos]
    # quebra em até 2 linhas se não couber
    linhas, linha, larg = [], [], 0
    for i, lw in enumerate(larguras):
        if linha and larg + espaco + lw > W - 120:
            linhas.append(linha)
            linha, larg = [], 0
        larg += (espaco if linha else 0) + lw
        linha.append(i)
    if linha:
        linhas.append(linha)
    alt = int(f.size * 1.15)
    y = y_centro - alt * len(linhas) // 2
    for ln in linhas:
        total = sum(larguras[i] for i in ln) + espaco * (len(ln) - 1)
        x = (W - total) / 2
        for i in ln:
            cor = ap.rgb(ap.DOURADO) if i == atual else ap.rgb(ap.CREME)
            d.text((x, y), textos[i], font=f, fill=cor, stroke_width=7, stroke_fill=ap.rgb(ap.PETROLEO_ESCURO))
            x += larguras[i] + espaco
        y += alt


def renderizar(capa: Image.Image | None, livro: str, autor: str, palavras: list[dict], audio: Path | None,
               duracao_fala: float, destino: Path) -> Path:
    base, camada, (topo_capa,) = fundo_base(capa, livro, autor)
    final = cartao_final(base).convert("RGB")
    blocos = grupos(palavras)
    total = min(duracao_fala + 0.4 + FIM_SEG, DURACAO_MAX)
    inicio_fim = total - FIM_SEG
    n = int(math.ceil(total * FPS))
    y_leg = 1440
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-"]
    if audio:
        cmd += ["-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"]
    cmd += ["-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-af", f"apad,afade=t=out:st={total - 0.6:.2f}:d=0.6",
            "-t", f"{total:.2f}", "-movflags", "+faststart", str(destino)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    base_rgb = base.convert("RGB")
    bi = 0
    for k in range(n):
        t = k / FPS
        if t >= inicio_fim:
            a = min(1.0, (t - inicio_fim) / 0.35)
            quadro = final if a >= 1 else Image.blend(quadro_fala, final, a)
            proc.stdin.write(quadro.tobytes())
            continue
        quadro = base_rgb.copy()
        if camada is not None:
            z = 1.0 + 0.06 * (t / max(inicio_fim, 1))          # zoom lento na capa
            cw, ch = int(camada.width * z), int(camada.height * z)
            c = camada.resize((cw, ch), Image.BILINEAR)
            quadro.paste(c, ((W - cw) // 2, topo_capa - (ch - camada.height) // 2 - 40), c)
        while bi + 1 < len(blocos) and blocos[bi + 1][0]["inicio"] <= t:
            bi += 1
        if blocos and t >= blocos[0][0]["inicio"] - 0.05 and t <= palavras[-1]["fim"] + 0.4:
            g = blocos[bi]
            atual = max((i for i, p in enumerate(g) if p["inicio"] <= t), default=0)
            desenhar_legenda(quadro, g, atual, y_leg)
        quadro_fala = quadro
        proc.stdin.write(quadro.tobytes())
    proc.stdin.close()
    if proc.wait():
        raise SystemExit("ffmpeg falhou ao montar o vídeo")
    return destino


# ---------------------------------------------------------------- Drive

def _drive():
    from google_api import Drive, credenciais_do_ambiente
    return Drive(credenciais_do_ambiente())


def baixar_capa(drive, codigo: str, pasta: Path) -> Image.Image | None:
    raiz = os.environ.get("DRIVE_PASTA_RAIZ", "").strip()
    capas = next((i for i in drive.listar(raiz) if drive.eh_pasta(i) and i["name"].strip().lower() == PASTA_CAPAS), None)
    if not capas:
        log("Aviso: pasta 'Capas Novas' não encontrada; o vídeo sai sem capa.")
        return None
    item = next((i for i in drive.listar(capas["id"])
                 if re.match(rf"{re.escape(codigo)}\b", i["name"].strip(), re.I) and not drive.eh_pasta(i)), None)
    if not item:
        log(f"Aviso: capa {codigo} não encontrada; o vídeo sai sem capa.")
        return None
    arq = drive.baixar(item["id"], pasta / ("capa" + Path(item["name"]).suffix.lower()))
    return ImageOps.exif_transpose(Image.open(arq)).convert("RGB")


def ler_roteiro(nome: str) -> tuple[str, dict]:
    arqs = sorted(p for p in PASTA_ROTEIROS.glob("*.yaml") if nome.lower() in p.stem.lower())
    if len(arqs) != 1:
        raise SystemExit(f"Roteiro '{nome}': achei {len(arqs)} arquivos em reels/ (precisa ser exatamente 1).")
    dados = yaml.safe_load(arqs[0].read_text(encoding="utf-8"))
    dados["texto"] = " ".join(dados["texto"].split())
    return arqs[0].stem, dados


# ---------------------------------------------------------------- modos

def modo_saldo() -> None:
    s = saldo()
    log(f"Saldo ElevenLabs: restam {s['restam']} de {s['limite']} créditos (plano {s['plano']}).")
    log("Vozes da conta (nome | gênero | sotaque | idiomas):")
    for v in vozes():
        lab = v.get("labels") or {}
        langs = ",".join(sorted({l.get("language", "") for l in (v.get("verified_languages") or [])}))
        log(f"  {v['name']} | {lab.get('gender', '')} | {lab.get('accent', '')} | {langs}"
            f"{'  <- português' if _eh_pt(v) else ''}")
    for p in sorted(PASTA_ROTEIROS.glob("*.yaml")):
        n = len(" ".join(yaml.safe_load(p.read_text(encoding="utf-8"))["texto"].split()))
        log(f"Roteiro {p.stem}: {n} caracteres = {n} créditos no v3 (ou {n // 2} no flash).")


def modo_narrar(nome: str, voz: str, modelo: str, confirmar: bool) -> None:
    stem, r = ler_roteiro(nome)
    texto = r["texto"]
    if len(texto) > LIMITE_CARACTERES:
        raise SystemExit(f"Texto com {len(texto)} caracteres: passa do limite de {LIMITE_CARACTERES}.")
    custo = int(math.ceil(len(texto) * CUSTO.get(modelo, 1.0)))
    v = achar_voz(vozes(), voz)
    log(f"Roteiro {stem}: {len(texto)} caracteres, voz {v['name']}, modelo {modelo}: custo de até {custo} créditos.")
    drive = _drive()
    pasta = drive.pasta("root", PASTA_DRIVE)
    pasta_audio = drive.pasta(pasta, "_audio")
    chave_cache = hashlib.sha1(f"{texto}|{v['voice_id']}|{modelo}".encode()).hexdigest()[:10]
    nome_audio = f"{stem}-{chave_cache}"
    tmp = Path(tempfile.mkdtemp())
    mp3, js = tmp / "voz.mp3", tmp / "tempos.json"
    ja = {i["name"]: i for i in drive.listar(pasta_audio)}
    if f"{nome_audio}.mp3" in ja and f"{nome_audio}.json" in ja:
        log("Este texto já foi narrado com esta voz e modelo: reaproveitando o áudio (0 créditos).")
        drive.baixar(ja[f"{nome_audio}.mp3"]["id"], mp3)
        alinh = json.loads(drive.ler_texto(ja[f"{nome_audio}.json"]["id"]))
    else:
        if not confirmar:
            raise SystemExit("Sem a confirmação 'gastar créditos' marcada: nada foi narrado.")
        s = saldo()
        log(f"Saldo antes: {s['restam']} créditos.")
        if s["restam"] < custo + MARGEM_CREDITOS:
            raise SystemExit("Saldo insuficiente para este roteiro: nada foi narrado.")
        audio, alinh = narrar(texto, v["voice_id"], modelo)
        mp3.write_bytes(audio)
        js.write_text(json.dumps(alinh), encoding="utf-8")
        drive.enviar(mp3, pasta_audio, f"{nome_audio}.mp3", "audio/mpeg")
        drive.enviar(js, pasta_audio, f"{nome_audio}.json", "application/json")
        log(f"Saldo depois: {saldo()['restam']} créditos.")
    palavras = palavras_do_alinhamento(alinh)
    dur = palavras[-1]["fim"] if palavras else 0
    log(f"Fala com {dur:.1f} s; vídeo com {min(dur + 0.4 + FIM_SEG, DURACAO_MAX):.1f} s.")
    if dur + 0.4 + FIM_SEG > DURACAO_MAX:
        log("Aviso: a fala passou do tempo; o fim do vídeo foi cortado em 60 s. Encurte o texto.")
    capa = baixar_capa(drive, r["codigo"], tmp)
    video = renderizar(capa, r["livro"], r["autor"], palavras, mp3, dur, tmp / f"{stem}.mp4")
    rotulo = f"Reels - {r['livro']} ({v['name'].split(' ')[0]}, {modelo})"
    drive.enviar(video, pasta, f"{rotulo}.mp4", "video/mp4")
    leg = tmp / "legenda.txt"
    leg.write_text(r.get("legenda_post", ""), encoding="utf-8")
    drive.enviar(leg, pasta, f"{rotulo} - legenda do post.txt", "text/plain")
    log(f"Pronto: vídeo e legenda do post na pasta '{PASTA_DRIVE}' do Drive.")


def modo_previa(nome: str, capa_arq: str | None, saida: Path) -> None:
    stem, r = ler_roteiro(nome)
    palavras = palavras_ficticias(r["texto"])
    capa = ImageOps.exif_transpose(Image.open(capa_arq)).convert("RGB") if capa_arq else None
    saida.mkdir(parents=True, exist_ok=True)
    video = renderizar(capa, r["livro"], r["autor"], palavras, None, palavras[-1]["fim"], saida / f"{stem}-previa.mp4")
    log(f"Prévia: {video}")


def main() -> None:
    ap_ = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap_.add_argument("--saldo", action="store_true")
    ap_.add_argument("--previa", action="store_true")
    ap_.add_argument("--roteiro", default="")
    ap_.add_argument("--voz", default="")
    ap_.add_argument("--modelo", default="eleven_v3", choices=sorted(CUSTO))
    ap_.add_argument("--gastar", action="store_true", help="autoriza gastar créditos da ElevenLabs")
    ap_.add_argument("--capa", default=None)
    ap_.add_argument("--saida", default="saida_reels")
    a = ap_.parse_args()
    if a.saldo:
        modo_saldo()
    elif a.previa:
        modo_previa(a.roteiro, a.capa, Path(a.saida))
    else:
        if not a.roteiro:
            raise SystemExit("Diga qual roteiro (--roteiro).")
        modo_narrar(a.roteiro, a.voz, a.modelo, a.gastar)


if __name__ == "__main__":
    main()
