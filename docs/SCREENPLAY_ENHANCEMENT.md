# 剧本影视化优化：调研与工作流整合

> **全局生效。** 本规范适用于所有 `novel-cinematic` 故事，不是王六郎项目
> 专用；以后每个故事都必须经过 `screenplay` 门禁和 `scene_plan` 镜头拆分。

## 调研结论

仓库里已有三类相邻能力，但没有一个专门做“在忠实剧本基础上增加影视化镜头”的 skill：

| 现有能力 | 作用 | 为什么不满足 |
|---|---|---|
| `pipelines/novel-cinematic/novel-director.md` | 把小说拆成忠实的基础剧本 | 只保证事实与节奏，不做视觉 enrich |
| `pipelines/cinematic/script-director.md` | 预告片式 beat map、标题卡、reveal | 面向既有素材剪辑，不是小说/剧本增写 |
| `creative/storytelling.md` | 解释型视频的 hook、结构和节奏 | 面向 explainer，不是叙事电影 |
| `creative/enhancement-strategy.md` | 叠加层/信息图密度 | 不是剧作 |

因此新增一个专门阶段：`screenplay`，由
`pipelines/novel-cinematic/screenplay-director.md` 驱动。

## 它做什么

输入：

- `script`：忠实基础剧本；
- 原文/段落 ids；
- 目标时长；
- 已批准的角色、场景、声音约束。

输出：

- `screenplay_treatment`：logline、主题、视觉母题、beat map、新增镜头、
  镜头机会、转场、声音计划、fidelity ledger、未采用想法；
- 增强后的 `script`：保留原 section 和原台词，新增视觉 section；时间连贯，
  按剧情需要决定总时长。目标时长只是规划估计，不是硬上限。

对白原则：

- **对白优先，旁白最后。** 能在场景里由人物说出来的，不要用旁白解释。
- 旁白只用于角色无法见证的时间跳跃；不要用旁白复述画面。
- 可以写连接性对白（招呼、拒绝、追问、警告、玩笑、告别），但每一句
  新对白都要登记在 `added_dialogue`，写清它服务的原文事实和戏剧目的。
- 不为对白新增剧情事件、角色、地点或结局。

核心边界：

- 可以加：反应镜头、物件插入、门槛/出入画、母题 setup/payoff、声音桥、
  负空间、静默、镜头语言、已隐含的天气/光线/质感。
- 不可以加：新角色、新地点、新剧情事件、改结局、把原文留白解释成新事实。
- 连接性对白可以写，但必须登记在 `added_dialogue`，不能借对白新增剧情事实。
- 新增镜头必须引用原文段落；如果它只是重复信息或装饰，就删掉；如果剧情
  需要呼吸，就允许成片变长。没有硬性时长上限。
- 每个新增镜头都要在 fidelity ledger 里有一行。

## 工作流位置

```text
breakdown -> screenplay -> scene_plan -> assets -> edit -> compose -> publish
```

- `breakdown` 仍由 `novel-director` 写忠实基础剧本；
- `screenplay` 是新的影视化优化门禁，必须人工批准；
- `scene_plan` 同时读取增强 `script` 和 `screenplay_treatment`，把每个
  scene 拆成 **3–12 个 H3 镜头（通常 3–7 个），每个 take ≤328 帧（参考图 ≤3）或 ≤260 帧（参考图 4+）**；每个镜头写清帧数、机位、
  光、走位、对白、连续性和 H3 提示；不能把整场塞进一个长 take。

## 命令

```bash
# 审计 treatment（schema + runtime + coverage + 台词保真）
PYTHONPATH=.:openmontage .venv-openmontage/bin/python scripts/audit_screenplay.py \
  --treatment projects/<id>/artifacts/screenplay_treatment.json \
  --script projects/<id>/artifacts/script_breakdown.json \
  --out projects/<id>/artifacts/screenplay_audit.json
```

产出必须 `status="pass"`，然后写 `awaiting_human` checkpoint，向用户展示：

- 3–5 个最高价值新增镜头；
- 每个的 fidelity risk；
- runtime 与规划估计的差异（只提示，不设上限）；
- 需要用户拍板的问题。

## 模板

- `openmontage/skills/pipelines/novel-cinematic/screenplay-treatment-template.json`
- Schema：`openmontage/schemas/artifacts/screenplay_treatment.schema.json`
- Skill：`openmontage/skills/pipelines/novel-cinematic/screenplay-director.md`

## 角色参考图联动

新故事的男女主参考图按
[`CHARACTER_ASSET_SHEET.md`](CHARACTER_ASSET_SHEET.md) 的两视图资产卡规范
生成；`screenplay` 阶段在写新增镜头时必须遵守已经批准的角色/场景资产，
不得为了一个视觉想法临时增加新角色或新地点。

> 剧本层的专业标准（钩子、场景目标/障碍/转折、潜台词、覆盖、轴线、母题、结尾行动）见 [`SCREENPLAY_CRAFT.md`](SCREENPLAY_CRAFT.md)。
