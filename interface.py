"""
Interface no navegador para criar públicos de engajamento do Instagram.

Uso:
    py interface.py      (ou dois cliques em "Abrir interface.bat")

Abre uma página local (só neste computador) que usa o mesmo motor do
criar_publicos_ig.py. Deixe a janela preta aberta enquanto usa a página.
"""

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import criar_publicos_ig as motor

PORTA_INICIAL = 8765
ARQUIVO_HTML = motor.PASTA / "interface.html"
CABECALHO_APP = "publicos-ig"  # exigido nos POSTs para outros sites não conseguirem chamar a API local

trava = threading.Lock()
contas_ig_validas = {}       # conta de anúncio -> {id do IG: username}
cache_existentes = {}        # conta de anúncio -> nomes de públicos que já existem
tarefa = {"ativa": False, "terminado": False}


class ErroUsuario(Exception):
    pass


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

def api_status(_):
    return {"token": bool(motor.TOKEN), "env": motor.ARQUIVO_ENV.exists()}


def api_token(dados):
    token = str(dados.get("token") or "").strip()
    if not token:
        raise ErroUsuario("Cole o token de acesso.")
    motor.TOKEN = token
    cache_existentes.clear()
    if dados.get("salvar"):
        motor.ARQUIVO_ENV.write_text(f"META_ACCESS_TOKEN={token}\n", encoding="utf-8")
    return {"ok": True}


def api_buscar(dados):
    conta = normalizar_conta(dados.get("conta"))
    contas_ig, erro = motor.listar_contas_ig(conta)
    if erro:
        raise ErroUsuario(
            "Não deu para acessar essa conta de anúncio com o token atual.\n"
            + motor.explicar_erro(erro)
            + "\nConfira o ID da conta e, se estiver certo, peça um token com "
              "permissão ads_management para essa conta."
        )
    if not motor.pode_criar_na_conta(conta):
        raise ErroUsuario(motor.AVISO_SEM_ACESSO)
    contas = motor.detalhes_contas_ig(contas_ig)
    if not contas:
        raise ErroUsuario(
            "Essa conta de anúncio não tem nenhum Instagram vinculado. Vincule o Instagram "
            "do cliente à conta de anúncio no Gerenciador de Negócios e tente de novo."
        )
    contas_ig_validas[conta] = {c["id"]: c.get("username", "?") for c in contas}
    cache_existentes.pop(conta, None)
    return {"conta": conta, "contas": contas}


def api_previa(dados):
    conta, publicos = planejar(dados)
    ja_existem = existentes(conta)
    for p in publicos:
        p["existe"] = p["nome"] in ja_existem
    novos = sum(not p["existe"] for p in publicos)
    return {"publicos": publicos, "novos": novos, "existentes": len(publicos) - novos}


def api_criar(dados):
    conta, publicos = planejar(dados)
    ig_id = str(dados.get("ig_id") or "")
    if ig_id not in contas_ig_validas.get(conta, {}):
        raise ErroUsuario("Busque a conta de anúncio e escolha o Instagram antes de criar.")

    with trava:
        if tarefa.get("ativa"):
            raise ErroUsuario("Já existe uma criação em andamento. Aguarde terminar.")
        novos = [p for p in publicos if p["nome"] not in existentes(conta, atualizar=True)]
        if not novos:
            raise ErroUsuario("Todos esses públicos já existem nessa conta. Nada a criar.")
        tarefa.clear()
        tarefa.update({
            "ativa": True, "terminado": False, "conta": conta,
            "ig": contas_ig_validas[conta][ig_id], "total": len(novos),
            "feitos": 0, "sucesso": 0, "erros": 0, "aguardando": 0,
            "itens": [], "relatorio": "",
        })

    threading.Thread(target=executar, args=(conta, ig_id, novos), daemon=True).start()
    return {"ok": True, "total": len(novos)}


def executar(conta, ig_id, novos):
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
        relatorio = motor.salvar_relatorio(conta, linhas) if linhas else ""
        cache_existentes.pop(conta, None)
        with trava:
            tarefa.update({"ativa": False, "terminado": True, "relatorio": str(relatorio)})


def api_progresso(_):
    with trava:
        return json.loads(json.dumps(tarefa))


def api_abrir_relatorios(_):
    motor.PASTA_RELATORIOS.mkdir(exist_ok=True)
    if sys.platform == "win32":
        os.startfile(motor.PASTA_RELATORIOS)
    else:
        abridor = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.run([abridor, str(motor.PASTA_RELATORIOS)], check=False)
    return {"ok": True}


ROTAS_GET = {"/api/status": api_status, "/api/progresso": api_progresso}
ROTAS_POST = {
    "/api/token": api_token,
    "/api/buscar": api_buscar,
    "/api/previa": api_previa,
    "/api/criar": api_criar,
    "/api/abrir-relatorios": api_abrir_relatorios,
}


# ---------------------------------------------------------------------------
# Servidor
# ---------------------------------------------------------------------------

class Manipulador(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def responder(self, status, corpo, tipo="application/json; charset=utf-8"):
        if not isinstance(corpo, bytes):
            corpo = json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def executar_rota(self, funcao, dados):
        try:
            self.responder(200, funcao(dados))
        except ErroUsuario as erro:
            self.responder(400, {"erro": str(erro)})
        except Exception as erro:  # noqa: BLE001 — mostrar qualquer falha na tela
            self.responder(500, {"erro": f"Erro inesperado: {erro}"})

    def do_GET(self):
        caminho = self.path.split("?")[0]
        if caminho == "/":
            self.responder(200, ARQUIVO_HTML.read_bytes(), "text/html; charset=utf-8")
        elif caminho in ROTAS_GET:
            self.executar_rota(ROTAS_GET[caminho], {})
        else:
            self.responder(404, {"erro": "Não encontrado"})

    def do_POST(self):
        caminho = self.path.split("?")[0]
        if self.headers.get("X-App") != CABECALHO_APP:
            self.responder(403, {"erro": "Acesso negado"})
            return
        if caminho not in ROTAS_POST:
            self.responder(404, {"erro": "Não encontrado"})
            return
        tamanho = int(self.headers.get("Content-Length") or 0)
        try:
            dados = json.loads(self.rfile.read(tamanho) or b"{}")
        except ValueError:
            self.responder(400, {"erro": "Dados inválidos"})
            return
        self.executar_rota(ROTAS_POST[caminho], dados)


def iniciar_servidor():
    for porta in range(PORTA_INICIAL, PORTA_INICIAL + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", porta), Manipulador), porta
        except OSError:
            continue
    motor.encerrar("Não achei uma porta livre para abrir a interface.")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    motor.TOKEN = os.environ.get("META_ACCESS_TOKEN") or motor.ler_env().get("META_ACCESS_TOKEN", "")
    servidor, porta = iniciar_servidor()
    url = f"http://127.0.0.1:{porta}/"

    print("=" * 64)
    print("  Interface de públicos do Instagram aberta no navegador")
    print(f"  Endereço: {url}")
    print("  Deixe esta janela aberta enquanto usa. Para fechar: Ctrl+C.")
    print("=" * 64)

    if "--sem-navegador" not in sys.argv:
        webbrowser.open(url)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nInterface encerrada.")


if __name__ == "__main__":
    main()
