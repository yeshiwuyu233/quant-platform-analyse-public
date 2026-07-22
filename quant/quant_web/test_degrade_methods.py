import ast
import os
import unittest
from pathlib import Path


PIPELINE_WRAPPER = Path(os.environ.get("PIPELINE_WRAPPER_PATH", "/root/pipeline_wrapper.sh"))
DAILY_SPIDER = Path(__file__).with_name("daily_spider.py")


def _function_node(source: str, name: str) -> ast.FunctionDef:
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name} not found")


def _assigned_list_in_function(function: ast.FunctionDef, variable: str) -> list[str]:
    for node in ast.walk(function):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == variable for target in node.targets):
            continue
        if isinstance(node.value, ast.List):
            return [item.value for item in node.value.elts if isinstance(item, ast.Constant)]
    raise AssertionError(f"assignment to {variable} not found")


def _call_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def _calls(node: ast.AST, name: str) -> list[ast.Call]:
    return [
        item
        for item in ast.walk(node)
        if isinstance(item, ast.Call) and _call_name(item) == name
    ]


def _constant_strings(node: ast.AST) -> list[str]:
    return [
        item.value
        for item in ast.walk(node)
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    ]


class TestDegradeMethods(unittest.TestCase):
    def test_pipeline_degrade_methods_are_not_duplicates(self):
        if not PIPELINE_WRAPPER.exists():
            self.skipTest(f"{PIPELINE_WRAPPER} is not available in this environment")

        source = PIPELINE_WRAPPER.read_text()
        preferred_methods = _function_node(source, "preferred_methods")

        self.assertEqual(_assigned_list_in_function(preferred_methods, "methods"), ["chrome", "direct_ip"])

    def test_daily_spider_only_accepts_active_crawl_methods(self):
        source = DAILY_SPIDER.read_text()

        for retired_method in ("scrapling", "alt_url", "backup_source"):
            self.assertNotIn(f'method == "{retired_method}"', source)
            self.assertNotIn(f"fetch_via_{retired_method}", source)

    def test_cache_refresher_uses_storage_mode_aware_command_and_full_date(self):
        source = PIPELINE_WRAPPER.read_text()
        refresh = _function_node(source, "refresh_sqlite_cache")
        strings = _constant_strings(refresh)

        self.assertIn("/app/quant_web/refresh_market_cache.py", strings)
        self.assertIn("--date", strings)
        self.assertNotIn("/app/quant_web/import_market_xlsx.py", strings)
        self.assertEqual([arg.arg for arg in refresh.args.args], ["full_date"])
        self.assertTrue(
            any(isinstance(item, ast.Name) and item.id == "full_date" for item in ast.walk(refresh))
        )

    def test_full_date_is_resolved_once_per_wrapper_run(self):
        module = ast.parse(PIPELINE_WRAPPER.read_text())
        assignments = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "full_date" for target in node.targets)
        ]

        self.assertEqual(len(assignments), 1)
        self.assertIn("%Y%m%d", _constant_strings(assignments[0]))

    def test_success_paths_share_one_post_crawl_cache_refresh(self):
        module = ast.parse(PIPELINE_WRAPPER.read_text())
        refresh_calls = _calls(module, "refresh_sqlite_cache")

        self.assertEqual(len(refresh_calls), 1)
        self.assertEqual(len(refresh_calls[0].args), 1)
        self.assertIsInstance(refresh_calls[0].args[0], ast.Name)
        self.assertEqual(refresh_calls[0].args[0].id, "full_date")

        for loop in [node for node in ast.walk(module) if isinstance(node, (ast.For, ast.While))]:
            self.assertEqual(_calls(loop, "refresh_sqlite_cache"), [])
            self.assertEqual(_calls(loop, "run_backtest"), [])
            self.assertEqual(_calls(loop, "run_weekly"), [])

        crawl_success_assignments = [
            node
            for node in ast.walk(module)
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "crawl_succeeded"
                for target in node.targets
            )
            and isinstance(node.value, ast.Constant)
            and node.value.value is True
        ]
        self.assertEqual(len(crawl_success_assignments), 2)

    def test_daily_spider_has_container_timeout_before_python(self):
        source = PIPELINE_WRAPPER.read_text()
        try_crawl = _function_node(source, "try_crawl")
        command_strings = _assigned_list_in_function(try_crawl, "cmd")

        self.assertEqual(source.count("/app/quant_web/daily_spider.py"), 1)
        self.assertIn("/usr/bin/timeout", command_strings)
        self.assertIn("python", command_strings)
        timeout_index = command_strings.index("/usr/bin/timeout")
        python_index = command_strings.index("python")
        self.assertLess(timeout_index, python_index)
        self.assertIn("--signal=TERM", command_strings)
        self.assertIn("--kill-after=30s", command_strings)

        subprocess_calls = [
            call
            for call in _calls(try_crawl, "run")
            if isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id == "subprocess"
        ]
        self.assertEqual(len(subprocess_calls), 1)
        timeout_keywords = [kw.value for kw in subprocess_calls[0].keywords if kw.arg == "timeout"]
        self.assertEqual(len(timeout_keywords), 1)
        self.assertIsInstance(timeout_keywords[0], ast.BinOp)
        self.assertIsInstance(timeout_keywords[0].op, ast.Add)
        self.assertIsInstance(timeout_keywords[0].left, ast.Name)
        self.assertEqual(timeout_keywords[0].left.id, "timeout")
        self.assertIsInstance(timeout_keywords[0].right, ast.Constant)
        self.assertGreater(timeout_keywords[0].right.value, 30)

    def test_postprocessing_failure_exits_without_recrawling_or_scheduling(self):
        module = ast.parse(PIPELINE_WRAPPER.read_text())
        success_blocks = [
            node
            for node in module.body
            if isinstance(node, ast.If)
            and isinstance(node.test, ast.Name)
            and node.test.id == "crawl_succeeded"
        ]
        self.assertEqual(len(success_blocks), 1)

        postprocess = success_blocks[0]
        handlers = [node for node in postprocess.body if isinstance(node, ast.Try)]
        self.assertEqual(len(handlers), 1)
        failure_handler = handlers[0].handlers[0]
        self.assertEqual(_calls(failure_handler, "try_crawl"), [])
        self.assertEqual(_calls(failure_handler, "schedule_evening_retry"), [])
        self.assertEqual(len(_calls(failure_handler, "exit")), 1)


if __name__ == "__main__":
    unittest.main()
