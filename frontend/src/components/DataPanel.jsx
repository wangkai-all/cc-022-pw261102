import React from "react";
import { Badge, Empty, Section, Stat } from "./ui.jsx";

const TABLE_COPY = {
  customers: { title: "客户主表", note: "身份、联系方式与注册时间" },
  orders: { title: "订单表", note: "下单、发货时间与金额" },
  after_sales: { title: "售后表", note: "受理、解决时间与关联订单" },
};

export default function DataPanel({ dataset, seed, onNext }) {
  if (!dataset) return <Empty title="尚未加载数据" text="正在读取本地合成数据源。" />;
  const facts = dataset.facts || {};
  return (
    <div className="panel-stack">
      <section className="hero-card">
        <div className="hero-copy">
          <Badge tone="indigo">合成测试数据 · 3 张表</Badge>
          <h2>跨表一致替换，业务关系不受伤</h2>
          <p>
            客户编号在三张表中同步替换；手机号、邮箱与姓名按“租户 + 身份”独立生成；
            日期按客户整体平移。下面的数据专门覆盖跨表复用、同名客户、跨租户同手机号和缺失字段。
          </p>
          <div className="hero-facts">
            <span>跨表复用客户 <strong>{facts.customers_in_all_three_tables}</strong> 位</span>
            <span>同名身份组 <strong>{facts.same_name_identity_groups}</strong> 组</span>
            <span>跨租户同手机号 <strong>{facts.same_phone_across_tenants}</strong> 个</span>
            <span>含缺失字段客户 <strong>{facts.customer_rows_with_missing_field}</strong> 位</span>
          </div>
          <button className="primary-button" onClick={onNext} type="button">
            配置脱敏规则 <span className="arrow">→</span>
          </button>
        </div>
        <div className="hero-stats">
          <Stat label="租户" value={facts.tenants?.length ?? "—"} sub={(facts.tenants || []).join(" / ")} />
          <Stat label="客户" value={facts.customers ?? "—"} sub="customers" />
          <Stat label="订单" value={facts.orders ?? "—"} sub="orders" />
          <Stat label="售后" value={facts.after_sales ?? "—"} sub="after_sales" />
          <Stat label="空值单元格" value={facts.null_cells ?? "—"} sub="导出的空值保持为空" tone="warn" />
          <Stat
            label="本地种子"
            value={seed?.configured ? "已配置" : "缺失"}
            sub={seed?.configured ? "值不进入导出" : "运行 setup_local.py"}
            tone={seed?.configured ? "good" : "bad"}
          />
        </div>
      </section>

      {!seed?.configured && (
        <div className="alert alert-warn">
          <strong>缺少本地种子。</strong>
          <span>{seed?.detail}</span>
          <code>python scripts/setup_local.py</code>
        </div>
      )}

      <div className="table-grid">
        {dataset.tables?.map((table) => {
          const copy = TABLE_COPY[table.name] || { title: table.name, note: "" };
          return (
            <Section
              key={table.name}
              title={copy.title}
              subtitle={`${table.name} · ${table.rows} 行 · ${copy.note}`}
              actions={<Badge tone="slate">{table.columns.length} 列</Badge>}
            >
              <div className="column-list">
                {table.columns.map((column) => (
                  <div key={column.name} className="column-row">
                    <div className="column-name">
                      <code>{column.name}</code>
                      {column.nulls > 0 && <Badge tone="amber">{column.nulls} 空值</Badge>}
                    </div>
                    <span className="column-type">{column.type}</span>
                  </div>
                ))}
              </div>
            </Section>
          );
        })}
      </div>

      <Section title="数据特征如何被验证" subtitle="每条特征都有对应的检查项，失败则不发布">
        <div className="feature-grid">
          <div className="feature">
            <span className="feature-index">01</span>
            <h4>跨表复用</h4>
            <p>同一客户在客户、订单、售后表中的编号替换结果一致，外键零违规。</p>
          </div>
          <div className="feature">
            <span className="feature-index">02</span>
            <h4>同名不合并</h4>
            <p>姓名映射键包含客户身份，同名的两位客户会得到不同的假姓名。</p>
          </div>
          <div className="feature">
            <span className="feature-index">03</span>
            <h4>租户隔离</h4>
            <p>同一手机号、同一客户编号跨租户出现时，映射空间按租户分离。</p>
          </div>
          <div className="feature">
            <span className="feature-index">04</span>
            <h4>空值与日期</h4>
            <p>NULL 保持 NULL；同一客户的下单、发货、售后时间平移同一天数。</p>
          </div>
        </div>
      </Section>
    </div>
  );
}
