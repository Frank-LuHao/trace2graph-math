# 紧凑走线图：输入、构建和复现

默认使用包内 `scripts/render_graph.py`、`scripts/render_routed.cjs`、`scripts/root_layout.cjs` 和 `assets/routed/`，无需复制上一任务的脚本。渲染版本为 `routed-1.1`；规范图仍采用 `exploration-graph/1.0`，显示、布局分别版本化。固定样式保留在资源文件中，不能靠提示词要求下一次绘图“看起来一样”。

## 一次构建

先完成规范数据及覆盖检查。准备支持 Node >=20 的环境、Python jsonschema 和 Chrome。Codex 桌面可用 `load_workspace_dependencies` 查询随应用提供的 Node/模块目录，传 `--node /absolute/node --node-modules /absolute/node_modules`，不要写死用户机器路径。模块版本必须匹配包内 `scripts/package.json`：Graphviz WASM `@viz-js/viz=3.25.0`，Playwright `1.62.1`。

没有匹配模块时，将依赖安装在任务输出目录：

```bash
mkdir -p "$OUT/.render-runtime"
cp "$SKILL_DIR/scripts/package.json" "$OUT/.render-runtime/package.json"
npm install --prefix "$OUT/.render-runtime" --ignore-scripts --no-audit --no-fund
python3 "$SKILL_DIR/scripts/render_graph.py" "$OUT/graph.json" \
  --output "$OUT/graph.html" --node-modules "$OUT/.render-runtime/node_modules"
```

默认启动 `--browser-channel chrome`。其他 Chromium 可传 `--browser-executable /absolute/browser`；需沙箱外启动时仅为本地渲染申请相应权限。浏览器或依赖缺失时说明缺项，不用其他布局冒充完成。构建和打开成品不请求网络；依赖安装可能需要网络。

输出文件同名：

| 后缀 | 内容 |
|---|---|
| `.html` | 嵌入数据、样式、交互和最终坐标，离线可用 |
| `.png` | 1.5 倍像素密度的纯图，适合文档插图 |
| `.svg` | 使用 foreignObject 保留 HTML 排版；浏览器可显示，部分非浏览器软件不支持 |
| `.source.json` | 完整输入副本，保留实例和证据 |
| `.display.json` | 无坐标显示模型 |
| `.layout.json` | 实际节点尺寸、坐标及连线路径 |
| `.view.json` | 显示模型与布局的完整快照 |
| `.render-audit.json` | 版本、内容 hash、结构与视觉检查 |

## 显示模型 `trace2graph-view/1.0`

普通输入是规范状态图，脚本自动产生显示模型。不要手工将日志顺序变成边。

- 顶层：`schema_version`、`semantic_model`、`graph_id`、`nodes[]`、`edges[]`、`scope`。状态图保留完整 `source_graph`，校验显示结构及状态标记与源图一致。
- 根节点：`root_id` 指向题目初始结点。状态图从 `source_graph.initial_state_id` 精确定位；模块图用显式 `root_id` 指定 `task`，或使用唯一无入边的 `task`。多个独立问题应分别绘制，不按节点数组顺序、S0 字样或最上方位置猜根。
- 根的显示标题统一为“原题条件”，`root=true`、`preview=""`；原名保留为 `source_label`。完整问题条件仍在内容和详情中，原始规范图不改名、不改内容。根节点内文字水平居中。
- 节点：`id` 是布局键；`canonical_id` 是源图 ID；`role=state|action|task|method`；`label` 是数学内容标题；`body` 为摘要；`tone=neutral|success|failed|unknown`；`evidence_refs[]` 为证据。完整内容、观察、待解目标进入详情。
- 动作节点附 `source`、`target`、`effect`、`outcome`、`parameters`、`transition_ids[]` 和重复次数 `count`。它是动作边的展开，不是新的 solution state。
- 边：`id,source,target,kind`，源图动作边带 `transition_ids[]`。`attempt` 表示状态→动作；`transition` 表示动作→实际新状态。未改变状态和未知目标只展示从源状态延伸的动作叶，完整数据仍分别记录 `source=target` 或 `target=null`。
- 只有起终点、完整动作、effect、outcome 都相同时才聚合显示，保留全部实例 ID。多个无进展搜索应从同一状态分叉。
- 明确的组合依赖可放在动作参数 `requires_states: [完整状态ID]`，渲染为 `requires` 虚线，不计作额外动作。兼容旧 `merge_requires` 和可唯一匹配的短 ID；新数据使用完整 ID，不根据标题猜依赖。

兼容旧数学模块图时可显式 `--view` 输入上述显示协议并声明 `semantic_model=method_dependency`；节点仅用 `task|method`，边仅用 `decomposition|dependency|requires|probe`（probe 仅记录样例试验关联）。分解线用虚线。只有表示完整已通过结果的节点才能设绿色，并填写 `acceptance_scope=complete_task` 与 `validation_evidence_refs`。不能把整题通过标记放到局部终止性、上界或某个引理模块上。该模式保留旧依赖结构，不宣称恢复了探索轨迹。

## 布局与验收

- 先测量真实字体和节点高度，再用 dot 正交布线；转角半径 9px，交叉处白色底线。多个尝试紧凑排列，无形排版约束不输出为数学边。
- dot 后使用 `centerRoot(layout, rootId)`：将根及首个分叉前的独立主线放在画布中轴，把分叉出口接回原有走线；必要时仅增加出口区的纵向间距，不靠扩大横向空白来居中普通图。后续分支、合流、动作实例和颜色保持。存在回边或其他并行根时保留走线，用对称边距居中声明的初始节点，并在 `root_presentation.mode` 说明回退方式。
- 图面只保留节点内容与连线。S0/M0 等 ID 留在数据和详情中。状态浅蓝；未成功的尝试叶红；验证完整通过绿；结果未观察到或待定灰。单一路径动作可缩为连线中的文字。完整数学文本不因摘要截断而丢失。
- 校验根标题、文字居中和根中心相对画布中轴的误差（≤1px），并校验节点和边的 ID/端点一致、节点不重叠、文字不溢出、线不穿过无关节点、详情可打开；不擅自删除失败分支、合流或回退来通过布局检查。循环会关闭只适合 DAG 的分支网格约束。审计保存 `root_presentation`、移动节点与新增高度。
- 查看至少一张复杂分叉/合流图及一个未完成案例。结构和几何检查不能证明数学标注正确；状态划分和最终验收范围仍需语义审查。

布局可重放：

```bash
python3 "$SKILL_DIR/scripts/render_graph.py" "$OUT/graph.json" \
  --output "$OUT/replay/graph.html" --node-modules "$OUT/.render-runtime/node_modules" \
  --layout "$OUT/graph.layout.json"
```

只有显示内容 hash 一致才接受旧布局。保存源 JSON、模板/脚本版本、依赖锁文件、布局与审计报告；同一浏览器版本、系统字体和像素密度下可比较 PNG hash。跨系统字体或 Chrome 版本变化可能影响换行与像素，固定坐标不能保证像素一致；尺寸不匹配会报错而不静默截断。规范数据中的缺失证据不能由复现图片补齐。

需要多个问题时，对每份规范图重复执行同一命令，将图片组织到外层索引；问题和模型标题放在索引，不叠到图里。更新远端文档属于后续用户授权的独立动作。
