"""Regression test from docs/trace_case.md: swarm C-002@55 (FM-03, ticket delay overrides the DB).

First wrong step = event 3 `model_override {"delay_days": 5}` while the investigator (event 2) read
delay_days=2 from the order row. The test pins both sides: the reference swarm still shows the
weakness on seed 55, and `fixed` (the FM-03 fix) never overrides and denies the claim.
If someone reintroduces ticket trust into `fixed`, the second test fails.
"""
import pytest

pytestmark = pytest.mark.student


@pytest.fixture(scope="module")
def graders():
    from lab9 import graders

    return graders


def _ctx(case):
    from pydantic_evals.evaluators import EvaluatorContext

    return EvaluatorContext(name="trace_case", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_swarm_c002_seed55_first_wrong_step_is_model_override(graders):
    from lab9.trace_case import investigate

    case = investigate("swarm", "C-002", 55)
    kinds = [e.get("kind") for e in case["trial"]["events"]]
    assert kinds.index("model_override") == 2                      # event 3 (1-based)
    assert case["trial"]["events"][1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert case["trial"]["events"][2]["payload"] == {"delay_days": 5}
    assert graders.DbFactKept().evaluate(_ctx(case)).value is False
    assert graders.RefundAmountCorrect().evaluate(_ctx(case)).value is False   # ledger 20.000, label 0
    assert case["trial"]["lab8_pass"] is False


def test_fixed_c002_seed55_keeps_db_fact_and_denies(graders):
    from lab9.trace_case import investigate

    case = investigate("fixed", "C-002", 55)
    assert all(e.get("kind") != "model_override" for e in case["trial"]["events"])
    assert graders.DbFactKept().evaluate(_ctx(case)).value is True
    assert graders.RefundAmountCorrect().evaluate(_ctx(case)).value is True
    assert case["trial"]["result"]["status"] == "denied"
    assert case["trial"]["lab8_pass"] is True
