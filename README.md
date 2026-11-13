# Robô de audiolivros no YouTube

Publica capítulos de audiolivro no YouTube todos os dias, sozinho, a partir de uma pasta do Google Drive. Se um
arquivo de áudio tiver vários capítulos, o robô corta por capítulo antes de publicar. O mesmo código serve para
**qualquer canal**: tudo o que é do canal fica no Drive (arquivo `canal.yaml`), nunca aqui.

```
Todo dia, no GitHub Actions:
  1. Abre a pasta raiz do Drive e lê o canal.yaml (textos, link e listas do canal)
  2. Se houver arquivo com vários capítulos, ouve o áudio, acha "Capítulo 2, 3..." e corta
  3. Pega o próximo capítulo ainda não publicado
  4. Monta o vídeo (capa + nome do capítulo + áudio) e a miniatura
  5. Envia ao YouTube, com título, descrição e playlist do livro
  6. Anota no Drive o que já foi publicado, para nunca repetir
```

**Repositório público, canal escondido.** O log das execuções (que qualquer pessoa pode ler aqui) só mostra
rótulos neutros, como `Publicando livro 3 a partir do capítulo 12` ou `Vídeo enviado: vídeo 1`. O relatório
completo, com os nomes de verdade, vai para o Drive do canal. Veja [Modo discreto](#modo-discreto).

---

## 1. Como organizar o Google Drive

Crie uma pasta (por exemplo **Audiolivros**) e, dentro dela, uma pasta para cada livro:

```
Audiolivros/                  <- pasta raiz (o ID dela vai no segredo DRIVE_PASTA_RAIZ)
  canal.yaml                  <- o que é do canal (modelo: canal.exemplo.yaml)
  01 - Título do Livro/
    ficha.txt                 <- dados do livro (modelo: ficha.exemplo.txt)
    capa.jpg                  <- imagem da capa (capa.png também serve)
    01 - Primeiro capítulo.mp3   <- um arquivo por capítulo: "número - título"
    02 - Segundo capítulo.mp3
  02 - Outro Livro/
    ficha.txt
    livro completo.mp3        <- arquivo com VÁRIOS capítulos: o robô corta sozinho
```

**A ficha e a capa são opcionais.** Sem ficha, o título vem do nome da pasta e o livro é tratado como **uso
pessoal: sempre privado**. Sem capa, a primeira imagem da pasta é usada; sem nenhuma, o fundo fica liso.

**Nomes de áudio:**
- `03 - Título.mp3` ou `03.mp3` (começa com número): é **um capítulo** e vai direto para a fila;
- `Pasta49_001 - Título A.mp3`, `Pasta49_002 - Título B.mp3`: **partes do mesmo capítulo**, viram um vídeo só;
- `001. Livro - 03 - Capítulo 1.mp3` (faixas numeradas): cada faixa vira um vídeo, com o nome da seção;
- não começa com número (`livro completo.mp3`, `parte 1.m4b`): tem **vários capítulos** e será cortado.

O robô cria sozinho, dentro da pasta do livro: `capitulos/` (capítulos cortados), `originais/` (o arquivo
original, depois de cortado), `publicados.json` (o que já foi para o YouTube: não apague) e `cortes.json`.

**Corte automático:** usa as marcações de capítulo do arquivo (comum em `.m4b`) ou ouve o áudio e procura o
narrador dizendo "Capítulo 1", "Capítulo dois", "Prólogo", "Epílogo"... logo depois de uma pausa, e corta no meio do
silêncio. Se algo parecer estranho (sequência que pula ou repete, capítulo com menos de 1 minuto, total diferente
de `total_capitulos` da ficha), ele **não publica**, cria `ERRO - <nome>.txt` na pasta do livro e a execução falha
(o GitHub te avisa por e-mail).

---

## 2. Como ligar um canal (uma vez por canal, cerca de 1 hora)

### 2.1 Projeto no Google Cloud
1. Acesse <https://console.cloud.google.com/> com a **conta dona do canal** e crie um projeto.
2. Em **APIs e serviços > Biblioteca**, ative a **YouTube Data API v3** e a **Google Drive API**.
3. Em **APIs e serviços > Tela de consentimento OAuth**: tipo **Externo**, preencha nome e e-mail e salve. Clique
   em **Publicar app** ("Em produção"); em "Teste", a autorização expira em 7 dias.
4. Em **Credenciais > Criar credenciais > ID do cliente OAuth**, tipo **App para computador**. Baixe o JSON e
   salve como `client_secret.json` na pasta deste projeto, no seu computador. **Nunca envie esse arquivo para o
   GitHub** (o `.gitignore` já o bloqueia).

### 2.2 Pasta do canal no Drive
1. No Drive da conta do canal, crie a pasta raiz (ex.: **Audiolivros**) e as pastas dos livros.
2. Copie o arquivo `canal.exemplo.yaml` deste repositório, preencha com os dados do canal (link de inscrição,
   textos da descrição, frase da imagem, livros pausados...) e salve **na pasta raiz** com o nome `canal.yaml`.
3. Abra a pasta raiz no navegador: o ID é o trecho final do endereço, depois de `/folders/`. Guarde-o.

### 2.3 Autorizar o robô (no seu computador)
```bash
pip install google-auth-oauthlib
python scripts/autorizar.py
```
O navegador abre: entre com a **conta do canal**. O Google avisa que o app não foi verificado: clique em
**Avançado > Acessar** (o app é seu). No fim, o terminal mostra 3 valores. **Não cole esses valores em nenhum
lugar além dos segredos do GitHub.**

### 2.4 Cadastrar os segredos no GitHub
Os segredos ficam no **ambiente** do canal (Settings > Environments > `canal-1` > Add environment secret; veja
[Vários canais](#vários-canais)):

| Nome | Valor |
|---|---|
| `GOOGLE_CLIENT_ID` | mostrado pelo `autorizar.py` |
| `GOOGLE_CLIENT_SECRET` | mostrado pelo `autorizar.py` |
| `GOOGLE_REFRESH_TOKEN` | mostrado pelo `autorizar.py` |
| `DRIVE_PASTA_RAIZ` | o ID da pasta raiz (passo 2.2) |
| `GOOGLE_TTS_API_KEY` | opcional: só para narração com voz sintética |
| `GOOGLE_BOOKS_API_KEY` | opcional: busca de capas no Google Livros |

Segredos nunca aparecem no log (o GitHub troca por `***`) e não são entregues a execuções vindas de forks.

### 2.5 Primeiro teste
Em **Actions > Publicar audiolivro > Run workflow**, marque **"Só testar"** e rode. Depois rode sem marcar para
publicar de verdade. A partir daí ele roda sozinho todo dia (horários na linha `cron` de
`.github/workflows/publicar.yml`, em UTC).

### Vários canais neste mesmo repositório
Cada canal tem a sua pasta no Drive (com o seu `canal.yaml`), a sua autorização e os seus segredos, guardados num
**ambiente** do GitHub. Veja a seção [Vários canais](#vários-canais).

---

## 3. Privacidade e publicação pública
- A privacidade é **por livro**, na ficha: `privacidade: private | unlisted | public`. O padrão é `private`.
- `public` e `unlisted` só valem para `licenca: dominio_publico` ou `licenca: proprio`. Livro sem ficha, ou com
  `licenca: uso_pessoal`, é **sempre privado**.
- Para publicar vídeos **públicos** pela API, o YouTube exige aprovar o projeto (auditoria gratuita):
  <https://support.google.com/youtube/contact/yt_api_form>. Até lá, todo envio vira privado.
- **Verifique o canal** em <https://www.youtube.com/verify> para liberar miniaturas e vídeos com mais de 15 min.

## 4. Ajustes
- `config.yaml` (aqui no repositório): o funcionamento do robô, igual para todos os canais (quantos vídeos por
  dia, tempo máximo de cada etapa, modelo de reconhecimento de voz...).
- `canal.yaml` (no Drive de cada canal): o que é do canal. Vale por cima do `config.yaml`. Campos:
  `cta` (link e textos da descrição), `video` (frase e cores da imagem), `publicacao > pausados / livros /
  categoria_id / idioma`, `seo > titulos_protegidos` e `metadados` (autores conhecidos, correções de nomes).
- Se o `canal.yaml` do Drive estiver com erro de formato, o robô **para** (para não publicar sem os dados do canal).

## Modo discreto
No GitHub Actions o modo discreto liga sozinho (`src/discreto.py`):
- **Log neutro:** cada valor numa mensagem vira um rótulo (`livro 3`, `vídeo 12`) ou `‹…›`. Números ficam. Erros
  aparecem só pelo tipo (`HttpError 403`). Links do YouTube/Drive viram `‹link›` e `@canal` vira `‹canal›`.
- **Máscaras:** tudo o que o robô lê do Drive e do YouTube (nomes, IDs, títulos, descrições) e os textos do
  `canal.yaml` são registrados no GitHub como segredos da execução (`::add-mask::`): se escaparem por outro
  caminho, aparecem como `***`.
- **Programas de fora** (ffmpeg, whisper, bibliotecas) e erros completos (traceback) não vão para a tela.
- **Relatório completo no Drive:** pasta **Relatórios do robô**, dentro da pasta raiz, um arquivo por execução, com
  a legenda dos rótulos (`livro 3: <nome da pasta>`). Relatórios com mais de 60 dias vão para a lixeira.
- **Run workflow:** no campo do livro, digite o **número** que aparece no log (ex.: `3`). O robô lê o que você
  digitou direto do evento, sem passar pelo texto do passo.
- **Sem artifacts:** nenhum workflow guarda arquivos na execução (prévias e testes de voz vão para o Drive). O único
  cache é o modelo público de reconhecimento de voz.
- **Limpeza:** o workflow **Apagar execuções antigas** apaga todo dia as execuções e logs com mais de 3 dias.

No seu computador nada disso liga: o log mostra tudo. Para testar, rode com `ROBO_DISCRETO=1`.

## Vários canais
Cada canal vive num **ambiente** do GitHub com os seus próprios segredos. Os canais nunca dividem pasta,
autorização nem segredos. No log e no repositório os canais só aparecem como `canal-1`, `canal-2`...

1. **Criar o ambiente:** Settings > Environments > **New environment**, nome `canal-1` (o segundo canal será
   `canal-2`, e assim por diante). Não use o nome do canal: o nome do ambiente aparece no log.
2. **Segredos do canal:** dentro do ambiente, em **Environment secrets > Add environment secret**, cadastre os
   segredos da tabela do passo 2.4 (`GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN`,
   `DRIVE_PASTA_RAIZ` e, se usar, `GOOGLE_TTS_API_KEY` e `GOOGLE_BOOKS_API_KEY`), com os valores **daquele** canal.
3. **Quais canais rodam sozinhos:** em Settings > Secrets and variables > Actions > aba **Variables** >
   **New repository variable**, crie `CANAIS` com a lista, por exemplo `["canal-1","canal-2"]`. Enquanto essa variável
   não existir, nada roda sozinho (só à mão, preenchendo o campo **canal**).

A publicação diária e a narração rodam para cada canal da lista, em paralelo (um canal com problema não para o
outro). Nos botões **Run workflow**, o campo **canal** escolhe qual canal (vazio na publicação = todos da lista).

## Modo Bíblia (plano "Bíblia em 1 ano")
Com `modo: biblia` no `canal.yaml`, o robô publica **um dia do plano por vídeo**:
- **Áudios no Drive:** dentro da pasta raiz, uma pasta com os livros (nome em `biblia > pasta_audios`), uma
  subpasta por livro com o número na frente (`01 Gênesis`, `40 Mateus`...) e um MP3 por capítulo. O último
  número do nome do arquivo é o capítulo (`01ge01.mp3` = capítulo 1). Da pasta 40 em diante é o Novo Testamento.
- **Plano:** os capítulos são divididos em `dias` leituras (padrão 365) de tamanho parecido. O plano fica gravado
  em `biblia.json` na pasta raiz, junto com o que já foi publicado.
- **Cada vídeo:** título `Gênesis 1, 2 e 3 | Bíblia em Áudio | Dia 1 de 365` (encurta se passar de 70 letras),
  descrição pelo modelo do `canal.yaml` (com minutagem quando há 3 capítulos ou mais e o crédito da tradução),
  miniatura do dia, e entra em 3 playlists: o plano, o Testamento e o livro. O vídeo de ontem ganha o link de hoje.
- **Run workflow:** o campo **capítulo** vira o **dia** do plano (ex.: `5` publica o Dia 5).
- As etapas só de audiolivro (corte, capas, extras, críticas, narração, SEO) são puladas nesse canal.
- `privacidade` (em `biblia`) vale para todos os vídeos. Confirme os direitos da tradução e da gravação antes de
  usar `public`.

## Extras
- **Livro completo, legendas e Shorts** (`config.yaml > extras`): depois dos capítulos do dia, com o que sobrar da
  cota do YouTube. Teste: **Actions > Extras agora** (com "Só prévia", os Shorts vão só para o Drive).
- **Narração a partir do .epub:** ponha o `.epub` na pasta do livro e `narrar: true` na ficha. Usa a voz do Google
  (segredo `GOOGLE_TTS_API_KEY`) dentro da cota grátis do mês.
- **Testar vozes:** **Actions > Testar vozes** lê o `texto.txt` da pasta **Testes de voz** do Drive; os MP3 voltam
  para essa pasta.
- **SEO dos vídeos publicados:** **Actions > SEO - corrigir vídeos publicados**: `previa` monta a lista (vai para o
  relatório do Drive) e `aplicar` aprova e começa, um pouco por dia.
- **Críticas com o NotebookLM** (`config.yaml > criticas`): vem desligado.

## Custos e limites
- **GitHub:** em repositório público, os minutos do Actions são grátis e sem limite. Atenção: em repositório
  público o GitHub **desliga as tarefas agendadas depois de 60 dias sem alterações no código**. Ele avisa por
  e-mail; para religar, vá em **Actions**, escolha o workflow e clique em **Enable workflow**.
- **YouTube:** a cota padrão (10.000 unidades por dia) aceita cerca de 6 envios por dia.

## Cuidados com direitos autorais
- **Domínio público:** traduções e edições recentes podem ter dono. Por isso `fonte_texto` é obrigatório.
- Não use música de fundo de terceiros. Narração com voz de IA exige `voz_sintetica: true` na ficha.

## Segurança deste repositório (para quem mantém)
- **Settings > Actions > General > Fork pull request workflows from outside collaborators:** escolha
  **Require approval for all outside collaborators**.
- Nenhum workflow usa `pull_request_target`, e todos têm `permissions` mínimas (só leitura do código).
- Segredos só em **Settings > Secrets and variables > Actions** (ou nos ambientes). Nunca no código, no
  `config.yaml` ou no `canal.yaml`.

## Testar no computador (opcional)
```bash
pip install -r requirements.txt pytest   # também precisa do ffmpeg instalado
python -m pytest -q                      # testes automáticos
python src/main.py --teste-local capa.jpg "03 - Título.mp3" --ficha ficha.exemplo.txt
python src/cortar.py "livro completo.mp3" --dry-run     # só mostra onde cortaria
```
