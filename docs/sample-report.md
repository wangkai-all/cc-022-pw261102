> 示例报告：由本地合成数据生成，种子值不包含在任何导出文件中。

# MaskFlow 脱敏生成报告

- 任务编号：`run-20261111-233614-6b572388`
- 生成时间：2026-11-11T23:36:14+00:00
- 规则版本：`1.0.0`
- 规则指纹：`3172d0beef17576e`
- 内容指纹：`d7351a3e883e9f617a3d1a88`
- 种子来源：local config (masking.local.toml)（种子值未写入导出文件）

## 结论

- 发布状态：通过，已原子发布
- 源数据行数：39
- 替换值数量：149
- 映射值数量：42
- 碰撞次数：0
- 原敏感值残留：0

## 替换数量

| 表 | 列 | 策略 | 替换数量 | 保留空值 | 输出去重值 |
| --- | --- | --- | ---: | ---: | ---: |
| customers | customer_id | 代理编号 | 12 | 0 | 12 |
| customers | name | 姓名假值 | 11 | 1 | 11 |
| customers | phone | 手机号假值 | 10 | 2 | 10 |
| customers | email | 邮箱假值 | 9 | 3 | 9 |
| customers | created_at | 日期平移 | 12 | 0 | 11 |
| orders | customer_id | 代理编号 | 18 | 0 | 11 |
| orders | contact_phone | 手机号假值 | 14 | 4 | 9 |
| orders | order_date | 日期平移 | 18 | 0 | 17 |
| orders | ship_date | 日期平移 | 13 | 5 | 13 |
| after_sales | customer_id | 代理编号 | 9 | 0 | 8 |
| after_sales | contact_email | 邮箱假值 | 7 | 2 | 7 |
| after_sales | created_at | 日期平移 | 9 | 0 | 9 |
| after_sales | resolved_at | 日期平移 | 7 | 2 | 7 |

## 碰撞处理

| 命名空间 | 类型 | 租户 | 分配值 | 碰撞次数 | 残留规避 | 最大尝试 |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| customer | surrogate_id | T-ACME | 6 | 0 | 0 | 1 |
| customer | surrogate_id | T-GLOBEX | 4 | 0 | 0 | 1 |
| customer | surrogate_id | T-INITECH | 2 | 0 | 0 | 1 |
| email | fake_email | T-ACME | 4 | 0 | 0 | 1 |
| email | fake_email | T-GLOBEX | 4 | 0 | 0 | 1 |
| email | fake_email | T-INITECH | 1 | 0 | 0 | 1 |
| person_name | fake_name | T-ACME | 5 | 0 | 0 | 1 |
| person_name | fake_name | T-GLOBEX | 4 | 0 | 0 | 1 |
| person_name | fake_name | T-INITECH | 2 | 0 | 0 | 1 |
| phone | fake_phone | T-ACME | 5 | 0 | 0 | 1 |
| phone | fake_phone | T-GLOBEX | 3 | 0 | 0 | 1 |
| phone | fake_phone | T-INITECH | 2 | 0 | 0 | 1 |

碰撞通过确定性二次探测解决；原值集合被预先加入禁用集合，因此生成值不会与任何原始敏感值相同。

## 关联与完整性校验

### 主键唯一

| 表 | 主键 | 行数 | 重复键 | 空键 | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| customers | tenant_id, customer_id | 12 | 0 | 0 | 通过 |
| orders | tenant_id, order_id | 18 | 0 | 0 | 通过 |
| after_sales | tenant_id, case_id | 9 | 0 | 0 | 通过 |

### 外键完整

| 子表 | 外键列 | 引用 | 检查行数 | 违规 | 结果 |
| --- | --- | --- | ---: | ---: | --- |
| orders | tenant_id, customer_id | customers.['tenant_id', 'customer_id'] | 18 | 0 | 通过 |
| after_sales | tenant_id, order_id | orders.['tenant_id', 'order_id'] | 9 | 0 | 通过 |
| after_sales | tenant_id, customer_id | customers.['tenant_id', 'customer_id'] | 9 | 0 | 通过 |

### 行数与空值

| 表 | 源行数 | 输出行数 | 结果 |
| --- | ---: | ---: | --- |
| customers | 12 | 12 | 通过 |
| orders | 18 | 18 | 通过 |
| after_sales | 9 | 9 | 通过 |

| 表.列 | 源空值 | 输出空值 | 非空变空 | 结果 |
| --- | ---: | ---: | ---: | --- |
| customers.customer_id | 0 | 0 | 0 | 通过 |
| customers.name | 1 | 1 | 0 | 通过 |
| customers.phone | 2 | 2 | 0 | 通过 |
| customers.email | 3 | 3 | 0 | 通过 |
| customers.created_at | 0 | 0 | 0 | 通过 |
| orders.customer_id | 0 | 0 | 0 | 通过 |
| orders.contact_phone | 4 | 4 | 0 | 通过 |
| orders.order_date | 0 | 0 | 0 | 通过 |
| orders.ship_date | 5 | 5 | 0 | 通过 |
| after_sales.customer_id | 0 | 0 | 0 | 通过 |
| after_sales.contact_email | 2 | 2 | 0 | 通过 |
| after_sales.created_at | 0 | 0 | 0 | 通过 |
| after_sales.resolved_at | 2 | 2 | 0 | 通过 |

## 日期整体平移

- 平移客户数：12；偏移范围：-29 ~ 28 天；不同偏移：11 种
- 配置范围：-30 ~ 30 天；范围检查：通过

| 表.日期列 | 身份列 | 非空变空 | 空变非空 | 偏移不一致 | 结果 |
| --- | --- | ---: | ---: | ---: | --- |
| customers.created_at | customer_id | 0 | 0 | 0 | 通过 |
| orders.order_date | customer_id | 0 | 0 | 0 | 通过 |
| orders.ship_date | customer_id | 0 | 0 | 0 | 通过 |
| after_sales.created_at | customer_id | 0 | 0 | 0 | 通过 |
| after_sales.resolved_at | customer_id | 0 | 0 | 0 | 通过 |

| 表 | 先后约束 | 检查行数 | 违规 | 结果 |
| --- | --- | ---: | ---: | --- |
| orders | 下单日期不晚于发货日期 | 13 | 0 | 通过 |
| after_sales | 售后受理时间不晚于解决时间 | 7 | 0 | 通过 |

| 表 | 间隔 | 检查行数 | 间隔变化 | 结果 |
| --- | --- | ---: | ---: | --- |
| orders | order_date -> ship_date | 13 | 0 | 通过 |
| after_sales | created_at -> resolved_at | 7 | 0 | 通过 |

| 表 | 事件键 | 排序依据 | 检查行数 | 次序变化 | 结果 |
| --- | --- | --- | ---: | ---: | --- |
| orders | order_id | order_date, order_id | 18 | 0 | 通过 |
| after_sales | case_id | created_at, case_id | 9 | 0 | 通过 |

## 原敏感值残留检查

| 命名空间 | 类型 | 原值数量 | 覆盖列 | 精确命中 | 子串命中 | 模式 | 结果 |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| customer | surrogate_id | 11 | 3 | 0 | 0 | exact | 通过 |
| email | fake_email | 9 | 2 | 0 | 0 | exact+substring | 通过 |
| person_name | fake_name | 8 | 1 | 0 | 0 | exact | 通过 |
| phone | fake_phone | 7 | 2 | 0 | 0 | exact+substring | 通过 |

## 业务查询等价性

| 查询 | 说明 | 源分组数 | 脱敏后分组数 | 源签名 | 脱敏签名 | 结果 |
| --- | --- | ---: | ---: | --- | --- | --- |
| orders_per_customer | 跨表关联：每位客户的订单数分布 | 11 | 11 | `cdd939f65ac40819` | `cdd939f65ac40819` | 通过 |
| revenue_by_status | 聚合：各租户各订单状态的销售额 | 8 | 8 | `209bdbbe6a5bfec2` | `209bdbbe6a5bfec2` | 通过 |
| after_sales_per_order | 关联：每个订单关联的售后单数 | 9 | 9 | `95bc04275cbe8b49` | `95bc04275cbe8b49` | 通过 |
| order_amounts | 明细：订单金额（src） | 18 | 18 | `2894a910e07a2e1a` | `2894a910e07a2e1a` | 通过 |
| repeat_customers | 留存：复购客户数量 | 3 | 3 | `8dd8180c768f8363` | `8dd8180c768f8363` | 通过 |

## 输出文件

| 文件 | 行数 | SHA-256 |
| --- | ---: | --- |
| customers.csv | 12 | `4606f6dd8818515040ca231e23dd28895feafcb3f1ef7f0e9314b855bfa09cd3` |
| orders.csv | 18 | `3316883e5f7242c8842f0c93b2d3878810d91f22a3fd62c1aa033b907b3a4d59` |
| after_sales.csv | 9 | `7dc2a58b252dd55e03fc790f49eb156d55e1eb59dc142c1489fdad84e8cc03d8` |

> 导出目录不包含种子、原始敏感值或内部映射表；只有通过全部校验后才会原子发布。
