# 测试策略文档:盘后诊股室

**文档版本**:v1.3
**创建日期**:2026-08-01
**最后更新**:2026-08-01(v1.3 新增 Key 加密/解密测试 + 脱敏规则 + 优雅降级测试)
**文档状态**:已通过评审,准备实施
**目标读者**:开发者(自用项目,实际就是用户本人)
**配套文档**:
- `project-book.md`(PM 项目书,Source of Truth,验收标准见 7.2)
- `backend-architecture.md`(后端架构,可测试性见第 13 章)
- `frontend-architecture.md`(前端架构,可测试性见第 14 章)

---

## 1. 测试目标

| 目标 | 验收口径 |
|---|---|
| 核心算法可信 | cost_engine / scorer 单测 100% 覆盖,与同花顺/东财对照误差 ≤ 0.01 |
| 数据准确 | 数据源返回校验(交易日/昨收/未来日期),见 backend §13.3 |
| 并发安全 | 并发写测试无 `database is locked`,见 backend §4.6 |
| 数据不丢 | 导出 → 导入还原测试,见 project-book 9.5 |
| 前端交互 | 关键组件行为测试(热力图/评分三态/止损弹窗) |

---

## 2. 测试金字塔

```
        E2E(v0.3 可选,Playwright)
         ▲
        ╱ ╲
       ╱   ╲
      ╱─────╲     集成测试:API 端到端(pytest + httpx.AsyncClient)
     ╱       ╲    并发安全 + 数据准确性(每日/每周)
    ╱─────────╲
   ╱           ╲  单元测试:Domain 纯函数,覆盖率 100%
  ╱             ╲    cost_engine / scorer / decimal_helper
 ─────────────────
```

---

## 3. 各层测试清单

### 3.1 单元测试(每次开发后跑)

| 文件 | 覆盖重点 | 目标 |
|---|---|---|
| `tests/test_cost_engine.py` | 加仓/减仓/做T/清仓 4 类场景 + 边界 | 100% |
| `tests/test_scorer.py` | 5 维度各分支 + 0 数据降级 + 三档市场环境 | 100% |
| `tests/test_decimal_helper.py` | 精度、quantize、格式 | 100% |
| `tests/test_annual_report_service.py` | 聚合逻辑(胜率/Top5/周转率) | 100% |

### 3.2 集成测试(API)

| 文件 | 覆盖重点 |
|---|---|
| `tests/test_calculator_api.py` | 入参校验(422)、清仓边界、持仓不存在 |
| `tests/test_diagnose_api.py` | 评分落库、AI 失败降级、SSE 事件顺序 |
| `tests/test_llm_factory.py`(v1.1 新增) | 3 个 provider 都能实例化,无 key 抛错,有 key 通过 |
| `tests/test_llm_prompt_consistency.py`(v1.1 新增) | 同样输入下 3 个 provider 返回差异度(用于 A/B 对比) |
| `tests/test_stop_loss_api.py` | 设置/更新/删除、触发标记幂等 |
| `tests/test_transactions_api.py` | CRUD、卖出超额 422 |

### 3.3 并发测试(每日)

```python
# tests/test_concurrency.py(见 backend §4.6.4)
- 并发 20 笔写(流水+评分+止损):全部成功,无锁冲突
```

### 3.4 数据准确性测试(每日 + 每周)

见 `backend-architecture.md` §13.3:
- **每日**(单元级):交易日判断、节假日
- **每周**(集成,周日 02:00):昨收一致性、无未来日期、负价格拒绝

### 3.5 迁移还原测试(每次发布前)

```
导出 JSON → 删除 data.db → 导入 → 断言:
  持仓股数/总成本一致
  评分明细与 AI 评语一致
  止损设置一致
```

### 3.6 前端测试(vitest + @testing-library/react)

| 组件 | 测试重点 |
|---|---|
| `PnlHeatmap` | 21 档渲染、当前价标线、hover 放大 |
| `ScoreDetail` | 三态切换(完整/加载中/失败) |
| `StopLossAlert` | 必选其一、不可关闭遮罩 |
| `useStopLossChecker` | 触发条件、每天最多 1 次 |
| `aggregatePositions`(派生) | 加仓/减仓/清仓聚合正确 |

### 3.7 E2E(v0.3,可选)

- Playwright:录入 → 计算 → 诊断 全流程
- MVP 不做(单人工具,手动验证成本低)

### 3.8 截图识别测试(v1.2 新增)

| 文件 | 测试重点 |
|---|---|
| `tests/test_paddle_client.py` | OCR 文本提取:空文件 / 超大文件 / 非图片格式 / 置信度过滤 |
| `tests/test_screenshot_service.py` | 主路径(OCR+LLM)+ 降级路径(JSON 粘贴)+ confirm / reject |
| `tests/test_screenshot_api.py` | 5 端点:upload / pending / confirm / reject / parse-paste |
| `tests/test_text_extract.py` | 同花顺持仓 / 流水 / 自选股 布局的字段提取规则(行扫描 + 正则)|
| `tests/fixtures/tencent_screenshots/` | 5 张测试用截图(持仓 2 + 流水 2 + 自选股 1) |

### 3.9 Prompt 模板测试(v1.2 新增)

| 文件 | 测试重点 |
|---|---|
| `tests/test_vision_prompt.py` | 断言 OCR_USER_TEMPLATE 字段完整 + 占位符正确 + JSON 示例合法 |
| Prompt 哈希快照测试 | 防止意外改动(vision_prompt.py 的 SHA-256 写进 fixture,改动需 review) |

### 3.10 截图路径覆盖率(v1.2 新增)

```
主路径:95%(同花顺 + LLM 解析成功)
降级路径:100%(粘贴 JSON 解析 + 校验)
失败路径:90%(OCR 失败 / JSON 不合法 / 图片超大 都走 422 友好提示)
```

### 3.11 LLM Key 加密 + 优雅降级测试(v1.3 新增)

| 文件 | 测试重点 |
|---|---|
| `tests/test_crypto.py` | Fernet 加解密往返;InvalidToken 抛错;空 Key 不抛异常 |
| `tests/test_llm_keys_repo.py` | upsert / get_decrypted 往返;缺 Key 返回 None;解密失败返回 None |
| `tests/test_llm_factory.py`(升级) | Key 缺时 ProviderFactory.get 返回 None(不抛错)|
| `tests/test_diagnose_api.py`(升级) | Key 缺时 trade.failed 推送 reason="Provider 未配置 Key" |
| `tests/test_llm_keys_api.py` | GET 返回配置状态(不返回明文);PUT 更新 3 Provider;FERNET_KEY 变更后 GET 返回未配置 |

### 3.12 Key 测试安全规范(v1.3 新增)

```
✓ 测试 fixture 使用 mock Key(如 "sk-test-xxx"),不用真实 Key
✓ 测试日志 / 异常消息 不打印明文 Key
✓ CI 环境禁用真实 Key 调用 LLM(用 stub)
✓ test_llm_keys_repo.py 加 teardown 清理明文 Key fixture
```

---

## 4. 测试数据

## 4. 测试数据

### 4.1 种子数据

```bash
cd backend
python scripts/seed_test_data.py   # 生成:3 只持仓 + 30 笔历史流水 + 10 笔待诊断
```

### 4.2 Ground Truth 样本(评分校准,v1.3 R18 配套)

- `tests/fixtures/ground_truth.json`:10 个真实交易样本
- 每个样本:交易数据 + **人工打的分** + 各维度理由
- 用途:`test_scorer.py` 断言评分函数输出与人工打分差 ≤ 10 分
- 数据来源:用户真实历史交易(脱敏)

---

## 5. 验收标准 ↔ 测试映射(project-book 7.2)

| 验收标准 | 对应测试 | 触发时机 |
|---|---|---|
| 计算器 4 类场景误差 ≤ 0.01 | `test_cost_engine.py` + 人工对照 | 每次开发 + 发布前 |
| 诊断触发成功率 ≥ 95% | `test_diagnose_api.py` + 监控埋点 | 发布前 |
| 诊断耗时 < 30s | `test_diagnose_api.py` 断言耗时 | 发布前 |
| 评分 + 评语 100% 单测覆盖 | 覆盖率报告(`pytest --cov`) | 每次开发 |
| SSE 推送成功率 > 90% | 集成测试 + 前端降级观察 | 发布前 |

---

## 6. 运行方式与频率

| 时机 | 命令 | 说明 |
|---|---|---|
| 每次修改核心算法后 | `pytest tests/test_cost_engine.py tests/test_scorer.py -q` | 秒级 |
| 每天开始开发前 | `pytest -q`(全量) | 确认无回归 |
| 每天结束前 | `pytest --cov=app/core --cov=app/services` | 覆盖率回落检查 |
| 每周日 02:00 | `pytest tests/integration -m integration` | 数据准确性巡检 |
| 发布前 | 全量 + 迁移还原测试 + 前端 `npm run test` + `typecheck` | release-process §4 |

**失败即修,不跨天**:个人项目,测试红了就是当天的活。

---

## 7. 常见坑与约定

| 坑 | 约定 |
|---|---|
| Decimal 断言 `==` 误差 | 用 `quantize(0.001)` 后比较,或 `abs(a-b) < 0.001` |
| asyncio 测试 | `pytest.mark.asyncio`;临时 DB 用 `tmp_path` + 独立 aiosqlite 文件 |
| 网络依赖 | akshare/东财/LLM **不 mock 网络库**,而是 mock 数据源返回(见 backend §4.4 纯函数分离的好处);真实网络只进 integration 标记 |
| httpx mock | `httpx.MockTransport` 构造东财响应 fixture |
| 测试不碰真实 `data.db` | 统一 `settings.database_url` 指向 `tmp_path` |
| LLM 不真调用 | `DeepSeekClient` 在测试中替换为 stub,断言 Prompt 内容 |
| 多 Provider mock(v1.1 新增) | 3 个 client 各自 stub,断言各自构造的请求 URL/Headers/Body 正确(DeepSeek/MiniMax/豆包) |
| Provider 切换状态(v1.1 新增) | llm_settings 表切换后,下次 score_and_notify 必须用新 provider(集成测试)|
| Provider API 兼容性差异(v1.1 新增) | DeepSeek/豆包用 OpenAI 兼容,MiniMax 自有格式;测试需覆盖消息体适配 |
| PaddleOCR 首次加载慢(v1.2 新增) | lazy init,首次识别 5~10s(冷启动);测试 fixture 用 mock,集成测试才真加载 |
| OCR 置信度 < 0.5(v1.2 新增) | 过滤该行,不送给 LLM;items 中标记 `low_confidence: true` |
| 用户粘贴 JSON 不合法(v1.2 新增) | 返回 422 + 友好提示"JSON 格式错误,请检查" |
| 截图格式(v1.2 新增) | 后端校验:只 jpg / png / webp;其他 415 |
| 截图大小 > 5MB(v1.2 新增) | 前端压缩(canvas.toBlob)+ 后端再次校验 |
| 截图原图清理(v1.2 新增) | reject 时删除 `~/rich/uploads/{uuid}.jpg`,不留垃圾 |
| Key 脱敏(v1.3 新增) | 日志 / 异常消息 / SSE 推送 / API 响应 都不出现明文 Key;用 `***` 替代 |
| Key 测试 fixture(v1.3 新增) | 用 `sk-test-xxx` 占位,绝不写真实 Key 进 git |
| FERNET_KEY 丢失(v1.3 新增) | decrypt 抛 InvalidToken → 返回 None + 提示用户重新输入 |
| Key 路径不阻塞启动(v1.3 新增) | 启动时缺 Key 不报错;只触发诊断时才提示 |

---

**文档结束。**
