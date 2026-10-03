"""NarrativeForge 最小选句依据组件。

根据已计算的阈值事实与有序规则模板，生成一个叙述句及其可审计证据。
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations, product
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

# 条件 JSON 树：
#   {"fact": "<fact_id>"}
#   {"and": [<cond>, ...]}   非空
#   {"or":  [<cond>, ...]}   非空
Condition = Dict[str, Any]

# 事实：{"id": str, "value": bool, "citation": str}
Fact = Dict[str, Any]

# 模板：{"rules": [{"id", "condition", "sentence"}], "default": {"id", "sentence"}}
Template = Dict[str, Any]


@dataclass(frozen=True)
class EvidenceItem:
    """一条证据事实，原样保留输入的布尔值与引用说明。"""

    id: str
    value: bool
    citation: str


@dataclass(frozen=True)
class GenerateResult:
    """generate 的返回：选中规则 id、句子、证据事实列表。"""

    rule_id: str
    sentence: str
    evidence: List[EvidenceItem]


def evaluate(condition: Condition, values: Mapping[str, bool]) -> bool:
    """在给定事实取值下求条件 JSON 树的布尔值。"""
    if "fact" in condition:
        return bool(values[condition["fact"]])
    if "and" in condition:
        return all(evaluate(child, values) for child in condition["and"])
    if "or" in condition:
        return any(evaluate(child, values) for child in condition["or"])
    raise ValueError(f"未知条件节点: {condition!r}")


def condition_fact_ids(condition: Condition) -> Set[str]:
    """收集条件树中引用到的全部事实 id。"""
    if "fact" in condition:
        return {condition["fact"]}
    children = condition.get("and") or condition.get("or") or []
    ids: Set[str] = set()
    for child in children:
        ids |= condition_fact_ids(child)
    return ids


def select_rule_id(conditions: Sequence[Condition], rule_ids: Sequence[str],
                   default_id: str, values: Mapping[str, bool]) -> str:
    """返回第一个条件为真的规则 id；全部为假时返回默认句 id。"""
    for rule_id, condition in zip(rule_ids, conditions):
        if evaluate(condition, values):
            return rule_id
    return default_id


def _is_valid_evidence(subset: Tuple[str, ...],
                       referenced_ids: Sequence[str],
                       values: Mapping[str, bool],
                       conditions: Sequence[Condition],
                       rule_ids: Sequence[str],
                       default_id: str,
                       target_id: str) -> bool:
    """固定 subset 中事实的当前取值，其余被引用事实任意独立取值时，
    检查选中的规则 id 是否始终等于 target_id。"""
    pinned = {fact_id: values[fact_id] for fact_id in subset}
    free_ids = [fact_id for fact_id in referenced_ids if fact_id not in pinned]
    for free_values in product((False, True), repeat=len(free_ids)):
        assignment = dict(pinned)
        assignment.update(zip(free_ids, free_values))
        if select_rule_id(conditions, rule_ids, default_id, assignment) != target_id:
            return False
    return True


def find_minimal_evidence(referenced_ids: Sequence[str],
                          values: Mapping[str, bool],
                          conditions: Sequence[Condition],
                          rule_ids: Sequence[str],
                          default_id: str,
                          target_id: str) -> Tuple[str, ...]:
    """返回事实数最少的有效证据集合；并列时取 id 升序序列字典序最小者。

    按集合大小递增、同大小按 id 升序元组的字典序枚举，第一个有效集合即答案。
    """
    ordered_ids = sorted(referenced_ids)
    for size in range(len(ordered_ids) + 1):
        for subset in combinations(ordered_ids, size):
            if _is_valid_evidence(subset, ordered_ids, values, conditions,
                                  rule_ids, default_id, target_id):
                return subset
    raise AssertionError("全部事实构成的集合必然有效，不应到达此处")


def generate(facts: List[Fact], template: Template) -> GenerateResult:
    """选择第一个条件为真的规则（全假时选默认句），并给出最小可审计证据。"""
    values = {fact["id"]: bool(fact["value"]) for fact in facts}
    citations = {fact["id"]: fact["citation"] for fact in facts}
    rules = template["rules"]
    conditions = [rule["condition"] for rule in rules]
    rule_ids = [rule["id"] for rule in rules]
    default_id = template["default"]["id"]

    selected_id = select_rule_id(conditions, rule_ids, default_id, values)

    if selected_id == default_id:
        sentence = template["default"]["sentence"]
    else:
        sentence = next(rule["sentence"] for rule in rules if rule["id"] == selected_id)

    referenced: Set[str] = set()
    for condition in conditions:
        referenced |= condition_fact_ids(condition)

    evidence_ids = find_minimal_evidence(sorted(referenced), values, conditions,
                                         rule_ids, default_id, selected_id)
    evidence = [
        EvidenceItem(id=fact_id, value=values[fact_id], citation=citations[fact_id])
        for fact_id in evidence_ids
    ]
    return GenerateResult(rule_id=selected_id, sentence=sentence, evidence=evidence)
