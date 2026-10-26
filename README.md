# Automação de públicos do Instagram (Meta Ads)

Cria os públicos personalizados de engajamento do Instagram (7 tipos × 10 janelas = 70 públicos) numa conta de anúncio, por uma página simples no navegador. O passo a passo técnico está em [automacao-publicos-ig.md](automacao-publicos-ig.md).

## Como abrir

Precisa ter o **Python 3** instalado ([python.org/downloads](https://www.python.org/downloads/)).

- **Windows:** dois cliques em `Abrir interface.bat`.
- **Mac:** dois cliques em `Abrir interface.command`.
  - Baixe a pasta com `git clone` (ou pelo GitHub Desktop), não pelo botão "Download ZIP": assim o Mac não bloqueia o atalho.
  - Na primeira vez com Python do python.org, rode `Install Certificates.command` (em Aplicativos → Python 3.x).

A página abre sozinha no navegador. Deixe a janela do terminal aberta enquanto usa.

## Token de acesso

Na primeira vez a página pede o token. Ele é gerado na BM em **Configurações → Usuários → Usuários do sistema → Gerar token**, com validade **Nunca** e as permissões:

`ads_management`, `ads_read`, `business_management`, `instagram_basic`, `pages_show_list`

Antes, o usuário do sistema precisa ter, com **acesso total**: o app (com o produto **API de Marketing**), a conta de anúncio e o Instagram do cliente.

O token fica salvo só no computador, no arquivo `.env`, que não vai para o GitHub.

## Publicar como site (Easypanel)

1. No Easypanel, crie um serviço **App** e, em **Source**, aponte para este repositório do GitHub (branch `main`).
2. Em **Build**, escolha **Dockerfile** (o arquivo já está na raiz).
3. Em **Environment**, cadastre:

   | Variável | O que é |
   |---|---|
   | `APP_PASSWORD` | Senha que o time digita para entrar na página. Obrigatória. |
   | `META_ACCESS_TOKEN` | Token do usuário do sistema de uma BM. |
   | `META_ACCESS_TOKEN_<NOME>` | Tokens de outras BMs, se houver (ex.: `META_ACCESS_TOKEN_BM2`). |

   Com vários tokens, a página usa sozinha o que tiver permissão na conta de anúncio digitada.
4. Em **Domains**, crie o domínio apontando para a porta **8000** e ative HTTPS.
5. Clique em **Deploy**.

No site, os tokens não aparecem nem podem ser trocados pela página, apenas pelas variáveis de ambiente. O relatório de cada criação é baixado em CSV no fim do processo.

## Uso pelo terminal (opcional)

```
python criar_publicos_ig.py            # Windows: py criar_publicos_ig.py
python criar_publicos_ig.py --simular  # mostra o que seria criado, sem criar
```

Os relatórios de cada execução ficam na pasta `relatorios/` (também fora do GitHub).
