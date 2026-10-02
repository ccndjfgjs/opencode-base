# mcp-ldplayer

**MCP Server for Android Pentesting via LDPlayer Emulator**

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP Protocol](https://img.shields.io/badge/MCP-2024--11--05-purple.svg)](https://modelcontextprotocol.io/)

---

## What is this?

A [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that turns LDPlayer Android emulator into a full pentesting workstation. It exposes **38 tools** that AI assistants (Claude, Copilot, etc.) can call to control emulators, run ADB commands, and execute Android security assessments — all through natural language.

**Zero external dependencies.** Pure Python 3.10+ standard library. Just install and run.

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    AI Assistant (Claude, Copilot)         │
│                         ▼ MCP Protocol (stdio)           │
├──────────────────────────────────────────────────────────┤
│                    mcp-ldplayer Server                    │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ LD Controller│  │Pentest Toolkit│  │  Frida Scripts │  │
│  │  (ldconsole) │  │  (22 tools)  │  │  (6 built-in)  │  │
│  └──────┬───────┘  └──────┬───────┘  └────────────────┘  │
│         │                 │                               │
│         ▼                 ▼                               │
│  ┌─────────────────────────────┐                         │
│  │    LDPlayer 9 (ldconsole)   │                         │
│  │         + ADB 34.x          │                         │
│  └──────────┬──────────────────┘                         │
│             ▼                                            │
│  ┌─────────────────────────────┐                         │
│  │   Android Emulator Instance │                         │
│  │   (ARM/x86, rooted, ADB)   │                         │
│  └─────────────────────────────┘                         │
└──────────────────────────────────────────────────────────┘
```

---

## Features

### Emulator Management (9 tools)
| Tool | Description |
|------|-------------|
| `ld_list` | List all emulator instances with status/PID |
| `ld_launch` | Start an instance |
| `ld_quit` | Stop an instance |
| `ld_reboot` | Restart an instance |
| `ld_create` | Create new instance |
| `ld_modify` | Change CPU, memory, resolution, root, identity |
| `ld_screenshot` | Capture screenshot |
| `ld_backup` | Full instance backup |
| `ld_restore` | Restore backup |

### ADB Commands (7 tools)
| Tool | Description |
|------|-------------|
| `adb_shell` | Execute any shell command (with optional root) |
| `adb_install` | Install APK |
| `adb_pull` | Pull file from emulator |
| `adb_push` | Push file to emulator |
| `adb_packages` | List installed packages |
| `adb_launch_app` | Open app by package name |
| `adb_kill_app` | Kill running app |

### Pentest Arsenal (22 tools)
| Tool | Description |
|------|-------------|
| `pt_recon` | Full device reconnaissance (30+ properties) |
| `pt_network_scan` | Network scan: interfaces, routes, DNS, connections, ports |
| `pt_port_scan` | Port scan from emulator (no nmap needed) |
| `pt_apk_analyze` | Deep APK analysis: permissions, components, risk score |
| `pt_apk_extract` | Extract APK for local analysis (jadx, apktool) |
| `pt_traffic_start` | Start packet capture (tcpdump → pcap) |
| `pt_traffic_stop` | Stop capture and download pcap |
| `pt_proxy_setup` | Configure proxy (Burp/mitmproxy/ZAP) with iptables |
| `pt_proxy_remove` | Remove proxy config |
| `pt_frida_inject` | Inject built-in Frida scripts |
| `pt_frida_custom` | Inject custom JavaScript Frida scripts |
| `pt_ssl_bypass` | SSL Pinning bypass (OkHttp3, TrustManager, WebView, Conscrypt) |
| `pt_root_bypass` | Root detection bypass (File.exists, Runtime.exec, Build.TAGS) |
| `pt_cert_install` | Install CA certificate in system trust store |
| `pt_cert_list` | List installed CA certificates |
| `pt_intent_fuzz` | Intent fuzzing with XSS, SQLi, path traversal payloads |
| `pt_deeplink_test` | Test deep links extracted from manifest |
| `pt_spoof_device` | Spoof identity (samsung/pixel/xiaomi/huawei/oneplus) |
| `pt_security_assessment` | Drozer-style security audit |
| `pt_logcat` | Log capture with sensitive data detection |
| `pt_filesystem` | App filesystem analysis (root) |
| `pt_gps_spoof` | GPS location spoofing |

### Built-in Frida Scripts
| Script | What it does |
|--------|-------------|
| `ssl_bypass` | Bypass SSL pinning (TrustManager, OkHttp3, WebView, Conscrypt) |
| `root_bypass` | Bypass root detection (su checks, Build.TAGS, SystemProperties) |
| `keylogger` | Monitor all EditText input events |
| `crypto_hook` | Intercept Cipher encrypt/decrypt + SharedPreferences reads |
| `network_hook` | Monitor OkHttp3 requests and URL.openConnection |
| `anti_debug` | Bypass Debug.isDebuggerConnected and TracerPid checks |

---

## Installation

### Prerequisites
- **Python 3.10+**
- **LDPlayer 9** installed (auto-detected at common paths)
- **Windows** (LDPlayer is Windows-only)

### Setup

```bash
# Clone
git clone https://github.com/ThiagoFrag/mcp-ldplayer.git
cd mcp-ldplayer

# Install (optional, can run directly)
pip install -e .
```

### Configure in VS Code

Add to your `.vscode/mcp.json`:

```json
{
    "mcpServers": {
        "pt-ldplayer": {
            "command": "python",
            "args": ["path/to/mcp-ldplayer/mcp_ldplayer/mcp_server.py"]
        }
    }
}
```

Or if installed via pip:

```json
{
    "mcpServers": {
        "pt-ldplayer": {
            "command": "mcp-ldplayer"
        }
    }
}
```

### Configure in Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
    "mcpServers": {
        "pt-ldplayer": {
            "command": "python",
            "args": ["C:/path/to/mcp-ldplayer/mcp_ldplayer/mcp_server.py"]
        }
    }
}
```

---

## Usage

### Via AI Assistant

Once configured, just ask naturally:

> "List my LDPlayer instances"

> "Run a full security assessment on com.example.app"

> "Set up Burp Suite proxy on 10.0.2.2:8080 with SSL bypass"

> "Spoof this emulator as a Samsung Galaxy S21"

> "Capture network traffic for 60 seconds and download the pcap"

> "Fuzz all exported intents of com.target.app"

### Via CLI

```bash
# List all 38 tools
python -m mcp_ldplayer.mcp_server --list-tools

# Run as MCP server (stdio)
python -m mcp_ldplayer.mcp_server

# Specify LDPlayer path manually
python -m mcp_ldplayer.mcp_server --ldplayer-path "D:\LDPlayer\LDPlayer9"
```

### Via Python

```python
from mcp_ldplayer import LDController, PentestToolkit

# Auto-detect LDPlayer
ld = LDController()

# List instances
for instance in ld.list_instances():
    print(f"{instance.name}: {instance.status}")

# Pentest toolkit
pt = PentestToolkit(ld)

# Device reconnaissance
recon = pt.device_recon("LDPlayer")

# Security assessment
audit = pt.security_assessment("LDPlayer", "com.target.app")

# SSL bypass
bypass = pt.inject_frida_script("LDPlayer", "ssl_bypass", "com.target.app")
```

---

## Pentest Workflows

### Full App Assessment
```
1. pt_recon          → Device info + security posture
2. pt_apk_analyze    → Permissions, components, risk
3. pt_security_assessment → Drozer-style audit
4. pt_intent_fuzz    → Test exported activities
5. pt_deeplink_test  → Test URI schemes
6. pt_logcat         → Check for sensitive data leaks
7. pt_filesystem     → Analyze app data directory
```

### Traffic Interception
```
1. pt_proxy_setup    → Configure Burp/mitmproxy
2. pt_cert_install   → Install CA cert in system store
3. pt_ssl_bypass     → Bypass SSL pinning
4. pt_traffic_start  → Start packet capture
5. [interact with app]
6. pt_traffic_stop   → Download pcap for Wireshark
```

### Stealth Mode
```
1. pt_spoof_device   → Change IMEI, MAC, model
2. pt_root_bypass    → Hide root from apps
3. pt_gps_spoof      → Fake location
4. pt_frida_inject anti_debug → Bypass debugger detection
```

---

## MCP Resources

| URI | Description |
|-----|-------------|
| `pt-ldplayer://status` | Server status, LDPlayer path, instances |
| `pt-ldplayer://frida-scripts` | Available Frida scripts with previews |

## MCP Prompts

| Prompt | Description |
|--------|-------------|
| `pentest_app` | Full pentest workflow for an app |
| `setup_intercept` | Configure interception environment |
| `stealth_mode` | Configure emulator stealth |

---

## Project Structure

```
mcp-ldplayer/
├── mcp_ldplayer/
│   ├── __init__.py          # Package exports
│   ├── ld_controller.py     # LDPlayer interface (ldconsole + ADB)
│   ├── pentest_toolkit.py   # Pentest arsenal (22 tools)
│   └── mcp_server.py        # MCP protocol server (38 tools)
├── frida_scripts/
│   ├── ssl_bypass.js        # SSL Pinning bypass
│   ├── root_bypass.js       # Root detection bypass
│   ├── keylogger.js         # Input monitoring
│   ├── crypto_hook.js       # Crypto + SharedPrefs interception
│   ├── network_hook.js      # HTTP/HTTPS monitoring
│   └── anti_debug.js        # Anti-debug bypass
├── examples/
│   ├── quick_test.py        # Quick connectivity test
│   ├── pentest_workflow.py  # Full pentest example
│   └── intercept_setup.py   # Traffic interception setup
├── tests/
│   ├── test_controller.py   # LDController unit tests
│   ├── test_toolkit.py      # PentestToolkit unit tests
│   └── test_mcp_protocol.py # MCP protocol compliance tests
├── pyproject.toml
├── requirements.txt
├── LICENSE
└── README.md
```

---

## LDPlayer Path Auto-Detection

The server searches these paths in order:

1. `C:\LDPlayer\LDPlayer9`
2. `C:\LDPlayer\LDPlayer4.0`
3. `C:\Program Files\LDPlayer\LDPlayer9`
4. `C:\Program Files (x86)\LDPlayer\LDPlayer9`
5. `%LOCALAPPDATA%\LDPlayer\LDPlayer9`
6. `D:\LDPlayer\LDPlayer9`

Override with `--ldplayer-path` if installed elsewhere.

---

## Protocol Compliance

Tested against MCP specification `2024-11-05`:

| Test | Status |
|------|--------|
| `initialize` handshake | OK |
| `tools/list` (38 tools) | OK |
| `resources/list` (2 resources) | OK |
| `prompts/list` (3 prompts) | OK |
| `resources/read` (both URIs) | OK |
| `tools/call` dispatch | OK |
| Error handling (-32601, -32603) | OK |
| Unknown method rejection | OK |
| CLI `--list-tools` | OK |

---

## Security Notice

This tool is designed for **authorized security testing only**. Use responsibly and only on systems you have permission to test. The authors are not responsible for misuse.

---

## License

[MIT](LICENSE)

---

## Author

**ThiagoFrag** - [GitHub](https://github.com/ThiagoFrag)
