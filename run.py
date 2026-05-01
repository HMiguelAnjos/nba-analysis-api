"""
Ponto de entrada para o executável PyInstaller.

Uso direto:
    python run.py                  # porta padrão 8000
    PORT=9000 python run.py        # porta customizada
    python run.py --port 9000      # alternativa via argumento

O Electron usa esse executável em modo produção.
"""

import argparse
import os

import uvicorn


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NBA Analysis API")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Porta em que a API vai escutar (padrão: 8000)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=os.getenv("HOST", "127.0.0.1"),
        help="Host/interface de rede (padrão: 127.0.0.1)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        log_level="info",
    )
