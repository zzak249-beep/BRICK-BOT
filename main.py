"""Punto de entrada. Uso:
    python main.py                  # bucle continuo (Railway)
    python main.py --once           # un solo escaneo y salir
    python main.py --test-telegram  # envía un mensaje de prueba
    python main.py --list-symbols   # muestra los pares que se vigilarán
"""
from __future__ import annotations

import argparse
import logging
import sys

from bot.config import load_settings
from bot.scanner import Scanner


def main() -> int:
    ap = argparse.ArgumentParser(description="Bot de señales BingX -> Telegram")
    ap.add_argument("--once", action="store_true", help="un solo escaneo y salir")
    ap.add_argument("--test-telegram", action="store_true", help="enviar un mensaje de prueba")
    ap.add_argument("--list-symbols", action="store_true", help="listar los pares vigilados")
    args = ap.parse_args()

    try:
        cfg = load_settings()
    except ValueError as exc:
        print(f"Configuración inválida: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    scanner = Scanner(cfg)

    if args.test_telegram:
        return 0 if scanner.tg.send("✅ Prueba del bot de señales BingX: Telegram funciona.") else 1

    scanner.refresh_universe()
    if args.list_symbols:
        print("\n".join(scanner.symbols))
        return 0
    if args.once:
        scanner.scan_once()
        return 0

    scanner.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
