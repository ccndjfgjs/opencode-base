#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
    pt.ldplayer - MCP Pentest Server v1.0
    Model Context Protocol Server para Pentesting Android via LDPlayer

    Integra LDPlayer + ADB + Frida + SSL Bypass + Root Bypass + Network Scan
    + Traffic Capture + Intent Fuzzing + Drozer-like Assessment + Spoofing
    + Proxy Setup + Cert Install + APK Analysis + Logcat + Filesystem Analysis

    Autor: ThiagoFrag
    Versao: 1.0.0
================================================================================
"""

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

# Adicionar diretorio pai ao path para imports relativos
sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_ldplayer.ld_controller import LDController
from mcp_ldplayer.pentest_toolkit import PentestToolkit

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger("pt.ldplayer.mcp")

# ============================================================================
# CONSTANTES
# ============================================================================

VERSION = "1.0.0"
SERVER_NAME = "pt-ldplayer-pentest"

# ============================================================================
# TOOL DEFINITIONS
# ============================================================================

TOOLS = [
    # === EMULATOR MANAGEMENT ===
    {
        "name": "ld_list",
        "description": "Lista todas as instancias do emulador LDPlayer com status (running/stopped), PIDs e indices.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "ld_launch",
        "description": "Inicia uma instancia do LDPlayer pelo nome.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia do emulador"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ld_quit",
        "description": "Para uma instancia do LDPlayer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ld_reboot",
        "description": "Reinicia uma instancia do LDPlayer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ld_create",
        "description": "Cria nova instancia do emulador LDPlayer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome para a nova instancia (opcional)"},
            },
        },
    },
    {
        "name": "ld_modify",
        "description": "Modifica configuracoes de uma instancia: CPU, memoria, resolucao, root, IMEI, MAC, modelo, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "cpu": {"type": "integer", "description": "Numero de CPUs (1-4)"},
                "memory": {"type": "integer", "description": "RAM em MB (512/1024/2048/4096/8192)"},
                "resolution": {"type": "string", "description": "Resolucao 'w,h,dpi' ex: '1080,1920,320'"},
                "root": {"type": "integer", "description": "1=habilitar root, 0=desabilitar"},
                "imei": {"type": "string", "description": "IMEI (ou 'auto')"},
                "mac": {"type": "string", "description": "MAC address (ou 'auto')"},
                "androidid": {"type": "string", "description": "Android ID (ou 'auto')"},
                "manufacturer": {"type": "string", "description": "Fabricante (ex: samsung)"},
                "model": {"type": "string", "description": "Modelo (ex: SM-G950F)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "ld_screenshot",
        "description": "Tira screenshot da instancia do emulador e salva localmente.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "output": {"type": "string", "description": "Caminho local para salvar (opcional)"},
            },
            "required": ["name"],
        },
    },
    # === ADB COMMANDS ===
    {
        "name": "adb_shell",
        "description": "Executa comando shell no emulador Android via ADB. Permite executar qualquer comando Linux/Android dentro do emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "command": {"type": "string", "description": "Comando shell a executar"},
                "root": {"type": "boolean", "description": "Executar como root (via su)"},
                "timeout": {"type": "integer", "description": "Timeout em segundos (default: 30)"},
            },
            "required": ["name", "command"],
        },
    },
    {
        "name": "adb_install",
        "description": "Instala APK no emulador LDPlayer.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "apk_path": {"type": "string", "description": "Caminho local do arquivo APK"},
            },
            "required": ["name", "apk_path"],
        },
    },
    {
        "name": "adb_pull",
        "description": "Puxa arquivo do emulador para maquina local.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "remote_path": {"type": "string", "description": "Caminho no emulador"},
                "local_path": {"type": "string", "description": "Caminho local destino"},
            },
            "required": ["name", "remote_path", "local_path"],
        },
    },
    {
        "name": "adb_push",
        "description": "Envia arquivo da maquina local para o emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "local_path": {"type": "string", "description": "Caminho local do arquivo"},
                "remote_path": {"type": "string", "description": "Caminho destino no emulador"},
            },
            "required": ["name", "local_path", "remote_path"],
        },
    },
    {
        "name": "adb_packages",
        "description": "Lista pacotes/apps instalados no emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "third_party_only": {"type": "boolean", "description": "Apenas apps de terceiros (default: true)"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "adb_launch_app",
        "description": "Abre um app no emulador pelo package name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package name do app (ex: com.whatsapp)"},
            },
            "required": ["name", "package"],
        },
    },
    {
        "name": "adb_kill_app",
        "description": "Fecha/mata um app no emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package name do app"},
            },
            "required": ["name", "package"],
        },
    },
    # === PENTEST - RECONNAISSANCE ===
    {
        "name": "pt_recon",
        "description": "Reconhecimento completo do dispositivo: modelo, versao Android, kernel, rede, seguranca, root status, criptografia, etc.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - NETWORK ===
    {
        "name": "pt_network_scan",
        "description": "Scan de rede do emulador: interfaces, rotas, DNS, conexoes ativas, portas abertas, tabela ARP, WiFi.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "pt_port_scan",
        "description": "Port scan a partir do emulador contra um alvo. Usa /dev/tcp (nao precisa nmap).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "target": {"type": "string", "description": "IP ou hostname alvo"},
                "ports": {"type": "string", "description": "Range de portas: '1-1024' ou '80,443,8080'"},
            },
            "required": ["name", "target"],
        },
    },
    # === PENTEST - APK ANALYSIS ===
    {
        "name": "pt_apk_analyze",
        "description": "Analise profunda de APK: permissoes, activities exportadas, services, receivers, providers, risco, versao, SDK.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package name do app a analisar"},
            },
            "required": ["name", "package"],
        },
    },
    {
        "name": "pt_apk_extract",
        "description": "Extrai APK do emulador para disco local (para analise com jadx, apktool, etc).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package name do app"},
                "output_dir": {"type": "string", "description": "Diretorio local para salvar (default: temp)"},
            },
            "required": ["name", "package"],
        },
    },
    # === PENTEST - TRAFFIC ===
    {
        "name": "pt_traffic_start",
        "description": "Inicia captura de trafego de rede (tcpdump) no emulador. Salva pcap para analise no Wireshark.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "filter": {"type": "string", "description": "Filtro tcpdump (ex: 'port 443', 'host 10.0.0.1')"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "pt_traffic_stop",
        "description": "Para captura de trafego e baixa o arquivo pcap para analise local.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "output": {"type": "string", "description": "Caminho local para salvar pcap (opcional)"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - PROXY ===
    {
        "name": "pt_proxy_setup",
        "description": "Configura proxy (Burp Suite/mitmproxy/ZAP OWASP) no emulador para interceptacao de trafego HTTP/HTTPS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "host": {"type": "string", "description": "IP do proxy (ex: 10.0.2.2 para host)"},
                "port": {"type": "integer", "description": "Porta do proxy (ex: 8080)"},
            },
            "required": ["name", "host", "port"],
        },
    },
    {
        "name": "pt_proxy_remove",
        "description": "Remove configuracao de proxy do emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - FRIDA INJECTION ===
    {
        "name": "pt_frida_inject",
        "description": "Injeta scripts Frida no emulador. Scripts: ssl_bypass, root_bypass, keylogger, crypto_hook, network_hook, anti_debug.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "script": {
                    "type": "string",
                    "description": "Script a injetar: ssl_bypass | root_bypass | keylogger | crypto_hook | network_hook | anti_debug",
                    "enum": ["ssl_bypass", "root_bypass", "keylogger", "crypto_hook", "network_hook", "anti_debug"],
                },
                "target_package": {"type": "string", "description": "Package do app alvo (opcional)"},
            },
            "required": ["name", "script"],
        },
    },
    {
        "name": "pt_frida_custom",
        "description": "Injeta script Frida customizado (conteudo JavaScript) no emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "script_content": {"type": "string", "description": "Conteudo JavaScript do script Frida"},
                "target_package": {"type": "string", "description": "Package do app alvo (opcional)"},
            },
            "required": ["name", "script_content"],
        },
    },
    # === PENTEST - SSL/ROOT BYPASS ===
    {
        "name": "pt_ssl_bypass",
        "description": "Aplica bypass de SSL Pinning via Frida (OkHttp3, TrustManager, WebView, Conscrypt). Permite interceptar HTTPS.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "target_package": {"type": "string", "description": "Package do app alvo"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "pt_root_bypass",
        "description": "Aplica bypass de Root Detection via Frida (File.exists, Runtime.exec, Build.TAGS, SystemProperties).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "target_package": {"type": "string", "description": "Package do app alvo"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - CERTIFICATE ===
    {
        "name": "pt_cert_install",
        "description": "Instala certificado CA customizado no sistema do emulador para interceptar HTTPS (Burp/mitmproxy CA).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "cert_path": {"type": "string", "description": "Caminho local do certificado PEM"},
            },
            "required": ["name", "cert_path"],
        },
    },
    {
        "name": "pt_cert_list",
        "description": "Lista certificados CA instalados no sistema do emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - INTENT FUZZING ===
    {
        "name": "pt_intent_fuzz",
        "description": "Fuzzing de Intents Android: testa activities exportadas com payloads de XSS, SQLi, path traversal, buffer overflow.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package do app alvo"},
                "activity": {"type": "string", "description": "Activity especifica (opcional, se vazio testa todas exportadas)"},
            },
            "required": ["name", "package"],
        },
    },
    # === PENTEST - DEEP LINKS ===
    {
        "name": "pt_deeplink_test",
        "description": "Testa deep links de um app: extrai URI schemes do manifest e testa cada um.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package do app alvo"},
                "uris": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de URIs para testar (opcional, se vazio extrai do manifest)",
                },
            },
            "required": ["name", "package"],
        },
    },
    # === PENTEST - DEVICE SPOOFING ===
    {
        "name": "pt_spoof_device",
        "description": "Altera identidade do emulador (IMEI, MAC, AndroidID, modelo). Perfis: random, samsung, pixel, xiaomi, huawei, oneplus.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "profile": {
                    "type": "string",
                    "description": "Perfil de device: random | samsung | pixel | xiaomi | huawei | oneplus",
                    "enum": ["random", "samsung", "pixel", "xiaomi", "huawei", "oneplus"],
                },
            },
            "required": ["name"],
        },
    },
    # === PENTEST - SECURITY ASSESSMENT ===
    {
        "name": "pt_security_assessment",
        "description": "Avaliacao de seguranca estilo Drozer: attack surface, exported components, world-readable files, SharedPrefs sensiveis, SQLite, backup, native libs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package do app a avaliar"},
            },
            "required": ["name", "package"],
        },
    },
    # === PENTEST - LOGCAT ===
    {
        "name": "pt_logcat",
        "description": "Captura e analisa logs do emulador. Detecta vazamento de dados sensiveis (passwords, tokens, keys) nos logs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Filtrar por package (opcional)"},
                "lines": {"type": "integer", "description": "Numero de linhas (default: 100)"},
                "level": {"type": "string", "description": "Nivel minimo: V|D|I|W|E (opcional)"},
            },
            "required": ["name"],
        },
    },
    # === PENTEST - FILESYSTEM ===
    {
        "name": "pt_filesystem",
        "description": "Analise do filesystem de um app: arquivos, databases, SharedPrefs, libs nativas, caches, permissoes abertas.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "package": {"type": "string", "description": "Package do app"},
            },
            "required": ["name", "package"],
        },
    },
    # === GPS SPOOF ===
    {
        "name": "pt_gps_spoof",
        "description": "Define localizacao GPS falsa no emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "latitude": {"type": "number", "description": "Latitude (ex: -23.5505)"},
                "longitude": {"type": "number", "description": "Longitude (ex: -46.6333)"},
            },
            "required": ["name", "latitude", "longitude"],
        },
    },
    # === BACKUP ===
    {
        "name": "ld_backup",
        "description": "Faz backup completo de uma instancia do emulador.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "filepath": {"type": "string", "description": "Caminho para salvar o backup"},
            },
            "required": ["name", "filepath"],
        },
    },
    {
        "name": "ld_restore",
        "description": "Restaura backup de uma instancia.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Nome da instancia"},
                "filepath": {"type": "string", "description": "Caminho do arquivo de backup"},
            },
            "required": ["name", "filepath"],
        },
    },
]


# ============================================================================
# MCP SERVER
# ============================================================================


class PentestMCPServer:
    """Servidor MCP para pentesting Android via LDPlayer."""

    def __init__(self, ldplayer_path: Optional[str] = None):
        self.ld: Optional[LDController] = None
        self.pt: Optional[PentestToolkit] = None
        self.initialized = False
        try:
            self.ld = LDController(ldplayer_path)
            self.pt = PentestToolkit(self.ld)
            self.initialized = True
            logger.info(f"LDPlayer controller inicializado: {self.ld.base_path}")
        except FileNotFoundError as e:
            logger.error(f"LDPlayer nao encontrado: {e}")

        self.running = True

    def _text_result(self, request_id, data: Any) -> Dict:
        """Retorna resultado MCP com texto."""
        if isinstance(data, (dict, list)):
            text = json.dumps(data, indent=2, ensure_ascii=False, default=str)
        else:
            text = str(data)
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": text}],
            },
        }

    def _error_result(self, request_id, message: str, code: int = -32603) -> Dict:
        """Retorna erro MCP."""
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def _adb_to_dict(self, result) -> Dict:
        """Converte ADBResult para dict."""
        return {
            "success": result.success,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_ms": result.elapsed_ms,
        }

    # ========================================================================
    # REQUEST HANDLING
    # ========================================================================

    async def handle_request(self, request: Dict) -> Optional[Dict]:
        """Processa requisicao MCP."""
        method = request.get("method", "")
        params = request.get("params", {})
        request_id = request.get("id")

        logger.info(f"[REQ] {method}")

        try:
            if method == "initialize":
                return self._handle_initialize(request_id)
            elif method == "initialized":
                return None
            elif method == "shutdown":
                self.running = False
                return {"jsonrpc": "2.0", "id": request_id, "result": None}
            elif method == "tools/list":
                return self._handle_tools_list(request_id)
            elif method == "tools/call":
                return await self._handle_tool_call(request_id, params)
            elif method == "resources/list":
                return self._handle_resources_list(request_id)
            elif method == "resources/read":
                return self._handle_resource_read(request_id, params)
            elif method == "prompts/list":
                return self._handle_prompts_list(request_id)
            else:
                return self._error_result(request_id, f"Metodo desconhecido: {method}", -32601)
        except Exception as e:
            logger.error(f"Erro em {method}: {e}", exc_info=True)
            return self._error_result(request_id, str(e))

    def _handle_initialize(self, request_id) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": SERVER_NAME, "version": VERSION},
                "capabilities": {
                    "tools": {"listChanged": True},
                    "resources": {"subscribe": False, "listChanged": True},
                    "prompts": {"listChanged": True},
                },
            },
        }

    def _handle_tools_list(self, request_id) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {"tools": TOOLS},
        }

    async def _handle_tool_call(self, request_id, params: Dict) -> Dict:
        """Dispatch de chamadas de ferramentas."""
        tool = params.get("name", "")
        args = params.get("arguments", {})

        if not self.initialized:
            return self._text_result(request_id, {
                "error": "LDPlayer nao encontrado no sistema.",
                "hint": "Instale LDPlayer ou informe o caminho via --ldplayer-path",
            })

        try:
            result = await self._dispatch_tool(tool, args)
            return self._text_result(request_id, result)
        except Exception as e:
            logger.error(f"Erro na tool {tool}: {e}", exc_info=True)
            return self._text_result(request_id, {"error": str(e), "tool": tool})

    async def _dispatch_tool(self, tool: str, args: Dict) -> Any:
        """Executa a ferramenta correspondente."""
        name = args.get("name", "")

        # === EMULATOR MANAGEMENT ===
        if tool == "ld_list":
            instances = self.ld.list_instances()
            running = self.ld.running_instances()
            return {
                "instances": [
                    {"index": i.index, "name": i.name, "status": i.status, "pid": i.pid}
                    for i in instances
                ],
                "running": running,
                "total": len(instances),
            }

        elif tool == "ld_launch":
            r = self.ld.launch(name)
            return {"action": "launch", "instance": name, **self._adb_to_dict(r)}

        elif tool == "ld_quit":
            r = self.ld.quit(name)
            return {"action": "quit", "instance": name, **self._adb_to_dict(r)}

        elif tool == "ld_reboot":
            r = self.ld.reboot(name)
            return {"action": "reboot", "instance": name, **self._adb_to_dict(r)}

        elif tool == "ld_create":
            r = self.ld.create_instance(name or None)
            return {"action": "create", **self._adb_to_dict(r)}

        elif tool == "ld_modify":
            kwargs = {k: v for k, v in args.items() if k != "name" and v is not None}
            r = self.ld.modify_instance(name, **kwargs)
            return {"action": "modify", "instance": name, "settings": kwargs, **self._adb_to_dict(r)}

        elif tool == "ld_screenshot":
            output = args.get("output", os.path.join(tempfile.gettempdir(), f"ldplayer_{name}_screenshot.png"))
            r = self.ld.screenshot(name, output)
            return {"action": "screenshot", "file": output, **self._adb_to_dict(r)}

        # === ADB COMMANDS ===
        elif tool == "adb_shell":
            cmd = args.get("command", "")
            is_root = args.get("root", False)
            timeout = args.get("timeout", 30)
            if is_root:
                r = self.ld.shell_root(name, cmd, timeout)
            else:
                r = self.ld.shell(name, cmd, timeout)
            return self._adb_to_dict(r)

        elif tool == "adb_install":
            r = self.ld.install_apk(name, args.get("apk_path", ""))
            return {"action": "install", **self._adb_to_dict(r)}

        elif tool == "adb_pull":
            r = self.ld.pull(name, args.get("remote_path", ""), args.get("local_path", ""))
            return {"action": "pull", **self._adb_to_dict(r)}

        elif tool == "adb_push":
            r = self.ld.push(name, args.get("local_path", ""), args.get("remote_path", ""))
            return {"action": "push", **self._adb_to_dict(r)}

        elif tool == "adb_packages":
            third = args.get("third_party_only", True)
            packages = self.pt.list_packages(name, third)
            return {"packages": packages, "count": len(packages), "third_party_only": third}

        elif tool == "adb_launch_app":
            r = self.ld.launch_app(name, args.get("package", ""))
            return {"action": "launch_app", **self._adb_to_dict(r)}

        elif tool == "adb_kill_app":
            r = self.ld.kill_app(name, args.get("package", ""))
            return {"action": "kill_app", **self._adb_to_dict(r)}

        # === PENTEST TOOLS ===
        elif tool == "pt_recon":
            return self.pt.device_recon(name)

        elif tool == "pt_network_scan":
            return self.pt.network_scan(name)

        elif tool == "pt_port_scan":
            return self.pt.port_scan(name, args.get("target", ""), args.get("ports", "1-1024"))

        elif tool == "pt_apk_analyze":
            return self.pt.analyze_package(name, args.get("package", ""))

        elif tool == "pt_apk_extract":
            output_dir = args.get("output_dir", tempfile.gettempdir())
            r = self.pt.extract_apk(name, args.get("package", ""), output_dir)
            return {"action": "extract", "output_dir": output_dir, **self._adb_to_dict(r)}

        elif tool == "pt_traffic_start":
            filt = args.get("filter", "")
            r = self.pt.start_traffic_capture(name, filter_expr=filt)
            return {"action": "traffic_start", "filter": filt, **self._adb_to_dict(r)}

        elif tool == "pt_traffic_stop":
            self.pt.stop_traffic_capture(name)
            output = args.get("output", os.path.join(tempfile.gettempdir(), "capture.pcap"))
            r = self.pt.download_capture(name, local_file=output)
            return {"action": "traffic_stop", "pcap_file": output, **self._adb_to_dict(r)}

        elif tool == "pt_proxy_setup":
            return self.pt.setup_proxy(name, args.get("host", ""), args.get("port", 8080))

        elif tool == "pt_proxy_remove":
            return self.pt.remove_proxy(name)

        elif tool == "pt_frida_inject":
            return self.pt.inject_frida_script(
                name, args.get("script", ""), args.get("target_package", "")
            )

        elif tool == "pt_frida_custom":
            return self.pt.inject_custom_frida(
                name, args.get("script_content", ""), args.get("target_package", "")
            )

        elif tool == "pt_ssl_bypass":
            return self.pt.inject_frida_script(name, "ssl_bypass", args.get("target_package", ""))

        elif tool == "pt_root_bypass":
            return self.pt.inject_frida_script(name, "root_bypass", args.get("target_package", ""))

        elif tool == "pt_cert_install":
            return self.pt.install_ca_cert(name, args.get("cert_path", ""))

        elif tool == "pt_cert_list":
            certs = self.pt.list_ca_certs(name)
            return {"certificates": certs, "count": len(certs)}

        elif tool == "pt_intent_fuzz":
            return self.pt.fuzz_intents(name, args.get("package", ""), args.get("activity", ""))

        elif tool == "pt_deeplink_test":
            return self.pt.test_deeplinks(name, args.get("package", ""), args.get("uris"))

        elif tool == "pt_spoof_device":
            return self.pt.spoof_device(name, args.get("profile", "random"))

        elif tool == "pt_security_assessment":
            return self.pt.security_assessment(name, args.get("package", ""))

        elif tool == "pt_logcat":
            return self.pt.logcat_capture(
                name,
                args.get("package", ""),
                args.get("lines", 100),
                args.get("level", ""),
            )

        elif tool == "pt_filesystem":
            return self.pt.analyze_filesystem(name, args.get("package", ""))

        elif tool == "pt_gps_spoof":
            r = self.ld.set_gps(name, args.get("longitude", 0), args.get("latitude", 0))
            return {
                "action": "gps_spoof",
                "latitude": args.get("latitude"),
                "longitude": args.get("longitude"),
                **self._adb_to_dict(r),
            }

        elif tool == "ld_backup":
            r = self.ld.backup(name, args.get("filepath", ""))
            return {"action": "backup", **self._adb_to_dict(r)}

        elif tool == "ld_restore":
            r = self.ld.restore(name, args.get("filepath", ""))
            return {"action": "restore", **self._adb_to_dict(r)}

        else:
            return {"error": f"Tool desconhecida: {tool}", "available": [t["name"] for t in TOOLS]}

    # ========================================================================
    # RESOURCES
    # ========================================================================

    def _handle_resources_list(self, request_id) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "resources": [
                    {
                        "uri": "pt-ldplayer://status",
                        "name": "Server Status",
                        "description": "Status do servidor, LDPlayer e instancias",
                        "mimeType": "application/json",
                    },
                    {
                        "uri": "pt-ldplayer://frida-scripts",
                        "name": "Frida Scripts Library",
                        "description": "Biblioteca de scripts Frida embutidos",
                        "mimeType": "application/json",
                    },
                ],
            },
        }

    def _handle_resource_read(self, request_id, params: Dict) -> Dict:
        uri = params.get("uri", "")

        if uri == "pt-ldplayer://status":
            instances = self.ld.list_instances() if self.initialized else []
            data = {
                "server": SERVER_NAME,
                "version": VERSION,
                "ldplayer_path": str(self.ld.base_path) if self.ld else None,
                "initialized": self.initialized,
                "instances": [
                    {"index": i.index, "name": i.name, "status": i.status}
                    for i in instances
                ],
                "tools_count": len(TOOLS),
            }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps(data, indent=2),
                    }],
                },
            }

        elif uri == "pt-ldplayer://frida-scripts":
            scripts = {}
            if self.pt:
                scripts = {k: v[:200] + "..." for k, v in self.pt.frida_scripts.items()}
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "contents": [{
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"scripts": list(scripts.keys()), "previews": scripts}, indent=2),
                    }],
                },
            }

        return self._error_result(request_id, f"Resource nao encontrado: {uri}", -32602)

    # ========================================================================
    # PROMPTS
    # ========================================================================

    def _handle_prompts_list(self, request_id) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "prompts": [
                    {
                        "name": "pentest_app",
                        "description": "Executa pentest completo em um app Android: recon, analise de APK, security assessment, intent fuzzing, deeplink test",
                        "arguments": [
                            {"name": "instance", "description": "Nome da instancia LDPlayer", "required": True},
                            {"name": "package", "description": "Package name do app alvo", "required": True},
                        ],
                    },
                    {
                        "name": "setup_intercept",
                        "description": "Configura ambiente completo de interceptacao: proxy, certificado CA, SSL bypass",
                        "arguments": [
                            {"name": "instance", "description": "Nome da instancia LDPlayer", "required": True},
                            {"name": "proxy_host", "description": "IP do proxy", "required": True},
                            {"name": "proxy_port", "description": "Porta do proxy", "required": True},
                        ],
                    },
                    {
                        "name": "stealth_mode",
                        "description": "Configura emulador em modo stealth: spoof device, root bypass, anti-debug bypass",
                        "arguments": [
                            {"name": "instance", "description": "Nome da instancia LDPlayer", "required": True},
                            {"name": "profile", "description": "Perfil de device (samsung/pixel/xiaomi)", "required": False},
                        ],
                    },
                ],
            },
        }

    # ========================================================================
    # STDIO LOOP
    # ========================================================================

    async def run_stdio(self):
        """Loop principal stdin/stdout."""
        logger.info(f"pt.ldplayer MCP Server v{VERSION} iniciado")
        if self.initialized:
            logger.info(f"LDPlayer: {self.ld.base_path}")
            instances = self.ld.list_instances()
            logger.info(f"Instancias: {len(instances)}")
        logger.info(f"Tools: {len(TOOLS)}")

        while self.running:
            try:
                line = await asyncio.get_event_loop().run_in_executor(
                    None, sys.stdin.readline
                )
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    request = json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON invalido: {e}")
                    continue

                response = await self.handle_request(request)
                if response:
                    print(json.dumps(response), flush=True)

            except Exception as e:
                logger.error(f"Erro no loop: {e}", exc_info=True)
                break

        logger.info("Servidor encerrado")


# ============================================================================
# ENTRY POINT
# ============================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="pt.ldplayer - MCP Pentest Server")
    parser.add_argument("--ldplayer-path", type=str, help="Caminho do LDPlayer (auto-detecta se omitido)")
    parser.add_argument("--list-tools", action="store_true", help="Lista ferramentas disponiveis e sai")
    args = parser.parse_args()

    if args.list_tools:
        print(f"\npt.ldplayer MCP Server v{VERSION}")
        print(f"{'='*60}")
        print(f"Total: {len(TOOLS)} ferramentas\n")
        categories = {}
        for t in TOOLS:
            prefix = t["name"].split("_")[0]
            if prefix not in categories:
                categories[prefix] = []
            categories[prefix].append(t)

        for cat, tools in categories.items():
            print(f"[{cat.upper()}]")
            for t in tools:
                print(f"  {t['name']:30s} {t['description'][:60]}")
            print()
        return

    server = PentestMCPServer(args.ldplayer_path)
    asyncio.run(server.run_stdio())


if __name__ == "__main__":
    main()
