---
name: douyin-publish
description: 将 OpenMontage 成片发布到抖音创作者中心网页版，包括标题、简介、话题、AI 生成声明、4:3 横封面和 3:4 竖封面，并验证发布状态。Use when the user asks to publish or upload a video to Douyin/抖音, or to diagnose a Douyin upload that did not go through.
---

# 抖音发布

把一条已批准的 OpenMontage 成片发布到用户自己的抖音账号。只操作抖音创作者中心网页版；不要假装能操作手机 App。

## 前置检查

1. 确认项目与导出文件：
   - 成片：`projects/<id>/exports/<name>_final.mp4`（不要用 `_reference.mp4`）
   - 海报：`projects/<id>/exports/<name>_poster.jpg`
   - 横封面：`exports/<name>_cover_4x3.jpg`
   - 竖封面：`exports/<name>_cover_3x4.jpg`
2. 如果横/竖封面不存在，先从已批准海报生成，不要在上传页手工裁剪。如果连海报
   都还没有，把 payload 里的 `poster_path` 换成 `video_path` + `poster_time`，
   一次生成海报和两张封面：
   ```bash
   .venv-openmontage/bin/python studio.py tool publish_covers @covers_payload.json
   ```
   `covers_payload.json`（已有海报时）：
   ```json
   {
     "poster_path": "projects/<id>/exports/<name>_poster.jpg",
     "output_dir": "projects/<id>/exports",
     "base_name": "<name>",
     "platform": "douyin",
     "horizontal_focus": "left",
     "vertical_focus": "center"
   }
   ```
   标题在画面左侧用 `left`，居中用 `center`。输出必须是 1440x1080（4:3）和
   1080x1440（3:4）；抖音竖封面必须大于 600x800。
3. 校验视频与封面：
   ```bash
   ffprobe -v error -show_entries format=duration,size \
     -show_entries stream=codec_name,width,height,r_frame_rate -of json <video>
   ffprobe -v error -select_streams v:0 \
     -show_entries stream=width,height -of csv=p=0 <cover>
   ```
4. 准备文案。优先读 `exports/<name>_metadata.json` 或
   `checkpoint_publish.json` 的 `metadata_used`：
   - 标题 ≤ 30 字；
   - 简介 ≤ 1000 字，2–4 句，不编造原文没有的信息；
   - 话题 3–5 个；AI 作品建议带 `#AI电影`；
   - AI 生成作品必须声明「内容由AI生成」。
5. 如果用户没有明确批准标题、简介、可见范围，先在对话里确认；不要擅自改公开范围。

## 浏览器环境

用用户 Chrome 配置的只读副本，不杀、不接管用户正在用的窗口：

```bash
agent-browser --session douyin --profile Default --headed \
  open "https://creator.douyin.com/creator-micro/content/upload"
```

`--profile Default` 会把现有 Chrome 配置复制到临时目录，登录状态通常可直接复用。
如果页面要求扫码，说明副本里的登录已失效：让用户在自己的 Chrome 里登录抖音后重试，
不要在自动化窗口里索要密码。

`--session` 的名称统一用 `douyin`，后续命令都带它。页面变化后 ref 会失效，先重新
`snapshot -i`。

## 上传与填写

1. 进入「发布视频」上传页。不要点「选择文件」或「上传视频」（会弹原生文件框），
   直接给隐藏 input 设置文件：
   ```bash
   agent-browser --session douyin snapshot -i
   agent-browser --session douyin upload 'input[type=file][accept*="video"]' \
     "/abs/path/<name>_final.mp4"
   ```
   等待表单出现，再
   ```bash
   agent-browser --session douyin wait --text "作品描述"
   agent-browser --session douyin snapshot -i
   ```
2. 填标题：
   ```bash
   agent-browser --session douyin fill @<title-ref> "<标题>"
   ```
3. 填简介。`contenteditable` 的 `fill` 可能追加而不是替换，必须先清空：
   ```bash
   agent-browser --session douyin click @<desc-ref>
   agent-browser --session douyin press "Control+a"
   agent-browser --session douyin press "Backspace"
   agent-browser --session douyin fill @<desc-ref> "<简介>

#话题1 #话题2 #AI电影"
   agent-browser --session douyin click @<title-ref>
   ```
   填完用 `eval` 校验 `innerText`：不能有重复段落、开头多余的 `*`、或截断。
   ```bash
   cat <<'EOF' | agent-browser --session douyin eval --stdin
   document.querySelector('[contenteditable="true"]').innerText
   EOF
   ```
   注意：话题建议弹层会挡住以下区域。填完简介后点标题输入框收起弹层，不要在简介里
   按 Escape（可能插入杂字符）。

## 设置封面

必须同时设置横版 4:3 和竖版 3:4，否则抖音会提示「横/竖双封面缺失」，影响推荐。

1. 点横封面盒子（截图里较宽的那个「选择封面」）。当前版本可用：
   ```bash
   agent-browser --session douyin find first ".cover-Jg3T4p" click
   ```
   类名可能随前端更新变化；变了就用 `snapshot -i` 找「选择封面」的第一个盒子。
2. 在封面编辑器里，把文件设到主画布的上传 input，**不要**用左侧 `upload-btn-input`
   （那是参考图/侧栏上传）：
   ```bash
   agent-browser --session douyin upload \
     ".selectArea-BCIYQD input.semi-upload-hidden-input" \
     "projects/<id>/exports/<name>_cover_4x3.jpg"
   ```
   如果选择器失效，用 `eval` 列出 `input[type=file]`，选祖先带
   `selectArea` / `semi-upload` 的那个。
3. 点「完成」。弹窗询问竖封面时点「设置竖封面」，用同一选择器上传
   `<name>_cover_3x4.jpg`，再点「完成」。
4. 等待「封面设置成功」和「封面效果检测通过」；两个封面缩略图应替换掉灰盒。

## 自主声明

点「自主声明」→ 选「内容由AI生成」→「确定」。这是 AI 影片的合规声明，不要跳过。
预览区底部应出现「作者声明：内容由AI生成」。

## 发布

1. 滚到底部，让「发布」按钮可见：
   ```bash
   agent-browser --session douyin scrollintoview \
     "button.primary-cECiOJ.fixed-J9O8Yw"
   ```
2. 取底部按钮的准确 ref：
   ```bash
   agent-browser --session douyin snapshot -i | grep 'button "发布"'
   ```
   然后按 ref 点击，例如：
   ```bash
   agent-browser --session douyin click @e53
   ```
   **绝对不要**用 `agent-browser find role button click --name "发布"`：它会先匹配
   侧边栏的「作品发布」，把页面带回上传页，看起来像发布失败。
3. 成功标志：URL 变为
   `https://creator.douyin.com/creator-micro/content/manage?enter_from=publish`，
   作品数量 +1，列表第一条是刚发的视频。
4. 状态会从「审核中」变为「已发布」。刷新内容管理页确认：
   ```bash
   agent-browser --session douyin open \
     "https://creator.douyin.com/creator-micro/content/manage?tab=works"
   ```
5. 打开公开页验证：
   `https://www.douyin.com/video/<work-id>`。`<work-id>` 可从编辑页 URL 的
   `mid=` 取得。确认标题、时长、封面、AI 声明都在。
6. 把结果写回项目的 `artifacts/publish_log.json`：平台 `douyin`、公开链接、
   work id、发布时间、状态（`in_review` 或 `published`）、使用的标题/简介/话题。

## 常见故障

- **页面回到 `/content/upload`，提示「你还有上次未发布的视频」**：
  点「继续编辑」；一次没反应再点一次，或直接打开
  `/creator-micro/content/post/video?enter_from=draft`。草稿通常完整保留。
- **点发布后回到上传页**：几乎一定是点到了侧边栏「作品发布」。恢复草稿，滚到底部，
  用 `snapshot` 里的准确 ref 点「发布」。
- **封面编辑器一直转圈**：不要等 AI 推荐封面。直接把已批准封面传到主画布 input。
- **竖封面报「分辨率过低」**：重新用 `publish_covers` 生成 1080x1440，不要用
  576x768 原图。
- **简介重复或多了 `*`**：清空后重填，点击标题框收起话题弹层，并用 `eval` 校验。
- **发布按钮点不动**：先 `scrollintoview`，确认 ref 是底部按钮而不是导航按钮。

## 硬性规则

- 不发布未批准的文案或可见范围；不擅自设为公开。
- 不跳过 AI 声明；不把 AI 影片声明成「无需添加自主声明」。
- 不上传 `_reference.mp4`、未混音版本或错误项目。
- 不在封面缺失时发布；先补齐 4:3 和 3:4。
- 不在发布失败时删除草稿；先恢复并诊断。
