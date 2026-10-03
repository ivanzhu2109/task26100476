"""narrativeforge.generate 的自动化测试。

包含：独立穷举参照实现、固定种子随机模板对拍、以及针对性场景。
"""

import itertools
import random
import unittest

import narrativeforge as nf


# ---------------------------------------------------------------------------
# 独立参照实现：先为全部 2^n 个赋值预算选中结果，再按子集投影判定有效性。
# 与被测实现（按子集即时枚举）结构不同，用于对拍。
# ---------------------------------------------------------------------------

def _ref_outcome_table(referenced_ids, template):
    """返回 dict: 赋值元组(按 referenced_ids 顺序) -> 选中规则 id。"""
    rules = template["rules"]
    default_id = template["default"]["id"]
    table = {}
    for combo in itertools.product((False, True), repeat=len(referenced_ids)):
        values = dict(zip(referenced_ids, combo))
        selected = default_id
        for rule in rules:
            if nf.evaluate(rule["condition"], values):
                selected = rule["id"]
                break
        table[combo] = selected
    return table


def reference_generate(facts, template):
    """独立参照：返回 (rule_id, 最小证据 id 升序元组)。"""
    values = {f["id"]: bool(f["value"]) for f in facts}
    referenced = sorted(
        set().union(*(nf.condition_fact_ids(r["condition"]) for r in template["rules"]))
        if template["rules"] else set()
    )
    table = _ref_outcome_table(referenced, template)
    actual_key = tuple(values[i] for i in referenced)
    actual_outcome = table[actual_key]

    def is_valid(subset):
        idx = [referenced.index(i) for i in subset]
        pinned = tuple(values[i] for i in subset)
        for combo, outcome in table.items():
            if tuple(combo[j] for j in idx) == pinned and outcome != actual_outcome:
                return False
        return True

    for size in range(len(referenced) + 1):
        for subset in itertools.combinations(referenced, size):
            if is_valid(subset):
                return actual_outcome, subset
    raise AssertionError("unreachable")


def random_template(rng):
    """生成小规模随机模板与事实（覆盖嵌套、重复引用、真假混合）。"""
    fact_ids = [f"f{i}" for i in range(rng.randint(2, 5))]
    facts = [
        {"id": fid, "value": rng.random() < 0.5, "citation": f"cite-{fid}"}
        for fid in fact_ids
    ]

    def random_condition(depth):
        if depth == 0 or rng.random() < 0.4:
            return {"fact": rng.choice(fact_ids)}  # 允许跨规则/同条件重复引用
        op = rng.choice(["and", "or"])
        return {op: [random_condition(depth - 1)
                     for _ in range(rng.randint(1, 3))]}

    sentences = ["alpha", "beta", "gamma"]
    rules = []
    for i in range(rng.randint(1, 4)):
        rules.append({
            "id": f"rule-{i}",
            "condition": random_condition(depth=2),
            # 故意让句子可重复：相同句子也不能互相替代
            "sentence": rng.choice(sentences),
        })
    template = {
        "rules": rules,
        "default": {"id": "default", "sentence": rng.choice(sentences)},
    }
    return facts, template


def evidence_sufficient(facts, template, result):
    """性质检查：固定证据取值，其余事实任意独立取值，选中规则 id 不变。"""
    values = {f["id"]: bool(f["value"]) for f in facts}
    referenced = sorted(
        set().union(*(nf.condition_fact_ids(r["condition"]) for r in template["rules"]))
        if template["rules"] else set()
    )
    pinned = {e.id: e.value for e in result.evidence}
    free_ids = [i for i in referenced if i not in pinned]
    rules = template["rules"]
    for combo in itertools.product((False, True), repeat=len(free_ids)):
        assignment = dict(pinned)
        assignment.update(zip(free_ids, combo))
        selected = template["default"]["id"]
        for rule in rules:
            if nf.evaluate(rule["condition"], assignment):
                selected = rule["id"]
                break
        if selected != result.rule_id:
            return False
    return True


class GenerateTest(unittest.TestCase):

    def test_random_templates_against_reference(self):
        """固定种子随机模板：与独立穷举参照对拍，并做证据充分性性质检查。"""
        for seed in range(300):
            rng = random.Random(seed)
            facts, template = random_template(rng)
            result = nf.generate(facts, template)
            ref_rule_id, ref_evidence_ids = reference_generate(facts, template)

            self.assertEqual(result.rule_id, ref_rule_id, f"seed={seed}")
            self.assertEqual(
                tuple(e.id for e in result.evidence), ref_evidence_ids,
                f"seed={seed} 证据集合不一致",
            )
            self.assertTrue(
                evidence_sufficient(facts, template, result),
                f"seed={seed} 证据不足以固定选中规则",
            )
            # 证据必须原样保留输入的布尔值与引用说明
            fact_by_id = {f["id"]: f for f in facts}
            for item in result.evidence:
                src = fact_by_id[item.id]
                self.assertEqual(item.value, bool(src["value"]))
                self.assertEqual(item.citation, src["citation"])

    def test_evidence_must_exclude_earlier_rules(self):
        """只证明命中条件（a=True 使命中的 r2 为真）不足以排除更早的 r1。"""
        facts = [
            {"id": "a", "value": True, "citation": "cite-a"},
            {"id": "b", "value": False, "citation": "cite-b"},
        ]
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"and": [{"fact": "a"}, {"fact": "b"}]},
                 "sentence": "s1"},
                {"id": "r2",
                 "condition": {"or": [{"fact": "a"}, {"fact": "b"}]},
                 "sentence": "s2"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.rule_id, "r2")
        # 若证据只有 {a}，b 翻转为真时 r1 将命中，因此必须包含 b=False
        self.assertEqual([e.id for e in result.evidence], ["a", "b"])
        self.assertEqual(
            {e.id: e.value for e in result.evidence}, {"a": True, "b": False})

    def test_default_requires_excluding_all_rules(self):
        """默认句：证据必须证明全部规则均不命中。"""
        facts = [
            {"id": "a", "value": False, "citation": "cite-a"},
            {"id": "b", "value": True, "citation": "cite-b"},
        ]
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "a"}, "sentence": "s1"},
                {"id": "r2",
                 "condition": {"and": [{"fact": "b"}, {"fact": "a"}]},
                 "sentence": "s2"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.rule_id, "d")
        # a=False 同时使 r1、r2 为假，b 无需出现在证据中
        self.assertEqual([e.id for e in result.evidence], ["a"])

    def test_tie_break_lexicographic(self):
        """并列最优：{a} 与 {b} 都充分时，选 id 升序序列字典序最小者。"""
        facts = [
            {"id": "a", "value": True, "citation": "cite-a"},
            {"id": "b", "value": True, "citation": "cite-b"},
        ]
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"or": [{"fact": "b"}, {"fact": "a"}]},
                 "sentence": "s1"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.rule_id, "r1")
        self.assertEqual([e.id for e in result.evidence], ["a"])

    def test_repeated_reference_within_condition(self):
        """同一条件内重复引用同一事实，按 id 只计一次。"""
        facts = [
            {"id": "a", "value": True, "citation": "cite-a"},
            {"id": "b", "value": False, "citation": "cite-b"},
        ]
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"and": [
                     {"fact": "a"},
                     {"or": [{"fact": "a"}, {"fact": "b"}]},
                 ]},
                 "sentence": "s1"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.rule_id, "r1")
        # a=True 时 and 两项均真（or 由重复的 a 满足），b 无关
        self.assertEqual([e.id for e in result.evidence], ["a"])

    def test_same_sentence_not_substitutable(self):
        """两条规则句子相同也不能互相替代：命中后者仍需排除前者。"""
        facts = [
            {"id": "a", "value": True, "citation": "cite-a"},
            {"id": "b", "value": False, "citation": "cite-b"},
        ]
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"and": [{"fact": "a"}, {"fact": "b"}]},
                 "sentence": "same"},
                {"id": "r2", "condition": {"fact": "a"}, "sentence": "same"},
            ],
            "default": {"id": "d", "sentence": "same"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.rule_id, "r2")
        self.assertEqual(result.sentence, "same")
        self.assertEqual([e.id for e in result.evidence], ["a", "b"])

    def test_citation_preserved_verbatim(self):
        """引用说明原样保留，组件不重新计算或改写。"""
        citation = "营收>阈值: 见报表Q3#tab-2, 统计口径v1.7"
        facts = [{"id": "x", "value": True, "citation": citation}]
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "x"}, "sentence": "s1"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = nf.generate(facts, template)
        self.assertEqual(result.evidence[0].citation, citation)


if __name__ == "__main__":
    unittest.main()
