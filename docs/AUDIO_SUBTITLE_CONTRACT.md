# 声音绑定与字幕交付契约（全局）

这份契约适用于本仓库所有 H3 / FastH3 / FastVideo / VDN-H3 分镜，不区分项目、
故事或语言。它把两类已经发生过的交付事故变成可执行的硬门禁：

1. 王六郎拿到了许某的参考音色；
2. 字幕比语音晚数秒，或 H3 原生烫字与后期字幕叠成两层。

## 1. 声音：一个 take 只让一个人说话

H3 在请求里按 **音频文件列表顺序** 配对 **可见 Subject 顺序**。第 N 个
`audio_reference` 会被模型当成 `<Audio N>`，并倾向绑定给 `<Subject N>`。
更严重的是：当同一个角色在另一个角色之后再次说话时，H3 可能把上一个
说话人的音色带回来，即使 prompt 的 `<Audio N>` 标签完全正确。

因此新工作的硬规则是：

- **每个 H3 take 最多一个说话人。** 多人镜头可以保留，但其他人必须沉默，
  写沉默锁（`does not speak ... lips stay closed`）；对白场用正反打拆镜。
- `<Audio N>` 的 N 必须等于该音频在 `voices` 列表中的位置（从 1 开始）；
- 对可见说话人，`<Audio N>` 必须同时绑定 `<Subject N>`；
- 说话人必须排在可见 cast 的前面；沉默的可见角色排在说话人之后；画外音
  排在所有可见角色之后；
- 每个可见说话人都必须有独立参考 WAV；没有参考音是硬错误。

`build_spec` 默认拒绝多说话人镜头；只有已经通过 `voice_audit` 的历史
take 才能显式设置 `allow_multi_speaker=True`。`spec_audit` 会在每次渲染前
复查音频标签、列表顺序和 Subject 定义。

渲染完成后，`novel_h3.voice_audit` 优先用 Resemblyzer d-vector（缺失时回退
MFCC 统计量）对比每条台词的音色与所有参考 WAV：最接近的参考不是该台词的
说话人时判 `review`。这是第二道防线，用于人工听音前的分诊；`review` 的
镜头必须复听或重拍，不能直接交付。

手工拼 spec、绕过 `build_spec` 的脚本不进入生产。需要新能力时扩展
`ref2va_builder.py`，不要复制一份项目专用 prompt。

## 2. 字幕：按真实语音的词级时间对齐

字幕时间不能按台词编号平均分配，也不能只取 Whisper 最像的一整段。
Whisper 会把一句拆成多段，只取尾段会让字幕晚数秒。

`novel_h3.dialogue_audit.align_words` 用词级时间戳做单调对齐：

- 从整句的第一个词开始，到最后一个词结束；
- 一句跨多个断句时，字幕覆盖整句，不截掉句首；
- 对齐失败时回退到合同名义时间，并记录在 `timing.json` 供人工复核；
- 章节合成时按镜头起止时间拼接，字幕窗口不得跨镜。

每个章节合成后运行 `novel_h3.subtitle_qc.scan_duplicate_captions`：

- 在字幕带按每秒 2 帧采样；
- 同一帧出现两条独立文字行即判 `duplicate`；
- 报告写入 `v3/chapters/<章节>/subtitle_qc.json`，有命中必须人工处理。

## 3. H3 原生烫字：整镜跳过，不叠两层

H3 有时会把中文台词直接画进画面。交付规则：

- 每个 take 在进入章节前用 `novel_h3.subtitle_audit.scan_take` 扫描
  **96 帧**，先做亮字预筛，再用 `tesseract --psm 6` OCR；
- 只要该镜头出现原生字幕，章节合成时 **整镜跳过后期字幕**；
- 原生字幕已覆盖全部台词时，这是完整字幕；只覆盖部分台词时，仍按整镜
  跳过处理，不允许“后期字幕 + 原生字幕”同时出现；
- 需要更干净的版本时重拍该镜，或用既有去字工具处理，不得在成片里叠字；
- 后期字幕永远不覆盖原生字幕区域。

## 4. 新故事如何继承

新项目不需要重新实现这些规则：

1. 用 `novel_h3.ref2va_builder.build_spec` 生成 spec；
2. 用 `novel_h3.render_batch` / `fastvideo_batch` 渲染，预检自动执行；
3. 用 `novel_h3.chapter_export.compose_chapter` 出章节，字幕对齐、原生字幕
   扫描和重复字幕审计自动执行；
4. 在 `openmontage` 的 assets / compose checkpoint 中记录审计结果；
5. 人工听音和看片仍是最终门禁。

任何一条审计失败，都按“重拍或明确人工接受”处理，不允许静默跳过。
