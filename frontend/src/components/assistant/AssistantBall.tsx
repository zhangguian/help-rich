'use client';

import { useAssistant } from './AssistantProvider';
import AssistantExpression from './AssistantExpression';

/**
 * 右下角悬浮球(阶段 T4)
 *
 * **固定在右下角、全站可见**:挂在 AppShell 上,所以任何页面都能唤起助手。
 * 表情随助手状态切换(空闲/接收/思考/输出/出错…),切换用 CSS 过渡表达。
 *
 * **为什么不用 framer-motion**:悬浮球 idle 时必须**零 long task**
 * (性能验收项之一)。motion 组件常驻会带一堆动画运行时开销,
 * 这里用纯 CSS + `<img>` 切换就够,顺带省掉一个常驻订阅。
 */
export default function AssistantBall() {
  const { open, toggle, mood } = useAssistant();

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={open ? '收起 AI 助手' : '打开 AI 助手'}
      aria-expanded={open}
      data-testid="assistant-ball"
      className="fixed bottom-5 right-5 z-40 flex h-14 w-14 items-center justify-center
                 rounded-full border border-border-str bg-bg-surface shadow-lg
                 transition-colors hover:border-accent focus:outline-none
                 focus-visible:ring-1 focus-visible:ring-accent"
    >
      <AssistantExpression mood={mood} size={38} />
    </button>
  );
}
