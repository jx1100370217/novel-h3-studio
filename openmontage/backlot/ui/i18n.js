// Backlot UI localization. Default zh-CN, English fallback.
// The board is a local observer UI; this module translates rendered text
// nodes and attributes after each render so the production workflow can stay
// in English internally while the workbench reads Chinese.

const DICT = {
  // shell
  "Backlot": "片场",
  "Library": "项目库",
  "Backlot — Library": "片场 — 项目库",
  "IDLE": "空闲",
  "LIVE": "运行中",
  "CLOSE ✕": "关闭 ✕",
  "ESC · CLOSE": "ESC · 关闭",
  "▶ REPLAY RUN": "▶ 重放本次制作",
  "▶ REPLAY": "▶ 重放",
  "❚❚": "❚❚",
  "⤢ EXPAND SCRIPT": "⤢ 展开剧本",
  "◆ BESPOKE": "◆ 手工定制",
  "◈ AWAITING YOU": "◈ 等待你确认",
  "◉ GENERATING": "◉ 生成中",
  "● running": "● 运行中",
  "★ HERO": "★ 主镜头",
  "⚑ GATE SKIPPED": "⚑ 门禁被跳过",
  "⚠ STALLED?": "⚠ 卡住了？",
  "✕ LIVE": "✕ 实时",
  "No projects yet — run a production and it will appear here.": "还没有项目——运行一次制作后，它会出现在这里。",
  "PROJECT NOT FOUND": "未找到项目",
  "No canonical artifact found on disk for this stage.": "磁盘上还没有这一阶段的正式产物。",
  "This stage hasn't run yet.": "这一阶段还没有运行。",
  "This project has no checkpoints — Backlot is showing what it found on disk.": "这个项目还没有检查点——片场正在展示磁盘上找到的内容。",
  "Runs that follow the checkpoint protocol get the full board.": "遵循检查点协议的制作会显示完整看板。",
  "The agent is paused at this gate — reply ": "智能体已停在这个门禁处——请回复 ",
  "This is the final approval gate.": "这是最终批准门禁。",
  "What the watcher found": "监视器发现的内容",
  "asset in manifest, file missing": "清单中有素材，但文件缺失",
  "asset unavailable": "素材不可用",
  "no asset yet": "还没有素材",
  "unknown": "未知",
  "none": "无",
  "in progress": "进行中",
  "completed": "已完成",
  "failed": "失败",
  "pending": "待处理",
  "running": "运行中",
  "done": "完成",
  "awaiting_human": "等待人工",
  "in_progress": "进行中",
  "await": "等待",
  "idle": "空闲",
  "live": "运行中",
  "Activity": "动态",
  "Decisions": "决策",
  "Storyboard": "故事板",
  "Renders": "渲染",
  "Generated assets": "生成素材",
  "Scene plan": "分镜计划",
  "Production proposal": "制作提案",
  "Research brief": "研究简报",
  "Render report": "渲染报告",
  "Publish plan": "发布计划",
  "Publish destination": "发布目的地",
  "Edit decisions": "剪辑决策",
  "OPEN FULL ARTIFACT": "打开完整产物",
  "PENDING APPROVAL": "等待批准",
  "REVIEW GATE": "审阅门禁",
  "APPROVED": "已批准",
  "DRAFTING": "起草中",
  "SELECTED": "已选择",
  "Play narration": "播放旁白",
  "Click to expand full script": "点击展开完整剧本",
  "Click to read the full narration": "点击阅读完整旁白",
  "estimated cost": "预估成本",
  "generation cost": "生成成本",
  "generation spend": "生成花费",
  "data points": "数据点",
  "findings": "发现",
  "sources": "来源",
  "angles": "角度",
  "concepts": "概念",
  "destinations": "目的地",
  "platform": "平台",
  "runtime": "运行时",
  "duration": "时长",
  "when": "时间",
  "cost": "成本",
  "types": "类型",
  "section": "章节",
  "sections": "章节",
  "takes": "镜头条",
  "scenes": "场景",
  "script": "剧本",
  "assets": "素材",
  "audio": "音频",
  "video": "视频",
  "image": "图片",
  "metadata": "元数据",
  "status": "状态",
  "error": "错误",
  "notice": "提示",
  "warn": "警告",
  "crit": "严重",
  "sugg": "建议",
  "alert": "提醒",
  "theme": "主题",
  "dark": "深色",
  "light": "浅色",
  "open": "打开",
  "close": "关闭",
  "play": "播放",
  "pause": "暂停",
  "END": "结束",
  "start": "开始",
  "first": "第一",
  "finish": "完成",
  "thumb": "缩略图",
  "thumb approved": "缩略图已批准",
  "thumb generating": "缩略图生成中",
  "thumb missing": "缩略图缺失",
  "thumb spec": "缩略图规格",
  "thumb textcard": "文字卡缩略图",
  "snapshots / verification frames": "快照 / 验证帧",
  "hand-authored composition": "手工编排合成",
  "scrub the whole run": "拖动查看整次制作",
  "also considered: ": "同时考虑过：",
  "This is the final approval gate.": "这是最终批准门禁。",
  "NO MEDIA YET": "还没有媒体",
  "Play narration": "播放旁白",
  // stage names
  "breakdown": "剧本拆解",
  "scene_plan": "分镜计划",
  "assets": "素材生成",
  "edit": "剪辑决策",
  "compose": "合成导出",
  "publish": "发布",
  "research": "研究",
  "proposal": "提案",
  "script": "剧本",
  "idea": "构思",
};

const PATTERNS = [
  [/^(\d+) projects?$/, "$1 个项目"],
  [/^(\d+) LIVE$/, "$1 运行中"],
  [/^(\d+) scenes?$/, "$1 个场景"],
  [/^(\d+) shots?$/, "$1 个镜头"],
  [/^(\d+) takes?$/, "$1 条镜头"],
  [/^(\d+) assets?$/, "$1 个素材"],
  [/^(\d+) decisions?$/, "$1 条决策"],
  [/^(\d+) renders?$/, "$1 个渲染"],
  [/^SC\s*(\d+)$/, "场 $1"],
  [/^SCENE\s*(\d+)$/, "场景 $1"],
  [/^SHOT\s*(\d+)$/, "镜 $1"],
];

function translateString(value) {
  if (!value) return value;
  const text = value.trim();
  if (!text) return value;
  if (DICT[text]) return value.replace(text, DICT[text]);
  for (const [re, rep] of PATTERNS) {
    if (re.test(text)) return value.replace(text, text.replace(re, rep));
  }
  return value;
}

function translateNode(node) {
  if (node.nodeType === Node.TEXT_NODE) {
    const next = translateString(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) return;
  for (const attr of ["title", "placeholder", "aria-label", "alt"]) {
    if (node.hasAttribute && node.hasAttribute(attr)) {
      const value = node.getAttribute(attr);
      const next = translateString(value);
      if (next !== value) node.setAttribute(attr, next);
    }
  }
  for (const child of node.childNodes) translateNode(child);
}

let observer = null;

function translateAll(root) {
  if (observer) observer.disconnect();
  translateNode(root);
  if (observer) observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

export function startI18n() {
  document.documentElement.lang = "zh-CN";
  document.title = translateString(document.title);
  observer = new MutationObserver(() => translateAll(document.body));
  translateAll(document.body);
}
