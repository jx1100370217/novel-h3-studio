# novel-h3-studio — OpenMontage cinematic workflow

This repository is the local production host for the **OpenMontage cinematic
pipeline** plus the local FastH3-Omni NVFP4 QAD model service.

The binding workflow guide is [`openmontage/AGENT_GUIDE.md`](openmontage/AGENT_GUIDE.md).
Read it before any production work. The old `novel-cinematic` / `novel_h3`
chain workflow is removed; do not recreate it.

## Architecture

- `openmontage/` — the OpenMontage cinematic workflow: pipeline manifests,
  stage director skills, tools, schemas, checkpoints, Backlot board.
- `novel_h3/` — only the local model service backend:
  `fastvideo.py`, `project.py`, `safety.py`, `previs.py`,
  `previs_render.py`, `transition_audit.py`, `ref2va.py`, `memory_guard.py`.
- `projects/` — production data (scripts, scene plans, prompts, requests,
  shots, music, subtitles, renders).
- `runtime/` — model runtime, FastVideo service, caches.

## Defaults

- **Workflow: OpenMontage `cinematic`.** New projects use
  `studio.py init <project-id> --pipeline cinematic`.
- **Backlot is Chinese.** The board at `studio.py board` / `studio.py serve`
  is the Chinese observer UI; keep new labels in Chinese.
- **Video engine: FastH3-Omni NVFP4 QAD** on `127.0.0.1:8195`, 8 steps,
  1344×768 / 24 fps, native H3 audio.
- **One project = one project directory** with `project.json`,
  `artifacts/`, `assets/`, `prompts/`, `public/`, `renders/`, `exports/`.
- **Prompts/requests are project data.** For cinematic work the source of
  truth is `projects/<id>/assets/requests.json` and `prompts/S*.txt`; do not
  generate a competing prompt stack in a version script.
- **Composition:** project-local Remotion composition (atelier) via
  `video_compose`; use `CinematicRenderer` only when the project chooses the
  standard cut schema.
- **Final audio:** native H3 dialogue/sound effects, music bed ducked under
  speech, subtitles from the project's `.srt` / Remotion props.
- **Douyin publishing:** use the `douyin-publish` skill
  (`.agents/skills/douyin-publish/SKILL.md`); it encodes the creator-center
  flow, correct selectors, cover requirements, and the AI declaration.

## Commands

```bash
# Workflow environment
.venv-openmontage/bin/python studio.py doctor
.venv-openmontage/bin/python studio.py init <project-id> --title "..." --pipeline cinematic
.venv-openmontage/bin/python studio.py board <project-id>
.venv-openmontage/bin/python studio.py serve --port 4751

# FastH3 service
runtime/fastvideo-venv/bin/python start_fastvideo.py \
  --project projects/liaozhai-wangliulang-cinematic
# Full model acquisition/deployment: README.md "模型获取与部署"

# Render the cinematic project's requests one shot at a time
.venv-openmontage/bin/python scripts/render_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic --force

# Measure takes, align dialogue, rebuild props/captions
.venv-openmontage/bin/python scripts/qc_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-dialogue/bin/python scripts/align_cinematic_dialogue.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-openmontage/bin/python scripts/build_cinematic_edit.py \
  --project projects/liaozhai-wangliulang-cinematic

# Tighten action takes: dead-time trims, speed, shake (artifacts/pacing.json)
.venv-openmontage/bin/python scripts/pace_cinematic_shots.py \
  --project projects/liaozhai-wangliulang-cinematic

# Build the music bed and mix it under the picture
.venv-openmontage/bin/python scripts/build_cinematic_music_bed.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-dialogue/bin/python scripts/build_cinematic_score.py \
  --project projects/liaozhai-wangliulang-cinematic
.venv-openmontage/bin/python scripts/mix_cinematic_audio.py \
  --project projects/liaozhai-wangliulang-cinematic

# Compose via the OpenMontage tool registry
.venv-openmontage/bin/python studio.py tool video_compose @compose_picture_payload.json

# Generate the poster + Douyin covers (4:3 + 3:4) in one pass.
# With an approved poster: poster_path. Without one: video_path + poster_time.
.venv-openmontage/bin/python studio.py tool publish_covers @covers_payload.json
```

## Cinematic pipeline rules

1. Run the OpenMontage stages in order: `research` → `proposal` → `script` →
   `scene_plan` → `assets` → `edit` → `compose` → `publish`.
2. Each stage writes its checkpoint and artifact under the project directory.
   Do not skip a gated stage or write a competing artifact format.
3. `scene_plan` defines the shot list and the visual/sound intent. `assets`
   must render the project's `assets/requests.json`, not a different prompt
   stack.
4. Whenever the publish poster is produced, immediately generate platform
   covers with `publish_covers` (4:3 horizontal + 3:4 vertical for Douyin).
   Upload those covers; never hand-crop on the platform upload page.
5. `video_compose` is the only final render path. Atelier composition uses the
   project-local `index.tsx` / `Composition.tsx` / `public/props.json`.
6. **人物名牌与剧情说明卡（强制）**：每部影片在 `artifacts/cards.json` 写 `nameCards`
   （角色名 + 身份，首次出场时出现）和 `titleCards`（剧情推动所需的说明，如“儿媳新丧·尚未下葬”
   “符镇女尸”“县官验尸·写证明”）。`build_cinematic_edit.py` 会把它们写入 `public/props.json`。
   不要用“一”“二”这类无意义的幕间数字卡；说明卡必须帮助观众理解人物关系或剧情因果。
   视觉与文案必须遵循下方 **“统一字幕/说明卡规范（全局，强制）”**。
7. Backlot is an observer/approval UI. Keep it Chinese; do not replace it with
   the upstream English UI.
8. The old `novel-cinematic` coverage/anchor/chain scripts and their pipeline
   are removed. Do not import them from new work.

## 统一字幕/说明卡规范（全局，强制）

所有在本仓库生成的成片（cinematic 及其他含对白/叙事的视频）统一采用
**“毛笔体竖排人物名牌 + 全屏书法剧情卡 + 宋体对白字幕”** 的视觉系统。
新项目不得另起一套字体、版式或卡片层；题材确实需要变体时，只能在
`artifacts/cards.json` 记录变体理由，并保持以下层级、可读性和内容规则。

参考实现：`projects/liaozhai-huabi-cinematic/Composition.tsx` 中的
`InkCard` / `NameCardLayer` / `CaptionLayer`；新项目直接复制这套组件与
`public/fonts/MaShanZheng.ttf`，不要重写另一套样式。
内容示例：`projects/liaozhai-huabi-cinematic/artifacts/cards.json`。

### 1. 视觉系统

- 片名、人物名、剧情卡：`MaShanZheng` 毛笔体；字体文件放
  `public/fonts/MaShanZheng.ttf`，用 `staticFile("fonts/MaShanZheng.ttf")` 加载。
- 人物身份、对白字幕、片尾署名：`Noto Serif CJK SC` 宋体。
- 配色：米白/淡金色字、深色半透明底、暗红细分隔线；不加霓虹、粗描边、
  高饱和渐变或花哨动效。
- 卡片动效：短淡入淡出（约 12–24 帧），不做弹跳、旋转、逐字乱跳。
- 卡片文案只写在 `artifacts/cards.json`，不得硬编码在 `Composition.tsx`。

### 2. 片头卡

- 第 0 帧起约 3 秒：片名（2–4 字）+ 出处/副题（如“聊斋志异”）。
- 全屏轻暗底，毛笔体居中偏上；片名卡只出现一次，片中不重复。

### 3. 人物名牌

- 角色首次清晰出场时出现；写入 `cards.json` 的 `nameCards`。
- 结构：竖排角色名（毛笔体，约 68–84px @1344×768）+ 竖排身份
  （宋体，约 22–26px）。
- 身份写“角色是谁”，4–7 字：如“客居京中的举人”“同游友人”“古寺僧人”
  “东壁散花女”“画中巡查”。不写演员名、不写剧情评论、不新增原作没有的名字。
- 位置：左侧或右侧约 7%，顶部约 18%；深色渐变底 + 暗红竖线；
  不得遮挡面部、嘴部和对白字幕。
- 时长约 1.9–2.5 秒；同一角色只出现一次。

### 4. 时间卡

- 用 `variant: "time"`；顶部居中的横向深色条，毛笔体约 54px，
  如“画中次日”“三日后”“九年后”。
- 时长约 2.3 秒；不要放在画面中央，不遮挡人物脸。
- 只在时间跳跃或空间转换需要时使用，不为每个镜头加时间卡。

### 5. 剧情说明卡

- `titleCards` 的 `variant` 用 `opening` / `act` / `end`；`act` 为全屏近黑底 +
  居中毛笔体，最多两行，每行 4–5 字。
- 只放在改变人物处境/因果的节点：入画、禁令、搜查、召回、真相、结局；
  不要用“一”“二”“上集”等无意义数字卡，也不要用地点流水账。
- 文案写“发生了什么/为什么重要”，可用原作关键句或主题句
  （如“幻由人生”）；每部影片 3–5 张剧情卡为宜。
- 结尾卡优先用原作主题句/诗眼，放在最后一个画面，时长约 3 秒。

### 6. 对白字幕

- 宋体，约 34px @1344×768，底部居中，最大宽度 82%，底部留约 52px。
- 不加粗黑边、不压整条黑底；说明卡出现时，字幕不得与卡片互相遮挡。
- 字幕时间用镜头内相对时间；改了镜头时长后重建字幕与 props。

### 7. 数据与渲染

- 唯一数据源：`artifacts/cards.json`（`titleCards` / `nameCards`），
  字段用 `anchor` + `offset` + `duration`；`build_cinematic_edit.py`
  生成 `public/props.json`。
- 新项目必须把 `MaShanZheng.ttf` 放进 `public/fonts/`。
- 每次改卡片后重渲染，并至少抽帧检查：片头、每个人物名牌、每张剧情卡、
  时间卡、片尾卡；检查是否遮挡脸部/字幕、是否超框、是否与对白重复解释。
- 自动抽帧检查不能替代人工观看；交付前仍须完整看片。

## 统一影像风格：邵氏电影风格（全局，强制）

除非用户明确选择其他风格，所有古装、志怪、奇情、民国及年代题材的
cinematic 项目，默认采用 **1970 年代邵氏电影摄影棚美学**。这是美术与
镜头语言基准，不是复制某一部具体影片、演员、片头标志或配乐。

- **可见的棚景层次**：木作、帷幔、门廊、屏风、壁画、香炉、烛台组成清楚的
  前、中、后景；空间可以有搭建感，但材质、接缝和光影必须可信。
- **色彩与布光**：浓而有层次的赭红、石绿、黛蓝、暖金；钨丝暖主光配克制的
  冷蓝阴影，局部逆光与薄雾只用于区分画内外/前后景。禁止统一金黄滤镜。
- **镜头语言**：稳定构图、硬切、人物反应镜头为主；只在入画、搜查、揭示、
  回头等关键节点使用有目的的推、拉或变焦，不每镜都急推，不滥用慢动作。
- **人物与服装**：成年角色、完整古装发式与层次清楚的衣料；表演略带戏剧性
  但克制，视线和身体朝向要清楚。画面内不得出现现代器物、现代文字或穿帮。
- **质感**：细胶片颗粒、真实皮肤纹理、布料与木石的手工质感；不加划痕、
  闪烁、泛黄或重滤镜去遮住表演。
- **声音**：寺钟、木石、衣料、脚步、锁链、呼吸等现场声优先；对白用 H3
  原生音色；非剧情音乐按下方“统一配乐方案”定制。
- **禁止**：满屏粒子、连续慢动作、每镜急推、统一金色滤镜、无叙事用途的
  群舞、照搬上一部影片的恐怖配乐床。

参考实现：`projects/liaozhai-huabi-cinematic/art-direction.md` 与该项目
`assets/requests.json` / `prompts/S*.txt` 的邵氏棚景、暖金冷蓝和硬切写法。
新项目写 `art-direction.md`、scene_plan 和 H3 prompt 时必须先声明
“1970s Shaw Brothers period fantasy studio look”，再写具体场景。

## 统一配乐方案（全局，强制）

每部影片的配乐必须按题材、时代、地域、情绪曲线和声音设计重新定制；
不得默认复用上一部影片的 music bed、`score_cues.json` 或同一组曲目。
以下方案是默认工作流，不是可重复使用的音轨模板。

### 1. 默认生成方式

- **本机 ACE-Step 1.5（ComfyUI）** 为默认配乐生成器：
  `ace_step_1.5_turbo_aio.safetensors`，instrumental，no vocals；
  8 steps，cfg 1.0，euler/simple；48 kHz。
- 每部影片生成 4–6 个 stem：寺/环境底色、主情感主题、搜查/危险短重音、
  召回/结尾余韵；不要把整片铺成一条连续 wall-to-wall 音乐。
- 生成记录必须写入 `artifacts/music_research.json`：模型、许可证、prompt、
  seed、bpm、调性、源文件、SHA-256、用途、候选与淘汰理由。
- 模型不可用时，才改用 Pixabay / Freesound / Incompetech 等授权来源；
  仍须保存曲目页、许可证、下载记录和哈希，并按本片重新剪辑，不能直接
  把现成曲目整首铺上。

### 2. 配乐方向

- 古装/志怪/奇情按时代与地域选乐器：箫、古筝、二胡、琵琶、扬琴、古琴、
  低频鼓、钟磬等；不要把所有聊斋片都默认成“古琴 + 箫”。
- 恐怖/悬疑优先低频 drone、呼吸、金属/木质纹理、画外声与静默；
  情感段用拨弦、轻弦乐和留白；结尾给主题句或诗眼留余韵。
- 对白段必须让位：搜查、召回的紧张段可用短重音后接静默，不要用连续
  鼓点压住台词。

### 3. 编排与混音

- cue 表写到 `assets/music/score_cues.json`，以镜头 id + 镜头内 offset
  锚定；`scripts/build_cinematic_score.py` 生成
  `assets/music/music_bed.wav`（约 -20 LUFS）。
- 用 `audio_mixer` / `scripts/mix_cinematic_audio.py` 与 H3 原生对白混合，
  对白下侧链压低音乐；成片目标约 -16 LUFS，真峰值不高于 -1 dBTP。
- 片尾保留约 5 秒配乐署名卡；片尾文案只写“本片定制 · 古风器乐”等观众向
  信息，不写模型名、seed 或内部流程。
- 混音后必须人工试听对白可懂度、音乐是否压住台词、cue 进出是否突兀；
  `human_audition_completed` 未完成前不得声称配乐已通过。

参考实现：`projects/liaozhai-huabi-cinematic/assets/music/score_cues.json`、
`artifacts/music_research.json`、`artifacts/music_cue_notes.json`、
`scripts/build_cinematic_score.py`、`scripts/mix_cinematic_audio.py`。
该片的 `temple_a` / `painting_a` / `danger_b` / `return_a` / `return_e`
是“按分镜定制五段式”的参考，不是可复用的音轨。

## 视频审片规则（强制）

- **禁止只抽 2–3 帧就判断一条生成视频的动作是否正确。** 动作可能发生在开头或结尾；固定时间点抽样会漏掉整段表演。
- 每条 take 的动作审片必须生成覆盖**完整时间线**的 contact sheet，至少 2 fps，且必须包含首帧与末帧；必要时用 0.5 秒间隔复核。
- 对白/表演镜头必须逐项检查：动作起点、动作过程、说台词时的身体朝向与视线、结束状态；不能只看“整体构图”。
- 在声称某个动作缺失、错误或需要重拍之前，必须先用完整时间线复核。只看过局部帧时，不得下结论。
- QC 记录必须写明抽帧时间点；审片结论必须能追溯到具体帧。
- 快速生成全时间线审片图：
  ```bash
  ffmpeg -i <take>.mp4 -vf "fps=2,scale=420:-1,tile=5x4" -frames:v 1 review_sheet.jpg -y
  ```
- **案例（S20，2026-11-12）**：只抽 2s / 5s / 8.5s 三帧，漏掉了 0–1s 的敲门动作，误判为“没有敲门”。实际动作存在，真正的问题是喊“救命”时没有面向庙门。此后同类判断必须先看完整时间线。

## 动作镜头节奏规则（强制）

- **静止尾段必须裁掉**：动作、追逐、打斗镜头里连续静止超过约 1.5 秒的尾段要裁掉。判断依据是逐秒运动量或全时间线 contact sheet，不能凭单帧或印象。
- **动作戏用多镜头切角**：同一段动作优先写成多镜头 prompt（`[Shot N] At MM:SS.mmm`），每段约 5 秒（124 帧），一个镜头只放一个主要动作。不要用单机位长镜头硬拍 3–5 个动作，那样会拍成慢动作。
- **修剪只走配方**：用 `scripts/pace_cinematic_shots.py` 和 `artifacts/pacing.json` 裁剪、变速、加抖动；原始镜头不动，成片写入 `public/shots`。带台词的镜头只允许裁尾部，脚本会拒绝其他修剪（字幕时间按镜头起点计算）。
- **时间线随动**：卡片用 `anchor` + `offset` 锚定到镜头；字幕用镜头内相对时间（`local_start` / `local_end`）。改了镜头时长后，依次重建剪辑、配乐、合成载荷。
- **音效要卡点**：动作音效写入 `artifacts/sfx_cues.json`（按镜头内偏移），由 `scripts/build_cinematic_score.py` 与配乐一起生成；偏移应对照运动峰值或全时间线确定，不要在临时脚本里硬编码绝对时间。

## FastH3 生成与字幕清理规则（强制）

- **近景用脸部主参考**：特写/近景绑定 `assets/refs/faces/<name>_face.png`；全身参考只用于中远景。全身图的脸太小，近景会漂移成另一张脸。
- **所有含对白的 H3 分镜必须做强绑定（无条件，不等出错）**：每个说话角色先有
  `assets/voices/<name>_ref.wav` 音色参考；每句对白写成
  `<Subject N> (Sx) <Audio M>: <d>[Chinese] ...</d>`；`subject_definitions` 定义
  `<Audio M>` 是 `<Subject N> (Sx)` 的音色参考；`retention_analysis` 用 `reference`，
  只借音色/节奏，不复制参考录音。多人口型镜头保留双人/群像构图，用音频绑定和
  “说话者才动嘴、听者闭嘴”约束解决，不默认切单人特写。
  `scripts/render_cinematic_shots.py` 在启动 FastH3 前强制预检：缺少
  `reference_audio_paths`、`<Audio N>` 或每句 `(Sx) <Audio N>` 绑定的项目直接拒绝渲染。
- **每镜 1–2 个命名角色**：需要 3 人以上或复杂动作时，拆成近景、反应镜、阴影/画外音，不要让 H3 在一个镜头里完成多人调度。
- **恐怖动作靠镜头语法**：优先拍头部突然转动、手/指甲、影子、门缝、反应脸、POV/手持追逐、负空间和突然贴近；用硬切与声音/静默制造节奏，不要依赖全身“走过去/扑过去”的僵硬动作。说话人的对白必须由画面内本人嘴部承担；女鬼/怪物不能替人说话，必要时只拍她的手/身体，把脸移出画外。
- **原生字幕用字形蒙版清理**：不要把整条底部压黑。用
  ```bash
  .venv-dialogue/bin/python scripts/remove_captions_glyph.py --project projects/<id>
  ```
  只检测白色字形、膨胀后 LaMa 修补，输出到 `public/shots`，原始 take 留在 `assets/shots`。
  **只对确认有烧录字幕的镜头运行**：脚本按亮度阈值找白色像素，白色袍袖、符纸、布帘在底部时会被误判（逐帧“清理”，涂抹衣料）。无台词镜头和没有可见字幕的镜头一律用原始 take；运行前先抽底部条带确认。
- **长批量每镜重启 FastH3**：`render_cinematic_shots.py --service-unit om-fastvideo --restart-every 1`；失败后也重启。主机 swap 接近满时先释放内存再提交。
- **scene_plan 的每个 shot 必须有 `duration_seconds`**；旧文件缺字段时，脚本会回退到 `frames/24`，不要再让 align/edit 因 KeyError 中断。
- **QC/对齐用 `.venv-dialogue`**：`qc_cinematic_shots.py` 和 `align_cinematic_dialogue.py` 依赖 `faster_whisper`，`.venv-openmontage` 里没有。

## 配乐定制规则（强制）

- **每部影片的配乐必须按题材、时代、地域、情绪曲线和声音设计重新定制**；不得默认复用上一部影片的 `music bed`、`cues.json` 或同一组曲目。
- 在 proposal/asset 阶段写明本片的音乐方向：乐器、音色、能量、进入/退出点、静默窗口；再按该方向选曲或生成。
- 复用已有曲目时必须在 `decision_log` 记录理由，并确认它符合本片风格；不能因为“现成”而复用。
- 恐怖片优先低频 drone、呼吸/金属/木质纹理、画外声与静默；古装/志怪按时代与地域选乐器，避免把“古琴 + 箫”当成所有聊斋片的默认配乐。
- 音乐床的 cue 表、来源、许可证和最终混音报告随项目保存，作为下一部影片的反例/参考，而不是模板。

## Project-specific notes

- `projects/liaozhai-wangliulang-cinematic` is the approved Wang Liulang
  cinematic project: 45 shots, project-local Remotion composition, Chinese
  subtitles, native H3 audio.
- Character/scene/voice references live in
  `projects/liaozhai-wangliulang/assets/`.
- FastH3 request payloads use `reference_image_paths` (≤3), optional
  `reference_audio_paths` (≤3), on the `17n+5` frame grid.

## Codex CLI / ChatGPT Image 2.5 Sunburst 配置

本地参考图使用 **Codex 订阅里的 ChatGPT Image 2.5（Sunburst）**，不经过
OpenAI API key，也不走 OpenCode 图像 provider。工具入口是
`codex_image`（`openmontage/tools/graphics/codex_image.py`）。

### 1. 前置条件

- 本机已安装 Codex CLI，并已用 ChatGPT/Codex 计划登录：
  ```bash
  codex --version
  codex login status     # 期望输出：Logged in using ChatGPT
  ```
- 终端不会继承桌面 Codex 客户端的代理。跑任何 `codex` 命令前先导出：
  ```bash
  export HTTPS_PROXY=http://127.0.0.1:7897
  export HTTP_PROXY=http://127.0.0.1:7897
  export ALL_PROXY=http://127.0.0.1:7897
  ```
  代理地址按本机实际配置调整；不要把凭据或代理写进仓库。
- 如果 `codex login status` 不是已登录：先设置代理，再执行
  `codex login --device-auth`，打开它给出的 URL 输入一次性代码。
  **不要**为了“刷新”而先删 `~/.codex/auth.json`；该文件是 CLI 的凭据，
  删除会让 CLI 立刻变成未登录。确需重登时先备份：
  ```bash
  cp ~/.codex/auth.json ~/.codex/auth.json.bak
  ```

### 2. 调用方式

`codex_image` 的 `model` 是“能调用内置 image_gen 的 Codex 文本模型”，
默认 `gpt-6-luna`；`image_model` 只是记录本次生成使用的图像模型
（`gpt-image-2.5-sunburst`），**不是** CLI 的模型选择参数。

```json
{
  "prompt": "Use the attached head-and-shoulders portrait as the absolute identity reference...",
  "output_path": "projects/<project-id>/assets/refs/<name>.png",
  "reference_paths": [
    "projects/<project-id>/assets/refs/faces/<name>_face.png"
  ],
  "model": "gpt-6-luna",
  "image_model": "gpt-image-2.5-sunburst",
  "timeout_seconds": 900,
  "extra_instructions": "Image 1 is the absolute face identity; preserve the face exactly."
}
```

```bash
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 ALL_PROXY=http://127.0.0.1:7897 .venv-openmontage/bin/python studio.py tool codex_image @ref_payload.json
```

成功时返回 `provider=codex_subscription`、`model=gpt-image-2.5-sunburst`。
Codex 内置 `image_gen` 没有暴露图像模型选择器，实际生成使用订阅默认的
2.5 图像模型；不要在 prompt 里写“请使用 gpt-image-2.6-sunburst”之类的
模型选择句，Codex agent 会拒绝执行。

### 3. 参考图一致性协议（强制）

1. 每个角色先有且只有一张脸部主参考：
   `assets/refs/faces/<name>_face.png`。
2. 官服、群像、变体只从这张脸做“换装/换场景”，不重新文生图一个“同名人”。
3. 多参考图必须显式逐人绑定：
   - `Image 1 = Song Gong face identity`
   - `Image 2 = official robe/pose only`
   - `Image 3 = horse/prop only`
4. 群像图不要让“群像参考”决定名字脸；群像只提供构图。视频提示词只绑定
   个人参考。
5. 先出一张样图，人工确认脸、年龄、胡须、服装；通过后再批量。
6. 发现脸漂移就清掉旧图，放入 `assets/refs/inconsistent_backup/`，用脸部
   主参考重生成；不要用裁剪或换脸去掩盖身份错误。

### 4. 常见故障

| 现象 | 原因 | 处理 |
|---|---|---|
| `401 Missing bearer authentication` | CLI 没有有效 auth | 设置代理后 `codex login status`；未登录则设备登录 |
| `403 Forbidden` / `workspace routing timed out` | 终端没走代理或工作区不可达 | 导出 `HTTPS_PROXY` 后重试 |
| `model_not_found` | Codex 文本模型不可用 | 用 `model: "gpt-6-luna"` |
| “无法核验 gpt-image-2.6-sunburst” | 本地 CLI 未暴露 2.6 | 改用 2.5 Sunburst；不要伪造 2.6 |
| 生成了图但脸不对 | 身份参考不够近 | 用脸部特写 `faces/<name>_face.png` 重生成 |

### 5. 成本与边界

- 走 ChatGPT/Codex 订阅额度，不产生 OpenAI API 账单；仍然消耗订阅配额，
  批量前先出一张样图。
- 不要声称 CLI 能精确切换 Flare/Sunburst；本机当前实际是 2.5 订阅默认。
- 参考图是生产资产，输出必须落在 `projects/<id>/assets/refs/`；
  生成后做 contact sheet 人工复核。

## 发布文案规范（强制）

- 作品发布描述只写观众向的故事钩子、看点和情绪，不写制作技术说明。
- 不写模型名、H3、原生对白/音效、旁白条数、分辨率、时长、帧率、参考图流程等
  内部信息；这些留在项目 README、artifacts 和复盘里。
- 发布描述保持 2–4 句，话题 3–5 个，AI 作品仍必须带“内容由AI生成”声明。

## 提交规范（强制）

- 所有 Git commit message 一律使用中文，不使用英文标题或英文正文。
- 不带英文类型前缀；直接写中文，例如：
  `文档：记录 Codex 图像鉴权与参考图来源规则`
- 代码、配置、文档、脚本的提交都适用；如果需要说明范围，用中文括号，例如：
  `修复（FastH3）：重启服务后等待健康检查`

Structural checks do not replace human story/audio review.
