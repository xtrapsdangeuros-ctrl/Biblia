"""Rode UMA vez no seu computador para autorizar o robô a usar sua conta Google.

  1. Baixe o arquivo do cliente OAuth (tipo "App para computador") do Google Cloud e salve como
     client_secret.json nesta pasta.
  2. pip install google-auth-oauthlib
  3. python scripts/autorizar.py
  4. Faça login com a conta DONA DO CANAL e aceite. Copie os 3 valores mostrados para os segredos do GitHub.
"""

import json
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

ESCOPOS = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    # relatório de analytics (src/analytics.py)
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def main() -> None:
    arquivo = Path(sys.argv[1] if len(sys.argv) > 1 else "client_secret.json")
    if not arquivo.exists():
        sys.exit(f"Não achei {arquivo}. Baixe o JSON do cliente OAuth no Google Cloud e salve com esse nome.")
    fluxo = InstalledAppFlow.from_client_secrets_file(str(arquivo), ESCOPOS)
    cred = fluxo.run_local_server(port=0, access_type="offline", prompt="consent")
    dados = json.loads(arquivo.read_text())
    cliente = dados.get("installed") or dados.get("web")
    print("\nPronto! Crie estes segredos no GitHub (Settings > Secrets and variables > Actions):\n")
    print(f"GOOGLE_CLIENT_ID      = {cliente['client_id']}")
    print(f"GOOGLE_CLIENT_SECRET  = {cliente['client_secret']}")
    print(f"GOOGLE_REFRESH_TOKEN  = {cred.refresh_token}")
    print("\nNão compartilhe esses valores com ninguém.")


if __name__ == "__main__":
    main()
