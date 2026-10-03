"""narrative_forge 的自动化测试.

运行: python3 -m unittest test_narrative_forge.py -v
"""

import itertools
import random
import unittest

from narrative_forge import generate


# ---------- 独立参照实现 (穷举, 与被测实现逻辑分离) ----------

def _oracle_eval(cond, vals):
    if "fact" in cond:
        return vals[cond["fact"]]
    if "and" in cond:
        return all(_oracle_eval(c, vals) for c in cond["and"])
    return any(_oracle_eval(c, vals) for c in cond["or"])


def _oracle_select(template, vals):
    for rule in template["rules"]:
        if _oracle_eval(rule["condition"], vals):
            return rule["id"]
    return template["default"]["id"]


def oracle_generate(facts, template):
    """穷举参照: 返回 (rule_id, 最小证据 id 升序列表).

    对每个候选子集, 枚举其余事实的全部 2^k 种独立取值,
    验证选中规则 id 不变; 按 (大小, id 序列字典序) 取最优.
    """
    values = {f["id"]: f["value"] for f in facts}
    actual = _oracle_select(template, values)
    ids = sorted(values)
    for size in range(len(ids) + 1):
        for combo in itertools.combinations(ids, size):
            fixed = dict(zip(combo, [values[i] for i in combo]))
            free = [i for i in ids if i not in fixed]
            ok = True
            for bits in itertools.product([False, True], repeat=len(free)):
                vals = dict(fixed)
                vals.update(zip(free, bits))
                if _oracle_select(template, vals) != actual:
                    ok = False
                    break
            if ok:
                return actual, list(combo)
    raise AssertionError("unreachable")


# ---------- 随机模板生成 ----------

def random_condition(rng, fact_ids, depth):
    if depth == 0 or rng.random() < 0.4:
        return {"fact": rng.choice(fact_ids)}
    kind = rng.choice(["and", "or"])
    return {kind: [random_condition(rng, fact_ids, depth - 1)
                   for _ in range(rng.randint(1, 3))]}


def random_instance(rng, n_facts=5, n_rules=3, depth=3):
    facts = [
        {"id": f"f{i}", "value": rng.random() < 0.5,
         "citation": f"cite-{i}"}
        for i in range(n_facts)
    ]
    fact_ids = [f["id"] for f in facts]
    rules = [
        {"id": f"r{i}", "condition": random_condition(rng, fact_ids, depth),
         "sentence": f"sentence-{i}"}
        for i in range(n_rules)
    ]
    return facts, {"rules": rules,
                   "default": {"id": "d0", "sentence": "default-sentence"}}


# ---------- 测试 ----------

def make_facts(pairs):
    return [{"id": fid, "value": val, "citation": f"见报表{fid}"}
            for fid, val in pairs]


class DeterministicTest(unittest.TestCase):
    def test_hit_only_evidence_cannot_exclude_earlier_rules(self):
        # 仅证明命中条件 (q 为真) 不够, 还必须固定 p 为假以排除更早的 r1.
        facts = make_facts([("p", False), ("q", True)])
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "p"}, "sentence": "s1"},
                {"id": "r2", "condition": {"fact": "q"}, "sentence": "s2"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual(result["rule_id"], "r2")
        self.assertEqual([e["id"] for e in result["evidence"]], ["p", "q"])
        # 只含 q 的"证据"在 p 取真时会选中 r1, 故非法.
        self.assertNotEqual(oracle_generate(facts, template)[1], ["q"])

    def test_default_requires_excluding_all_rules(self):
        facts = make_facts([("a", False), ("b", True), ("c", False)])
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "a"}, "sentence": "s1"},
                {"id": "r2",
                 "condition": {"and": [{"fact": "b"}, {"fact": "c"}]},
                 "sentence": "s2"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual(result["rule_id"], "d")
        # r2 的 and 条件只需固定 c=false 即可排除, b 自由不影响.
        self.assertEqual([e["id"] for e in result["evidence"]], ["a", "c"])

    def test_tie_break_lexicographic(self):
        # a 或 b 任一为真即可证明命中; 两者皆真, 选 id 序列字典序最小者.
        facts = make_facts([("a", True), ("b", True)])
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"or": [{"fact": "a"}, {"fact": "b"}]},
                 "sentence": "s1"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual([e["id"] for e in result["evidence"]], ["a"])

    def test_tie_break_across_different_facts(self):
        # 排除 r1 (and 条件, p/r 皆假) 可固定 p 或 r; ("p","q") < ("q","r").
        facts = make_facts([("p", False), ("q", True), ("r", False)])
        template = {
            "rules": [
                {"id": "r1",
                 "condition": {"and": [{"fact": "p"}, {"fact": "r"}]},
                 "sentence": "s1"},
                {"id": "r2", "condition": {"fact": "q"}, "sentence": "s2"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual([e["id"] for e in result["evidence"]], ["p", "q"])

    def test_nested_and_repeated_references(self):
        cond = {"or": [
            {"and": [{"fact": "x"}, {"fact": "y"}]},
            {"and": [{"fact": "x"}, {"fact": "x"}]},  # 重复引用, 只计一次
        ]}
        facts = make_facts([("x", True), ("y", False)])
        template = {
            "rules": [{"id": "r1", "condition": cond, "sentence": "s1"}],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual(result["rule_id"], "r1")
        self.assertEqual([e["id"] for e in result["evidence"]], ["x"])

    def test_same_sentence_rules_not_substitutable(self):
        # 两条规则句子相同, 但证据必须锁定是 r2 命中, 而非 r1.
        facts = make_facts([("p", False), ("q", True)])
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "p"}, "sentence": "same"},
                {"id": "r2", "condition": {"fact": "q"}, "sentence": "same"},
            ],
            "default": {"id": "d", "sentence": "same"},
        }
        result = generate(facts, template)
        self.assertEqual(result["rule_id"], "r2")
        self.assertEqual([e["id"] for e in result["evidence"]], ["p", "q"])

    def test_evidence_preserves_value_and_citation(self):
        facts = [{"id": "m", "value": True, "citation": "阈值>3, 见月报P12"}]
        template = {
            "rules": [
                {"id": "r1", "condition": {"fact": "m"}, "sentence": "s1"},
            ],
            "default": {"id": "d", "sentence": "sd"},
        }
        result = generate(facts, template)
        self.assertEqual(result["evidence"],
                         [{"id": "m", "value": True,
                           "citation": "阈值>3, 见月报P12"}])


def has_nested(cond, depth=0):
    if "fact" in cond:
        return depth >= 2
    children = cond.get("and") or cond.get("or")
    return any(has_nested(c, depth + 1) for c in children)


def has_repeat(cond, seen=None):
    seen = seen if seen is not None else set()
    if "fact" in cond:
        fid = cond["fact"]
        if fid in seen:
            return True
        seen.add(fid)
        return False
    children = cond.get("and") or cond.get("or")
    return any(has_repeat(c, seen) for c in children)


class RandomizedCrossCheckTest(unittest.TestCase):
    SEEDS = list(range(60))

    def test_against_exhaustive_oracle(self):
        coverage = {"mixed": 0, "nested": 0, "repeat": 0,
                    "default": 0, "tie": 0}
        for seed in self.SEEDS:
            rng = random.Random(seed)
            facts, template = random_instance(rng)
            with self.subTest(seed=seed):
                expected_id, expected_ev = oracle_generate(facts, template)
                result = generate(facts, template)
                self.assertEqual(result["rule_id"], expected_id)
                self.assertEqual([e["id"] for e in result["evidence"]],
                                 expected_ev)
                # 证据内容原样保留布尔值与引用说明
                by_id = {f["id"]: f for f in facts}
                for e in result["evidence"]:
                    self.assertEqual(e["value"], by_id[e["id"]]["value"])
                    self.assertEqual(e["citation"],
                                     by_id[e["id"]]["citation"])
            # 覆盖统计
            vals = [f["value"] for f in facts]
            if any(vals) and not all(vals):
                coverage["mixed"] += 1
            if any(has_nested(r["condition"]) for r in template["rules"]):
                coverage["nested"] += 1
            if any(has_repeat(r["condition"]) for r in template["rules"]):
                coverage["repeat"] += 1
            if expected_id == template["default"]["id"]:
                coverage["default"] += 1
            # 并列最优: 存在另一个同样大小的有效证据集
            values = {f["id"]: f["value"] for f in facts}
            ids = sorted(values)
            alts = 0
            for combo in itertools.combinations(ids, len(expected_ev)):
                fixed = {i: values[i] for i in combo}
                free = [i for i in ids if i not in fixed]
                if all(
                    _oracle_select(template,
                                   {**fixed, **dict(zip(free, bits))})
                    == expected_id
                    for bits in itertools.product([False, True],
                                                  repeat=len(free))
                ):
                    alts += 1
            if alts > 1:
                coverage["tie"] += 1
        for key, count in coverage.items():
            self.assertGreater(count, 0, f"场景未覆盖: {key}")


if __name__ == "__main__":
    unittest.main()
