"""定稿日档案公开 interface 测试。

覆盖率闸门、定稿池、涨停三池、档案组装入口 —— 对准 `duanxian.settled_archive`
公开 API；兼容期仍核对 `emotion_metrics` 再导出。
"""

from __future__ import annotations

import pytest

from duanxian import emotion_metrics as em
from duanxian import settled_archive as sa


# ---------------------------------------------------------------- 覆盖率闸门
@pytest.mark.unit
class TestCoverageGate:
    """数据源半死不活时只回来几只票。照样出结论 = 拿 3 只票冒充全体赚钱效应，
    数字看着完全正常，是最难发现的一类错。"""

    def test_full_coverage_is_not_partial(self):
        c = sa.coverage([1.0] * 50, 50)
        assert c["coverage_rate"] == 1.0 and c["partial"] is False

    def test_low_coverage_is_flagged_partial(self):
        c = sa.coverage([1.0] * 30, 50)      # 60%
        assert c["partial"] is True and c["sample"] == 30 and c["expected_sample"] == 50

    def test_partial_shows_warning_in_prompt_text(self):
        """覆盖率必须进 prompt——不写的话模型会把部分样本的均值当全体读数用。"""
        note = em._cov_note({"partial": True, "sample": 3, "expected_sample": 50})
        assert "3/50" in note and "样本不全" in note
        assert em._cov_note({"partial": False}) == ""

    def test_gate_threshold_ordering(self):
        assert 0 < sa._COVERAGE_MIN < sa._COVERAGE_PARTIAL <= 1

    def test_coverage_reexport_compat(self):
        """过渡期：em 再导出须与档案模块同一实现。"""
        assert em._coverage is sa.coverage
        assert em._COVERAGE_MIN == sa._COVERAGE_MIN
        assert em._COVERAGE_PARTIAL == sa._COVERAGE_PARTIAL


# ---------------------------------------------------------------- 定稿日档案
@pytest.mark.unit
class TestSettledArchive:
    """覆盖率 / 定稿池 / 组装入口收在 settled_archive；落盘键名不变。"""

    def test_coverage_lives_in_archive_module(self):
        c = sa.coverage([1.0] * 30, 50)
        assert c["partial"] is True and c["sample"] == 30
        assert sa._COVERAGE_MIN == em._COVERAGE_MIN

    def test_emotion_half_delegates_to_build_metrics(self, monkeypatch):
        monkeypatch.setattr(
            "duanxian.emotion_metrics.build_metrics",
            lambda d, with_cycle=True: {"date": d, "with_cycle": with_cycle, "money_effect": {"available": False}},
        )
        out = sa.emotion_half("2026-08-20", with_cycle=False)
        assert out["date"] == "2026-08-20" and out["with_cycle"] is False

    def test_archive_shape_keeps_review_keys(self, monkeypatch):
        monkeypatch.setattr(sa, "emotion_half", lambda d, with_cycle=True: {"date": d, "money_effect": {}})
        monkeypatch.setattr(sa, "facts_half", lambda d: {"breadth": {"available": False}, "theme_tree": {}})
        arch = sa.archive("2026-08-20")
        assert set(arch) >= {"date", "emotion_metrics", "market_facts"}
        assert "theme_tree" in arch["market_facts"]

    def test_theme_tree_of_is_archive_entry(self, monkeypatch):
        """题材树 build 只经档案入口。"""
        called = []

        def _fake(d, **kw):
            called.append((d, kw))
            return {"available": True, "date": d}

        monkeypatch.setattr("duanxian.theme_tree.build", _fake)
        out = sa.theme_tree_of("2026-08-20", force=True)
        assert out["available"] is True and called == [("2026-08-20", {"force": True})]

    def test_settled_pool_delegates_to_fetch(self, monkeypatch):
        monkeypatch.setattr(
            "duanxian.data.fetch_prev_pool",
            lambda d: [{"code": "000001", "ret": 1.2, "prev_boards": 2}],
        )
        rows = sa.settled_pool("2026-08-20")
        assert rows and rows[0]["code"] == "000001"

    def test_limit_pools_delegates_to_market_facts(self, monkeypatch):
        monkeypatch.setattr(
            "duanxian.market_facts.pools",
            lambda d: {"zt": [{"code": "000001"}], "zb": [], "dt": []},
        )
        pools = sa.limit_pools("2026-08-20")
        assert pools and pools["zt"][0]["code"] == "000001"

    def test_zt_pool_adapts_from_limit_pools(self, monkeypatch):
        monkeypatch.setattr(sa, "limit_pools", lambda _d: {
            "zt": [
                {"code": "000001", "name": "平安", "boards": 3, "broken_times": 0},
                {"code": "000002", "name": "万科", "boards": 1, "broken_times": 2},
            ],
            "zb": [{"code": "000003"}],
            "dt": [],
        })
        z = em._zt_pool("2026-08-20")
        assert z["highest_consec"] == 3
        assert z["zb_count"] == 1
        assert {s["code"] for s in z["ladder"]} == {"000001", "000002"}
        s = em._summarize(z)
        assert s["limit_up"] == 2
        assert s["never_broken_rate"] == 0.5
        assert abs(s["broken_rate"] - 1 / 3) < 1e-9

    def test_zt_pool_none_when_limit_pools_empty(self, monkeypatch):
        monkeypatch.setattr(sa, "limit_pools", lambda _d: None)
        assert em._zt_pool("2026-08-20") is None


# ---------------------------------------------------------------- 档案形状 ↔ 前端投影
@pytest.mark.unit
class TestArchiveShapeMatchesViewModel:
    """档案两半的键 = 前端 view-model 的字段。

    这份 dict 原样落进复盘 JSON，前端 `agent.ts` 再照着它声明类型 —— 同一套词汇
    写在两处。任一侧单独改都不报错：后端新加一张卡，前端不认就永远不渲染；
    TS 留着后端已删的键，那张卡就永远显示"暂不可用"。两种都是静默的。
    """

    @staticmethod
    def _py_keys(fn) -> set[str]:
        """函数体里 dict 字面量的键 + `out["x"] = ...` 这类后补的键。"""
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        keys = {k.value for n in ast.walk(tree) if isinstance(n, ast.Dict)
                for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}
        for n in ast.walk(tree):
            if not isinstance(n, ast.Assign):
                continue
            for t in n.targets:
                if (isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                        and isinstance(t.slice.value, str)):
                    keys.add(t.slice.value)
        return keys

    @staticmethod
    def _ts_fields(interface: str) -> set[str]:
        import pathlib
        import re

        src = pathlib.Path("frontend/src/lib/agent.ts").read_text(encoding="utf-8")
        m = re.search(r"export interface %s \{([^}]*)\}" % interface, src)
        assert m, f"agent.ts 里找不到 interface {interface}"
        return set(re.findall(r"^\s*(\w+)\??:", m.group(1), re.M))

    def test_emotion_half_matches_ts(self):
        assert self._py_keys(em.build_metrics) == self._ts_fields("EmotionMetrics"), \
            "派生情绪指标的键与 agent.ts 的 EmotionMetrics 对不上"

    def test_facts_half_matches_ts(self):
        assert self._py_keys(sa.facts_half) == self._ts_fields("MarketFacts"), \
            "客观事实的键与 agent.ts 的 MarketFacts 对不上"

    def test_extractor_actually_sees_keys(self):
        """提取器自身失效时上面两条会双双"通过"（空集 == 空集），先钉住它。"""
        assert "money_effect" in self._py_keys(em.build_metrics)
        assert "cycle" in self._py_keys(em.build_metrics), "条件写入的键也要算进来"
        assert "theme_tree" in self._ts_fields("MarketFacts")
