#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pt.ldplayer - Quick test / Demo
Testa o controller e pentest toolkit diretamente sem MCP.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pt_ldplayer.ld_controller import LDController
from pt_ldplayer.pentest_toolkit import PentestToolkit


def main():
    print("=" * 60)
    print("pt.ldplayer - Quick Test")
    print("=" * 60)

    try:
        ld = LDController()
        print(f"LDPlayer: {ld.base_path}")
    except FileNotFoundError as e:
        print(f"ERRO: {e}")
        return

    # Listar instancias
    instances = ld.list_instances()
    print(f"\nInstancias ({len(instances)}):")
    for i in instances:
        print(f"  [{i.index}] {i.name} - {i.status} (PID: {i.pid})")

    running = ld.running_instances()
    print(f"\nEm execucao: {running if running else 'nenhuma'}")

    if not running:
        print("\nNenhuma instancia rodando. Inicie uma para testes de pentest.")
        print("Use: ld_launch ou inicie pelo LDPlayer GUI.")
        return

    # Se tem instancia rodando, fazer recon
    name = running[0]
    print(f"\nExecutando recon em '{name}'...")
    pt = PentestToolkit(ld)

    recon = pt.device_recon(name)
    print(json.dumps(recon, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
