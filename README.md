# task26100476

NarrativeForge 最小选句依据组件（纯 Python 标准库）。

## 运行测试

```sh
python3 -m unittest test_narrative_forge.py -v
```

## 接口

`narrative_forge.generate(facts, template)` 返回
`{"rule_id", "sentence", "evidence"}`，证据按事实 id 升序，
每项保留输入的布尔值与引用说明。条件编码见 `narrative_forge.py` 模块 docstring。

## 复杂度与最坏情况

设相关事实数 n（被选中规则及其之前规则引用到的不同事实数）、
规则数 R、单条条件树大小 C：

- 选中规则：一次求值，O(R·C)。
- 证据搜索：按子集大小递增枚举，每个子集做三值求值验证，
  共 O(2^n · R · C)。
- 最坏情况：最小证据接近全集（例如默认句且所有规则都是
  只含假事实的 and 条件），需枚举约 2^n 个子集，即指数级。
  这是"最小证书"问题的固有代价；组件面向小规模规则集，
  且只统计相关事实（n 通常远小于事实总数）。
