'use client';

import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import { api, apiErrorCode, apiErrorMessage, apiPost } from '@/lib/api';
import { decimalFormat, priceFormat } from '@/lib/decimalFormat';
import { normalizeCode } from '@/lib/stockCode';
import type { CalculatorResponse, Transaction, TransactionCreate } from '@/lib/types';

import { Button } from '../ui/Button';

/**
 * 交易录入表单(frontend-arch §10.3 / ui-ux §4.3)
 */
const schema = z.object({
  stockCode: z
    .string()
    .regex(
      /^(?:\d{6}(?:\.(?:SH|SZ|BJ|sh|sz|bj))?|(?:sh|sz|bj)\d{6})$/,
      '格式:6 位数字 或 600519.SH(可省略市场后缀)'
    ),
  action: z.enum(['buy', 'sell']),
  shares: z.number().int().positive('股数必须 > 0'),
  price: z.string().regex(/^\d+(\.\d{1,3})?$/, '价格格式:数字,最多 3 位小数'),
  tradeDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, '日期格式 YYYY-MM-DD'),
  tradeTime: z
    .string()
    .regex(/^([01]\d|2[0-3]):[0-5]\d$/, '时间格式 HH:MM')
    .optional()
    .or(z.literal('')),
  note: z.string().max(200).optional(),
});

type FormData = z.infer<typeof schema>;

/** 今天(YYYY-MM-DD)—— 判断「日期是不是今天」用 */
function todayStr(): string {
  const d = new Date();
  const off = d.getTimezoneOffset();
  return new Date(d.getTime() - off * 60_000).toISOString().slice(0, 10);
}

/** 当前时刻(HH:MM) */
function nowHm(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

interface TransactionFormProps {
  onSuccess?: (tx: Transaction) => void;
  onCancel?: () => void;
  /** 预填股票代码(外部弹窗场景,如持仓/自选录入流水);输入框将只读 */
  initialStockCode?: string;
  /** 预填方向(补T接回场景 = buy) */
  initialAction?: 'buy' | 'sell';
  /** 预填股数(补T接回场景 = 待接回股数) */
  initialShares?: number;
  /** 预填价格(补T接回场景 = 不亏本接回线) */
  initialPrice?: string;
}

export function TransactionForm({
  onSuccess,
  onCancel,
  initialStockCode,
  initialAction,
  initialShares,
  initialPrice,
}: TransactionFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  // 录入前实时试算(复用 POST /api/calculator —— 纯算术,不拉 K 线)
  const [preview, setPreview] = useState<CalculatorResponse | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    setValue,
    formState: { errors },
    reset,
  } = useForm<FormData>({
    resolver: zodResolver(schema) as never, // exactOptionalPropertyTypes 兼容
    defaultValues: {
      stockCode: initialStockCode ?? '',
      action: initialAction ?? ('buy' as const),
      shares: initialShares ?? 500,
      price: initialPrice ?? '',
      tradeDate: todayStr(),
      tradeTime: nowHm(),
      note: '',
    },
  });

  const watched = watch();

  // 时间点跟随日期:
  // - 日期是今天且时间为空 → 填当前时刻(这笔交易就是当下发生的)
  // - 日期改成非今天 → 清空时间(避免出现「昨天 14:38」这种不成立的组合)
  useEffect(() => {
    const date = String(watched.tradeDate ?? '');
    const time = String(watched.tradeTime ?? '');
    if (date === todayStr()) {
      if (!time) setValue('tradeTime', nowHm());
    } else if (time) {
      setValue('tradeTime', '');
    }
  }, [watched.tradeDate, watched.tradeTime, setValue]);

  // 输入停 600ms 后试算一次「录入后持仓」
  //
  // 用 validateStatus 而不是抛错:边打字边看结论,422(卖出超额)不该每次都弹 toast,
  // 业务文案就地展示即可。
  useEffect(() => {
    const code = normalizeCode(String(watched.stockCode ?? ''));
    const price = String(watched.price ?? '').trim();
    const shares = Number(watched.shares);
    const action = watched.action;
    if (!code || !/^\d+(\.\d{1,3})?$/.test(price) || !Number.isFinite(shares) || shares <= 0) {
      setPreview(null);
      setPreviewError(null);
      return;
    }
    const handle = setTimeout(async () => {
      setPreviewing(true);
      try {
        const r = await api.post<CalculatorResponse>(
          '/calculator',
          { stockCode: code, action, txShares: shares, txPrice: price },
          { timeout: 15000, validateStatus: () => true },
        );
        if (r.status === 200) {
          setPreview(r.data);
          setPreviewError(null);
        } else {
          setPreview(null);
          const detail = (r.data as { detail?: { message?: string } })?.detail;
          setPreviewError(detail?.message ?? `试算失败 (HTTP ${r.status})`);
        }
      } catch (e) {
        setPreview(null);
        setPreviewError(e instanceof Error ? e.message : '试算失败');
      } finally {
        setPreviewing(false);
      }
    }, 600);
    return () => clearTimeout(handle);
  }, [watched.stockCode, watched.action, watched.shares, watched.price]);

  const onSubmit = async (data: FormData) => {
    setSubmitting(true);
    setError(null);
    setErrorCode(null);
    try {
      const payload: TransactionCreate = {
        stockCode: data.stockCode,
        action: data.action,
        shares: data.shares,
        price: data.price,
        tradeDate: data.tradeDate,
        ...(data.tradeTime ? { tradeTime: data.tradeTime } : {}),
        ...(data.note ? { note: data.note } : {}),
      };
      const tx = await apiPost<Transaction>('/transactions', payload);
      reset();
      onSuccess?.(tx);
    } catch (e) {
      setErrorCode(apiErrorCode(e));
      setError(apiErrorMessage(e, '录入失败'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">股票代码</label>
          <input
            type="text"
            inputMode="numeric"
            maxLength={12}
            placeholder="600519 或 600519.SH"
            readOnly={!!initialStockCode}
            className={`w-full px-3 py-2 border border-border-str rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface ${
              initialStockCode ? 'opacity-70 cursor-not-allowed' : ''
            }`}
            {...register('stockCode')}
          />
          {errors.stockCode && (
            <p className="text-up text-xs mt-1">{errors.stockCode.message}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">交易方向</label>
          <div className="flex gap-2">
            <label className="flex-1">
              <input
                type="radio"
                value="buy"
                className="mr-2"
                {...register('action')}
              />
              <span className="text-down">买入</span>
            </label>
            <label className="flex-1">
              <input
                type="radio"
                value="sell"
                className="mr-2"
                {...register('action')}
              />
              <span className="text-up">卖出</span>
            </label>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">交易日期</label>
          <input
            type="date"
            className="w-full px-3 py-2 border border-border-str rounded-sm focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface"
            {...register('tradeDate')}
          />
          {errors.tradeDate && (
            <p className="text-up text-xs mt-1">{errors.tradeDate.message}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">交易时间(可选)</label>
          <input
            type="time"
            step="60"
            className="w-full px-3 py-2 border border-border-str rounded-sm focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface font-mono"
            {...register('tradeTime')}
          />
          {errors.tradeTime && (
            <p className="text-up text-xs mt-1">{errors.tradeTime.message}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">股数</label>
          <input
            type="number"
            min={1}
            step={100}
            className="w-full px-3 py-2 border border-border-str rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface"
            {...register('shares', { valueAsNumber: true })}
          />
          {errors.shares && (
            <p className="text-up text-xs mt-1">{errors.shares.message}</p>
          )}
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">价格(3 位小数)</label>
        <input
          type="text"
          inputMode="decimal"
          placeholder="10.500"
          className="w-full px-3 py-2 border border-border-str rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface"
          {...register('price')}
        />
        {errors.price && (
          <p className="text-up text-xs mt-1">{errors.price.message}</p>
        )}
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">备注(可选)</label>
        <input
          type="text"
          maxLength={200}
          placeholder="看好银行板块..."
          className="w-full px-3 py-2 border border-border-str rounded-sm focus:outline-none focus:ring-2 focus:ring-accent bg-bg-surface"
          {...register('note')}
        />
        {errors.note && (
          <p className="text-up text-xs mt-1">{errors.note.message}</p>
        )}
      </div>

      {(preview || previewError || previewing) && (
        <div className="bg-bg-elevated border border-border-def border-l-[3px] border-l-accent rounded-md px-3 py-2.5">
          <div className="text-[11px] text-text-ter mb-1.5">
            录入后(实时试算 · 复用 POST /api/calculator)
            {previewing ? ' · 计算中...' : ''}
          </div>
          {previewError ? (
            <div className="text-xs text-warn">⚠ {previewError}</div>
          ) : preview ? (
            <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-text-sec">
              <span>
                当前{' '}
                <b className="font-mono text-text-pri">
                  {preview.before.shares} 股 @ {priceFormat(preview.before.costPrice)}
                </b>
              </span>
              <span>
                成交后股数{' '}
                <b className="font-mono text-text-pri">
                  {preview.after.shares.toLocaleString()}
                </b>
              </span>
              <span>
                新摊薄成本{' '}
                <b className="font-mono text-text-pri">
                  {preview.after.costPrice ? priceFormat(preview.after.costPrice) : '—'}
                </b>
              </span>
              <span>
                持仓资金{' '}
                <b className="font-mono text-text-pri">
                  ¥{decimalFormat(preview.after.totalCost)}
                </b>
              </span>
              <span>
                本笔已实现{' '}
                <b className="font-mono text-text-pri">
                  ¥{decimalFormat(preview.after.realizedPnlNet)}
                </b>
              </span>
              <span>
                费用{' '}
                <b className="font-mono text-text-pri">
                  ¥{decimalFormat(preview.after.feePaid)}
                </b>
              </span>
            </div>
          ) : null}
        </div>
      )}

      <div className="text-[11px] leading-relaxed text-text-ter">
        <span className="text-warn">基准语义:</span>
        若该笔已被持仓基准吸收,改 / 删会被拒绝(409
        <code className="font-mono"> TX_ABSORBED </code>)—— 需要修正这段历史时,先在持仓页重新导入该股票的基准。
        <br />
        <span className="text-warn">链自洽:</span>
        卖出超过「该日可卖额度」时,录入会被拒绝(422
        <code className="font-mono"> INSUFFICIENT_SHARES </code>),不会写坏成本链。
        <br />
        <span className="text-warn">时间点:</span>
        同一交易日的多笔流水按「交易时间」先后计入成本(留空 = 时间未知,
        排在同日有时间的流水之前)。填错会改变当天的成本顺序,录完可在流水列表里改。
      </div>

      {error && (
        <div className="p-3 bg-danger-bg text-danger rounded-sm text-sm">
          {errorCode && (
            <span className="font-mono text-xs mr-1.5 opacity-80">{errorCode}</span>
          )}
          {error}
        </div>
      )}

      <div className="flex gap-2 justify-end">
        {onCancel && (
          <Button type="button" variant="ghost" onClick={onCancel}>
            取消
          </Button>
        )}
        <Button type="submit" loading={submitting}>
          提交
        </Button>
      </div>
    </form>
  );
}