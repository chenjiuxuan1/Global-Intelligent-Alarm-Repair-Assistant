import json
import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / "deploy" / "n8n" / "templates"
EXPECTED = {
    "中国": ("cn", "ds-quality-alert1"),
    "泰国": ("th", "78ec70e4-e362-4497-b9d1-f8d3f0bc2eca"),
    "印尼": ("ine", "ds-quality-alert"),
    "巴基斯坦": ("pk", "da2a77d6-d23e-4a79-95ce-fedc2642e7e3"),
    "墨西哥": ("mx", "a65c1eff-53ee-4e6f-8572-14a2f274d55b"),
    "菲律宾": ("ph", "caf4deab-c72b-413c-adb8-72a5638db5ca"),
}


class N8nWorkflowTemplateTests(unittest.TestCase):
    def load_template(self, display):
        path = TEMPLATE_DIR / f"智能告警修复-{display}-统一平台模板.json"
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)

    def commands(self, workflow):
        for node in workflow["nodes"]:
            command = node.get("parameters", {}).get("command")
            if command:
                yield node["name"], command

    def test_templates_keep_country_webhook_paths_and_platform_metadata(self):
        for display, (country, webhook_path) in EXPECTED.items():
            with self.subTest(display=display):
                workflow = self.load_template(display)
                self.assertEqual(workflow["meta"]["platformCountry"], country)
                webhooks = [
                    node
                    for node in workflow["nodes"]
                    if node["type"] == "n8n-nodes-base.webhook"
                ]
                self.assertTrue(any(node["parameters"].get("path") == webhook_path for node in webhooks))

    def test_repair_and_check_commands_use_platform_repo_and_country(self):
        for display, (country, _) in EXPECTED.items():
            with self.subTest(display=display):
                workflow = self.load_template(display)
                relevant = [
                    command
                    for name, command in self.commands(workflow)
                    if name in {"智能修复", "智能修复1", "环境检测", "执行环境检测"}
                ]
                self.assertGreaterEqual(len(relevant), 2)
                for command in relevant:
                    self.assertIn("/root/Global-Intelligent-Alarm-Repair-Assistant", command)
                    self.assertIn("APP_COUNTRY=", command)
                    self.assertIn(country, command)

    def test_templates_do_not_embed_known_inline_secrets(self):
        secret_patterns = [
            re.compile(r"DS_TOKEN=[a-zA-Z0-9]{16,}"),
            re.compile(r"DB_PASSWORD=[^\\s'\"]+"),
            re.compile(r"--sr-password\\s+'(?!\\$\\{SR_PASSWORD\\})"),
            re.compile(r"--sr-backup-password\\s+'(?!\\$\\{SR_BACKUP_PASSWORD\\})"),
            re.compile(r"token:\\s*[0-9a-f]{16,}", re.IGNORECASE),
        ]
        for path in TEMPLATE_DIR.glob("*.json"):
            text = path.read_text(encoding="utf-8")
            for pattern in secret_patterns:
                with self.subTest(path=path.name, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))


if __name__ == "__main__":
    unittest.main()
