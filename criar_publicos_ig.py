"""
Cria públicos personalizados de engajamento do Instagram em uma conta de anúncio
do Meta Ads, seguindo o guia automacao-publicos-ig.md.

Uso:
    py criar_publicos_ig.py                 # modo interativo
    py criar_publicos_ig.py --conta 123456  # já informa a conta de anúncio
    py criar_publicos_ig.py --simular       # mostra o que seria criado, sem criar

O token de acesso é lido (nesta ordem) da variável de ambiente META_ACCESS_TOKEN,
do arquivo .env ao lado deste script, ou é pedido na hora.
"""

import argparse
import csv
import getpass
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"
PASTA = Path(__file__).resolve().parent
ARQUIVO_ENV = PASTA / ".env"
PASTA_RELATORIOS = PASTA / "relatorios"

JANELAS_PADRAO = [3, 7, 14, 30, 60, 90, 180, 365, 540, 730]
JANELA_MAXIMA = 730

# Passo 5 — sempre os mesmos 7 tipos
TIPOS = [
    ("ENV", "ig_business_profile_all"),
    ("VISITOU", "ig_business_profile_visit"),
    ("MENSAGEM", "ig_business_profile_user_messaged"),
    ("SALVOU", "ig_business_profile_ad_saved"),
    ("ENGA", "ig_business_profile_engaged"),
    ("CTA-IG", "ig_ad_cta_click"),
    ("SwipeCar", "ig_organic_carousel_swipe"),
]


def montar_nome(tipo, dias, id_cliente="", formato=None):
    if formato:
        return (formato.replace("{TIPO}", tipo).replace("{DIAS}", str(dias))
                .replace("{ID_CLIENT}", id_cliente))
    if tipo == "VISITOU":
        return f"[IG] VISITOU {id_cliente}{dias}D"
    if id_cliente:
        return f"[IG] {tipo} {id_cliente} {dias}D"
    return f"[IG] {tipo} {dias}D"


# Códigos de erro do Graph API que indicam limite de chamadas
CODIGOS_LIMITE = {4, 17, 32, 613, 80003, 80004}
ESPERAS_LIMITE = [30, 60, 120]

TOKEN = ""


# ---------------------------------------------------------------------------
# Utilidades de terminal
# ---------------------------------------------------------------------------

def titulo(texto):
    print()
    print("=" * 64)
    print(f"  {texto}")
    print("=" * 64)


def perguntar(texto, padrao=None):
    sufixo = f" [{padrao}]" if padrao not in (None, "") else ""
    resposta = input(f"{texto}{sufixo}: ").strip()
    return resposta if resposta else (padrao or "")


def perguntar_sim_nao(texto, padrao=True):
    opcoes = "S/n" if padrao else "s/N"
    while True:
        resposta = input(f"{texto} ({opcoes}): ").strip().lower()
        if not resposta:
            return padrao
        if resposta in ("s", "sim", "y", "yes"):
            return True
        if resposta in ("n", "nao", "não", "no"):
            return False
        print("  Responda com 's' ou 'n'.")


def encerrar(mensagem, codigo=1):
    print()
    print(mensagem)
    sys.exit(codigo)


# ---------------------------------------------------------------------------
# Token e chamadas à API
# ---------------------------------------------------------------------------

def ler_env():
    valores = {}
    if ARQUIVO_ENV.exists():
        for linha in ARQUIVO_ENV.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                chave, valor = linha.split("=", 1)
                valores[chave.strip()] = valor.strip().strip('"').strip("'")
    return valores


def carregar_token():
    token = os.environ.get("META_ACCESS_TOKEN") or ler_env().get("META_ACCESS_TOKEN")
    if token:
        return token
    print("Nenhum token encontrado (META_ACCESS_TOKEN no .env ou no ambiente).")
    token = getpass.getpass("Cole o token de acesso (não aparece na tela): ").strip()
    if not token:
        encerrar("Sem token não dá para continuar.")
    if perguntar_sim_nao("Salvar esse token no arquivo .env para as próximas vezes?", False):
        ARQUIVO_ENV.write_text(f"META_ACCESS_TOKEN={token}\n", encoding="utf-8")
        print(f"  Token salvo em {ARQUIVO_ENV}. Não compartilhe esse arquivo.")
    return token


def _requisicao(url, dados=None):
    metodo = "POST" if dados is not None else "GET"
    corpo = urlencode(dados).encode() if dados is not None else None
    try:
        with urlopen(Request(url, data=corpo, method=metodo), timeout=60) as resposta:
            return json.load(resposta)
    except HTTPError as erro:
        try:
            return json.load(erro)
        except ValueError:
            return {"error": {"message": f"HTTP {erro.code} sem detalhes"}}
    except URLError as erro:
        if "CERTIFICATE_VERIFY_FAILED" in str(erro.reason):
            return {"error": {"message": (
                "O Python deste computador está sem os certificados de segurança. No Mac, abra a "
                "pasta Aplicativos → Python 3.x e dê dois cliques em 'Install Certificates.command'."
            )}}
        return {"error": {"message": f"Falha de conexão: {erro.reason}"}}


def graph_get(caminho, **params):
    params["access_token"] = TOKEN
    return _requisicao(f"{BASE_URL}/{caminho}?{urlencode(params)}")


def graph_post(caminho, **params):
    params["access_token"] = TOKEN
    return _requisicao(f"{BASE_URL}/{caminho}", params)


def explicar_erro(erro):
    codigo = erro.get("code")
    mensagem = erro.get("message", "erro desconhecido")
    dicas = {
        190: "O token é inválido ou expirou.",
        10: "O token não tem permissão para essa ação.",
        200: "O usuário do token não tem permissão nessa conta de anúncio ou nesse Instagram "
             "(atribua os dois a ele na BM, com controle total).",
        100: "Algum dado está errado (ex.: ID da conta de anúncio não existe ou o token não enxerga essa conta).",
        2635: "A versão da API usada não é aceita.",
        2654: "A conta de anúncio recusou a gravação. Veja se há pagamento pendente na conta "
              "e se o app do token tem o produto API de Marketing.",
    }
    dica = dicas.get(codigo, "")
    texto = f"[código {codigo}] {mensagem}" if codigo is not None else mensagem
    return f"{dica}\n  Detalhe técnico: {texto}" if dica else texto


# ---------------------------------------------------------------------------
# Passos do guia
# ---------------------------------------------------------------------------

def listar_contas_ig(conta):
    """Junta os perfis de IG ligados à conta de anúncio.

    O edge instagram_accounts (do guia) pode vir vazio quando o perfil foi conectado
    pela BM; nesse caso ele aparece em connected_instagram_accounts.
    Retorna (lista, erro) — erro é o dict de erro da API se o token não acessar a conta.
    """
    resposta = graph_get(f"act_{conta}/instagram_accounts", fields="id,username")
    if "error" in resposta:
        return [], resposta["error"]
    contas = {c["id"]: c for c in resposta.get("data", [])}
    conectadas = graph_get(f"act_{conta}/connected_instagram_accounts", fields="id,username")
    for c in conectadas.get("data", []):
        contas.setdefault(c["id"], c)
    return list(contas.values()), None


AVISO_SEM_ACESSO = (
    "O token enxerga essa conta de anúncio, mas não tem permissão para criar nela.\n"
    "O que fazer: na BM, vá em Usuários do sistema → selecione o usuário do token →\n"
    "Atribuir ativos → Contas de anúncio → marque essa conta com Controle total."
)


def pode_criar_na_conta(conta):
    """False quando o usuário do token não tem a tarefa ADVERTISE/MANAGE na conta.

    Sem essas tarefas toda criação volta com "[código 200] Permissions error".
    Se a consulta falhar, retorna True e deixa a criação mostrar o erro real.
    """
    resposta = graph_get(f"act_{conta}", fields="user_tasks")
    if "error" in resposta:
        return True
    return bool({"ADVERTISE", "MANAGE"} & set(resposta.get("user_tasks") or []))


def passo_1_validar_token(conta):
    titulo("Passo 1 — Conferindo se o token funciona nessa conta")
    contas_ig, erro = listar_contas_ig(conta)
    if erro:
        encerrar(
            "Não deu para acessar essa conta de anúncio com o token atual.\n"
            f"  {explicar_erro(erro)}\n\n"
            "O que fazer: confira o ID da conta e peça um token com permissão\n"
            "ads_management para essa conta específica."
        )
    if not pode_criar_na_conta(conta):
        encerrar(AVISO_SEM_ACESSO)
    print(f"Token ok. Contas de Instagram ligadas à conta de anúncio: {len(contas_ig)}")
    return contas_ig


def detalhes_contas_ig(contas_ig):
    """Consulta cada conta de IG e ordena da que tem mais seguidores para a que tem menos."""
    detalhes = []
    for conta in contas_ig:
        info = graph_get(
            conta["id"],
            fields="username,name,followers_count,media_count,biography,profile_picture_url",
        )
        if "error" in info:
            info = {"username": conta.get("username", "?")}
        info["id"] = conta["id"]
        detalhes.append(info)
    detalhes.sort(key=lambda d: d.get("followers_count") or 0, reverse=True)
    return detalhes


def passo_2_escolher_ig(contas_ig):
    titulo("Passo 2 — Identificando a conta de Instagram (IG Business)")
    if not contas_ig:
        encerrar(
            "Essa conta de anúncio não tem nenhuma conta de Instagram vinculada.\n"
            "Vincule o Instagram do cliente à conta de anúncio no Gerenciador de Negócios\n"
            "e rode de novo."
        )

    detalhes = detalhes_contas_ig(contas_ig)

    for i, d in enumerate(detalhes, 1):
        bio = (d.get("biography") or "").replace("\n", " ")
        if len(bio) > 70:
            bio = bio[:67] + "..."
        print(f"\n  {i}) @{d.get('username', '?')}  —  {d.get('name', '')}")
        print(f"     ID: {d['id']}")
        print(f"     Seguidores: {d.get('followers_count', '?')}   Posts: {d.get('media_count', '?')}")
        if bio:
            print(f"     Bio: {bio}")

    print()
    if len(detalhes) == 1:
        if not perguntar_sim_nao(f"Essa é a conta certa (@{detalhes[0].get('username', '?')})?"):
            encerrar("Ok, parando. Confirme com o time qual Instagram deve ser usado.")
        return detalhes[0]

    print("Sugestão: a de cima (mais seguidores). Contas secundárias costumam")
    print("ter a bio apontando para o perfil oficial.")
    while True:
        escolha = perguntar("Número da conta oficial (na dúvida, confirme com o time)", "1")
        if escolha.isdigit() and 1 <= int(escolha) <= len(detalhes):
            escolhida = detalhes[int(escolha) - 1]
            if perguntar_sim_nao(f"Confirmar @{escolhida.get('username', '?')} ({escolhida['id']})?"):
                return escolhida
        else:
            print(f"  Digite um número de 1 a {len(detalhes)}.")


def passo_3_nomenclatura():
    titulo("Passo 3 — Nome dos públicos")
    print("Padrão: [IG] {TIPO} {ID_CLIENT} {dias}D   (ex.: [IG] ENV ABC 30D)")
    print("O código do cliente (2 ou 3 letras) é opcional.")

    if perguntar_sim_nao("Usar o padrão de nomes?", True):
        while True:
            id_cliente = perguntar("Código do cliente (Enter para deixar sem)").upper()
            if not id_cliente or (id_cliente.isalpha() and 2 <= len(id_cliente) <= 3):
                break
            print("  O código deve ter 2 ou 3 letras (ex.: ABC).")
        return lambda tipo, dias: montar_nome(tipo, dias, id_cliente)

    print("\nDigite o formato usando {TIPO} e {DIAS} (obrigatórios).")
    print("Ex.: Cliente X | IG {TIPO} | {DIAS} dias")
    while True:
        formato = perguntar("Formato")
        if "{TIPO}" in formato and "{DIAS}" in formato:
            break
        print("  O formato precisa ter {TIPO} e {DIAS}, senão os nomes se repetem.")
    return lambda tipo, dias: montar_nome(tipo, dias, formato=formato)


def passo_4_janelas():
    titulo("Passo 4 — Janelas de retenção (dias)")
    print("Padrão: " + ", ".join(str(d) for d in JANELAS_PADRAO))
    if perguntar_sim_nao("Usar as janelas padrão?", True):
        return list(JANELAS_PADRAO)
    while True:
        texto = perguntar("Digite os dias separados por vírgula (ex.: 7, 30, 90)")
        try:
            janelas = sorted({int(p) for p in texto.replace(";", ",").split(",") if p.strip()})
        except ValueError:
            print("  Use só números separados por vírgula.")
            continue
        if janelas and all(1 <= d <= JANELA_MAXIMA for d in janelas):
            return janelas
        print(f"  Cada janela deve estar entre 1 e {JANELA_MAXIMA} dias.")


def nomes_existentes(conta):
    nomes = set()
    resposta = graph_get(f"act_{conta}/customaudiences", fields="name", limit=500)
    while True:
        if "error" in resposta:
            print("  Aviso: não consegui listar os públicos existentes; não vou checar duplicados.")
            return nomes
        nomes.update(p.get("name", "") for p in resposta.get("data", []))
        proxima = resposta.get("paging", {}).get("next")
        if not proxima:
            return nomes
        resposta = _requisicao(proxima)


def montar_regra(ig_id, dias, evento):
    regra = {
        "inclusions": {
            "operator": "or",
            "rules": [{
                "event_sources": [{"id": ig_id, "type": "ig_business"}],
                "retention_seconds": dias * 86400,
                "filter": {
                    "operator": "and",
                    "filters": [{"field": "event", "operator": "eq", "value": evento}],
                },
            }],
        }
    }
    return json.dumps(regra, separators=(",", ":"))


def criar_publico(conta, nome, regra, ao_esperar=None):
    for espera in ESPERAS_LIMITE + [None]:
        resposta = graph_post(
            f"act_{conta}/customaudiences", name=nome, rule=regra, prefill="1"
        )
        erro = resposta.get("error")
        if not erro or erro.get("code") not in CODIGOS_LIMITE or espera is None:
            return resposta
        print(f"    Limite de chamadas da Meta atingido. Esperando {espera}s...")
        if ao_esperar:
            ao_esperar(espera)
        time.sleep(espera)
        if ao_esperar:
            ao_esperar(0)
    return resposta


def salvar_relatorio(conta, linhas):
    PASTA_RELATORIOS.mkdir(exist_ok=True)
    arquivo = PASTA_RELATORIOS / f"publicos_{conta}_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with arquivo.open("w", newline="", encoding="utf-8-sig") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["nome", "tipo", "dias", "status", "id_publico", "erro"])
        escritor.writerows(linhas)
    return arquivo


# ---------------------------------------------------------------------------
# Fluxo principal
# ---------------------------------------------------------------------------

def main():
    global TOKEN

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Cria públicos de engajamento do Instagram no Meta Ads.")
    parser.add_argument("--conta", help="ID da conta de anúncio (com ou sem act_)")
    parser.add_argument("--simular", action="store_true", help="Mostra o que seria criado, sem criar nada")
    args = parser.parse_args()

    titulo("Criação de públicos de engajamento do Instagram")
    if args.simular:
        print("MODO SIMULAÇÃO: nada será criado.")

    TOKEN = carregar_token()

    conta = args.conta or ""
    while True:
        conta = conta.strip().removeprefix("act_")
        if conta.isdigit():
            break
        conta = perguntar("ID da conta de anúncio (só os números)")

    contas_ig = passo_1_validar_token(conta)
    ig = passo_2_escolher_ig(contas_ig)
    montar_nome = passo_3_nomenclatura()
    janelas = passo_4_janelas()

    planejados = [
        (montar_nome(tipo, dias), tipo, evento, dias)
        for tipo, evento in TIPOS
        for dias in janelas
    ]

    print("\nVerificando públicos que já existem na conta...")
    existentes = nomes_existentes(conta)
    novos = [p for p in planejados if p[0] not in existentes]
    repetidos = len(planejados) - len(novos)

    titulo("Resumo antes de criar")
    print(f"Conta de anúncio : act_{conta}")
    print(f"Instagram        : @{ig.get('username', '?')} (ID {ig['id']})")
    print(f"Tipos            : {len(TIPOS)}  |  Janelas: {', '.join(map(str, janelas))}")
    print(f"Públicos a criar : {len(novos)}")
    if repetidos:
        print(f"Já existem       : {repetidos} (com o mesmo nome; serão pulados)")
    print("\nExemplos de nomes:")
    for nome, *_ in novos[:5]:
        print(f"  - {nome}")
    if len(novos) > 5:
        print(f"  ... e mais {len(novos) - 5}")

    if not novos:
        encerrar("Todos os públicos já existem nessa conta. Nada a fazer.", 0)
    if args.simular:
        encerrar("Simulação concluída. Rode sem --simular para criar de verdade.", 0)
    if not perguntar_sim_nao(f"\nCriar os {len(novos)} públicos agora?", False):
        encerrar("Cancelado. Nada foi criado.", 0)

    titulo("Passo 6 — Criando públicos")
    linhas, sucesso, falhas = [], 0, []
    for i, (nome, tipo, evento, dias) in enumerate(novos, 1):
        resposta = criar_publico(conta, nome, montar_regra(ig["id"], dias, evento))
        if "id" in resposta:
            sucesso += 1
            print(f"  [{i}/{len(novos)}] OK    {nome}")
            linhas.append([nome, tipo, dias, "criado", resposta["id"], ""])
        else:
            msg = explicar_erro(resposta.get("error", {})).replace("\n", " ")
            falhas.append((nome, msg))
            print(f"  [{i}/{len(novos)}] ERRO  {nome}  ->  {msg}")
            linhas.append([nome, tipo, dias, "erro", "", msg])
        time.sleep(0.5)

    titulo("Passo 7 — Resultado")
    print(f"Criados com sucesso: {sucesso} de {len(novos)}")
    if falhas:
        print(f"Com erro: {len(falhas)}  (rode o script de novo: os já criados são pulados)")
    relatorio = salvar_relatorio(conta, linhas)
    print(f"Relatório salvo em: {relatorio}")
    print(
        "\nIMPORTANTE: daqui a alguns dias, confira no Gerenciador de Anúncios se o\n"
        "tamanho dos públicos não está zerado. Público com tamanho 0 é sinal de que\n"
        "a conta de Instagram escolhida estava errada."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        encerrar("\nInterrompido pelo usuário.", 130)
