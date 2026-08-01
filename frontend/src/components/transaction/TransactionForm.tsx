'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';

import { apiPost } from '@/lib/api';
import type { Transaction, TransactionCreate } from '@/lib/types';

import { Button } from '../ui/Button';

/**
 * 交易录入表单(frontend-arch §10.3 / ui-ux §4.3)
 */
const schema = z.object({
  stockCode: z.string().length(6).regex(/^\d{6}$/, '股票代码必须是 6 位数字'),
  action: z.enum(['buy', 'sell']),
  shares: z.number().int().positive('股数必须 > 0'),
  price: z.string().regex(/^\d+(\.\d{1,3})?$/, '价格格式:数字,最多 3 位小数'),
  tradeDate: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, '日期格式 YYYY-MM-DD'),
  note: z.string().max(200).optional(),
});

type FormData = z.infer<typeof schema>;

interface TransactionFormProps {
  onSuccess?: (tx: Transaction) => void;
  onCancel?: () => void;
}

export function TransactionForm({ onSuccess, onCancel }: TransactionFormProps) {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors },
    reset,
  } = useForm<FormData>({
    resolver: zodResolver(schema) as never, // exactOptionalPropertyTypes 兼容
    defaultValues: {
      stockCode: '',
      action: 'buy' as const,
      shares: 500,
      price: '',
      tradeDate: new Date().toISOString().slice(0, 10),
      note: '',
    },
  });

  const onSubmit = async (data: FormData) => {
    setSubmitting(true);
    setError(null);
    try {
      const payload: TransactionCreate = {
        stockCode: data.stockCode,
        action: data.action,
        shares: data.shares,
        price: data.price,
        tradeDate: data.tradeDate,
        ...(data.note ? { note: data.note } : {}),
      };
      const tx = await apiPost<Transaction>('/transactions', payload);
      reset();
      onSuccess?.(tx);
    } catch (e) {
      if (e instanceof Error) setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">股票代码</label>
          <input
            type="text"
            inputMode="numeric"
            maxLength={6}
            placeholder="000001"
            className="w-full px-3 py-2 border border-border-strong rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent"
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

      <div className="grid grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium mb-1">交易日期</label>
          <input
            type="date"
            className="w-full px-3 py-2 border border-border-strong rounded-sm focus:outline-none focus:ring-2 focus:ring-accent"
            {...register('tradeDate')}
          />
          {errors.tradeDate && (
            <p className="text-up text-xs mt-1">{errors.tradeDate.message}</p>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium mb-1">股数</label>
          <input
            type="number"
            min={1}
            step={100}
            className="w-full px-3 py-2 border border-border-strong rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent"
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
          className="w-full px-3 py-2 border border-border-strong rounded-sm font-mono focus:outline-none focus:ring-2 focus:ring-accent"
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
          className="w-full px-3 py-2 border border-border-strong rounded-sm focus:outline-none focus:ring-2 focus:ring-accent"
          {...register('note')}
        />
        {errors.note && (
          <p className="text-up text-xs mt-1">{errors.note.message}</p>
        )}
      </div>

      {error && (
        <div className="p-3 bg-up-bg text-up rounded-sm text-sm">{error}</div>
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