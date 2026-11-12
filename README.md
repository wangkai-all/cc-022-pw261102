# MaskFlow · 确定性跨表数据脱敏工作台

面向测试环境的三表（客户 / 订单 / 售后）脱敏工具。规则在网页上编辑，先全量计算映射再预览，
校验全部通过后原子发布一套新的 CSV。Python + DuckDB 负责数据处理，FastAPI 提供 API，
React 提供规则编辑、样例预览和报告界面。

## 核心保证

| 需求 | 实现 |
| --- | --- |
| 客户编号跨三表一致替换 | 同一 `namespace` 的 `surrogate_id` 映射键为 `(租户, 原客户编号)`，三表共享映射表 |
| 手机号 / 邮箱 / 姓名稳定假值 | 映射键为 `(租户, 客户身份, 规范值)`，同一身份同一原值始终得到同一结果 |
| NULL 仍是 NULL | 只对非空值分配映射，SQL 侧 `CASE WHEN col IS NULL THEN NULL` |
| 同租户同身份一致，不同租户隔离 | HMAC 输入包含租户；租户不共享映射表 |
| 同名客户不合并 | 姓名键包含客户身份，不按姓名值聚合 |
| 目标长度限制 | `max_length` 在规则校验与生成器中双重约束：编号截断、手机号定长、邮箱按域名预留、姓名按字符数组合 |
| 碰撞处理 | 每个命名空间维护已用值集合，确定性二次探测（HMAC 尝试序号）；原值集合预先禁用，避免假值等于任何原值 |
| 主键唯一 / 外键完整 | 输出后逐表检查重复主键、空主键与每个外键的违规行数 |
| 日期整体平移 | 每个 `(租户, 客户)` 由种子确定一个偏移天数，客户注册、下单、发货、售后受理、解决共用同一位移 |
| 可复现 | HMAC(本地种子 + 规则版本 + 规则指纹 + 租户 + 身份 + 原值 + 尝试序号)；同版本同种子内容一致 |
| 换种子另一套 | 种子参与每个映射；不同种子得到不同假值 |
| 种子不进入导出 | 种子只在本机配置/环境变量中；CSV、manifest、report 均不含种子值 |
| 不发布半套结果 | 先写入 `data/exports/.staging-*`，全部校验通过后才 `os.replace` 为正式任务目录；失败只写失败日志 |
| 业务查询仍成立 | 在源表和脱敏表上分别执行订单数分布、销售额、售后关联、金额明细、复购客户等查询并比对结果签名 |

## 合成数据

`data/source/` 由 `backend/maskflow/synthetic.py` 生成，专门覆盖：

- **跨表复用**：8 位客户同时出现在客户、订单、售后表。
- **同名客户**：`张伟` 在 `T-ACME` 与 `T-GLOBEX` 中各有两个不同身份（4 个身份）。
- **不同租户相同手机号**：`13800001001` 同时出现在 `T-ACME` 与 `T-GLOBEX`；同租户内也有两人共用该号码。
- **缺失字段**：空姓名、空手机号、空邮箱、空发货时间、空解决时间。
- **日期关系**：下单 ≤ 发货；售后受理 ≤ 解决。
- **无子行客户**：`T-INITECH / C3002` 没有订单，用于验证左连接类查询。

表结构：

| 表 | 主键 | 外键 / 关键列 |
| --- | --- | --- |
| `customers` | `(tenant_id, customer_id)` | `name`, `phone`, `email`, `created_at` |
| `orders` | `(tenant_id, order_id)` | `customer_id → customers`, `contact_phone`, `order_date`, `ship_date` |
| `after_sales` | `(tenant_id, case_id)` | `order_id → orders`, `customer_id → customers`, `contact_email`, `created_at`, `resolved_at` |

## 映射与确定性

### 映射键

| 字段类型 | 键 |
| --- | --- |
| 代理编号（客户号） | `(tenant_id, namespace="customer", 原值)` |
| 假姓名 | `(tenant_id, namespace="person_name", 客户身份, 原姓名)` |
| 假手机号 | `(tenant_id, namespace="phone", 客户身份, 原手机号规范化)` |
| 假邮箱 | `(tenant_id, namespace="email", 客户身份, 原邮箱规范化)` |
| 日期偏移 | `(tenant_id, 客户身份)` |

规范化：手机号去除非数字字符，邮箱 `trim + lower`，其余 `trim`。不同租户即使原值相同也不会共享映射。
同一租户内两位同名客户的姓名键不同，因此假姓名不同；同一手机号被多人共用时也按身份分别生成。

### 生成公式

```
candidate(attempt) = generator(
    HMAC-SHA256(seed,
        "maskflow" | rule_version | rules_hash | kind | namespace
        | tenant | identity | normalized_raw | attempt)
)
```

- `rules_hash` 为规则文档规范化 JSON 的 SHA-256 前 16 位，避免“版本号不变但规则内容变了”导致误判可复现。
- 排序输入键后按确定性顺序分配，碰撞探测结果与源文件行顺序无关。
- 每个命名空间的原值集合会加入禁用集合；生成值既不会与已分配值重复，也不会等于任何原始敏感值。
- 碰撞次数、残留规避次数、最大尝试次数写入报告。

### 日期平移

```
offset(tenant, customer) = min_days + HMAC256(seed, "date_shift" | version | rules_hash
                                             | tenant | customer) mod (max_days - min_days + 1)
```

所有带 `date_shift` 规则的日期列，只要身份列相同，就使用同一位移。
`DATE + offset` 保留原有先后顺序与事件间隔。

## 校验与发布

生成阶段在 DuckDB 临时表上完成以下检查，全部通过才允许写文件：

1. **规则完整性**：三张表每列必须有规则；主键/外键/身份列存在；外键两端策略与命名空间一致；参数可生成。
2. **主键**：重复键、空键均为 0。
3. **外键**：每个子行都能在父表找到对应主键。
4. **行数**：源表与输出表行数一致。
5. **空值**：每个脱敏列源空值数 = 输出空值数；不存在“非空变空”。
6. **日期**：逐列核对 `输出日期 - 源日期 = 该客户的偏移`；范围合法；先后约束与事件间隔不变；客户内事件排序不变。
7. **残留**：按命名空间把原值集合与输出列比对。电话/邮箱额外做子串扫描；姓名/编号做精确匹配。
8. **业务查询**：源/脱敏表分别执行相同 SQL，比较结果行（签名哈希）：
   - 每位客户订单数分布
   - 各租户各状态销售额
   - 每个订单关联售后数
   - 订单金额明细
   - 复购客户数量

发布流程：

```
规则校验 → 全量映射分配 → 日期偏移 → 转换内存表 → 全部校验
   ├─ 失败：删除临时目录，写 data/failures/<job>.json，导出目录无文件
   └─ 成功：data/exports/.staging-<job>/ → 写 CSV / report.json / report.md / manifest.json
            → os.replace() 原子改名为 data/exports/<job>/
```

报告包含：替换数量、命名空间/租户级碰撞与残留规避、主键/外键/行数/空值、日期与间隔、
残留扫描、业务查询签名、文件行数/SHA-256、内容指纹。报告与 manifest 都不含种子值、原始敏感值或内部映射表。

## 运行

```bash
# 1. 后端依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 2. 生成仅本机使用的种子 + 合成数据
#    config/masking.local.toml 已被 .gitignore 忽略，值为随机 48 字节
.venv/bin/python scripts/setup_local.py

# 3. 前端构建（也可分开跑 dev）
cd frontend
npm install
npm run build
cd ..

# 4. 启动（同时提供 API 与构建后的网页）
./run.sh
# 浏览器打开 http://127.0.0.1:8000
```

开发模式（两个终端）：

```bash
.venv/bin/uvicorn maskflow.api:app --app-dir backend --reload --port 8000
cd frontend && npm run dev   # Vite 代理 /api → :8000
```

种子来源优先级：

1. 环境变量 `MASKFLOW_SEED`（适合 CI / 测试）
2. `config/masking.local.toml` 中的 `[masking].seed`
3. 都没有则拒绝预览和生成

可用 `MASKFLOW_DATA_DIR` 切换数据目录，`MASKFLOW_CONFIG` 切换本地配置文件路径。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查与种子状态（不返回值） |
| GET | `/api/bootstrap` | 数据概览、默认规则、历史任务、种子状态 |
| POST | `/api/rules/validate` | 规则完整性、覆盖度、规则指纹 |
| POST | `/api/preview` | 全量映射后的样例对照（`limit` 控制每表行数） |
| POST | `/api/generate` | 生成、校验、原子发布，返回完整报告 |
| GET | `/api/jobs` | 已发布任务列表 |
| GET | `/api/jobs/{job_id}` | 重新载入报告 |
| GET | `/api/jobs/{job_id}/download/{file}` | 下载 CSV / report / manifest |

预览与生成接收：

```json
{ "rules": { "version": "1.0.0", "tenant_column": "tenant_id", "...": "..." } }
```

## 测试

```bash
.venv/bin/pytest -q backend/tests
```

覆盖：

- 三表客户编号一致、联系方式跨表复用、同名不合并、同租户/跨租户同手机号隔离、NULL 保持
- 全量校验通过（主键、外键、日期、间隔、排序、残留、业务查询）
- 同一客户在 5 个日期列上的偏移一致且在配置范围内
- 同种子同版本字节级可复现；换种子/换版本内容变化
- 碰撞探测、原值禁用重试、空间耗尽时抛错而非产生重复
- 规则缺列、外键命名空间不一致、种子缺失时拒绝生成且不发布
- 注入孤儿售后行后外键校验失败，暂存目录与导出目录均无残留
- 导出文件中不含种子和任何原始敏感值
- API 全流程、非法下载路径、422 规则错误

## 目录

```
backend/maskflow/
  api.py          FastAPI 路由 / 静态页面挂载
  service.py      预览、生成、原子发布、任务读取
  engine.py       DuckDB 源数据加载、映射构建、日期偏移、转换、预览、导出
  mapping.py      HMAC 确定性生成、碰撞探测、禁用原值
  rules.py        Pydantic 规则模型与完整性校验
  checks.py       主键/外键/空值/日期/残留/业务查询校验
  report.py       JSON 与 Markdown 报告
  synthetic.py    合成三表数据
  settings.py     本地种子/数据目录配置
backend/tests/    pytest 单元与 API 测试
frontend/         React + Vite 规则编辑器、预览、报告
scripts/          setup_local.py · generate_synthetic.py
data/source/      合成源数据（已生成）
data/exports/     原子发布的任务目录（运行时生成，git 忽略）
```

## 边界说明

- 该实现针对固定三表结构；新增表需要同时扩展 `COLUMN_TYPES` 与规则校验。引擎本身按规则表/列遍历，接入其他同构数据集时可复用。
- 英文/中文姓名生成器只使用与源数据不相交的字池；若换成真实数据，仍会通过“原值禁用集合”保证不残留，但姓名可读性会下降，可按需替换字池。
- 残留扫描为精确值 + 高熵字段子串扫描；姓名只做精确匹配，避免短姓名子串误报。
- 种子一旦丢失无法复现旧结果；请把 `config/masking.local.toml` 或 CI 密钥单独保管。
