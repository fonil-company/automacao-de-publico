"""
Interface web para criar públicos de engajamento do Instagram.

Local (só neste computador):
    py interface.py      (ou "Abrir interface.bat" / "Abrir interface.command")

Servidor (Easypanel, via Dockerfile):
    HOST=0.0.0.0 PORT=8000 APP_PASSWORD=... META_ACCESS_TOKEN=... python interface.py

Variáveis de ambiente:
    META_ACCESS_TOKEN, META_ACCESS_TOKEN_<NOME>   um token por BM; cada conta de anúncio
                                                  usa o primeiro token que consegue criar nela
    APP_PASSWORD   senha da página (obrigatória quando HOST não é o localhost)
    HOST, PORT     endereço do servidor (padrão: 127.0.0.1, porta livre a partir de 8765)
"""

import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import criar_publicos_ig as motor

ARQUIVO_HTML = motor.PASTA / "interface.html"
CABECALHO_APP = "publicos-ig"  # exigido nos POSTs para outros sites não conseguirem chamar a API
HOSTS_LOCAIS = {"127.0.0.1", "localhost"}

HOST = os.environ.get("HOST", "127.0.0.1")
PORTA = os.environ.get("PORT")
SENHA = os.environ.get("APP_PASSWORD", "")
MODO_SERVIDOR = HOST not in HOSTS_LOCAIS
DURACAO_SESSAO = 12 * 3600

trava = threading.Lock()
sessoes = {}                 # id da sessão -> horário em que expira
token_manual = ""            # token colado na página (só no modo local)
token_por_conta = {}         # conta de anúncio -> token que tem acesso a ela
contas_ig_validas = {}       # conta de anúncio -> {id do IG: username}
cache_existentes = {}        # conta de anúncio -> nomes de públicos que já existem
tarefas = {}                 # id da tarefa -> progresso da criação


class ErroUsuario(Exception):
    def __init__(self, mensagem, status=400):
        super().__init__(mensagem)
        self.status = status


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

def tokens_configurados():
    variaveis = {**motor.ler_env(), **os.environ}
    tokens = [token_manual] + [
        valor.strip() for chave, valor in sorted(variaveis.items())
        if chave.startswith("META_ACCESS_TOKEN") and valor.strip()
    ]
    return list(dict.fromkeys(t for t in tokens if t))


def token_da_conta(conta):
    token = token_por_conta.get(conta)
    if not token:
        raise ErroUsuario("Busque a conta de anúncio de novo antes de continuar.")
    motor.usar_token(token)
    return token


# ---------------------------------------------------------------------------
# Regras
# ---------------------------------------------------------------------------

def normalizar_conta(valor):
    conta = str(valor or "").strip().removeprefix("act_")
    if not conta.isdigit():
        raise ErroUsuario("O ID da conta de anúncio deve ter só números (ex.: 123456789).")
    return conta


def planejar(dados):
    conta = normalizar_conta(dados.get("conta"))

    id_cliente = str(dados.get("id_cliente") or "").strip().upper()
    if id_cliente and not (id_cliente.isalpha() and 2 <= len(id_cliente) <= 3):
        raise ErroUsuario("O código do cliente deve ter 2 ou 3 letras (ex.: ABC).")

    formato = str(dados.get("formato") or "").strip() or None
    if formato and ("{TIPO}" not in formato or "{DIAS}" not in formato):
        raise ErroUsuario("O formato personalizado precisa ter {TIPO} e {DIAS}.")

    try:
        janelas = sorted({int(d) for d in dados.get("janelas") or []})
    except (TypeError, ValueError):
        raise ErroUsuario("As janelas devem ser números de dias.")
    if not janelas:
        raise ErroUsuario("Escolha pelo menos uma janela de dias.")
    if not all(1 <= d <= motor.JANELA_MAXIMA for d in janelas):
        raise ErroUsuario(f"Cada janela deve estar entre 1 e {motor.JANELA_MAXIMA} dias.")

    publicos = [
        {"nome": motor.montar_nome(tipo, dias, id_cliente, formato),
         "tipo": tipo, "evento": evento, "dias": dias}
        for tipo, evento in motor.TIPOS
        for dias in janelas
    ]
    return conta, publicos


def existentes(conta, atualizar=False):
    if atualizar or conta not in cache_existentes:
        cache_existentes[conta] = motor.nomes_existentes(conta)
    return cache_existentes[conta]


# ---------------------------------------------------------------------------
# Rotas da API
# ---------------------------------------------------------------------------

def api_token(dados):
    global token_manual
    if MODO_SERVIDOR:
        raise ErroUsuario("No servidor, os tokens ficam nas variáveis de ambiente do Easypanel.")
    token = str(dados.get("token") or "").strip()
    if not token:
        raise ErroUsuario("Cole o token de acesso.")
    token_manual = token
    token_por_conta.clear()
    cache_existentes.clear()
    if dados.get("salvar"):
        motor.ARQUIVO_ENV.write_text(f"META_ACCESS_TOKEN={token}\n", encoding="utf-8")
    return {"ok": True}


def api_buscar(dados):
    conta = normalizar_conta(dados.get("conta"))
    candidatos = tokens_configurados()
    if not candidatos:
        raise ErroUsuario("Nenhum token de acesso configurado.")

    primeiro_erro, achou_sem_permissao, escolhido = None, False, None
    for token in candidatos:
        motor.usar_token(token)
        contas_ig, erro = motor.listar_contas_ig(conta)
        if erro:
            primeiro_erro = primeiro_erro or erro
        elif not motor.pode_criar_na_conta(conta):
            achou_sem_permissao = True
        else:
            escolhido = (token, contas_ig)
            break

    if not escolhido:
        if achou_sem_permissao:
            raise ErroUsuario(motor.AVISO_SEM_ACESSO)
        raise ErroUsuario(
            "Nenhum token configurado tem acesso a essa conta de anúncio.\n"
            + motor.explicar_erro(primeiro_erro or {})
            + "\nConfira o ID da conta e se ela está atribuída ao usuário do sistema da BM."
        )

    token, contas_ig = escolhido
    motor.usar_token(token)
    if not contas_ig:
        raise ErroUsuario(
            "Essa conta de anúncio não tem nenhum Instagram vinculado. Vincule o Instagram "
            "do cliente à conta de anúncio no Gerenciador de Negócios e tente de novo."
        )
    contas = motor.detalhes_contas_ig(contas_ig)
    token_por_conta[conta] = token
    contas_ig_validas[conta] = {c["id"]: c.get("username", "?") for c in contas}
    cache_existentes.pop(conta, None)
    return {"conta": conta, "contas": contas}


def api_previa(dados):
    conta, publicos = planejar(dados)
    token_da_conta(conta)
    ja_existem = existentes(conta)
    for p in publicos:
        p["existe"] = p["nome"] in ja_existem
    novos = sum(not p["existe"] for p in publicos)
    return {"publicos": publicos, "novos": novos, "existentes": len(publicos) - novos}


def api_criar(dados):
    conta, publicos = planejar(dados)
    token = token_da_conta(conta)
    ig_id = str(dados.get("ig_id") or "")
    if ig_id not in contas_ig_validas.get(conta, {}):
        raise ErroUsuario("Busque a conta de anúncio e escolha o Instagram antes de criar.")

    with trava:
        if any(t["ativa"] and t["conta"] == conta for t in tarefas.values()):
            raise ErroUsuario("Já existe uma criação em andamento para essa conta. Aguarde terminar.")
        novos = [p for p in publicos if p["nome"] not in existentes(conta, atualizar=True)]
        if not novos:
            raise ErroUsuario("Todos esses públicos já existem nessa conta. Nada a criar.")
        id_tarefa = secrets.token_hex(8)
        tarefas[id_tarefa] = {
            "ativa": True, "terminado": False, "conta": conta,
            "ig": contas_ig_validas[conta][ig_id], "total": len(novos),
            "feitos": 0, "sucesso": 0, "erros": 0, "aguardando": 0,
            "itens": [], "relatorio": False, "_arquivo": "",
        }

    threading.Thread(
        target=executar, args=(id_tarefa, token, conta, ig_id, novos), daemon=True
    ).start()
    return {"id": id_tarefa, "total": len(novos)}


def executar(id_tarefa, token, conta, ig_id, novos):
    motor.usar_token(token)
    tarefa = tarefas[id_tarefa]
    linhas = []

    def ao_esperar(segundos):
        with trava:
            tarefa["aguardando"] = segundos

    try:
        for p in novos:
            regra = motor.montar_regra(ig_id, p["dias"], p["evento"])
            resposta = motor.criar_publico(conta, p["nome"], regra, ao_esperar)
            with trava:
                tarefa["feitos"] += 1
                if "id" in resposta:
                    tarefa["sucesso"] += 1
                    tarefa["itens"].append({"nome": p["nome"], "ok": True})
                    linhas.append([p["nome"], p["tipo"], p["dias"], "criado", resposta["id"], ""])
                else:
                    msg = motor.explicar_erro(resposta.get("error", {})).replace("\n", " ")
                    tarefa["erros"] += 1
                    tarefa["itens"].append({"nome": p["nome"], "ok": False, "erro": msg})
                    linhas.append([p["nome"], p["tipo"], p["dias"], "erro", "", msg])
            time.sleep(0.5)
    finally:
        arquivo = motor.salvar_relatorio(conta, linhas) if linhas else ""
        cache_existentes.pop(conta, None)
        with trava:
            tarefa.update({
                "ativa": False, "terminado": True,
                "relatorio": bool(arquivo), "_arquivo": str(arquivo),
            })


def buscar_tarefa(params):
    tarefa = tarefas.get((params.get("id") or [""])[0])
    if not tarefa:
        raise ErroUsuario("Não encontrei essa criação (o servidor pode ter reiniciado).", 404)
    return tarefa


def api_progresso(params):
    tarefa = buscar_tarefa(params)
    with trava:
        return {k: v for k, v in json.loads(json.dumps(tarefa)).items() if not k.startswith("_")}


ROTAS_GET = {"/api/progresso": api_progresso}
ROTAS_POST = {
    "/api/token": api_token,
    "/api/buscar": api_buscar,
    "/api/previa": api_previa,
    "/api/criar": api_criar,
}


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def responder(self, status, corpo, tipo="application/json; charset=utf-8", cabecalhos=None):
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        for chave, valor in (cabecalhos or {}).items():
            self.send_header(chave, valor)
        self.end_headers()
        self.wfile.write(corpo)

    def executar_rota(self, funcao, dados):
        try:
            self.responder(200, funcao(dados))
        except ErroUsuario as erro:
            self.responder(erro.status, {"erro": str(erro)})
        except Exception as erro:  # noqa: BLE001 — mostrar qualquer falha na tela
            self.responder(500, {"erro": f"Erro inesperado: {erro}"})

    # --- sessão -----------------------------------------------------------

    def id_sessao(self):
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        return cookie["sessao"].value if "sessao" in cookie else ""

    def logado(self):
        if not SENHA:
            return True
        expira = sessoes.get(self.id_sessao())
        return bool(expira and expira > time.time())

    def cookie_sessao(self, valor, duracao):
        seguro = "; Secure" if self.headers.get("X-Forwarded-Proto") == "https" else ""
        return f"sessao={valor}; Path=/; HttpOnly; SameSite=Strict; Max-Age={duracao}{seguro}"

    def entrar(self, dados):
        senha = str(dados.get("senha") or "")
        if not SENHA or not secrets.compare_digest(senha.encode(), SENHA.encode()):
            time.sleep(1)
            self.responder(401, {"erro": "Senha incorreta."})
            return
        sessao = secrets.token_urlsafe(32)
        sessoes[sessao] = time.time() + DURACAO_SESSAO
        self.responder(200, {"ok": True},
                       cabecalhos={"Set-Cookie": self.cookie_sessao(sessao, DURACAO_SESSAO)})

    def sair(self):
        sessoes.pop(self.id_sessao(), None)
        self.responder(200, {"ok": True}, cabecalhos={"Set-Cookie": self.cookie_sessao("", 0)})

    def status(self):
        logado = self.logado()
        self.responder(200, {
            "servidor": MODO_SERVIDOR,
            "precisa_login": bool(SENHA),
            "logado": logado,
            "token": logado and bool(tokens_configurados()),
        })

    # --- rotas ------------------------------------------------------------

    def do_GET(self):
        partes = urlsplit(self.path)
        caminho, params = partes.path, parse_qs(partes.query)
        if caminho == "/":
            self.responder(200, ARQUIVO_HTML.read_bytes(), "text/html; charset=utf-8")
        elif caminho == "/api/status":
            self.status()
        elif not self.logado():
            self.responder(401, {"erro": "Entre com a senha."})
        elif caminho == "/api/relatorio":
            self.baixar_relatorio(params)
        elif caminho in ROTAS_GET:
            self.executar_rota(ROTAS_GET[caminho], params)
        else:
            self.responder(404, {"erro": "Não encontrado"})

    def do_POST(self):
        caminho = urlsplit(self.path).path
        if self.headers.get("X-App") != CABECALHO_APP:
            self.responder(403, {"erro": "Acesso negado"})
            return
        tamanho = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            self.responder(400, {"erro": "Dados inválidos"})
            return

        if caminho == "/api/login":
            self.entrar(dados)
        elif caminho == "/api/sair":
            self.sair()
        elif not self.logado():
            self.responder(401, {"erro": "Sua sessão expirou. Entre de novo."})
        elif caminho in ROTAS_POST:
            self.executar_rota(ROTAS_POST[caminho], dados)
        else:
            self.responder(404, {"erro": "Não encontrado"})

    def baixar_relatorio(self, params):
        try:
            arquivo = Path(buscar_tarefa(params)["_arquivo"])
        except ErroUsuario as erro:
            self.responder(erro.status, {"erro": str(erro)})
            return
        if not arquivo.is_file():
            self.responder(404, {"erro": "Relatório não encontrado."})
            return
        self.responder(200, arquivo.read_bytes(), "text/csv; charset=utf-8",
                       {"Content-Disposition": f'attachment; filename="{arquivo.name}"'})


def iniciar_servidor():
    if PORTA:
        return ThreadingHTTPServer((HOST, int(PORTA)), Manipulador), int(PORTA)
    for porta in range(8765, 8785):
        try:
            return ThreadingHTTPServer((HOST, porta), Manipulador), porta
        except OSError:
            continue
    motor.encerrar("Não achei uma porta livre para abrir a interface.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    if MODO_SERVIDOR and not SENHA:
        motor.encerrar(
            "Para rodar como site (HOST diferente de 127.0.0.1) é obrigatório definir APP_PASSWORD,\n"
            "senão qualquer pessoa com o link conseguiria criar públicos nas contas."
        )

    servidor, porta = iniciar_servidor()
    url = f"http://{'127.0.0.1' if not MODO_SERVIDOR else HOST}:{porta}/"

    print("=" * 64, flush=True)
    if MODO_SERVIDOR:
        print(f"  Interface de públicos rodando em {HOST}:{porta}", flush=True)
        print(f"  Tokens configurados: {len(tokens_configurados())}", flush=True)
    else:
        print("  Interface de públicos do Instagram aberta no navegador", flush=True)
        print(f"  Endereço: {url}", flush=True)
        print("  Deixe esta janela aberta enquanto usa. Para fechar: Ctrl+C.", flush=True)
    print("=" * 64, flush=True)

    if not MODO_SERVIDOR and "--sem-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nInterface encerrada.")


if __name__ == "__main__":
    main()
