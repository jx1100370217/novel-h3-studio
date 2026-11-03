# 剧本优化标准（全局）

适用于所有走 `novel-cinematic` 的故事。剧本阶段（breakdown 之后的 `screenplay`）
必须逐条自检，并在 `screenplay_treatment` 里留下证据；`scene_plan` 与分镜必须继承
这些决定。

> 依据：场景目标/冲突/转折（Zen Writer、The Good Earth、K.M. Weiland）、
> show-don't-tell 与潜台词（NCW、Script Magazine）、覆盖与 180° 轴线
> （FilmSkills、StudioBinder）、以及 Bordwell 对"对话驱动也可以极好"的提醒——
> 关键不是少说话，而是话里有潜台词、身上有代价。

## 一、12 条硬标准

### 1. 前 15 秒给钩子
开场必须让观众产生一个问题，而不是只看到一种状态。允许的做法：一句不该出现的声音、
一个反常的物件、一个结果先于原因的瞬间。不要用旁白解释。

### 2. 每场一个具体欲望
"想要被理解""想要陪伴"太虚；要落到这一场、这几分钟能拿到或拿不到的东西：
一条鱼、一个答案、一顿酒、一句道歉、一次见面。

### 3. 每场一个障碍
障碍可以是人、规则、天气、时间、身份，也可以是主角自己的恐惧。
没有障碍的场景是"有人的地点"，不是戏。

### 4. 每场一个转折
场景结束时，局面必须和开始时不同：目标达成、失败、被替换，或代价被抬出来。
连续两个 beat 没有改变力量关系，就是停摆，必须删或改。

### 5. 晚进早出
从目标已经生效的那一刻进场，转折一落地就切走。不写进门寒暄、不写告别后的路、
不写"所以你的意思是"式的复述。初稿后可以试着删掉每场头三句和尾三句。

### 6. 用身体和道具承担信息
能被看见的，不要用嘴说。干袖、无影、空壶、空杯、鞋、鱼篓、灯——
一个道具至少承担一次"变化"，否则删掉。

### 7. 对白要有潜台词
人物说的和做的永远差一层。允许答非所问、打断、说一半、用天气和鱼价挡情绪。
把主题句（"因为我把你当兄弟""你心善"）留给最不该说的人，或者干脆删掉。

### 8. 重场戏用物理过程，不用独白
全片最重要的一场（道德抉择、生死、告别）必须有一个可以被看见的过程：
手伸出又收回、水没顶、杯子空了、风把纸钱卷走。不要用自言自语交代心理。

### 9. 母题三段式
每个母题至少出现三次，并且每次变一个意思：谜 → 恐惧 → 悲悯；
祭 → 共饮 → 独饮。只在同一个意思上重复的母题，是装饰，不是结构。

### 10. 反应镜头
听话的人比说话的人更重要。重场戏至少给一次"决定瞬间"的反应近景；
不给反应，观众就不知道该看谁。

### 11. 守 180° 轴线与屏幕方向
同一场对话，人物在画面左/右的关系不能变；手从哪边入画，就属于哪边的人。
调度错误不能靠后期镜像修补，只能重拍或改写调度。

### 12. 结尾用行动回环
最后一个动作要同时指向至少两个人或两个母题：把酒洒回河里、穿上妻子给的鞋、
把空杯放在门槛上。不要用符号总结，不要用旁白点题。

## 二、七维极佳标准（craft v5，binding）

V4 的问题不是“不忠实”，而是“技术上完成、戏剧上不吸引人”。从 V5 起，
`novel-cinematic` 的剧本阶段除了上面的 12 条硬标准，还必须通过
`novel_h3.craft_audit` 的七维门禁。`metadata.craft_version >= "5.0"`（或携带
`metadata.seven_dimensions`）即视为选择严格模式；旧剧本继续按旧标准验证。

七维不是七个形容词，而是七组可检查的证据。每一维在
`metadata.seven_dimensions` 里写 `score`（1–5）和 `evidence`（具体到场/动作/
物件，不能写“很好”）。交付目标为 5/5；4/5 只给警告，低于 4 直接失败。

### 1. 文学质感（literary_texture）

不是“有古风”，而是**一个具体的道德问题，被具体的人以具体的代价回答**。

- `protagonist.moral_question` 必须是一个观众能替主角回答“会/不会”的问题；
- `theme` 不能是口号，不能在全片被人物原样说出；
- 至少一场戏让观众对主角产生羞耻感或不安，而不是只有同情；
- 结尾不解释主题，只留下一个动作的余味。

### 2. 母题设计（motif_design）

每个母题至少 **3 个 beat**，并且每次换一个意思。`visual_motifs[].beats[]`
逐条写 `section_id / phase / meaning`，`phase` 必须覆盖
`setup → turn → payoff`。

反例：酒在 S01、S02、S03、S05、S07 都只是“两个人喝酒”。
正例：酒是祭品（交易）→ 共饮（交情）→ 满杯喝不了（人神相隔）→
洒回河里（放手）。

### 3. 物件叙事（object_narrative）

至少 **3 条 object arc**，每条至少 **3 个可见状态**，并且至少一条走到最后
一场。物件必须真的改变状态：鞋从柜里→桌上→泥里→门口并排；杯从空→两只→
满而喝不了→空→两只。

`object_arcs[].states[]` 写 `section_id` 和 `state`；`final_state` 写它最后
变成了什么。只在背景里出现的道具不算。

### 4. 戏剧冲突（dramatic_conflict）

至少 **两股对抗力量**，其中至少一股是**会行动的人/制度/规则**，至少一股是
主角**内部的占有、恐惧或羞耻**。`antagonism[]` 写 `force / kind / scenes /
pressure`；`kind` 取 `human / rule / internal / environment / institution`。

全片不能只有“天气不好”“人神殊途”这种抽象阻力。妻子要拦、村民要索求、
河规要倒计时；主角自己也要想要一个不该要的东西。

### 5. 主角弧光（protagonist_arc）

核心选择必须由主角做出，而且要有代价。`protagonist` 写
`want / need / flaw / start_state / midpoint_state / end_state /
moral_question / choice_scenes`。

- `want` 和 `need` 不能相同；
- `start_state` 和 `end_state` 不能相同；
- `choice_scenes` 至少 3 场，且必须包含 `pacing.midpoint_scene`；
- 每场 `protagonist_choice` 非空；真正做选择的场必须写 `choice_cost`；
- 配角可以牺牲，但不能替主角完成他的道德选择。

### 6. 中段节奏（mid_section_escalation）

- `pacing.midpoint_scene` 必须落在全片 **40–65%**，并且压力为 5/5；
- `pacing.climax_scene` 必须落在 **75–95%**，压力至少 4/5；
- 中段之后必须还有至少一个 5/5 的压力点，不能危机一过就泄气；
- `scene_job` 每场必填；**连续两场不能做同一件事**；
- 每个 job 有次数上限（hook/meet/discovery/revelation/crisis/loss/climax/
  test/aftermath/journey/audience 各 1 次；foreshadow/intimacy/opposition
  最多 2 次）。第二次告别、第三次河边喝酒会直接失败；
- `stakes_clock` 写 `public / private / deadline / consequence /
  planted_in / paid_in`，至少在两场里埋下，在危机/高潮里兑现。

### 7. 结尾余波（ending_aftermath）

- `pacing.aftermath_scenes` 最多 2 场，总时长不超过全片 **20%**；
- `ending.final_action` 必须是一个可见动作，不是总结；
- `ending.echo_scene` 必须指向更早的一场，`echo_object` 必须是
  `object_arcs` 里的物件；
- 最后一场必须有 `protagonist_choice` 和 `ending_echo`；
- 最后一场不能有旁白。

### 对白规则（craft v5 追加）

- `dialogue_policy.theme_lines` 最多 1 条；主题句如果出现，只能由最不该说的人
  说，或者被动作打断；
- 每个有对白的场景都要写 `subtext`，而且不能复述 `want` / `turn`；
- `dialogue_policy.silence_scenes` 至少 1 场，重场戏要敢留白；
- 台词要像人话：允许答非所问、打断、说一半、用天气和鱼价挡情绪。
  不要让人物替作者解释主题。

### 七维门禁的失败示例

- 核心选择由王六郎做出，许某只是看着 → `protagonist_arc` 失败；
- S01–S05、S07 都在河边喝酒，没有换 job → `mid_section_escalation` 失败；
- 妇人到 S06 才第一次出现，观众不认识她 → `stakes_clock` 失败；
- S07 封神告别、S11 村口再告别 → `scene_job` 的 `loss` / 第二次告别超限；
- S08–S12 五场余波占全片 40% → `ending_aftermath` 失败；
- 台词说“你心善，会是个好土地” → `dialogue_policy` 的主题句失败；
- 镜头都是正反打，没有调度 → `scene_plan` 的 staging 审计失败。

## 三、每场必须写进 treatment 的字段


`enhanced_sections[]` 每场必须有：

```json
{
  "id": "S06",
  "want": "救那个妇人",
  "obstacle": "救了她，王六郎就走不了",
  "turn": "手伸出又收回；妇人自己爬上岸",
  "coverage": "24/35/85 交叉剪辑 + 水下 + 王六郎近景",
  "location": "河岸 / 水下",
  "time_of_day": "正午",
  "props": ["one wooden boat", "one mooring stone", "one baby bundle", "river water"],
  "set_dressing": "阴天灰绿河面，陡岸；无桌、无室内"
}
```

`metadata.opening_hook` 写清前 15 秒的钩子是什么。

### 场景 / 道具合同（craft v4+，binding）

- 每场必须写 `location`、`time_of_day`、`props`、`set_dressing`；
  `props` 是精确可见道具列表，故意空场写 `["none"]`，不能省略。
- 场景里没有写的桌子、椅子、凳子、窗、墙、饭菜、碗筷、额外器皿，
  一律视为生成缺陷；必须重拍，不能靠后期擦除。
- `script.json` 与 `scene_plan.json` 必须继承同一组字段；
  `scripts/audit_scene_contract.py` 必须 pass。
- 画外音必须标成无可视说话人；可见人物全程闭唇、下颌不动。
  画外音不要放进 H3 生成音频：H3 的音频条件会把唯一可见的脸带成对口型。
  镜头按静默反应拍（`post_dialogue: true`），画外音在 compose 阶段用
  `lines.json` 的 `role: "off_screen"` + `wav` 叠加。
- 只有剧本明确写出的桌子/酒菜才能出现（例如 S08 许家木桌、S09 客店酒桌）；
  这些场景必须在 `props` 里逐项列出。

## 四、编剧阶段自检清单

- [ ] 前 15 秒有问题，不是状态；
- [ ] 每场都能一句话说出 want / obstacle / turn；
- [ ] 没有连续两场做同一件事（例如两次"发现异常"、两次"被认出"、两次"告别"）；
- [ ] 重场戏有物理过程，没有心理独白；
- [ ] 每个母题至少变三次；
- [ ] 每个配角至少有一次自己的战术，并且失败；
- [ ] 台词读出来像人话，不像作者总结；
- [ ] 结尾是一个动作，不是一句总结；
- [ ] added_dialogue 每条都有 source_fact 与 purpose；
- [ ] 每场都有 location / time_of_day / props / set_dressing；
- [ ] 没有把桌子、椅子、窗、饭菜等未授权陈设写成默认背景；
- [ ] 画外音没有绑定给可见人物，可见人物不会对画外音动嘴；
- [ ] 没有新增情节事件、人物、地点或结局。

## 五、和分镜的接口

`scene_plan` 必须继承每场的 `coverage`，并把它拆成 3–12 个镜头：
master / two-shot / single / insert / reaction，守 180° 轴线；
H3 take 上限按参考图数量分档（≤3 张 328 帧，4+ 张 260 帧）。
