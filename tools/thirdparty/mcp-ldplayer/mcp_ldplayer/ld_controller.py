#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
    pt.ldplayer - LDPlayer Controller
    Interface de controle para emulador Android LDPlayer via ldconsole/ADB

    Gerencia instancias, executa comandos ADB, controla estado do emulador.
================================================================================
"""

import logging
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("pt.ldplayer.controller")

# ============================================================================
# AUTO-DETECT LDPLAYER
# ============================================================================

LDPLAYER_SEARCH_PATHS = [
    r"C:\LDPlayer\LDPlayer9",
    r"C:\LDPlayer\LDPlayer4.0",
    r"C:\Program Files\LDPlayer\LDPlayer9",
    r"C:\Program Files (x86)\LDPlayer\LDPlayer9",
    os.path.expandvars(r"%LOCALAPPDATA%\LDPlayer\LDPlayer9"),
    r"D:\LDPlayer\LDPlayer9",
]


def find_ldplayer() -> Optional[Path]:
    """Auto-detecta instalacao do LDPlayer."""
    for p in LDPLAYER_SEARCH_PATHS:
        path = Path(p)
        if path.exists() and (path / "ldconsole.exe").exists():
            return path
    return None


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class EmulatorInstance:
    """Representa uma instancia de emulador."""
    index: int
    name: str
    status: str = "unknown"
    pid: int = 0
    properties: Dict[str, str] = field(default_factory=dict)


@dataclass
class ADBResult:
    """Resultado de comando ADB."""
    success: bool
    stdout: str
    stderr: str
    returncode: int
    command: str
    elapsed_ms: int = 0


@dataclass
class PackageInfo:
    """Info de um pacote Android."""
    package_name: str
    version: str = ""
    apk_path: str = ""
    permissions: List[str] = field(default_factory=list)
    activities: List[str] = field(default_factory=list)
    services: List[str] = field(default_factory=list)
    receivers: List[str] = field(default_factory=list)
    providers: List[str] = field(default_factory=list)


# ============================================================================
# LDPLAYER CONTROLLER
# ============================================================================


class LDController:
    """Controlador principal do LDPlayer via ldconsole + ADB."""

    def __init__(self, ldplayer_path: Optional[str] = None):
        if ldplayer_path:
            self.base_path = Path(ldplayer_path)
        else:
            detected = find_ldplayer()
            if not detected:
                raise FileNotFoundError(
                    "LDPlayer nao encontrado. Instale ou informe o caminho."
                )
            self.base_path = detected

        self.ldconsole = self.base_path / "ldconsole.exe"
        self.adb = self.base_path / "adb.exe"

        if not self.ldconsole.exists():
            raise FileNotFoundError(f"ldconsole.exe nao encontrado em {self.base_path}")

        logger.info(f"LDPlayer detectado: {self.base_path}")

    # ========================================================================
    # EXECUCAO DE COMANDOS
    # ========================================================================

    def _run_ld(self, *args, timeout: int = 30) -> ADBResult:
        """Executa comando ldconsole."""
        cmd = [str(self.ldconsole)] + list(args)
        return self._execute(cmd, timeout)

    def _run_adb(self, *args, timeout: int = 30) -> ADBResult:
        """Executa comando ADB direto."""
        cmd = [str(self.adb)] + list(args)
        return self._execute(cmd, timeout)

    def _run_ld_adb(self, instance: str, adb_cmd: str, timeout: int = 30) -> ADBResult:
        """Executa comando ADB via ldconsole em instancia especifica."""
        cmd = [
            str(self.ldconsole), "adb",
            "--name", instance,
            "--command", adb_cmd,
        ]
        return self._execute(cmd, timeout)

    def _execute(self, cmd: List[str], timeout: int = 30) -> ADBResult:
        """Executa comando e retorna resultado estruturado."""
        cmd_str = " ".join(cmd)
        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = int((time.time() - start) * 1000)
            return ADBResult(
                success=proc.returncode == 0,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                returncode=proc.returncode,
                command=cmd_str,
                elapsed_ms=elapsed,
            )
        except subprocess.TimeoutExpired:
            elapsed = int((time.time() - start) * 1000)
            return ADBResult(
                success=False,
                stdout="",
                stderr=f"Timeout apos {timeout}s",
                returncode=-1,
                command=cmd_str,
                elapsed_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            return ADBResult(
                success=False,
                stdout="",
                stderr=str(e),
                returncode=-1,
                command=cmd_str,
                elapsed_ms=elapsed,
            )

    # ========================================================================
    # GERENCIAMENTO DE INSTANCIAS
    # ========================================================================

    def list_instances(self) -> List[EmulatorInstance]:
        """Lista todas as instancias do LDPlayer."""
        result = self._run_ld("list2")
        instances = []
        if result.success and result.stdout:
            for line in result.stdout.strip().split("\n"):
                parts = line.strip().split(",")
                if len(parts) >= 3:
                    instances.append(EmulatorInstance(
                        index=int(parts[0]) if parts[0].isdigit() else 0,
                        name=parts[1],
                        status="running" if len(parts) > 2 and parts[2] != "0" else "stopped",
                        pid=int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
                    ))
        return instances

    def running_instances(self) -> List[str]:
        """Lista instancias em execucao."""
        result = self._run_ld("runninglist")
        if result.success and result.stdout:
            return [n.strip() for n in result.stdout.strip().split("\n") if n.strip()]
        return []

    def is_running(self, name: str) -> bool:
        """Verifica se instancia esta rodando."""
        result = self._run_ld("isrunning", "--name", name)
        return result.success and "running" in result.stdout.lower()

    def launch(self, name: str) -> ADBResult:
        """Inicia uma instancia."""
        return self._run_ld("launch", "--name", name)

    def quit(self, name: str) -> ADBResult:
        """Para uma instancia."""
        return self._run_ld("quit", "--name", name)

    def quit_all(self) -> ADBResult:
        """Para todas as instancias."""
        return self._run_ld("quitall")

    def reboot(self, name: str) -> ADBResult:
        """Reinicia uma instancia."""
        return self._run_ld("reboot", "--name", name)

    def create_instance(self, name: Optional[str] = None) -> ADBResult:
        """Cria nova instancia."""
        args = ["add"]
        if name:
            args.extend(["--name", name])
        return self._run_ld(*args)

    def remove_instance(self, name: str) -> ADBResult:
        """Remove uma instancia."""
        return self._run_ld("remove", "--name", name)

    def clone_instance(self, name: str, from_name: str) -> ADBResult:
        """Clona uma instancia existente."""
        return self._run_ld("copy", "--name", name, "--from", from_name)

    # ========================================================================
    # CONFIGURACAO DE INSTANCIA
    # ========================================================================

    def modify_instance(self, name: str, **kwargs) -> ADBResult:
        """
        Modifica configuracoes de uma instancia.
        
        Args:
            name: Nome da instancia
            resolution: "w,h,dpi" ex: "1080,1920,320"
            cpu: 1-4
            memory: 256|512|768|1024|1536|2048|4096|8192
            manufacturer: ex: "samsung"
            model: ex: "SM-G950F"
            imei: "auto" ou valor
            mac: "auto" ou valor hex
            androidid: "auto" ou valor hex
            root: 1|0
        """
        args = ["modify", "--name", name]
        valid_keys = [
            "resolution", "cpu", "memory", "manufacturer", "model",
            "pnumber", "imei", "imsi", "simserial", "androidid",
            "mac", "autorotate", "lockwindow", "root",
        ]
        for key, value in kwargs.items():
            if key in valid_keys:
                args.extend([f"--{key}", str(value)])
        return self._run_ld(*args)

    def enable_root(self, name: str) -> ADBResult:
        """Habilita root na instancia."""
        return self.modify_instance(name, root=1)

    def disable_root(self, name: str) -> ADBResult:
        """Desabilita root na instancia."""
        return self.modify_instance(name, root=0)

    def set_device_identity(
        self, name: str,
        imei: str = "auto",
        mac: str = "auto",
        androidid: str = "auto",
        manufacturer: str = "",
        model: str = "",
    ) -> ADBResult:
        """Configura identidade do dispositivo (spoofing)."""
        kwargs = {"imei": imei, "mac": mac, "androidid": androidid}
        if manufacturer:
            kwargs["manufacturer"] = manufacturer
        if model:
            kwargs["model"] = model
        return self.modify_instance(name, **kwargs)

    def set_gps(self, name: str, longitude: float, latitude: float) -> ADBResult:
        """Define localizacao GPS falsa."""
        return self._run_ld("locate", "--name", name, "--LLI", f"{longitude},{latitude}")

    # ========================================================================
    # APK / APPS
    # ========================================================================

    def install_apk(self, name: str, apk_path: str) -> ADBResult:
        """Instala APK na instancia."""
        return self._run_ld("installapp", "--name", name, "--filename", apk_path)

    def uninstall_app(self, name: str, package: str) -> ADBResult:
        """Desinstala app."""
        return self._run_ld("uninstallapp", "--name", name, "--packagename", package)

    def launch_app(self, name: str, package: str) -> ADBResult:
        """Abre um app."""
        return self._run_ld("runapp", "--name", name, "--packagename", package)

    def kill_app(self, name: str, package: str) -> ADBResult:
        """Mata um app."""
        return self._run_ld("killapp", "--name", name, "--packagename", package)

    # ========================================================================
    # ADB SHELL
    # ========================================================================

    def shell(self, name: str, command: str, timeout: int = 30) -> ADBResult:
        """Executa comando shell na instancia via ADB."""
        return self._run_ld_adb(name, f"shell {command}", timeout)

    def shell_root(self, name: str, command: str, timeout: int = 30) -> ADBResult:
        """Executa comando como root via su."""
        return self.shell(name, f"su -c '{command}'", timeout)

    # ========================================================================
    # TRANSFERENCIA DE ARQUIVOS
    # ========================================================================

    def pull(self, name: str, remote_path: str, local_path: str) -> ADBResult:
        """Puxa arquivo do emulador."""
        return self._run_ld(
            "pull", "--name", name,
            "--remote", remote_path,
            "--local", local_path,
        )

    def push(self, name: str, local_path: str, remote_path: str) -> ADBResult:
        """Envia arquivo para o emulador."""
        return self._run_ld(
            "push", "--name", name,
            "--remote", remote_path,
            "--local", local_path,
        )

    # ========================================================================
    # PROPRIEDADES
    # ========================================================================

    def get_prop(self, name: str, key: str = "") -> ADBResult:
        """Le propriedade do sistema."""
        args = ["getprop", "--name", name]
        if key:
            args.extend(["--key", key])
        return self._run_ld(*args)

    def set_prop(self, name: str, key: str, value: str) -> ADBResult:
        """Define propriedade do sistema."""
        return self._run_ld("setprop", "--name", name, "--key", key, "--value", value)

    # ========================================================================
    # BACKUP / RESTORE
    # ========================================================================

    def backup(self, name: str, filepath: str) -> ADBResult:
        """Faz backup da instancia."""
        return self._run_ld("backup", "--name", name, "--file", filepath)

    def restore(self, name: str, filepath: str) -> ADBResult:
        """Restaura backup."""
        return self._run_ld("restore", "--name", name, "--file", filepath)

    def backup_app(self, name: str, package: str, filepath: str) -> ADBResult:
        """Faz backup de app especifico."""
        return self._run_ld(
            "backupapp", "--name", name,
            "--packagename", package,
            "--file", filepath,
        )

    def restore_app(self, name: str, package: str, filepath: str) -> ADBResult:
        """Restaura app especifico."""
        return self._run_ld(
            "restoreapp", "--name", name,
            "--packagename", package,
            "--file", filepath,
        )

    # ========================================================================
    # SCREENSHOT
    # ========================================================================

    def screenshot(self, name: str, local_path: str) -> ADBResult:
        """Tira screenshot da instancia."""
        remote = "/sdcard/screenshot_mcp.png"
        r1 = self.shell(name, f"screencap -p {remote}")
        if not r1.success:
            return r1
        return self.pull(name, remote, local_path)
