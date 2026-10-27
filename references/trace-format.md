# 输入适配与事件覆盖

## 适配器支持范围

`normalize_trace.py` 逐文件处理 JSONL，不执行日志命令，不扫描其他目录，不访问网络。支持 Python 3.9+，标准化阶段仅用标准库。

- Claude Code：`type=user|assistant` 的 `message.content` 中 text、tool_use、tool_result。通过同一来源/会话的 `tool_use.id` 与 `tool_result.tool_use_id` 配对。保留 uuid、parentUuid、sessionId、isSidechain 和 timestamp。
- Codex：`response_item.payload` 的公开 message、function_call/custom_tool_call 及相应 output；`call_id` 配对。`event_msg` 作为辅助状态流排除，避免与 response_item 双计。若输入只有 event_msg，则当前适配器不能重建完整动作，应报告缺口并编写针对实际格式的适配，不宣称无动作。
- thinking、redacted_thinking、reasoning、analysis 和加密内容排除；图片/音频/文档块只记录排除位置。API 请求副本、重复元数据等不作为新动作。排除列表不含原始隐藏内容。
- 已识别的 attachment 元数据（environment、model、工具/agent/skill 列表、session_context、date、remote_session_change、prompt_snapshot、deferred_tools_record）按各自类型记录排除。它们不是新动作；与任务相关的环境变化必要时定点核查，不把技能列表当调用证据。
- 未识别记录、无效 JSON、缺失结果、孤立结果保留为事件或 issues；不可静默丢弃。未知 attachment 等未支持记录须检查是否含任务相关的公开上下文。
- 新 harness/version 的结构若不同，先检查字段类型再扩展适配器；不要将本例布局冒充所有版本的通用格式。

## 标准化输出

`events.json` 顶层含 `schema_version=trace-events/1.0`、sources、evidence、events、excluded、issues、counts。
sources 包含绝对路径、完整输入字节 SHA-256、行数和检测到的格式。生成 graph.sources 时仅复制协议字段 `id,path,sha256`。

每个 event 包含来源/行号/block、session/uuid/parent 信息、kind、payload、truncated、evidence_refs。tool event 额外含 call_id、input_fingerprint、results、pairing。调用和结果可能占多行；每个结果都保留定位。不同来源文件不自动去重或跨文件配对，LLM 应核实重叠/父子关系。

同一 call ID 且完整规范化输入相同视为同次调用快照，附加证据，不创建重复执行。不同 call ID 保留为不同调用，即使参数一致。相同 call ID 但输入不同视为冲突，保留全部调用、把无法唯一配对的结果标为 ambiguous。这里只判断日志实例身份，不归约数学状态。

标准化默认每个 payload 最多 16000 字符，超出保留 preview、total_chars 并标 truncated。不能仅凭 preview 宣称事件已经完整解释；可提高 `--max-chars` 后重新标准化，或定点提取相关公开字段。不要把截断误判为没有结果。配对成功也不表示执行或任务成功。

## 覆盖表

每个 normalized event 恰有一条覆盖记录，允许一个事件关联多个动作（例如一批候选），也允许多事件关联同一尝试。LLM 写入：

```json
{
  "schema_version": "trace-coverage/1.0",
  "items": [
    {"event_id":"event.src1.L1.B0", "disposition":"mapped",
     "refs":[{"kind":"state","id":"s0"}], "reason":"定义问题初始条件"},
    {"event_id":"event.src1.L2.B0", "disposition":"mapped",
     "refs":[{"kind":"transition","id":"a1"}], "reason":"搜索二次证书并得到未找到结果"},
    {"event_id":"event.src1.L7.B0", "disposition":"excluded",
     "refs":[], "reason":"仅查询系统时间，与解状态无关"},
    {"event_id":"event.src1.L9.B0", "disposition":"unresolved",
     "refs":[], "reason":"输出缺失，无法判断对候选的影响"}
  ]
}
```

`refs.kind=state|transition|observation`，须引用归约后的 graph ID。mapped 须至少有一个引用，且引用记录的 evidence_refs 与此事件的证据相交；excluded/unresolved 不附引用，原因不得空。仅因失败、无最终答案或未通过验收不能 excluded。输入损坏/意义不明用 unresolved，不用 excluded 掩盖。

`audit_coverage.py` 检查事件是否逐条有处置、引用是否存在且有共同证据、graph.sources 与标准化来源是否一致、证据定位是否漂移，并复核输入文件哈希。输出结构校验、覆盖计数、unresolved 和适配问题。

所有事件都有记录意味着“已逐项处置”，不意味着“语义已全部重建”。存在 unresolved、truncation、unsupported 或缺失配对时，要在 graph.coverage.limitations 和交付说明中明确。excluded 的理由是否合理仍需 LLM 审查。

## 审查顺序

1. 从原始要求确定验收条件，查看一个成功、一条失败、一次重试、一处未知去向（若存在）。
2. 确认未找到搜索仍从原状态分叉；验证未制造内容相同的新状态。
3. 逐项审查 merge-decisions，确认不同候选/约束/证书/目标未被合并。
4. 运行结构和覆盖检查，修正异常；检查 HTML 中状态/动作详情和完整实例数。
5. 确认图仅反映指定 trace 的公开证据，报告真实缺口。没有最终通过记录的图同样是有效产物。
