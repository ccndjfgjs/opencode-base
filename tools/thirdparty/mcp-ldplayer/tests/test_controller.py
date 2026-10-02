#!/usr/bin/env python3
"""Unit tests for LDController."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_ldplayer.ld_controller import (
    ADBResult,
    EmulatorInstance,
    LDController,
    PackageInfo,
    find_ldplayer,
)


class TestDataClasses(unittest.TestCase):
    """Test dataclass creation and defaults."""

    def test_emulator_instance_defaults(self):
        inst = EmulatorInstance(index=0, name="Test")
        self.assertEqual(inst.index, 0)
        self.assertEqual(inst.name, "Test")
        self.assertEqual(inst.status, "unknown")
        self.assertEqual(inst.pid, 0)
        self.assertIsInstance(inst.properties, dict)

    def test_emulator_instance_full(self):
        inst = EmulatorInstance(index=2, name="MyEmu", status="running", pid=12345)
        self.assertEqual(inst.status, "running")
        self.assertEqual(inst.pid, 12345)

    def test_adb_result(self):
        r = ADBResult(
            success=True, stdout="OK", stderr="",
            returncode=0, command="test cmd", elapsed_ms=50,
        )
        self.assertTrue(r.success)
        self.assertEqual(r.stdout, "OK")
        self.assertEqual(r.elapsed_ms, 50)

    def test_adb_result_failure(self):
        r = ADBResult(
            success=False, stdout="", stderr="Error",
            returncode=1, command="bad cmd",
        )
        self.assertFalse(r.success)
        self.assertEqual(r.stderr, "Error")

    def test_package_info_defaults(self):
        p = PackageInfo(package_name="com.test.app")
        self.assertEqual(p.package_name, "com.test.app")
        self.assertEqual(p.version, "")
        self.assertIsInstance(p.permissions, list)
        self.assertIsInstance(p.activities, list)
        self.assertIsInstance(p.services, list)


class TestFindLDPlayer(unittest.TestCase):
    """Test auto-detection logic."""

    @patch("mcp_ldplayer.ld_controller.Path")
    def test_find_returns_none_when_not_found(self, mock_path_cls):
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_path_cls.return_value = mock_path
        result = find_ldplayer()
        self.assertIsNone(result)

    @patch("mcp_ldplayer.ld_controller.Path")
    def test_find_returns_path_when_found(self, mock_path_cls):
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_ldconsole = MagicMock()
        mock_ldconsole.exists.return_value = True
        mock_path.__truediv__ = MagicMock(return_value=mock_ldconsole)
        mock_path_cls.return_value = mock_path
        result = find_ldplayer()
        self.assertIsNotNone(result)


class TestLDControllerInit(unittest.TestCase):
    """Test controller initialization."""

    def test_init_raises_when_not_found(self):
        with patch("mcp_ldplayer.ld_controller.find_ldplayer", return_value=None):
            with self.assertRaises(FileNotFoundError):
                LDController()

    def test_init_with_explicit_path(self):
        mock_path = Path("C:/fake/ldplayer")
        with patch.object(Path, "exists", return_value=True):
            try:
                ld = LDController(str(mock_path))
            except FileNotFoundError:
                pass  # ldconsole.exe not found, expected in test


class TestLDControllerMethods(unittest.TestCase):
    """Test controller methods with mocked subprocess."""

    def setUp(self):
        with patch("mcp_ldplayer.ld_controller.find_ldplayer") as mock_find:
            mock_find.return_value = Path("C:/LDPlayer/LDPlayer9")
            with patch.object(Path, "exists", return_value=True):
                self.ld = LDController()

    @patch("subprocess.run")
    def test_list_instances_parses_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="0,LDPlayer,0\n1,TestEmu,12345\n",
            stderr="",
        )
        instances = self.ld.list_instances()
        self.assertEqual(len(instances), 2)
        self.assertEqual(instances[0].name, "LDPlayer")
        self.assertEqual(instances[0].status, "stopped")
        self.assertEqual(instances[1].name, "TestEmu")
        self.assertEqual(instances[1].status, "running")
        self.assertEqual(instances[1].pid, 12345)

    @patch("subprocess.run")
    def test_list_instances_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        instances = self.ld.list_instances()
        self.assertEqual(len(instances), 0)

    @patch("subprocess.run")
    def test_running_instances(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="LDPlayer\nTestEmu\n", stderr="",
        )
        running = self.ld.running_instances()
        self.assertEqual(running, ["LDPlayer", "TestEmu"])

    @patch("subprocess.run")
    def test_running_instances_empty(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        running = self.ld.running_instances()
        self.assertEqual(running, [])

    @patch("subprocess.run")
    def test_is_running_true(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="running", stderr="",
        )
        self.assertTrue(self.ld.is_running("LDPlayer"))

    @patch("subprocess.run")
    def test_is_running_false(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="stopped", stderr="",
        )
        self.assertFalse(self.ld.is_running("LDPlayer"))

    @patch("subprocess.run")
    def test_launch(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = self.ld.launch("LDPlayer")
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_quit(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = self.ld.quit("LDPlayer")
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_shell_command(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="uid=0(root)", stderr="",
        )
        r = self.ld.shell("LDPlayer", "id")
        self.assertTrue(r.success)
        self.assertIn("root", r.stdout)

    @patch("subprocess.run")
    def test_shell_root(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="root", stderr="",
        )
        r = self.ld.shell_root("LDPlayer", "whoami")
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_install_apk(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="Success", stderr="")
        r = self.ld.install_apk("LDPlayer", "C:/test.apk")
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_modify_instance(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = self.ld.modify_instance("LDPlayer", cpu=2, memory=4096, root=1)
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_set_gps(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        r = self.ld.set_gps("LDPlayer", -46.6333, -23.5505)
        self.assertTrue(r.success)

    @patch("subprocess.run")
    def test_execute_timeout(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        r = self.ld._execute(["test"], timeout=5)
        self.assertFalse(r.success)
        self.assertIn("Timeout", r.stderr)

    @patch("subprocess.run")
    def test_execute_exception(self, mock_run):
        mock_run.side_effect = OSError("File not found")
        r = self.ld._execute(["test"], timeout=5)
        self.assertFalse(r.success)
        self.assertIn("File not found", r.stderr)


if __name__ == "__main__":
    unittest.main()
