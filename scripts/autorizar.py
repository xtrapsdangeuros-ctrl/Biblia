"""Rode no seu computador para autorizar o robô a usar a conta Google do canal.

  1. Baixe o arquivo do cliente OAuth (tipo "App para computador") do Google Cloud e salve como
     client_secret.json nesta pasta.
  2. pip install google-auth-oauthlib
  3. python scripts/autorizar.py
  4. Faça login e aceite. Copie os valores mostrados para os segredos do GitHub (no ambiente do canal).

Canal que é uma "conta de marca" (um segundo canal dentro da sua conta Google) não tem Google Drive, e o Google
recusa o login com "Serviço indisponível". Nesse caso, autorize em duas partes:

  python scripts/autorizar.py --parte youtube   -> escolha o CANAL no login  -> GOOGLE_REFRESH_TOKEN
  python scripts/autorizar.py --parte drive     -> escolha a SUA CONTA       -> GOOGLE_REFRESH_TOKEN_DRIVE
"""

import argparse
import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

YOUTUBE = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    # relatório de analytics (src/analytics.py)
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
DRIVE = ["https://www.googleapis.com/auth/drive"]
PARTES = {"tudo": (YOUTUBE + DRIVE, "GOOGLE_REFRESH_TOKEN"),
          "youtube": (YOUTUBE, "GOOGLE_REFRESH_TOKEN"),
          "drive": (DRIVE, "GOOGLE_REFRESH_TOKEN_DRIVE")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("arquivo", nargs="?", default="client_secret.json")
    parser.add_argument("--parte", choices=sorted(PARTES), default="tudo",
                        help="tudo (padrão), youtube (só o canal) ou drive (só a pasta do Drive)")
    args = parser.parse_args()
    arquivo = Path(args.arquivo)
    if not arquivo.exists():
        sys.exit(f"Não achei {arquivo}. Baixe o JSON do cliente OAuth no Google Cloud e salve com esse nome.")
    escopos, segredo = PARTES[args.parte]
    if args.parte == "youtube":
        print("No login, escolha o CANAL (ex.: o segundo canal da sua conta).")
    elif args.parte == "drive":
        print("No login, escolha a SUA CONTA pessoal (a dona da pasta no Drive), não o canal.")
    fluxo = InstalledAppFlow.from_client_secrets_file(str(arquivo), escopos)
    cred = fluxo.run_local_server(port=0, access_type="offline", prompt="consent")
    dados = json.loads(arquivo.read_text())
    cliente = dados.get("installed") or dados.get("web")
    print("\nPronto! Crie estes segredos no GitHub (Settings > Environments > o ambiente do canal):\n")
    if args.parte != "drive":
        print(f"GOOGLE_CLIENT_ID            = {cliente['client_id']}")
        print(f"GOOGLE_CLIENT_SECRET        = {cliente['client_secret']}")
    print(f"{segredo:<27} = {cred.refresh_token}")
    print("\nNão compartilhe esses valores com ninguém.")


if __name__ == "__main__":
    main()
