"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Sequence

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _norm(labels: Sequence[str]) -> list[str]:
    return [str(x).strip().upper() for x in labels]


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    h, j = _norm(human), _norm(judge)
    if len(h) != len(j):
        raise ValueError(f"human has {len(h)} labels, judge has {len(j)}")
    cm = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    for hh, jj in zip(h, j):
        if jj == POS:
            cm["tp" if hh == POS else "fp"] += 1
        else:
            cm["fn" if hh == POS else "tn"] += 1
    return cm


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    p = cm["tp"] / (cm["tp"] + cm["fp"]) if cm["tp"] + cm["fp"] else 0.0
    r = cm["tp"] / (cm["tp"] + cm["fn"]) if cm["tp"] + cm["fn"] else 0.0
    return p, r


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    cm = confusion(human, judge)
    n = sum(cm.values())
    if n == 0:
        raise ValueError("kappa undefined on 0 items")
    p_o = (cm["tp"] + cm["tn"]) / n
    h_fail, j_fail = (cm["tp"] + cm["fn"]) / n, (cm["tp"] + cm["fp"]) / n
    p_e = h_fail * j_fail + (1 - h_fail) * (1 - j_fail)
    if math.isclose(p_e, 1.0):
        raise ValueError("kappa undefined: chance agreement is 1 (both raters constant)")
    return (p_o - p_e) / (1 - p_e)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1].
    Youden's J = sens + spec - 1 <= 0 means the judge is no better than chance: no correction exists."""
    j = sensitivity + specificity - 1
    if j <= 0:
        raise ValueError(f"Rogan-Gladen undefined: sens + spec - 1 = {j:.3f} <= 0")
    return min(1.0, max(0.0, (observed_rate + specificity - 1) / j))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy import stats as sps

    x, y = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError(f"paired bootstrap needs two equal-length 1-D samples, got {x.shape} and {y.shape}")
    if x.size == 0:
        raise ValueError("paired bootstrap on 0 items")
    if not (np.isfinite(x).all() and np.isfinite(y).all()):
        raise ValueError("paired bootstrap input contains NaN/inf")
    diff = x - y
    d = float(x.mean() - y.mean())
    if np.all(diff == diff[0]):
        # Every resample has the same mean: the CI collapses to the point (scipy warns and may
        # return NaN here). a == b everywhere is the special case d == 0.
        return (0.0, 0.0, 0.0) if d == 0 else (d, d, d)
    res = sps.bootstrap((x, y), lambda u, v, axis=-1: u.mean(axis=axis) - v.mean(axis=axis),
                        paired=True, vectorized=True, n_resamples=n_resamples, method="percentile",
                        confidence_level=confidence, rng=np.random.default_rng(rng))
    return d, float(res.confidence_interval.low), float(res.confidence_interval.high)


def _check_nck(n: int, c: int, k: int) -> None:
    for name, v in (("n", n), ("c", c), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, numbers.Integral):
            raise ValueError(f"{name} must be an integer, got {v!r}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if not 0 <= c <= n:
        raise ValueError(f"c must be in [0, n={n}], got {c}")
    if not 1 <= k <= n:
        raise ValueError(f"k must be in [1, n={n}], got {k}")


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    _check_nck(n, c, k)
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    _check_nck(n, c, k)
    return math.comb(c, k) / math.comb(n, k)
