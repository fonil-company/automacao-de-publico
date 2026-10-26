#!/bin/bash
# Atalho para Mac: dois cliques abrem a interface no navegador.
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python não encontrado. Instale pelo site https://www.python.org/downloads/ e abra de novo."
  read -n 1 -s -r -p "Aperte qualquer tecla para fechar."
  exit 1
fi

python3 interface.py
read -n 1 -s -r -p "Aperte qualquer tecla para fechar."
