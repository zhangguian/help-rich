/**
 * confetti(v0.4-roadmap §3.7)
 *
 * 轻量庆祝动效:从屏幕中心向四周喷射 emerald 粒子 + 下坠 + 淡出。
 * 无第三方依赖,创建一次性容器,播放完毕自清理。
 */

const PARTICLE_COLORS = ['#34d399', '#10b981', '#6ee7b7', '#ffffff'];

export function fireConfetti(durationMs = 900): void {
  if (typeof document === 'undefined') return;

  const container = document.createElement('div');
  container.style.cssText =
    'position:fixed;inset:0;pointer-events:none;z-index:100;overflow:hidden;';
  document.body.appendChild(container);

  const cx = window.innerWidth / 2;
  const cy = window.innerHeight / 3;

  for (let i = 0; i < 60; i++) {
    const particle = document.createElement('div');
    const size = 5 + Math.random() * 6;
    const color = PARTICLE_COLORS[Math.floor(Math.random() * PARTICLE_COLORS.length)];
    const angle = Math.random() * Math.PI * 2;
    const dist = 90 + Math.random() * 240;
    const dx = Math.cos(angle) * dist;
    const dy = Math.sin(angle) * dist + 60;
    const rot = Math.random() * 360;
    const delay = Math.random() * 0.12;

    particle.style.cssText = [
      'position:absolute',
      `left:${cx}px`,
      `top:${cy}px`,
      `width:${size}px`,
      `height:${size * 0.6}px`,
      `background:${color}`,
      'border-radius:2px',
      'opacity:1',
      `transform:rotate(0deg)`,
      `transition:transform ${durationMs}ms ease-out ${delay}s, opacity ${durationMs}ms ease-out ${delay}s`,
    ].join(';');
    container.appendChild(particle);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        particle.style.transform = `translate(${dx}px, ${dy}px) rotate(${rot}deg)`;
        particle.style.opacity = '0';
      });
    });
  }

  setTimeout(() => container.remove(), durationMs + 200);
}
