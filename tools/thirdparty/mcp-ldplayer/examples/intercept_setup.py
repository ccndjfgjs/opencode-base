#!/usr/bin/env python3
"""
Example: Configure traffic interception (Burp Suite / mitmproxy / OWASP ZAP).

This script:
1. Sets up proxy on the emulator
2. Applies SSL pinning bypass via Frida
3. Installs CA certificate (optional)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_ldplayer import LDController, PentestToolkit


def main():
    ld = LDController()
    pt = PentestToolkit(ld)

    running = ld.running_instances()
    if not running:
        print("No running instances.")
        return

    name = running[0]
    print(f"Instance: {name}")

    # Setup proxy (10.0.2.2 = host machine from emulator perspective)
    proxy_host = "10.0.2.2"
    proxy_port = 8080

    print(f"\n1. Setting proxy to {proxy_host}:{proxy_port}...")
    result = pt.setup_proxy(name, proxy_host, proxy_port)
    print(f"   Global proxy: {result['global_proxy']['success']}")
    print(f"   iptables HTTP: {result['iptables_http']['success']}")
    print(f"   iptables HTTPS: {result['iptables_https']['success']}")

    # SSL bypass
    print("\n2. Injecting SSL bypass script...")
    ssl = pt.inject_frida_script(name, "ssl_bypass")
    print(f"   Script pushed: {ssl['push']}")
    print(f"   Frida running: {ssl.get('frida_running', False)}")
    if not ssl.get("frida_running"):
        print(f"   Note: {ssl.get('note', 'Install Frida server first')}")

    # Root bypass (for apps that detect root)
    print("\n3. Injecting root detection bypass...")
    root = pt.inject_frida_script(name, "root_bypass")
    print(f"   Script pushed: {root['push']}")

    print("\nInterception setup complete.")
    print(f"Configure your proxy tool to listen on port {proxy_port}.")


if __name__ == "__main__":
    main()
