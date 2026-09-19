"""实时取 DS 令牌的检查。

背景：DS 令牌按实例隔离，写死在调度工作流里的值一旦被轮换就会静默失效（401），
而失败只体现在后台日志里。所以改为在跳板机上实时查 ``t_ds_access_token``。

这里要钉住的性质：

* 助手脚本不在（例如某国尚未部署）时返回空串，**绝不抛异常**——告警链路不能因为
  取令牌失败而整个断掉；
* 能取到令牌时原样返回，不走网络猜测；
* 用户名参与拼 SQL，必须是白名单字符，防止注入；
* ``main`` 的优先级是 显式参数 > 告警自带 > 实时查询 > ``$DS_TOKEN``。
"""

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import ds_failed_auto_retry as retry  # noqa: E402


FAKE_HELPER = '''
def find_ds_pid():
    return 0


def read_process_env(pid):
    return {{}}


def discover_ds_mysql_connection(args, process_env):
    raise RuntimeError("no process connection")


def configured_ds_mysql_connection(country):
    return {{"country": country}}


def query_mysql_rows(connection, sql):
    if "nosuchuser" in sql:
        return []
    if "boom" in sql:
        raise RuntimeError("db down")
    return [{{"user_name": "jiangchuanchen", "token": "{token}"}}]
'''


def _write_helper(directory: str, token: str = "deadbeef" * 4) -> Path:
    path = Path(directory) / "ds_match_candidate_query.py"
    path.write_text(FAKE_HELPER.format(token=token), encoding="utf-8")
    return path


class LiveTokenResolutionChecks(unittest.TestCase):
    def test_missing_helper_returns_empty_without_raising(self):
        with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES",
                               (Path("/nonexistent/helper.py"),)):
            self.assertEqual("", retry.resolve_live_ds_token("ine"))

    def test_reads_the_token_from_the_country_database(self):
        token = "7cc06baeddf2a569363fc252f17a919d"
        with tempfile.TemporaryDirectory() as tmp:
            helper = _write_helper(tmp, token=token)
            with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES", (helper,)):
                self.assertEqual(token, retry.resolve_live_ds_token("ine"))

    def test_helper_raising_is_swallowed(self):
        """数据库查询失败时返回空串，让调用方继续回退，而不是中断整个重跑。"""
        with tempfile.TemporaryDirectory() as tmp:
            helper = _write_helper(tmp)
            with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES", (helper,)):
                self.assertEqual("", retry.resolve_live_ds_token("ine", user="boom"))

    def test_unknown_user_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            helper = _write_helper(tmp)
            with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES", (helper,)):
                self.assertEqual("", retry.resolve_live_ds_token("ine", user="nosuchuser"))

    def test_username_is_whitelisted_before_reaching_sql(self):
        """用户名会被拼进 SQL，必须先过白名单，避免注入。"""
        with tempfile.TemporaryDirectory() as tmp:
            helper = _write_helper(tmp)
            with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES", (helper,)):
                for injected in ("a'; DROP TABLE t; --", "a b", "a\nb", "a*", "a%"):
                    self.assertEqual(
                        "",
                        retry.resolve_live_ds_token("ine", user=injected),
                        msg=f"应拒绝用户名: {injected!r}",
                    )

    def test_env_var_supplies_the_user(self):
        token = "3156bbdbcb1872aeff9bc76414bbcc38"
        with tempfile.TemporaryDirectory() as tmp:
            helper = _write_helper(tmp, token=token)
            with mock.patch.object(retry, "DS_TOKEN_HELPER_CANDIDATES", (helper,)):
                with mock.patch.dict(os.environ, {"DS_FAILED_TOKEN_USER": "jiangchuanchen"}):
                    self.assertEqual(token, retry.resolve_live_ds_token("cn"))


class TokenPrecedenceChecks(unittest.TestCase):
    """main 的令牌优先级：显式参数 > 告警自带 > 实时查询 > $DS_TOKEN。"""

    def _resolve(self, argv_token="", alert_token="", live="", env_token=""):
        captured = {}

        def fake_run_registered(**kwargs):
            captured["ds_token"] = kwargs.get("ds_token")
            return {"success": True}

        def fake_lock(*args, **kwargs):
            class _Ctx:
                def __enter__(self_inner):
                    return True

                def __exit__(self_inner, *exc):
                    return False

            return _Ctx()

        env = {"DS_TOKEN": env_token} if env_token else {}
        os.environ.pop("DS_TOKEN", None)
        argv = ["--country", "ine", "--payload-b64", "e30="]
        if argv_token:
            argv += ["--ds-token", argv_token]
        with mock.patch.object(retry, "resolve_live_ds_token", return_value=live), \
             mock.patch.object(retry, "run_registered_auto_retry", side_effect=fake_run_registered), \
             mock.patch.object(retry, "retry_lock", side_effect=fake_lock), \
             mock.patch.object(retry, "normalize_country", side_effect=lambda c: c), \
             mock.patch.object(retry, "normalize_alert_payload",
                               side_effect=lambda raw, country: {"retry_key": "k", "ds_token": alert_token}), \
             mock.patch.dict(os.environ, env, clear=False):
            retry.main(argv)
        return captured.get("ds_token")

    def test_explicit_argument_wins(self):
        self.assertEqual("arg", self._resolve(argv_token="arg", alert_token="alert", live="live", env_token="env"))

    def test_alert_payload_beats_live_lookup(self):
        self.assertEqual("alert", self._resolve(alert_token="alert", live="live", env_token="env"))

    def test_live_lookup_beats_env_fallback(self):
        self.assertEqual("live", self._resolve(live="live", env_token="env"))

    def test_env_is_the_last_resort(self):
        self.assertEqual("env", self._resolve(env_token="env"))


if __name__ == "__main__":
    unittest.main()
