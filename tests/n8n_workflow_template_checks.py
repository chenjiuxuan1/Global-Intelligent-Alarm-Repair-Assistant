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
                    self.assertFalse(command.startswith("="))
                    self.assertIn("/root/Global-Intelligent-Alarm-Repair-Assistant", command)
                    if country == "cn":
                        self.assertIn("master.tar.gz", command)
                        self.assertIn("curl -L", command)
                        self.assertIn("tar -xzf", command)
                        self.assertIn("跳过压缩包初始化", command)
                        self.assertNotIn("git clone https://", command)
                    else:
                        self.assertIn("git clone", command)
                        self.assertIn("Global-Intelligent-Alarm-Repair-Assistant.git", command)
                        self.assertIn("本节点不更新代码；如需更新，请单独执行【拉取最新代码】节点", command)
                    self.assertNotIn("git fetch origin master", command)
                    self.assertNotIn("git reset --hard origin/master", command)
                    self.assertIn("当前版本:", command)
                    self.assertIn("开始执行:", command)
                    self.assertIn("export APP_COUNTRY=", command)
                    self.assertIn("export WORKFLOW_CODE_ROOT=", command)
                    self.assertIn("export DS_WORKFLOW_LIST_MAX_SECONDS=", command)
                    self.assertIn("'30'", command)
                    self.assertIn("APP_COUNTRY=", command)
                    self.assertIn("WORKFLOW_CODE_ROOT=", command)
                    self.assertIn("WORKFLOW_CODE_COUNTRY=", command)
                    self.assertIn("/data/git/starrocks/workflow", command)
                    self.assertIn(country, command)

    def test_pull_commands_create_or_update_platform_repo(self):
        for display, (country, _) in EXPECTED.items():
            with self.subTest(display=display):
                workflow = self.load_template(display)
                relevant = [
                    command
                    for name, command in self.commands(workflow)
                    if name == "拉取最新代码"
                ]
                self.assertGreaterEqual(len(relevant), 1)
                for command in relevant:
                    self.assertFalse(command.startswith("="))
                    if country == "cn":
                        self.assertIn("master.tar.gz", command)
                        self.assertIn("curl -L", command)
                        self.assertIn("tar -xzf", command)
                        self.assertIn("开始通过压缩包拉取最新代码", command)
                        self.assertNotIn("git fetch origin master", command)
                        self.assertNotIn("git reset --hard origin/master", command)
                    else:
                        self.assertIn("git clone", command)
                        self.assertIn("Global-Intelligent-Alarm-Repair-Assistant.git", command)
                        self.assertIn("git remote set-url origin", command)
                        self.assertIn("git fetch origin master", command)
                        self.assertIn("git reset --hard origin/master", command)
                        self.assertIn("开始拉取最新代码", command)
                    self.assertIn("拉取完成", command)

    def test_china_commands_use_more_tolerant_ds_list_settings(self):
        workflow = self.load_template("中国")
        relevant = [
            command
            for name, command in self.commands(workflow)
            if name in {"智能修复", "智能修复1", "环境检测", "执行环境检测"}
        ]

        self.assertGreaterEqual(len(relevant), 2)
        for command in relevant:
            self.assertIn("DS_API_GET_TIMEOUT_SECONDS=", command)
            self.assertIn("'10'", command)
            self.assertIn("DS_API_GET_RETRY_COUNT=", command)
            self.assertIn("'1'", command)
            self.assertIn("DS_WORKFLOW_LIST_PAGE_SIZE=", command)
            self.assertIn("'20'", command)
            self.assertIn("DS_WORKFLOW_LIST_MAX_SECONDS=", command)
            self.assertIn("'30'", command)
            self.assertIn("PRIORITY_WORKFLOW_CODES_JSON=", command)
            self.assertIn("158514956979200", command)
            self.assertIn("158514957494272", command)

    def test_repair_commands_skip_when_same_country_repair_is_running(self):
        for display, (country, _) in EXPECTED.items():
            with self.subTest(display=display):
                workflow = self.load_template(display)
                relevant = [
                    command
                    for name, command in self.commands(workflow)
                    if name in {"智能修复", "智能修复1"}
                ]
                self.assertGreaterEqual(len(relevant), 1)
                for command in relevant:
                    self.assertIn(f"/tmp/intelligent_alarm_repair_{country}.lockdir", command)
                    self.assertIn("mkdir \"$LOCK_DIR\"", command)
                    self.assertNotIn("flock -n", command)
                    self.assertIn("已有智能修复任务运行中，跳过本次执行", command)
                    self.assertIn("REPAIR_WORKFLOW_CONFLICT_WAIT_SECONDS=", command)
                    self.assertIn("'300'", command)

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
