# ArcReel 适配与操作

## 适配范围

本工程是本地独立执行器，参考固定版本 ArcReel 的制作顺序和数据契约。没有声称将其完整网站、Claude Agent SDK、供应商客户端或 MCP 服务部署完成，也没有改写 vendor 源码。

直接对照的上游文件：`lib/asset_types.py`、`lib/script_models.py`、`lib/workflow_rules.py`、ADR 0041（内容/视觉分离）和 ADR 0072（角色衍生身份）。

| ArcReel 概念 | 本工程落点 |
| --- | --- |
| project_input / 原文 | `book.json`、`paragraphs.json`、无损原文副本 |
| asset_inventory | `bible/assets.json`：characters、scenes、props，事实/设计/证据分离 |
| character derivatives | 主角色下 `derivatives`；以 `角色/衍生` 引用，以主角色绑定台词 |
| episode_plan | `series.json` 和全书覆盖表；分集总表需由逐章分析形成 |
| script_plan_content | `content_plans/<episode>.json` 中的 `script`，符合 `DramaNormalizedScript` |
| script_plan_review | 按内容 SHA-256 保存审批记录；修改内容后自动失效 |
| prompt_authoring | 视觉工作单只返回 ID、图片提示词、H3 指令、对白时段 |
| storyboard / reference video | Images 2.5 首帧参考或 H3 Ref2VA 多图参考 |
| final_script | `episodes/` 中的精确 H3 帧级分镜 |
| export | `arcreel_export/<episode>/script.json` 和 `h3.json`；最终 MP4 / SRT / 报告 |

导出的 `script.json` 通过 ArcReel `DramaEpisodeScript` 数据模型验证。它是**剧本数据导出**，并非完整可直接恢复的 ArcReel 项目归档：原生数据库、全局资产库、供应商任务、成本记录、剪映草稿没有移植。`h3.json` 保存准确帧数、续接状态和模型指令；上游整数秒 `duration_seconds` 保留为编辑目标，不能拿来替代真实视频时长。

## 数据与回执

`examples/arcreel_content.json` 的外层包含本工程分集 ID、戏剧问题、转折、原文段落映射；内层 `script` 使用 ArcReel 模型。`source_text` 是逐字原文依据，不会被朗读。`utterances` 才是发声文本；对原文对白的必要改编要在内容层审阅，视觉层不能再改写。

`examples/arcreel_visual.json` 展示视觉输出。`h3.location_id` 是物理场景锚点，`scene_id` 是 ArcReel 分镜编号，两者不能混用。续接时物理场景、出场资产、出口/入口状态必须一致。

图片回执只允许记录真实工具输出。以下是字段说明，**不是可直接伪装生成来源的有效回执**：

```json
{
  "tool": "image_gen",
  "job_sha256": "实际图片工作单的 SHA-256",
  "generated_at": "实际工具完成时间",
  "prompt": "实际提交的提示词",
  "model_verified": false,
  "actual_model": "unknown",
  "model_evidence": "工具实际返回的型号证据；缺失时保持不可核实"
}
```

`model_verified` 不能根据请求型号、文件名、提示词或软件签名版本自行改成 true。当前项目按用户选择启用了真实内置工具、型号未知的路径；回执仍为 unknown/false，不得伪造型号。没有启用该策略的项目仍要求可核实的 Images 2.5 输出。程序检查回执、任务和文件的一致性；它不是能独立认证 OpenAI 后端的鉴定系统。

已生成但未验收的图片可登记为历史素材，型号满足项目策略且依赖参考图均已验收、文件与任务指纹均未变化，才能批准并进入视频图。衍生图记录基础图版本，基础图变化即失效。图片工具执行时先查看所有本地参考图，再通过 `referenced_image_paths` 传入；没有本地路径的会话图按内置工具实际机制交接。

## 操作命令

以下命令由 Codex 执行，也可在项目目录手工运行。网页提供对应阅读、导入、审阅和生成操作。

```bash
cd /home/jx/codes/novel-h3-studio

# 阅读指定物理章节；分析输出必须覆盖该章全部段落并有实际原文证据
python3 studio.py packet s0003
python3 studio.py import-analysis /absolute/path/chapter_result.json
python3 studio.py series-packet

# 导入角色、场景、道具；为基础和衍生形象生成图片工作单
python3 studio.py import-assets /absolute/path/assets.json
python3 studio.py asset-jobs

# 内容锁定后，取得视觉任务；示例仅为技术样片
python3 studio.py import-content examples/arcreel_content.json
python3 studio.py approve-content proof_tongtian --reviewer Codex --note '记录实际内容审阅结论'
python3 studio.py visual-packet proof_tongtian
python3 studio.py compile-visual proof_tongtian examples/arcreel_visual.json

# 当前图片工具生成后，登记真实文件与回执；型号策略、任务与参考图均需核对
python3 studio.py register-image keyframe_tongtian_001 /absolute/path/generated.png /absolute/path/receipt.json
python3 studio.py approve-image keyframe_tongtian_001 --reviewer Codex --note '记录实际视觉审阅结论'

# 在上镜通过后逐镜提交。失败或网络不确定时先同步，禁止盲目重试
python3 studio.py validate proof_tongtian
python3 studio.py approve-plan proof_tongtian --reviewer Codex --note '记录实际导演审阅结论'
python3 studio.py submit proof_tongtian
python3 studio.py sync
python3 studio.py cancel

# 用实际审片记录验收；检查项见 examples/review_template.json
python3 studio.py review-take t_ACTUAL_ID /absolute/path/review.json
python3 studio.py assemble proof_tongtian
python3 studio.py coverage
python3 studio.py assemble-book

# 每章一个固定文件；同章重做会原子覆盖旧文件
python3 studio.py assemble-chapter s0007

# 覆盖更新唯一的“截至当前已生成章节”全量视频
python3 studio.py assemble-latest
```

首次迁移至另一目录时，使用 `studio.py --project /absolute/project init /absolute/source.txt` 新建项目；当前项目已导入，不应重新初始化。`config.json` 中本机 ComfyUI 路径和独立输出目录须与实际部署一致。本机程序不下载大型模型。

程序不默认猜测头less Codex 的图片权限，不读取订阅凭据，不逆向 ChatGPT 私有接口，也不替换成 ArcReel 默认生图供应商。

## 续接、恢复与版本

H3 首镜保存完整采样后的 AV latent。下一连续镜仅引用已验收的前镜 latent；Motion Context 不替代换场剪辑，不保证无限长一致性。工作图随实际任务保存在 `renders/<take>/prompt.json`。

提交前先持久化唯一任务 ID。网络超时保留“提交待核实”，同步时从 ComfyUI 历史和队列的 `novel_h3_take` 找回原任务，避免重复采样。取消只删除本工程待运行项；只有运行项属于本工程才调用中断，保留已产生素材。

素材指纹含原文、内容与分镜版本、图片、模型、参数、风格、上游版本，以及前镜实际 take 和视频哈希。正式分集若跳过内容锁定、改台词或改原文引用，将被拒绝。视频或 latent 被外部修改，也不能继续传播原验收。

项目状态与每份工作单可备份恢复。持续制作前需预估磁盘：每镜 AV latent、视频、失败版本和合成中间文件都会增长。当前没有自动删除失败版本或长期磁盘配额任务；任何清理应先确认要保留的验收版本。

## 制作预览与声音分析

`submit-preview` 允许在真实画面抽查后继续样片制作，沿用实际观察到的结尾状态；它不会把镜头变为已验收。`assemble-preview` 输出 `previews/` 中的粗剪，并明确标记尚未验收。正式 `assemble` 和 `assemble-book` 仍检查完整审片及全书覆盖。

章节交付使用两个固定输出：`chapter_videos/chapter_s####.mp4` 为每个已有章节的当前版本，`final/latest_full_video.mp4` 为按原文顺序合并的全部已生成章节。新增章节后再次运行 `assemble-latest` 会覆盖后者；它只表示当前已有章节，不把未生成章节冒充为完整全书。

本地音频分析见 [本地音频理解](本地音频理解.md)，支持网页和 `studio.py listen`。模型辅助报告与实际视听验收分开记录，不以声学分数冒充人工听音。
