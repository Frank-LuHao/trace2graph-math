# 探索状态图协议 v1.0

机器接口以 [exploration-graph.schema.json](exploration-graph.schema.json) 为准。UTF-8 JSON，不接受 NaN/Infinity。

## 数学模型

采用有向多重图 `G=(S,E)`。`S` 为 solution states，`E` 为动作实例。
`e=(id,source,action,target,effect,outcome)`；允许自环、重边、分叉、合流和回退。
`target=null` 表示尚无法确认结果状态，不添加假想状态。动作框是边的展开，不计为状态。
最终验证在已有状态上标记 `acceptance`，无需新增内容相同的终止节点。

## 顶层必填字段

| 字段 | 定义 |
|---|---|
| schema_version | 固定 `1.0` |
| graph_id, title | 稳定 ID、人读标题 |
| initial_state_id | 本图任务初始状态 ID |
| granularity | `rule_version`、`state_rule`、`action_rule`；记录选用规则原文或等价的完整定义 |
| coverage | `scope` 与 `limitations[]`；声明文件、任务、局部范围及缺口 |
| states | 状态列表 |
| transitions | 动作实例列表，重复执行各有 ID |
| observations | 搜索、验证、执行、环境等反馈 |
| sources, evidence | 来源文件和定位证据 |
| state_aliases | 有依据的状态归约映射；无归约时 `[]` |

ID 只能使用字母、数字、`_ . : -`，首字符为字母或数字。各列表内 ID 唯一。引用不得悬空。

## 状态和动作

```json
{
  "id": "s0",
  "label": "目标不等式，尚无证书",
  "content": {
    "representation": "在指定实数域与约束下证明目标式非负",
    "candidate": null,
    "established": [],
    "open_goals": ["构造非负性证书"]
  },
  "content_scope": "summary",
  "acceptance": "unverified",
  "evidence_refs": ["src1.L1.B0"]
}
```

`content_scope=summary|snapshot`。未恢复内容用 `null`，不能把缺失摘要当等价。`acceptance=unverified|passed|failed`；passed 必须没有数学待解目标，并有关联的、附证据的最终验证通过观察。局部编译通过不足以推断任务通过。

```json
{
  "id": "a1",
  "source": "s0",
  "target": "s0",
  "action": {
    "type_id": "search.quadratic",
    "label": "搜索二次平方和证书",
    "group": "直接系数搜索",
    "goal": "证明目标式非负",
    "method": "待定系数并求解",
    "parameters": {"degree": 2}
  },
  "effect": "unchanged",
  "outcome": "not_found",
  "evidence_refs": ["src1.L2.B0", "src1.L3.B0"],
  "order": {},
  "metrics": {"duration_ms": null, "tokens": null}
}
```

- `effect=unchanged` ⇔ `source=target`；`changed` ⇔ 有不同的已知起终点；`unknown` ⇔ `target=null`。
- `outcome=progress|not_found|counterexample|error|abandoned|unknown`，与 effect 独立；反例可能改变候选，而错误未必改变状态。
- 同一 `type_id` 对应完全相同的 action 定义（含目标、方法、参数、分组和标题），执行实例 ID 仍不同。
- `order={}` 或 `{"batch_id":"b1","position":1}`。只记录已观察到的批内顺序。跨线程顺序留在 `events.json` 的 session、parent、timestamp、source-line 信息中，不由数组顺序猜测。
- `metrics` 未知用 null。共享一次调用的多个候选不得重复计费；无法归属时在动作层留空。

## 观察、证据与归约

```json
{
  "id": "o1", "subject_type": "transition", "subject_id": "a1",
  "kind": "search_result", "verdict": "not_applicable",
  "summary": "指定次数内未找到证书；不代表证书不存在",
  "evidence_refs": ["src1.L3.B0"]
}
```

`subject_type=state|transition`；`kind=search_result|validation|execution|environment|note`；`verdict=passed|failed|unknown|not_applicable`。verdict 专指观察中的验证结论，不能由 exit code 推断数学结论。

`sources` 每条为 `{id,path,sha256}`。`evidence` 每条为 `{id,source_id,line,output_line,timestamp,summary}`，行号从 1 起；`output_line` 和 `timestamp` 可为 null。标准化工具给调用与输出各自生成证据，不强制合并成一段。引用标准化证据时保留其 ID 和定位；补充文件证据时增加新 source/evidence。

`state_aliases` 每条为 `{original_id,canonical_id,basis,reason,evidence_refs}`。`basis=syntactic_normalization|verified_equivalence`；依据证据不得为空。归约后的图不保留 original 节点；端点和观察主体全部直接使用 canonical ID。

`merge-decisions.json` 是独立审查表，不改变协议：

```json
{
  "schema_version": "merge-decisions/1.0",
  "decisions": [{
    "state_ids": ["s2", "s5"],
    "decision": "keep_separate",
    "canonical_id": null,
    "comparison": {
      "representation": "equivalent",
      "candidate": "unknown",
      "established": "equivalent",
      "open_goals": "equivalent"
    },
    "reason": "未记录完整候选，不能证明等价",
    "evidence_refs": ["src1.L8.B0"]
  }]
}
```

`decision=merge|keep_separate|unresolved`，comparison 各项为 `equivalent|different|unknown`。只有全部 equivalent 且说明依据才 merge；`canonical_id` 为保留状态 ID。保留 `graph.before-merge.json`，逐项审查归约前后动作实例、证据和成本未丢失。脚本不自动审定这份表中的数学理由。

## 展示与验证边界

`graph_protocol.py` 先校验，再生成 `.view.json` 并渲染 SVG/HTML。仅当 source、target、完整 action、effect、outcome 完全相同，显示层才折叠动作框；`transition_ids` 保留所有实例。状态布局使用可达性顺序，不表示时间。

状态、动作组可点击显示数学内容、实例、观察和来源；支持未知目标、循环、断开的状态，不要求 DAG。所有来源文本按文本渲染，不作为 HTML 执行。标准程序不读取标题推断拓扑、不判断等价、不清除失败边。样式更改不应改变规范 JSON。

Schema 与程序校验只证明字段、引用和部分语义约束一致。LLM 仍需审查：切分粒度、等价依据、实际因果起点、真假数学结论及最终验收范围。
