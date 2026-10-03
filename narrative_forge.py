"""NarrativeForge 最小选句依据组件.

根据已计算的阈值事实与有序规则模板, 选出一个叙述句,
并给出可审计的最小证据集合.

条件编码 (JSON 树, 仅三种节点):
    {"fact": "<fact_id>"}        事实引用
    {"and": [<cond>, ...]}       非空合取
    {"or":  [<cond>, ...]}       非空析取

模板结构:
    {
        "rules": [
            {"id": str, "condition": <cond>, "sentence": str},
            ...
        ],
        "default": {"id": str, "sentence": str},
    }

事实结构:
    [{"id": str, "value": bool, "citation": str}, ...]
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List, Optional

Condition = Dict[str, Any]
Fact = Dict[str, Any]
Template = Dict[str, Any]


def generate(facts: List[Fact], template: Template) -> Dict[str, Any]:
    """选择叙述句并返回最小可审计证据.

    返回 {"rule_id": str, "sentence": str,
          "evidence": [{"id", "value", "citation"}, ...]},
    证据按事实 id 升序排列.
    """
    values = {f["id"]: bool(f["value"]) for f in facts}
    fact_by_id = {f["id"]: f for f in facts}
    rules = template["rules"]

    selected: Optional[int] = None
    for i, rule in enumerate(rules):
        if _evaluate(rule["condition"], values):
            selected = i
            break

    # 只有被选中规则及其之前的规则会影响选择结果,
    # 证据只需覆盖这些规则引用到的事实.
    scope = rules if selected is None else rules[: selected + 1]
    relevant = sorted({fid for r in scope for fid in _condition_facts(r["condition"])})

    evidence_ids = _min_evidence(scope, selected, values, relevant)

    if selected is None:
        chosen = template["default"]
    else:
        chosen = rules[selected]
    return {
        "rule_id": chosen["id"],
        "sentence": chosen["sentence"],
        "evidence": [
            {
                "id": fid,
                "value": values[fid],
                "citation": fact_by_id[fid]["citation"],
            }
            for fid in evidence_ids
        ],
    }


def _condition_facts(condition: Condition) -> List[str]:
    """收集条件树中引用的事实 id (可重复, 调用方自行去重)."""
    if "fact" in condition:
        return [condition["fact"]]
    children = condition.get("and") or condition.get("or") or []
    out: List[str] = []
    for c in children:
        out.extend(_condition_facts(c))
    return out


def _is_valid_evidence(
    scope: List[Dict[str, Any]], selected: Optional[int], partial: Dict[str, bool]
) -> bool:
    """判断部分赋值是否足以锁定选择结果.

    选中规则 k: 所有更早规则被强制为假, 且规则 k 被强制为真;
    默认句 (selected is None): 全部规则被强制为假.
    """
    if selected is None:
        return all(_forced(r["condition"], partial) is False for r in scope)
    return all(_forced(r["condition"], partial) is False for r in scope[:selected]) and (
        _forced(scope[selected]["condition"], partial) is True
    )


def _min_evidence(
    scope: List[Dict[str, Any]],
    selected: Optional[int],
    values: Dict[str, bool],
    relevant: List[str],
) -> List[str]:
    """枚举子集求最小证据; 并列时取 id 升序序列字典序最小者.

    relevant 已升序, combinations 按字典序产出, 故第一个有效集即答案.
    """
    for size in range(len(relevant) + 1):
        for combo in combinations(relevant, size):
            partial = {fid: values[fid] for fid in combo}
            if _is_valid_evidence(scope, selected, partial):
                return list(combo)
    raise AssertionError("全集必然是有效证据, 不应到达此处")


def _evaluate(condition: Condition, values: Dict[str, bool]) -> bool:
    """在完整赋值下求条件真值."""
    if "fact" in condition:
        return values[condition["fact"]]
    if "and" in condition:
        return all(_evaluate(c, values) for c in condition["and"])
    if "or" in condition:
        return any(_evaluate(c, values) for c in condition["or"])
    raise ValueError(f"未知条件节点: {condition!r}")


def _forced(condition: Condition, partial: Dict[str, bool]) -> Optional[bool]:
    """三值求值: 在部分赋值下条件被强制为真/假, 或 None 表示未定."""
    if "fact" in condition:
        fid = condition["fact"]
        return partial[fid] if fid in partial else None
    if "and" in condition:
        subs = [_forced(c, partial) for c in condition["and"]]
        if any(v is False for v in subs):
            return False
        if all(v is True for v in subs):
            return True
        return None
    if "or" in condition:
        subs = [_forced(c, partial) for c in condition["or"]]
        if any(v is True for v in subs):
            return True
        if all(v is False for v in subs):
            return False
        return None
    raise ValueError(f"未知条件节点: {condition!r}")
