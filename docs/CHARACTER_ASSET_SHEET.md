# 角色参考图：标准两视图人物资产卡

> 参考流程：猫斯卡《AI 漫剧女主美到犯规！6 套人物资产图，完整提示词直接抄》
> https://mp.weixin.qq.com/s/N3AmUeepfcRJIA_mTiqxZw
>
> 以后每个新故事的男女主参考图都按本文的两视图资产卡规范生成；不要临时手写一套提示词。

## 为什么固定成两视图

一张图里同时给出：

- 左：头顶到锁骨的人像特写，用来看脸、眼神光、肤色和发际线；
- 右：头顶到脚底的正面全身立像，用来看身高比例、发型、服装、配饰和鞋。

这样选角和后续服装连续性都只看一张卡，不会出现“特写和全身不是同一个人”的问题。

## 必须保留的硬约束

- 同一画面只有两个视图，**同一个人**；
- 无侧视图、无后视图、无 3/4 转身、无第三个视图、无第二个人；
- 人像特写从头顶到锁骨完整展示，不裁切头顶；
- 全身立像从头顶到脚底完整展示，不裁切头顶和脚部；
- 中性微表情，平视镜头，自然直立，双臂自然下垂；
- 不摆拍、不叉腰、不抱胸、不歪头、不低头、不侧身；
- 纯净中性灰背景；
- 85mm portrait lens，正面或侧前 45° 大柔光主光 + 补光，2:1 光比，轻微高调，暗部提亮但保留鼻梁/颧骨塑形；
- 白色取奶油白，最深只到焦糖棕，不用纯白/纯黑；
- **图中不要有任何文字**，画面铺满，无黑边、无遮幅；
- 这是角色素材卡，不是剧照，不做表情表演。

这些约束由 `novel_h3.character_sheet.build_character_sheet_prompt` 自动注入，故事项目只提供脸、肤色、身形、发型、服装、配饰和世界观。

## 生成一张卡，再裁一张 H3 参考

两视图资产卡是**选角/设计资产**，不是 H3 Ref2VA 的输入图。直接把两视图卡喂给 H3，模型可能把两个视图当成两个人。

正确流程：

1. 用本规范生成两视图资产卡，人工确认脸、发型、服装、配饰；
2. 从右侧全身立像裁出**单人单视图**，保存为 `assets/refs/<character>.png`；
3. H3 只使用这张单人参考图；特写视图可用于后续补拍或妆造核对，不直接作为多视图输入；
4. 同一角色后续镜头复用同一张单人参考，不重新生成脸。

## 用法

项目里先写一份 spec，例如 `projects/<id>/assets/character_sheets/songtao.json`：

```json
{
  "name": "宋焘",
  "gender": "male",
  "age": "四十岁",
  "world": "架空古风，寒门书生",
  "style": "realpeople_cinematic",
  "face": "清瘦长脸，眉骨清晰，剑眉，单眼皮，眼神沉静，鼻梁直，唇线偏薄，短须",
  "skin": "自然偏冷白肤色，真实肤质，毛孔可见，保留细纹，face slightly brighter than ambient",
  "body": "178cm tall，8 heads tall proportion，肩背清瘦，腰身收敛，体态端直，书生的清癯感",
  "hair": "黑发，发丝柔顺，束发戴黑色儒巾，鬓边留少量碎发",
  "costume": "深蓝暗纹长袍，灰白交领内衫，腰束深色布带，衣料有自然褶皱和轻微磨损",
  "accessories": "腰间一枚旧玉佩，手中不拿道具",
  "palette": "深蓝、灰白、焦糖棕，低饱和中国传统色",
  "height_cm": 178
}
```

然后：

```bash
.venv-openmontage/bin/python scripts/build_character_sheet.py \
  --spec projects/<id>/assets/character_sheets/songtao.json \
  --out projects/<id>/assets/character_sheets/songtao.prompt.txt
```

把 `.prompt.txt` 原样交给 `codex_image`/图像生成工具。不要删掉结尾的“只出两个视图/图中不要有任何文字”段落。

女主示例：

```json
{
  "name": "阿绣",
  "gender": "female",
  "age": "二十岁",
  "world": "架空古风，江南宅院",
  "style": "realpeople_sweet_romance",
  "face": "鹅蛋脸，下颌线干净，眉细上扬，丹凤眼眼尾微挑，浅琥珀色瞳仁，鼻梁直挺，唇形饱满，唇色正红，有明确面部记忆点",
  "skin": "冷白带暖调，natural true-to-life skin tone，face slightly brighter than ambient，luminous complexion，healthy blood flush，soft dewy sheen，保留自然皮肤质感",
  "body": "165cm tall，8 heads tall proportion，肩窄背薄，锁骨清晰，腰细，长腿笔直，体态自然舒展",
  "hair": "黑发，发丝柔顺有光泽，挽成低髻，鬓边垂两缕碎发，一支素银簪",
  "costume": "月白交领长裙，浅蓝披帛，裙身有极淡的银线暗纹，面料柔软垂坠，自然褶皱",
  "accessories": "耳畔一对小珍珠，腕间细银镯",
  "palette": "月白、浅蓝、奶油白，低饱和",
  "height_cm": 165
}
```

## 检查清单

- [ ] 左右两个视图是同一个人
- [ ] 只有两个视图，没有侧/后/3/4 视图，没有第二个人
- [ ] 特写不裁头顶，全身不裁头顶和脚
- [ ] 中性表情、平视、自然直立、双臂下垂
- [ ] 中性灰背景，柔光，2:1 光比，暗部有塑形
- [ ] 图中没有任何文字、黑边、遮幅
- [ ] 已从全身视图裁出单人参考图，未把两视图卡直接喂给 H3
