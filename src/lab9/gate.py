"""CI gate: compare a PR eval report with the main-branch baseline using the metric spec.

    python -m lab9.gate --pr reports/eval_workflow.json --baseline reports/baseline_v1.json

exit 0 = merge, exit 1 = blocked. Safety metrics: max 0, no averaging away.
Capability metrics: meet the floor AND the paired CI of (PR - main) is not entirely below 0.
Thresholds may only get stricter on the same eval-set version (ratchet).
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from lab8.console import utf8_stdio
from lab9 import stats
from lab9.eval import SPEC, aggregate, load_spec, per_item
from lab9.graders import GRADERS


def integrity_check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> list[str]:
    """M7 (Expert): refuse to compare reports that cannot be trusted. Return a list of problems
    (empty = trustworthy). A gate that passes a broken report is worse than no gate.
    Must catch at least:
      - any metric value in pr["metrics"] that is NaN or inf
      - len(pr["rows"]) != manifest items x len(manifest seeds)   (dropped / duplicated rows)
      - the (item_id, seed) set of PR differs from the baseline's (cherry-picked seeds/items)
      - pr["evaluator_failures"] non-empty, or a row whose value for a graded spec metric is
        None (a crashed grader silently scores as "missing" and drops out of the mean)
      - base_spec given and a threshold in spec is LOOSER than in base_spec for the same
        eval-set version (ratchet: max may not rise, min may not fall, a blocking metric may
        not become non-blocking, a metric may not disappear; the same for spec["slices"],
        including dropping no_significant_drop)
      - an item's slice tags in PR rows differ from the baseline's (relabelling an item out of a
        slice hides its regression from the slice gate)"""
    problems: list[str] = []
    graded = [m["id"] for m in spec.get("metrics") or [] if m["id"] in GRADERS]
    for name, rep in (("PR", pr), ("baseline", base)):
        problems += _report_problems(name, rep, graded, spec)
    problems += _pair_problems(pr, base)
    if base_spec is not None:
        problems += ratchet_problems(spec, base_spec)
    return problems


def _bad_number(v) -> bool:
    return isinstance(v, float) and not math.isfinite(v)


def _report_problems(name: str, rep: dict, graded: list[str], spec: dict) -> list[str]:
    """Checks one report against itself: a report must be internally consistent before any value in
    it is compared with anything."""
    out: list[str] = []
    metrics, rows, man = rep.get("metrics") or {}, rep.get("rows") or [], rep.get("manifest") or {}
    out += [f"{name} metric {k} = {v!r} (NaN/inf: a crashed grader, not a score)"
            for k, v in metrics.items() if _bad_number(v)]
    if rep.get("evaluator_failures"):
        out.append(f"{name} has {len(rep['evaluator_failures'])} evaluator failure(s), first: "
                   f"{str(rep['evaluator_failures'][0])[:80]}")
    seeds = man.get("seeds") or []
    want_rows = int(man.get("items") or 0) * len(seeds)
    if len(rows) != want_rows:
        out.append(f"{name} has {len(rows)} rows, manifest says {man.get('items')} items x {len(seeds)} seeds = {want_rows}")
    keys = [(r.get("item_id"), r.get("seed")) for r in rows]
    dup = len(keys) - len(set(keys))
    if dup:
        out.append(f"{name} has {dup} duplicated (item, seed) row(s)")
    if len({k[0] for k in keys}) != int(man.get("items") or 0):
        out.append(f"{name} rows cover {len({k[0] for k in keys})} items, manifest says {man.get('items')}")
    stray = sorted({s for _, s in keys} - set(seeds), key=str)
    if stray:
        out.append(f"{name} rows use seeds {stray} not in the manifest {seeds}")
    bad_vals: dict[str, int] = {}
    for r in rows:
        for m in graded:
            if not isinstance(r.get(m), bool):        # None = grader crashed/skipped; NaN/str = edited
                bad_vals[m] = bad_vals.get(m, 0) + 1
        if _bad_number(r.get("cost")):
            bad_vals["cost"] = bad_vals.get("cost", 0) + 1
    out += [f"{name} has {n} row(s) where {m} is not a pass/fail value (None/NaN drop out of the mean)"
            for m, n in sorted(bad_vals.items())]
    slices: dict[str, set] = {}
    for r in rows:
        slices.setdefault(r.get("item_id"), set()).add(tuple(sorted(r.get("slices") or [])))
    out += [f"{name} item {i} has inconsistent slice tags across seeds" for i, s in sorted(slices.items(), key=str) if len(s) > 1]
    missing = [m["id"] for m in spec.get("metrics") or [] if m["id"] not in metrics and m["id"] in graded]
    out += [f"{name} report has no value for spec metric {m}" for m in missing]
    # The headline numbers must be what the rows say. A hand-edited metric with untouched rows
    # (or rows edited without re-aggregating) shows up here.
    if rows and not bad_vals:
        has_cost = all(isinstance(r.get("cost"), (int, float)) for r in rows)
        try:
            ids = [m for m in graded if all(m in r for r in rows)]
            again = aggregate([{**r, "cost": r.get("cost") or 0.0} for r in rows], ids,
                              k_values=spec.get("pass_k", []))
        except (KeyError, TypeError, ValueError) as e:
            out.append(f"{name} rows cannot be re-aggregated ({type(e).__name__}: {e})")
        else:
            if not has_cost:
                again.pop("cost_per_success", None)
            for k, v in again.items():
                if k in metrics and not _same_number(v, metrics[k]):
                    out.append(f"{name} metric {k} = {metrics[k]!r} but its rows aggregate to {v!r}")
    return out


def _same_number(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, bool) or isinstance(b, bool) or not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a == b
    return math.isfinite(b) and abs(a - b) <= 1e-6


def _pair_problems(pr: dict, base: dict) -> list[str]:
    """Checks PR against baseline: the paired comparison needs the SAME (item, seed) grid and the
    same slice membership on both sides."""
    out: list[str] = []
    pk = {(r.get("item_id"), r.get("seed")) for r in pr.get("rows") or []}
    bk = {(r.get("item_id"), r.get("seed")) for r in base.get("rows") or []}
    if pk != bk:
        only_pr, only_base = sorted(pk - bk, key=str), sorted(bk - pk, key=str)
        out.append(f"(item, seed) set differs from baseline: {len(only_base)} missing in PR "
                   f"{only_base[:3]}, {len(only_pr)} extra {only_pr[:3]}")
    ps, bs = (pr.get("manifest") or {}).get("seeds"), (base.get("manifest") or {}).get("seeds")
    if sorted(ps or [], key=str) != sorted(bs or [], key=str):
        out.append(f"PR seeds {ps} differ from baseline seeds {bs}")
    if (pr.get("manifest") or {}).get("items") != (base.get("manifest") or {}).get("items"):
        out.append(f"PR has {(pr.get('manifest') or {}).get('items')} items, baseline {(base.get('manifest') or {}).get('items')}")
    tags = lambda rep: {r.get("item_id"): tuple(sorted(r.get("slices") or [])) for r in rep.get("rows") or []}
    pt, bt = tags(pr), tags(base)
    moved = sorted(i for i in set(pt) & set(bt) if pt[i] != bt[i])
    out += [f"item {i} slice tags {list(pt[i])} differ from baseline {list(bt[i])}" for i in moved]
    return out


def ratchet_problems(spec: dict, base_spec: dict) -> list[str]:
    """Same eval set => a threshold may only get stricter. Applies when the eval-set version is the
    same, and also when the spec renames the version but still points at the same eval set file."""
    if (spec.get("eval_set_version") != base_spec.get("eval_set_version")
            and spec.get("eval_set") != base_spec.get("eval_set")):
        return []
    out: list[str] = []
    new = {m["id"]: m for m in spec.get("metrics") or []}
    for old in base_spec.get("metrics") or []:
        mid = old["id"]
        if mid not in new:
            out.append(f"RATCHET metric {mid} was removed")
            continue
        out += [f"RATCHET metric {mid}: {p}" for p in _looser(old, new[mid], old.get("threshold") or {},
                                                             new[mid].get("threshold") or {})]
        if old.get("kind") == "safety" and new[mid].get("kind") != "safety":
            out.append(f"RATCHET metric {mid}: kind safety -> {new[mid].get('kind')}")
    skey = lambda s: (s.get("name"), s.get("metric"))
    new_s = {skey(s): s for s in spec.get("slices") or []}
    for old in base_spec.get("slices") or []:
        k = skey(old)
        if k not in new_s:
            out.append(f"RATCHET slice {k[0]}/{k[1]} was removed")
            continue
        out += [f"RATCHET slice {k[0]}/{k[1]}: {p}" for p in _looser(old, new_s[k], old, new_s[k])]
    ob, nb = base_spec.get("bootstrap") or {}, spec.get("bootstrap") or {}
    if nb.get("confidence", 0.95) > ob.get("confidence", 0.95):
        out.append(f"RATCHET bootstrap confidence {ob.get('confidence', 0.95)} -> {nb.get('confidence')} (wider CI, fewer blocks)")
    if nb.get("rng", 2027) != ob.get("rng", 2027):
        out.append(f"RATCHET bootstrap rng {ob.get('rng', 2027)} -> {nb.get('rng')} (re-rolling the CI until it touches 0)")
    if nb.get("n_resamples", 1000) < ob.get("n_resamples", 1000):
        out.append(f"RATCHET bootstrap n_resamples {ob.get('n_resamples', 1000)} -> {nb.get('n_resamples')}")
    if sorted(spec.get("seeds") or []) != sorted(base_spec.get("seeds") or []):
        out.append(f"RATCHET seeds {base_spec.get('seeds')} -> {spec.get('seeds')}")
    lost_k = sorted(set(base_spec.get("pass_k") or []) - set(spec.get("pass_k") or []))
    if lost_k:
        out.append(f"RATCHET pass_k lost {lost_k}")
    return out


def _looser(old_m: dict, new_m: dict, old: dict, new: dict) -> list[str]:
    out = []
    if old_m.get("blocking") and not new_m.get("blocking"):
        out.append("blocking -> non-blocking")
    if "min" in old and ("min" not in new or new["min"] < old["min"]):
        out.append(f"min {old['min']} -> {new.get('min')}")
    if "max" in old and ("max" not in new or new["max"] > old["max"]):
        out.append(f"max {old['max']} -> {new.get('max')}")
    if "max_increase" in old and ("max_increase" not in new or new["max_increase"] > old["max_increase"]):
        out.append(f"max_increase {old['max_increase']} -> {new.get('max_increase')}")
    if old.get("no_significant_drop") and not new.get("no_significant_drop"):
        out.append("no_significant_drop dropped")
    return out


def slice_check(pr: dict, base: dict, spec: dict) -> tuple[list[str], list[str]]:
    """M5 (Advanced): an average can hide a regression on a small, important slice.
    For each entry of spec["slices"] ({"name", "metric", "min"?, "no_significant_drop"?, "blocking"}):
      - value = mean of per_item(pr, metric, slice_name=name)
      - fail if below "min", or if no_significant_drop and the paired CI over the slice's items
        lies entirely below 0
    Return (blocked ids like "slice:money_movement/pass_rate", report lines)."""
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for s in spec.get("slices") or []:
        name, metric = s["name"], s["metric"]
        sid = f"slice:{name}/{metric}"
        a, b = per_item(pr, metric, slice_name=name), per_item(base, metric, slice_name=name)
        verdict, note, val = "ok", "", None
        if not a:
            verdict = "missing"            # a slice with no rows cannot be "fine": it was emptied
        else:
            val = round(sum(a.values()) / len(a), 4)
            if "min" in s and val < s["min"]:
                verdict = "fail"
            if "max" in s and val > s["max"]:
                verdict = "fail"
            keys = sorted(set(a) & set(b))
            if s.get("no_significant_drop") and keys:
                d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                                   n_resamples=bs.get("n_resamples", 1000),
                                                   rng=bs.get("rng", 2027), confidence=bs.get("confidence", 0.95))
                note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
                if hi < 0:
                    verdict = "fail"
        if verdict != "ok" and s.get("blocking"):
            blocked.append(sid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if s.get("blocking") else "warn")
        th = {k: s[k] for k in ("min", "max", "no_significant_drop") if k in s}
        lines.append(f"  {sid:<34} {val!s:<8} n={len(a):<3} {json.dumps(th):<36} {note:<28} {label}")
    return blocked, lines


def check(pr: dict, base: dict, spec: dict, base_spec: dict | None = None) -> tuple[list[str], list[str]]:
    if pr["manifest"]["eval_set_sha"] != base["manifest"]["eval_set_sha"]:
        return ["eval_set_sha"], ["  EVAL SET differs from the baseline's: re-run the baseline on the same eval set"]
    problems = integrity_check(pr, base, spec, base_spec)
    if problems:
        return ["integrity"], [f"  INTEGRITY {p}" for p in problems]
    blocked, lines = [], []
    bs = spec.get("bootstrap", {})
    for m in spec["metrics"]:
        mid, th, val = m["id"], m.get("threshold", {}), pr["metrics"].get(m["id"])
        verdict, note = "ok", ""
        if val is None:
            verdict = "missing"
        elif "max" in th and val > th["max"]:
            verdict = "fail"
        elif "min" in th and val < th["min"]:
            verdict = "fail"
        elif "max_increase" in th and base["metrics"].get(mid):
            if val > base["metrics"][mid] * (1 + th["max_increase"]):
                verdict = "fail"
        if th.get("no_significant_drop") and val is not None:
            a, b = per_item(pr, mid), per_item(base, mid)
            keys = sorted(set(a) & set(b))
            d, lo, hi = stats.paired_bootstrap([a[k] for k in keys], [b[k] for k in keys],
                                               n_resamples=bs.get("n_resamples", 1000), rng=bs.get("rng", 2027))
            note = f"Δ {d:+.3f} CI [{lo:+.3f}, {hi:+.3f}]"
            if hi < 0:
                verdict = "fail"
        if verdict != "ok" and m.get("blocking"):
            blocked.append(mid)
        label = {"ok": "ok", "missing": "MISSING"}.get(verdict, "BLOCK" if m.get("blocking") else "warn")
        lines.append(f"  {mid:<22} {val!s:<8} {json.dumps(th):<40} {note:<28} {label}")
    if spec.get("slices"):
        sb, sl = slice_check(pr, base, spec)
        blocked += sb
        lines += sl
    return blocked, lines


def main(argv: list[str] | None = None) -> int:
    utf8_stdio()
    ap = argparse.ArgumentParser(prog="lab9.gate")
    ap.add_argument("--pr", required=True)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--spec", default=str(SPEC))
    ap.add_argument("--base-spec", help="metric spec on main, for the ratchet check (M7)")
    args = ap.parse_args(argv)
    pr = json.loads(Path(args.pr).read_text(encoding="utf-8"))
    base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
    base_spec = load_spec(Path(args.base_spec)) if args.base_spec else None
    blocked, lines = check(pr, base, load_spec(Path(args.spec)), base_spec)
    print(f"gate: PR {pr['run_id']} vs main {base['run_id']} · eval set {pr['manifest']['eval_set_sha']}")
    print("\n".join(lines))
    if blocked:
        print(f"exit 1 — blocked: {', '.join(blocked)}")
        return 1
    print("exit 0 — merge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
