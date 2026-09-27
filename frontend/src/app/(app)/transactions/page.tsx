'use client';

import { useState } from 'react';

import { Button } from '@/components/ui/Button';
import { Card } from '@/components/ui/Card';
import { TransactionForm } from '@/components/transaction/TransactionForm';
import { TransactionTable } from '@/components/transaction/TransactionTable';

/**
 * 流水录入页(/transactions,P2.4 实施)
 *
 * 上半:录入表单(折叠/展开)
 * 下半:流水列表
 */
export default function TransactionsPage() {
  const [showForm, setShowForm] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <main className="min-h-screen p-8 max-w-6xl mx-auto">
      <header className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">交易流水</h1>
          <p className="text-text-sec text-sm mt-1">
            录入每笔交易,自动触发 AI 诊断评分(MVP v0.1.0)
          </p>
        </div>
        <Button onClick={() => setShowForm((v) => !v)}>
          {showForm ? '收起表单' : '+ 新增流水'}
        </Button>
      </header>

      {showForm && (
        <Card className="mb-6">
          <h2 className="text-lg font-semibold mb-4">新增交易</h2>
          <TransactionForm
            onSuccess={() => {
              setShowForm(false);
              setRefreshKey((k) => k + 1);
            }}
            onCancel={() => setShowForm(false)}
          />
        </Card>
      )}

      <Card padding="md">
        <TransactionTable refreshKey={refreshKey} />
      </Card>
    </main>
  );
}