#!/usr/bin/env python3
"""Unit tests for MCP protocol compliance."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from mcp_ldplayer.mcp_server import TOOLS, VERSION, SERVER_NAME, PentestMCPServer


class TestToolDefinitions(unittest.TestCase):
    """Validate all 38 tool definitions."""

    def test_tool_count(self):
        self.assertEqual(len(TOOLS), 38)

    def test_all_tools_have_name(self):
        for tool in TOOLS:
            self.assertIn("name", tool, f"Tool missing 'name': {tool}")
            self.assertIsInstance(tool["name"], str)
            self.assertGreater(len(tool["name"]), 0)

    def test_all_tools_have_description(self):
        for tool in TOOLS:
            self.assertIn("description", tool, f"Tool {tool['name']} missing 'description'")
            self.assertGreater(len(tool["description"]), 10)

    def test_all_tools_have_input_schema(self):
        for tool in TOOLS:
            self.assertIn("inputSchema", tool, f"Tool {tool['name']} missing 'inputSchema'")
            schema = tool["inputSchema"]
            self.assertEqual(schema["type"], "object")
            self.assertIn("properties", schema)

    def test_unique_tool_names(self):
        names = [t["name"] for t in TOOLS]
        self.assertEqual(len(names), len(set(names)), "Duplicate tool names found")

    def test_tool_categories(self):
        prefixes = set()
        for t in TOOLS:
            prefix = t["name"].split("_")[0]
            prefixes.add(prefix)
        self.assertIn("ld", prefixes)
        self.assertIn("adb", prefixes)
        self.assertIn("pt", prefixes)

    def test_required_fields_are_lists(self):
        for tool in TOOLS:
            schema = tool["inputSchema"]
            if "required" in schema:
                self.assertIsInstance(schema["required"], list)
                # All required fields must be in properties
                for req in schema["required"]:
                    self.assertIn(
                        req, schema["properties"],
                        f"Tool {tool['name']}: required field '{req}' not in properties",
                    )


class TestServerConstants(unittest.TestCase):
    """Test server metadata."""

    def test_version_format(self):
        parts = VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for p in parts:
            self.assertTrue(p.isdigit())

    def test_server_name(self):
        self.assertEqual(SERVER_NAME, "pt-ldplayer-pentest")


class TestMCPInitialize(unittest.TestCase):
    """Test MCP initialize handshake."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld:
            mock_ld.return_value = MagicMock()
            self.server = PentestMCPServer()

    def test_initialize_response(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        }))
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 1)
        result = response["result"]
        self.assertEqual(result["protocolVersion"], "2024-11-05")
        self.assertEqual(result["serverInfo"]["name"], "pt-ldplayer-pentest")
        self.assertEqual(result["serverInfo"]["version"], VERSION)
        self.assertIn("tools", result["capabilities"])
        self.assertIn("resources", result["capabilities"])
        self.assertIn("prompts", result["capabilities"])


class TestMCPToolsList(unittest.TestCase):
    """Test tools/list method."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld:
            mock_ld.return_value = MagicMock()
            self.server = PentestMCPServer()

    def test_tools_list(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }))
        tools = response["result"]["tools"]
        self.assertEqual(len(tools), 38)


class TestMCPResourcesList(unittest.TestCase):
    """Test resources/list method."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld:
            mock_ld.return_value = MagicMock()
            self.server = PentestMCPServer()

    def test_resources_list(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/list",
            "params": {},
        }))
        resources = response["result"]["resources"]
        self.assertEqual(len(resources), 2)
        uris = [r["uri"] for r in resources]
        self.assertIn("pt-ldplayer://status", uris)
        self.assertIn("pt-ldplayer://frida-scripts", uris)


class TestMCPPromptsList(unittest.TestCase):
    """Test prompts/list method."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld:
            mock_ld.return_value = MagicMock()
            self.server = PentestMCPServer()

    def test_prompts_list(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "prompts/list",
            "params": {},
        }))
        prompts = response["result"]["prompts"]
        self.assertEqual(len(prompts), 3)
        names = [p["name"] for p in prompts]
        self.assertIn("pentest_app", names)
        self.assertIn("setup_intercept", names)
        self.assertIn("stealth_mode", names)


class TestMCPErrorHandling(unittest.TestCase):
    """Test error responses."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld:
            mock_ld.return_value = MagicMock()
            self.server = PentestMCPServer()

    def test_unknown_method(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 5,
            "method": "nonexistent/method",
            "params": {},
        }))
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32601)

    def test_initialized_returns_none(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "method": "initialized",
            "params": {},
        }))
        self.assertIsNone(response)

    def test_shutdown(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 6,
            "method": "shutdown",
            "params": {},
        }))
        self.assertFalse(self.server.running)


class TestMCPToolCall(unittest.TestCase):
    """Test tools/call dispatch."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld_cls:
            self.mock_ld = MagicMock()
            mock_ld_cls.return_value = self.mock_ld
            self.server = PentestMCPServer()

    def test_ld_list(self):
        import asyncio
        from mcp_ldplayer.ld_controller import EmulatorInstance
        self.mock_ld.list_instances.return_value = [
            EmulatorInstance(0, "LDPlayer", "stopped", 0),
        ]
        self.mock_ld.running_instances.return_value = []

        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "ld_list", "arguments": {}},
        }))
        content = response["result"]["content"][0]["text"]
        data = json.loads(content)
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["instances"][0]["name"], "LDPlayer")

    def test_unknown_tool(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {"name": "nonexistent_tool", "arguments": {}},
        }))
        content = response["result"]["content"][0]["text"]
        data = json.loads(content)
        self.assertIn("error", data)
        self.assertIn("available", data)
        self.assertEqual(len(data["available"]), 38)


class TestMCPResourceRead(unittest.TestCase):
    """Test resources/read."""

    def setUp(self):
        with patch("mcp_ldplayer.mcp_server.LDController") as mock_ld_cls:
            self.mock_ld = MagicMock()
            mock_ld_cls.return_value = self.mock_ld
            self.server = PentestMCPServer()

    def test_read_status(self):
        import asyncio
        from mcp_ldplayer.ld_controller import EmulatorInstance
        self.mock_ld.list_instances.return_value = [
            EmulatorInstance(0, "LDPlayer", "stopped", 0),
        ]

        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 9,
            "method": "resources/read",
            "params": {"uri": "pt-ldplayer://status"},
        }))
        content = response["result"]["contents"][0]
        self.assertEqual(content["uri"], "pt-ldplayer://status")
        data = json.loads(content["text"])
        self.assertEqual(data["server"], "pt-ldplayer-pentest")
        self.assertTrue(data["initialized"])

    def test_read_frida_scripts(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "resources/read",
            "params": {"uri": "pt-ldplayer://frida-scripts"},
        }))
        content = response["result"]["contents"][0]
        data = json.loads(content["text"])
        self.assertEqual(len(data["scripts"]), 6)

    def test_read_unknown_resource(self):
        import asyncio
        response = asyncio.run(self.server.handle_request({
            "jsonrpc": "2.0",
            "id": 11,
            "method": "resources/read",
            "params": {"uri": "pt-ldplayer://nonexistent"},
        }))
        self.assertIn("error", response)
        self.assertEqual(response["error"]["code"], -32602)


if __name__ == "__main__":
    unittest.main()
