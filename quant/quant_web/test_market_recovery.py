import unittest

import pandas as pd

from quant_web.market_store import compare_reference_frames


def _frame():
    return pd.DataFrame([
        {
            "全称": "Alpha",
            "代码": "000001.SZ",
            "行业": "银行",
            "地域": "北京",
            "准确率": 0.61,
            "追踪天数": 90,
            "倍数": "1.20(+0.10)",
            "指标历史": "1.00(+1.00%)",
            "近三日涨幅": "2.00%",
            "今日指标": 1.1,
            "指标趋势": 0.3,
        },
        {
            "全称": "Beta",
            "代码": "000002.SZ",
            "行业": "电子",
            "地域": "上海",
            "准确率": 0.62,
            "追踪天数": 90,
            "倍数": "0.80(-0.10)",
            "指标历史": "0.90(-1.00%)",
            "近三日涨幅": "-1.00%",
            "今日指标": 0.9,
            "指标趋势": -0.2,
        },
    ])


class TestMarketRecovery(unittest.TestCase):
    def test_identical_reference_and_fetched_frames_pass(self):
        compare_reference_frames(_frame(), _frame())

    def test_missing_code_is_rejected_with_code_diagnostic(self):
        fetched = _frame().iloc[[0]].copy()

        with self.assertRaisesRegex(ValueError, "000002.SZ"):
            compare_reference_frames(_frame(), fetched)

    def test_changed_business_field_is_rejected_with_field_diagnostic(self):
        fetched = _frame().copy()
        fetched.loc[1, "今日指标"] = 9.9

        with self.assertRaisesRegex(ValueError, "今日指标"):
            compare_reference_frames(_frame(), fetched)


if __name__ == "__main__":
    unittest.main()
