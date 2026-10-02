#!/usr/bin/env python3
"""Unit tests for PentestToolkit."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_ldplayer.ld_controller import ADBResult, LDController
from mcp_ldplayer.pentest_toolkit import (
    FRIDA_ANTI_DEBUG,
    FRIDA_CRYPTO_HOOK,
    FRIDA_KEYLOGGER,
    FRIDA_NETWORK_HOOK,
    FRIDA_ROOT_BYPASS,
    FRIDA_SSL_BYPASS,
    PentestToolkit,
)


def make_adb_result(stdout="", stderr="", success=True, returncode=0):
    return ADBResult(
        success=success, stdout=stdout, stderr=stderr,
        returncode=returncode, command="mock", elapsed_ms=10,
    )


class TestFridaScripts(unittest.TestCase):
    """Test that all Frida scripts are present and non-empty."""

    def test_ssl_bypass_exists(self):
        self.assertIn("SSL Pinning", FRIDA_SSL_BYPASS)
        self.assertIn("Java.perform", FRIDA_SSL_BYPASS)

    def test_root_bypass_exists(self):
        self.assertIn("Root Detection", FRIDA_ROOT_BYPASS)
        self.assertIn("File.exists", FRIDA_ROOT_BYPASS)

    def test_keylogger_exists(self):
        self.assertIn("Input Monitor", FRIDA_KEYLOGGER)
        self.assertIn("EditText", FRIDA_KEYLOGGER)

    def test_crypto_hook_exists(self):
        self.assertIn("Crypto Hook", FRIDA_CRYPTO_HOOK)
        self.assertIn("Cipher", FRIDA_CRYPTO_HOOK)

    def test_network_hook_exists(self):
        self.assertIn("Network Hook", FRIDA_NETWORK_HOOK)
        self.assertIn("OkHttp", FRIDA_NETWORK_HOOK)

    def test_anti_debug_exists(self):
        self.assertIn("Anti-Debug", FRIDA_ANTI_DEBUG)
        self.assertIn("TracerPid", FRIDA_ANTI_DEBUG)


class TestPentestToolkitInit(unittest.TestCase):
    """Test toolkit initialization."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_has_all_frida_scripts(self):
        expected = {"ssl_bypass", "root_bypass", "keylogger", "crypto_hook", "network_hook", "anti_debug"}
        self.assertEqual(set(self.pt.frida_scripts.keys()), expected)

    def test_controller_reference(self):
        self.assertEqual(self.pt.ld, self.mock_ld)


class TestDeviceRecon(unittest.TestCase):
    """Test device reconnaissance."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_recon_returns_dict(self):
        self.mock_ld.shell.return_value = make_adb_result("test_value")
        result = self.pt.device_recon("LDPlayer")
        self.assertIsInstance(result, dict)
        self.assertIn("security_assessment", result)

    def test_recon_handles_failures(self):
        self.mock_ld.shell.return_value = make_adb_result(
            success=False, stderr="error",
        )
        result = self.pt.device_recon("LDPlayer")
        self.assertIsInstance(result, dict)
        # Should have N/A for failed commands
        for key, val in result.items():
            if key != "security_assessment":
                self.assertEqual(val, "N/A")


class TestPackageAnalysis(unittest.TestCase):
    """Test package listing and analysis."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_list_packages(self):
        self.mock_ld.shell.return_value = make_adb_result(
            "package:com.test.app1\npackage:com.test.app2\n"
        )
        packages = self.pt.list_packages("LDPlayer")
        self.assertEqual(packages, ["com.test.app1", "com.test.app2"])

    def test_list_packages_empty(self):
        self.mock_ld.shell.return_value = make_adb_result("")
        packages = self.pt.list_packages("LDPlayer")
        self.assertEqual(packages, [])

    def test_list_packages_failure(self):
        self.mock_ld.shell.return_value = make_adb_result(success=False)
        packages = self.pt.list_packages("LDPlayer")
        self.assertEqual(packages, [])

    def test_analyze_package_basic(self):
        dumpsys = (
            "versionName=1.2.3\n"
            "versionCode=42\n"
            "targetSdk=33\n"
            "minSdk=21\n"
            "android.permission.INTERNET\n"
            "android.permission.CAMERA\n"
            "android.permission.READ_SMS\n"
            "MainActivityActivity\n"
            "MyServiceService\n"
            "MyReceiverReceiver\n"
            "MyProviderProvider\n"
        )
        self.mock_ld.shell.return_value = make_adb_result(dumpsys)
        result = self.pt.analyze_package("LDPlayer", "com.test.app")
        self.assertEqual(result["package"], "com.test.app")
        self.assertEqual(result["version"], "1.2.3")
        self.assertIn("INTERNET", result["permissions"])
        self.assertIn("CAMERA", result["dangerous_permissions"])
        self.assertIn("risk_assessment", result)

    def test_analyze_package_risk_levels(self):
        # App with many dangerous permissions -> HIGH risk
        perms = "\n".join([
            f"android.permission.{p}" for p in [
                "READ_SMS", "SEND_SMS", "CAMERA", "RECORD_AUDIO",
                "ACCESS_FINE_LOCATION", "READ_CONTACTS", "INTERNET",
                "SYSTEM_ALERT_WINDOW",
            ]
        ])
        dumpsys = f"versionName=1.0\ntargetSdk=33\n{perms}\n"
        self.mock_ld.shell.return_value = make_adb_result(dumpsys)
        result = self.pt.analyze_package("LDPlayer", "com.risky.app")
        risk = result["risk_assessment"]
        self.assertIn(risk["level"], ["HIGH", "MEDIUM"])
        self.assertGreater(risk["score"], 0)


class TestNetworkTools(unittest.TestCase):
    """Test network scanning tools."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_network_scan(self):
        self.mock_ld.shell.return_value = make_adb_result("eth0: 10.0.2.15")
        result = self.pt.network_scan("LDPlayer")
        self.assertIsInstance(result, dict)
        self.assertIn("interfaces", result)
        self.assertIn("routes", result)
        self.assertIn("dns", result)

    def test_port_scan_single_port(self):
        self.mock_ld.shell.return_value = make_adb_result("OPEN:80")
        result = self.pt.port_scan("LDPlayer", "10.0.2.2", "80")
        self.assertEqual(result["target"], "10.0.2.2")
        self.assertIn(80, result["open"])

    def test_port_scan_range(self):
        self.mock_ld.shell.return_value = make_adb_result("OPEN:22\nOPEN:80")
        result = self.pt.port_scan("LDPlayer", "10.0.2.2", "1-100")
        self.assertEqual(result["target"], "10.0.2.2")

    def test_hex_to_ip_port(self):
        # 0100007F:0050 = 127.0.0.1:80
        result = self.pt._hex_to_ip_port("0100007F:0050")
        self.assertEqual(result, "127.0.0.1:80")

    def test_tcp_state_mapping(self):
        self.assertEqual(self.pt._tcp_state("01"), "ESTABLISHED")
        self.assertEqual(self.pt._tcp_state("0A"), "LISTEN")
        self.assertIn("UNKNOWN", self.pt._tcp_state("FF"))


class TestTrafficCapture(unittest.TestCase):
    """Test traffic capture tools."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_start_capture(self):
        self.mock_ld.shell_root.return_value = make_adb_result()
        r = self.pt.start_traffic_capture("LDPlayer")
        self.assertTrue(r.success)

    def test_stop_capture(self):
        self.mock_ld.shell_root.return_value = make_adb_result()
        r = self.pt.stop_traffic_capture("LDPlayer")
        self.assertTrue(r.success)


class TestProxy(unittest.TestCase):
    """Test proxy setup/removal."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_setup_proxy(self):
        self.mock_ld.shell.return_value = make_adb_result()
        self.mock_ld.shell_root.return_value = make_adb_result()
        result = self.pt.setup_proxy("LDPlayer", "10.0.2.2", 8080)
        self.assertEqual(result["proxy_address"], "10.0.2.2:8080")
        self.assertIn("note", result)

    def test_remove_proxy(self):
        self.mock_ld.shell.return_value = make_adb_result()
        self.mock_ld.shell_root.return_value = make_adb_result()
        result = self.pt.remove_proxy("LDPlayer")
        self.assertTrue(result["proxy_removed"])
        self.assertTrue(result["iptables_flushed"])


class TestFridaInjection(unittest.TestCase):
    """Test Frida script injection."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_inject_known_script(self):
        self.mock_ld.push.return_value = make_adb_result()
        self.mock_ld.shell.return_value = make_adb_result("")
        result = self.pt.inject_frida_script("LDPlayer", "ssl_bypass", "com.test")
        self.assertEqual(result["script"], "ssl_bypass")
        self.assertTrue(result["push"])

    def test_inject_unknown_script(self):
        result = self.pt.inject_frida_script("LDPlayer", "nonexistent")
        self.assertIn("error", result)

    def test_inject_all_scripts(self):
        self.mock_ld.push.return_value = make_adb_result()
        self.mock_ld.shell.return_value = make_adb_result("")
        for script_name in self.pt.frida_scripts:
            result = self.pt.inject_frida_script("LDPlayer", script_name)
            self.assertTrue(result["push"], f"Failed to inject {script_name}")

    def test_inject_custom_script(self):
        self.mock_ld.push.return_value = make_adb_result()
        result = self.pt.inject_custom_frida(
            "LDPlayer", "console.log('test');", "com.test",
        )
        self.assertTrue(result["push"])
        self.assertIn("frida_custom.js", result["script_path"])


class TestSpoofDevice(unittest.TestCase):
    """Test device identity spoofing."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_spoof_samsung(self):
        self.mock_ld.set_device_identity.return_value = make_adb_result()
        result = self.pt.spoof_device("LDPlayer", "samsung")
        self.assertEqual(result["profile"], "samsung")
        self.assertEqual(result["manufacturer"], "samsung")
        self.assertTrue(result["applied"])
        self.assertEqual(len(result["imei"]), 15)
        self.assertIn(":", result["mac"])

    def test_spoof_all_profiles(self):
        self.mock_ld.set_device_identity.return_value = make_adb_result()
        for profile in ["samsung", "pixel", "xiaomi", "huawei", "oneplus"]:
            result = self.pt.spoof_device("LDPlayer", profile)
            self.assertEqual(result["profile"], profile)
            self.assertTrue(result["applied"])

    def test_spoof_random(self):
        self.mock_ld.set_device_identity.return_value = make_adb_result()
        result = self.pt.spoof_device("LDPlayer", "random")
        self.assertIn(result["profile"], ["samsung", "pixel", "xiaomi", "huawei", "oneplus"])


class TestSecurityAssessment(unittest.TestCase):
    """Test Drozer-like security assessment."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_assessment_structure(self):
        self.mock_ld.shell.return_value = make_adb_result("")
        self.mock_ld.shell_root.return_value = make_adb_result("")
        result = self.pt.security_assessment("LDPlayer", "com.test.app")
        self.assertIn("package", result)
        self.assertIn("vulnerabilities", result)
        self.assertIn("warnings", result)
        self.assertIn("info", result)
        self.assertIn("summary", result)

    def test_assessment_detects_debuggable(self):
        def shell_side_effect(instance, cmd, *args, **kwargs):
            if "run-as" in cmd:
                return make_adb_result("uid=10123")
            return make_adb_result("")

        self.mock_ld.shell.side_effect = shell_side_effect
        self.mock_ld.shell_root.return_value = make_adb_result("")
        result = self.pt.security_assessment("LDPlayer", "com.test.app")
        types = [v["type"] for v in result["vulnerabilities"]]
        self.assertIn("DEBUGGABLE_APP", types)


class TestLogcat(unittest.TestCase):
    """Test logcat capture and analysis."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_logcat_basic(self):
        logs = "02-23 10:00:00 I/Test: Normal log\n02-23 10:00:01 E/Error: Something broke\n02-23 10:00:02 W/Warn: Watch out"
        self.mock_ld.shell.return_value = make_adb_result(logs)
        result = self.pt.logcat_capture("LDPlayer")
        self.assertEqual(result["total_lines"], 3)
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["warnings"], 1)

    def test_logcat_detects_sensitive_data(self):
        logs = (
            "I/App: token=abc123\n"
            "D/Auth: password check\n"
            "I/Normal: no issues\n"
        )
        self.mock_ld.shell.return_value = make_adb_result(logs)
        result = self.pt.logcat_capture("LDPlayer")
        self.assertGreater(len(result["sensitive_leaks"]), 0)

    def test_logcat_empty(self):
        self.mock_ld.shell.return_value = make_adb_result("")
        result = self.pt.logcat_capture("LDPlayer")
        self.assertEqual(result["total_lines"], 0)


class TestFilesystem(unittest.TestCase):
    """Test filesystem analysis."""

    def setUp(self):
        self.mock_ld = MagicMock(spec=LDController)
        self.pt = PentestToolkit(self.mock_ld)

    def test_filesystem_analysis(self):
        files = (
            "/data/data/com.test/databases/main.db\n"
            "/data/data/com.test/shared_prefs/config.xml\n"
            "/data/data/com.test/lib/libnative.so\n"
            "/data/data/com.test/cache/tmp.dat\n"
        )
        self.mock_ld.shell_root.return_value = make_adb_result(files)
        result = self.pt.analyze_filesystem("LDPlayer", "com.test")
        self.assertEqual(result["file_count"], 4)
        cats = result["categories"]
        self.assertEqual(len(cats["databases"]), 1)
        self.assertEqual(len(cats["shared_prefs"]), 1)
        self.assertEqual(len(cats["native_libs"]), 1)


if __name__ == "__main__":
    unittest.main()
