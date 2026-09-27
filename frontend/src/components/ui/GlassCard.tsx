import { Card, type CardProps } from './Card';

/** 旧 API 的 variant(映射见下方 LEGACY) */
type LegacyCardVariant = 'hover' | 'active';

type GlassCardProps = Omit<CardProps, 'variant'> & {
  variant?: CardProps['variant'] | LegacyCardVariant;
};

/**
 * @deprecated v0.7 Dark Terminal 起并入 Card。
 * 保留一版薄转发以免打断 6 个引用方,下个版本删除。
 *
 * 旧实现把 `variant="hover"` 映射到 `liquid-glass-hover` —— 那是个独立类,
 * 不含基础材质(无背景/边框/圆角),一旦有人用该值卡片就会丢失全部外观。
 * 新映射改为携带基础材质的 interactive / selected。
 */
const LEGACY: Record<LegacyCardVariant, NonNullable<CardProps['variant']>> = {
  hover: 'interactive',
  active: 'selected',
};

export const GlassCard = ({ variant, className, children, ...rest }: GlassCardProps) => {
  const mapped =
    variant === 'hover' || variant === 'active'
      ? LEGACY[variant]
      : (variant ?? 'default');
  return (
    <Card variant={mapped} className={className} {...rest}>
      {children}
    </Card>
  );
};
GlassCard.displayName = 'GlassCard';
