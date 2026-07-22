import unittest
import sys
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from quant_web import daily_spider


def market_html(rows: int) -> str:
    body = "\n".join(
        f"<tr><td>股票{i}</td><td>{i:06d}.SZ</td><td>行业</td><td>地域</td><td>0.8</td><td>1</td><td>1</td></tr>"
        for i in range(rows)
    )
    return (
        "<html><body><table>"
        "<tr><th>全称</th><th>代码</th><th>行业</th><th>地域</th><th>准确率</th><th>追踪天数</th><th>今日指标</th></tr>"
        f"{body}</table></body></html>"
    )


class TestDailySpiderCompleteness(unittest.TestCase):
    def test_blank_env_value_uses_default(self):
        with mock.patch.dict(daily_spider.os.environ, {"CRAWLER_USER": ""}):
            self.assertEqual(daily_spider.env_or_default("CRAWLER_USER", "user"), "user")

    def test_rejects_partial_market_dataframe(self):
        df = pd.DataFrame(
            {
                "代码": [f"{i:06d}.SZ" for i in range(229)],
                "准确率": [0.8] * 229,
                "今日指标": [1.0] * 229,
            }
        )

        with self.assertRaises(SystemExit):
            daily_spider.validate_market_dataframe(df)

    def test_accepts_full_market_dataframe(self):
        df = pd.DataFrame(
            {
                "代码": [f"{i:06d}.SZ" for i in range(4266)],
                "准确率": [0.8] * 4266,
                "今日指标": [1.0] * 4266,
            }
        )

        daily_spider.validate_market_dataframe(df)

    def test_direct_ip_fetch_uses_ip_url_host_header_and_basic_auth(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return market_html(4266).encode("utf-8")

        seen = {}

        def fake_urlopen(req, timeout=None, context=None):
            seen["url"] = req.full_url
            seen["headers"] = dict(req.header_items())
            seen["timeout"] = timeout
            seen["context"] = context
            return FakeResponse()

        with mock.patch.object(daily_spider.urllib.request, "urlopen", side_effect=fake_urlopen):
            html = daily_spider.fetch_via_direct_ip(
                "https://data.example.com/20260706/accuracy_markov_lyz_x.html"
            )

        self.assertIn("https://203.0.113.10/20260706/accuracy_markov_lyz_x.html", seen["url"])
        self.assertEqual(seen["headers"]["Host"], "data.example.com")
        self.assertIn("Basic ", seen["headers"]["Authorization"])
        self.assertIn("000001.SZ", html)

    def test_chrome_method_falls_back_to_direct_ip_when_chrome_fails(self):
        with mock.patch.dict(daily_spider.os.environ, {"CRAWL_METHOD": "chrome"}):
            with mock.patch.object(daily_spider, "fetch_via_chrome", return_value=None):
                with mock.patch.object(daily_spider, "fetch_via_direct_ip", return_value=market_html(4266)):
                    with mock.patch.object(daily_spider, "persist_market_dataframe") as persist:
                        df = daily_spider.fetch_and_sync_data(target_date="20260706", dry_run=True)

        self.assertEqual(len(df), 4266)
        persist.assert_not_called()

    def test_non_dry_run_persists_with_full_date(self):
        df = pd.DataFrame({"代码": ["000001.SZ"]})
        with mock.patch.dict(daily_spider.os.environ, {"CRAWL_METHOD": "direct_ip"}):
            with mock.patch.object(daily_spider, "fetch_via_direct_ip", return_value="html"):
                with mock.patch.object(daily_spider, "parse_table_from_html", return_value=df):
                    with mock.patch.object(
                        daily_spider,
                        "persist_market_dataframe",
                        return_value={
                            "mode": "csv",
                            "full_date": "20260706",
                            "legacy_date": "0706",
                            "csv_rows": 1,
                        },
                    ) as persist:
                        result = daily_spider.fetch_and_sync_data(target_date="20260706")

        persist.assert_called_once_with("20260706", df)
        self.assertIs(result, df)

    def test_shadow_failure_logs_guardian_marker(self):
        df = pd.DataFrame({"代码": ["000001.SZ"]})
        with mock.patch.dict(daily_spider.os.environ, {"CRAWL_METHOD": "direct_ip"}):
            with mock.patch.object(daily_spider, "fetch_via_direct_ip", return_value="html"):
                with mock.patch.object(daily_spider, "parse_table_from_html", return_value=df):
                    with mock.patch.object(
                        daily_spider,
                        "persist_market_dataframe",
                        return_value={
                            "mode": "shadow",
                            "full_date": "20260706",
                            "legacy_date": "0706",
                            "shadow_ok": False,
                            "shadow_error": "csv failed",
                        },
                    ):
                        with mock.patch("builtins.print") as print_mock:
                            daily_spider.fetch_and_sync_data(target_date="20260706")

        lines = [str(call.args[0]) for call in print_mock.call_args_list if call.args]
        self.assertTrue(any("SHADOW_CSV_FAILED" in line for line in lines))
        self.assertTrue(any("MARKET_STORAGE_MODE=shadow" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
