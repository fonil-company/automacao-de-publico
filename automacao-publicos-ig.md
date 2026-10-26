# Criar Públicos de Engajamento do Instagram — Guia para a IA executora

Guia para a IA/bot do time criar públicos personalizados de engajamento do Instagram em qualquer conta de anúncio, via Graph API.

## O que você recebe vs. o que você descobre

| Dado | Origem | Obrigatório |
|---|---|---|
| ID da conta de anúncio (sem `act_`) | A pessoa do time te passa | Sim |
| Token de acesso | Já configurado no seu bot | — |
| **ID do IG Business** | Você descobre (Passo 2) | Sim |
| Código do cliente (ID_CLIENT) | Só pergunte se quiserem personalizar o nome | Opcional |
| Nomenclatura | Use o padrão (Passo 3), a menos que peçam outro | Confirmar |
| Janelas de retenção | Use o padrão (Passo 4), a menos que escolham outras | Confirmar |

---

## Passo 1 — Confirmar que o token funciona para essa conta

Antes de qualquer coisa, teste o token na conta de anúncio recebida:

```bash
curl -s "https://graph.facebook.com/v25.0/act_{AD_ACCOUNT_ID}/instagram_accounts?access_token={TOKEN}"
```

- Veio `data` com uma ou mais contas de Instagram: token ok, siga pro Passo 2 (a resposta já serve pra isso).
- Veio `error` (token inválido, sem permissão, ou conta não encontrada): **pare e avise a pessoa**, sem tentar outro token por conta própria. Explique o erro recebido e peça um token com permissão `ads_management` para essa conta específica.

Como são pessoas sem conhecimento técnico, não assuma que "deve funcionar" — sempre confirme antes de seguir.

---

## Passo 2 — Descobrir o ID do IG Business

A pessoa não vai saber te passar esse ID. Use a resposta do Passo 1:

- Se vier só uma conta, use o `id` dela.
- Se vier mais de uma, identifique qual é a oficial consultando cada uma:
```bash
curl -s "https://graph.facebook.com/v25.0/{IG_ID}?fields=username,name,followers_count,media_count,biography&access_token={TOKEN}"
```
Critério: a conta oficial tem muito mais seguidores/posts. Uma conta secundária costuma ter a bio apontando pra outra (ex.: "Perfil oficial 👉 @...").

Se ficar em dúvida entre contas parecidas, **pergunte à pessoa do time** qual é a certa — não adivinhe.

⚠️ A criação do público não valida esse ID. Se estiver errado, o público é criado mas fica vazio (tamanho 0), e isso só aparece dias depois no Gerenciador de Anúncios. Confirme sempre por aqui, mesmo que alguém já tenha passado um ID antes.

---

## Passo 3 — Nomenclatura

Padrão:

- Com código de cliente: `[IG] {TIPO} {ID_CLIENT} {dias}D`
- Sem código de cliente: `[IG] {TIPO} {dias}D`

Exceção: no tipo VISITOU não tem espaço antes dos dias (`[IG] VISITOU {ID_CLIENT}{dias}D`).

- Pergunte se querem um `ID_CLIENT` (2–3 letras) pra identificar o cliente no nome, ou se preferem deixar sem.
- Se quiserem outro formato de nome, pergunte qual e use esse no lugar.

---

## Passo 4 — Janelas de retenção

Padrão: `3, 7, 14, 30, 60, 90, 180, 365, 540, 730` dias.

Pergunte se querem manter esse padrão ou escolher outras janelas. Sem resposta, use o padrão.

---

## Passo 5 — Tipos de público (sempre os mesmos 7)

| Tipo | Evento Graph API |
|---|---|
| ENV (todos) | `ig_business_profile_all` |
| VISITOU | `ig_business_profile_visit` |
| MENSAGEM | `ig_business_profile_user_messaged` |
| SALVOU | `ig_business_profile_ad_saved` |
| ENGA (envolveram) | `ig_business_profile_engaged` |
| CTA-IG | `ig_ad_cta_click` |
| SwipeCar | `ig_organic_carousel_swipe` |

---

## Passo 6 — Criar cada público

Para cada combinação de tipo × janela (padrão: 7 × 10 = 70 chamadas):

```bash
curl -s -X POST "https://graph.facebook.com/v25.0/act_{AD_ACCOUNT_ID}/customaudiences" \
  -F "name={NOME}" \
  -F 'rule={"inclusions":{"operator":"or","rules":[{"event_sources":[{"id":"{IG_ID}","type":"ig_business"}],"retention_seconds":{DIAS_EM_SEGUNDOS},"filter":{"operator":"and","filters":[{"field":"event","operator":"eq","value":"{EVENTO}"}]}}]}}' \
  -F "prefill=1" \
  -F "access_token={TOKEN}"
```

`DIAS_EM_SEGUNDOS = dias * 86400`.

---

## Passo 7 — Confirmar no final

Confira se todas as respostas trouxeram `id` (sem `error`). Avise quantos públicos foram criados com sucesso e peça para confirmarem, depois de alguns dias, que o tamanho dos públicos não está zerado no Gerenciador de Anúncios — sinal de ID do IG Business errado.
