'use client';

import clsx from 'clsx';

import { expressionForMood, type AssistantMood } from '@/lib/assistantExpressions';

/**
 * 助手表情(静态帧 + 切换过渡)
 *
 * **为什么是静态帧**:设计稿里的 `<svg>` 只有静态画面,动效(眨眼轮换 / 彩带自旋 /
 * 呼吸起伏)是原交互 demo 的 JS 行为,附件里没有脚本 —— 阶段10 确认只做
 * 「静态帧 + 切换过渡」,表情之间切换时用 CSS 淡入 + 轻微缩放表达。
 *
 * **切换怎么触发**:`key={expr.key}` —— 表情变了就换一个 DOM 节点,
 * 挂载动画(.assistant-expression)自然重放一次。
 *
 * **资源走 public 静态资源**:32 张合计约 110KB,进 JS bundle 会拖慢首屏,
 * 所以用 `<img src="/assistant/expressions/xxx.svg">` 让浏览器自己缓存。
 */
export default function AssistantExpression({
  mood,
  size = 40,
  className,
}: {
  mood: AssistantMood;
  size?: number;
  className?: string;
}) {
  const expr = expressionForMood(mood);
  return (
    <img
      key={expr.key}
      src={expr.file}
      alt={expr.label}
      title={expr.desc}
      width={size}
      height={size}
      draggable={false}
      className={clsx('assistant-expression', className)}
      style={{ width: size, height: size }}
    />
  );
}
