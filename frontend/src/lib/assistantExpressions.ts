/**
 * AI 助手表情库（2026-10-22 由用户提供的表情设计稿提取）
 *
 * **来源**：用户提供的 31 个表情 cell 缩略图稿。实测附件里有 **31 个 cell 但 32 个 svg**
 * ——「待机放空」那一格里塞了两个（多出来的是「好奇」），故实际落盘 **32 张**。
 * 画面内容一字未改，只把根 <svg> 的 `width/height` 从 100% 改成 259
 * （viewBox 是 `-15 -15 259 259`；用 `<img src>` 加载需要固有尺寸）。
 *
 * **动效范围（用户已确认）**：**静态帧 + 切换过渡**。
 * 设计稿 title 里描述的动效（眨眼轮换 / 彩带自旋 / 呼吸起伏 / 摇头等）属于原交互 demo 的 JS 行为，
 * 附件里没有脚本，本轮**不实现**。表情切换用 CSS 过渡（淡入 + 轻微缩放）表达。
 *
 * **资源位置**：`frontend/public/assistant/expressions/<key>.svg`
 * —— 走 `public/` 静态资源，**不进 JS bundle**（32 张合计约 106KB，进了 bundle 会拖慢首屏）。
 */

export interface AssistantExpression {
  /** 稳定英文 key（文件名） */
  key: string;
  /** 中文状态名 */
  label: string;
  /** 设计稿原文描述（用作 tooltip / aria-label） */
  desc: string;
  /** public 下的路径 */
  file: string;
}

/** 32 张表情（31 个有标题的 + 「待机放空」格里多出来的「好奇」） */
export const EXPRESSIONS: AssistantExpression[] = [
  { key: 'sleep', label: '睡眠', desc: '闭眼成细线，右上角 zzz 缓缓飘起，头微垂，只剩缓慢呼吸', file: '/assistant/expressions/sleep.svg' },
  { key: 'wake', label: '唤醒', desc: '从闭合眼环缓缓睁开，先揉眼似的眨两下，随后进入待机', file: '/assistant/expressions/wake.svg' },
  { key: 'idle', label: '待机放空', desc: '左看看、右看看，目光在两侧各停留片刻，偶尔自旋甩彩带 / 弹跳', file: '/assistant/expressions/idle.svg' },
  { key: 'curious', label: '好奇', desc: '好奇:设计稿放在「待机放空」格内的额外一帧,独立落盘备用', file: '/assistant/expressions/curious.svg' },
  { key: 'daze', label: '发呆', desc: '半闭眼环慢轮换，双眼各望各的，偶尔弹跳提神', file: '/assistant/expressions/daze.svg' },
  { key: 'boot', label: '加载苏醒', desc: '双眼缓慢交替亮起，像系统正在逐项初始化', file: '/assistant/expressions/boot.svg' },
  { key: 'hibernate', label: '休眠', desc: '困倦眼环 + 半开合，几乎静止，只剩极弱的呼吸起伏', file: '/assistant/expressions/hibernate.svg' },
  { key: 'shake_wake', label: '抖动唤醒', desc: '整球轻颤，闭合眼环交错睁开，随后进入待机', file: '/assistant/expressions/shake_wake.svg' },
  { key: 'happy', label: '开心', desc: '笑眼轮换，目光下看看、上看看，身体轻快起伏，偶尔自旋甩彩带', file: '/assistant/expressions/happy.svg' },
  { key: 'puzzled', label: '疑惑', desc: '斜眼环轮换，头微倾，一眼放大一眼收小', file: '/assistant/expressions/puzzled.svg' },
  { key: 'lost', label: '失落', desc: '困倦 / 闭合眼环慢轮换，眼睛下沉，目光低垂', file: '/assistant/expressions/lost.svg' },
  { key: 'surprised', label: '惊讶', desc: '双眼瞬间放大到 1.45 倍再回稳，身体轻抬定住', file: '/assistant/expressions/surprised.svg' },
  { key: 'shy', label: '害羞', desc: '目光躲向一侧，脸颊在一秒多里渐渐泛起粉色', file: '/assistant/expressions/shy.svg' },
  { key: 'tired', label: '疲惫', desc: '眼皮沉重半睁（低开合度 + 困倦眼环），目光下沉', file: '/assistant/expressions/tired.svg' },
  { key: 'focused', label: '专注', desc: '专注眼环族轮换，双眼微微内聚，身体几乎不动', file: '/assistant/expressions/focused.svg' },
  { key: 'panicked', label: '慌张', desc: '圆睁眼环高频轮换，目光乱晃，整球细颤', file: '/assistant/expressions/panicked.svg' },
  { key: 'helpless', label: '无奈', desc: '斜眼环轮换，头一歪，双眼翻向斜上方', file: '/assistant/expressions/helpless.svg' },
  { key: 'satisfied', label: '满意', desc: '目光正视前方，双眼有节奏地上下点动，如同点头认可', file: '/assistant/expressions/satisfied.svg' },
  { key: 'confused', label: '困惑', desc: '两眼大小不一，斜眼环轮换，注视方向对不齐', file: '/assistant/expressions/confused.svg' },
  { key: 'angry', label: '生气', desc: '怒目圆睁，脸色在 0.25s 内迅速涨红并保持，身体细微发抖', file: '/assistant/expressions/angry.svg' },
  { key: 'thinking', label: '思考中', desc: '思考眼环轮换，目光在上方巡回，一条彩带在头顶水平环绕', file: '/assistant/expressions/thinking.svg' },
  { key: 'received', label: '接收任务', desc: '轻轻眨一下并放大，像点头确认收到', file: '/assistant/expressions/received.svg' },
  { key: 'busy', label: '处理中忙碌', desc: '专注眼环轮换，目光小幅循环往复', file: '/assistant/expressions/busy.svg' },
  { key: 'done', label: '任务完成', desc: '笑眼轮换 + 自旋甩彩带 + 撒花庆祝', file: '/assistant/expressions/done.svg' },
  { key: 'error', label: '出错', desc: '圆睁眼环，脸色红白两色急促闪动，最后定格在警示红', file: '/assistant/expressions/error.svg' },
  { key: 'waiting', label: '等待输入', desc: '聆听眼环轮换，目光轻轻上下扫读', file: '/assistant/expressions/waiting.svg' },
  { key: 'connecting', label: '联网加载', desc: '左右眼轮流眨，像信号在两端来回跳', file: '/assistant/expressions/connecting.svg' },
  { key: 'recalling', label: '复述回忆', desc: '聆听眼环慢轮换，目光飘向上方翻检记忆', file: '/assistant/expressions/recalling.svg' },
  { key: 'refused', label: '拒绝/受限', desc: '斜眼下压，进入时连续摇头，明确表示不行', file: '/assistant/expressions/refused.svg' },
  { key: 'speaking', label: '输出回复', desc: '扫读眼环轮换，随输出节奏轻微缩放', file: '/assistant/expressions/speaking.svg' },
  { key: 'searching', label: '检索资料', desc: '6 组扫读眼环高速轮换（弹簧加速），目光左右快扫', file: '/assistant/expressions/searching.svg' },
  { key: 'stopped', label: '停止终止', desc: '闭合眼环，慢慢收小半闭后定格', file: '/assistant/expressions/stopped.svg' },
];

/** 助手的交互状态（表情要表达的语义） */
export type AssistantMood =
  | 'idle' // 空闲待命
  | 'loading_history' // 读本地历史
  | 'received' // 收到提问
  | 'searching' // 组装上下文（取行情/计划）
  | 'thinking' // 等待首个 token
  | 'speaking' // 流式输出中
  | 'done' // 本轮完成
  | 'error' // 出错
  | 'stopped' // 用户停止
  | 'unavailable' // LLM 未配置 / 不可用
  | 'sleeping'; // 长时间无交互

/**
 * 交互状态 → 表情 key
 *
 * 32 张里启用 12 张，其余（疑惑/失落/惊讶/害羞/疲惫/慌张/无奈/满意/困惑/生气/好奇/发呆…）
 * 保留在库里备扩展 —— 表情库是静态资源，多存不占 bundle。
 */
export const MOOD_EXPRESSION: Record<AssistantMood, string> = {
  idle: 'idle',
  loading_history: 'boot',
  received: 'received',
  searching: 'searching',
  thinking: 'thinking',
  speaking: 'speaking',
  done: 'done',
  error: 'error',
  stopped: 'stopped',
  unavailable: 'refused',
  sleeping: 'sleep',
};

const BY_KEY = new Map(EXPRESSIONS.map((e) => [e.key, e]));

/** 取表情定义（找不到时回落 idle，绝不抛错 —— 表情挂了不能拖垮对话） */
export function getExpression(key: string): AssistantExpression {
  return BY_KEY.get(key) ?? BY_KEY.get('idle')!;
}

/** 取某个交互状态对应的表情定义 */
export function expressionForMood(mood: AssistantMood): AssistantExpression {
  return getExpression(MOOD_EXPRESSION[mood] ?? 'idle');
}
