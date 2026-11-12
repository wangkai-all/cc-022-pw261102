import React, { useState } from "react";
import { Badge, Section, StatusPill } from "./ui.jsx";

const STRATEGIES = [
  ["passthrough", "保留原值", "原文照常输出"],
  ["surrogate_id", "代理编号", "跨表一致的确定性编号"],
  ["fake_name", "姓名假值", "按客户身份生成"],
  ["fake_phone", "手机号假值", "按客户身份生成"],
  ["fake_email", "邮箱假值", "按客户身份生成"],
  ["date_shift", "日期平移", "按客户整体平移"],
];

const STRATEGY_TONE = {
  passthrough: "slate",
  surrogate_id: "indigo",
  fake_name: "violet",
  fake_phone: "cyan",
  fake_email: "teal",
  date_shift: "amber",
};

function identityColumn(tableRules, columns) {
  if (columns.includes("customer_id")) return "customer_id";
  return (
    tableRules.primary_key.find(
      (column) => column !== "tenant_id" && columns.includes(column),
    ) ||
    columns[0] ||
    ""
  );
}

function defaultRule(strategy, column, tableRules, columns) {
  if (strategy === "surrogate_id") {
    return {
      strategy,
      namespace: column === "customer_id" ? "customer" : column,
      prefix: "MC",
      max_length: 12,
    };
  }
  if (strategy === "fake_name") {
    return {
      strategy,
      namespace: "person_name",
      identity: identityColumn(tableRules, columns),
      max_length: 8,
    };
  }
  if (strategy === "fake_phone") {
    return {
      strategy,
      namespace: "phone",
      identity: identityColumn(tableRules, columns),
      max_length: 11,
      prefixes: ["170", "171", "172", "173"],
    };
  }
  if (strategy === "fake_email") {
    return {
      strategy,
      namespace: "email",
      identity: identityColumn(tableRules, columns),
      max_length: 40,
      domain: "masked.example",
    };
  }
  if (strategy === "date_shift") {
    return {
      strategy,
      identity: identityColumn(tableRules, columns),
    };
  }
  return { strategy: "passthrough" };
}

function ColumnControls({ rule, column, tableName, tableRules, columns, onChange }) {
  if (rule.strategy === "passthrough") {
    return <span className="rule-muted">不修改该列，输出时保持原值</span>;
  }

  const update = (patch) => onChange({ ...rule, ...patch });

  return (
    <div className="rule-inputs">
      {rule.strategy !== "date_shift" && (
        <label className="field compact">
          <span>命名空间</span>
          <input
            value={rule.namespace || ""}
            onChange={(event) => update({ namespace: event.target.value })}
            spellCheck={false}
          />
        </label>
      )}
      {rule.strategy !== "surrogate_id" && (
        <label className="field compact">
          <span>身份列</span>
          <select
            value={rule.identity || ""}
            onChange={(event) => update({ identity: event.target.value })}
          >
            {columns.map((item) => (
              <option key={item} value={item}>
                {item}
              </option>
            ))}
          </select>
        </label>
      )}
      {rule.strategy !== "date_shift" && (
        <label className="field compact">
          <span>长度上限</span>
          <input
            type="number"
            min="1"
            max="512"
            value={rule.max_length ?? ""}
            onChange={(event) =>
              update({ max_length: Math.max(1, Number(event.target.value) || 1) })
            }
          />
        </label>
      )}
      {rule.strategy === "surrogate_id" && (
        <label className="field compact">
          <span>前缀</span>
          <input
            value={rule.prefix || ""}
            onChange={(event) => update({ prefix: event.target.value })}
            spellCheck={false}
          />
        </label>
      )}
      {rule.strategy === "fake_phone" && (
        <label className="field compact wide">
          <span>号段前缀（逗号分隔）</span>
          <input
            value={(rule.prefixes || []).join(",")}
            onChange={(event) =>
              update({
                prefixes: event.target.value
                  .split(",")
                  .map((item) => item.trim())
                  .filter(Boolean),
              })
            }
            spellCheck={false}
          />
        </label>
      )}
      {rule.strategy === "fake_email" && (
        <label className="field compact wide">
          <span>假邮箱域名</span>
          <input
            value={rule.domain || ""}
            onChange={(event) => update({ domain: event.target.value })}
            spellCheck={false}
          />
        </label>
      )}
      {rule.strategy === "date_shift" && (
        <span className="rule-muted">
          由种子为客户确定偏移天数，下单 / 发货 / 售后时间共用同一位移
        </span>
      )}
      {rule.strategy === "surrogate_id" && (
        <span className="rule-muted">
          同一命名空间的编号在 {tableName} 及其他表中保持一致
        </span>
      )}
    </div>
  );
}

export default function RulesEditor({
  rules,
  dataset,
  validation,
  onUpdate,
  onValidate,
  onReset,
  onNext,
  busy,
  seed,
}) {
  const [activeTable, setActiveTable] = useState(dataset?.tables?.[0]?.name || "customers");
  if (!rules || !dataset) return null;

  const tableNames = dataset.tables.map((table) => table.name);
  const active = tableNames.includes(activeTable) ? activeTable : tableNames[0];
  const table = rules.tables[active];
  const tableSchema = dataset.tables.find((item) => item.name === active);
  const columns = tableSchema?.columns.map((column) => column.name) || [];

  const setTable = (patch) =>
    onUpdate({
      ...rules,
      tables: { ...rules.tables, [active]: { ...table, ...patch } },
    });

  const setColumn = (column, nextRule) => {
    const nextColumns = { ...table.columns, [column]: nextRule };
    onUpdate({
      ...rules,
      tables: {
        ...rules.tables,
        [active]: { ...table, columns: nextColumns },
      },
    });
  };

  const maskedCount = Object.values(table.columns).filter(
    (rule) => rule.strategy !== "passthrough",
  ).length;

  return (
    <div className="panel-stack">
      <Section
        title="规则版本与日期平移"
        subtitle="规则版本与种子共同决定输出内容；种子只从本地配置读取"
        actions={
          <Badge tone={seed?.configured ? "green" : "red"} dot>
            {seed?.configured ? "种子已配置" : "种子缺失"}
          </Badge>
        }
      >
        <div className="config-grid">
          <label className="field">
            <span>规则版本</span>
            <input
              value={rules.version}
              onChange={(event) => onUpdate({ ...rules, version: event.target.value })}
              spellCheck={false}
            />
            <small>同一版本 + 同一种子重复生成，数据内容一致</small>
          </label>
          <label className="field">
            <span>最早平移（天）</span>
            <input
              type="number"
              value={rules.date_shift.min_days}
              onChange={(event) =>
                onUpdate({
                  ...rules,
                  date_shift: {
                    ...rules.date_shift,
                    min_days: Number(event.target.value),
                  },
                })
              }
            />
          </label>
          <label className="field">
            <span>最晚平移（天）</span>
            <input
              type="number"
              value={rules.date_shift.max_days}
              onChange={(event) =>
                onUpdate({
                  ...rules,
                  date_shift: {
                    ...rules.date_shift,
                    max_days: Number(event.target.value),
                  },
                })
              }
            />
          </label>
          <div className="config-note">
            <strong>确定性</strong>
            <span>
              HMAC(种子 + 规则版本 + 规则指纹 + 租户 + 身份)。不写回种子，不共享跨租户映射。
            </span>
          </div>
        </div>
      </Section>

      {validation && (
        <div className={`alert ${validation.valid ? "alert-ok" : "alert-error"}`}>
          <div className="alert-head">
            <StatusPill passed={validation.valid} label={validation.valid ? "规则完整" : "规则不完整"} />
            {validation.rules_hash && <code>rules #{validation.rules_hash}</code>}
            {validation.coverage?.masked_columns != null && (
              <span>
                覆盖 {validation.coverage.tables} 张表 / {validation.coverage.columns} 列，
                {validation.coverage.masked_columns} 列脱敏
              </span>
            )}
          </div>
          {validation.errors?.length > 0 && (
            <ul className="issue-list">
              {validation.errors.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          )}
          {validation.warnings?.length > 0 && (
            <ul className="issue-list warning">
              {validation.warnings.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          )}
        </div>
      )}

      <Section
        title="字段脱敏规则"
        subtitle="每张表的每一列都必须有规则；外键与主键的策略和命名空间必须一致"
        actions={
          <div className="inline-actions">
            <button className="ghost-button" onClick={onReset} type="button">
              重置默认
            </button>
            <button className="secondary-button" onClick={onValidate} disabled={busy} type="button">
              校验规则
            </button>
          </div>
        }
      >
        <div className="table-tabs">
          {tableNames.map((name) => {
            const item = rules.tables[name];
            const masked = Object.values(item?.columns || {}).filter(
              (rule) => rule.strategy !== "passthrough",
            ).length;
            return (
              <button
                key={name}
                type="button"
                className={`table-tab ${name === active ? "active" : ""}`}
                onClick={() => setActiveTable(name)}
              >
                <span>{name}</span>
                <Badge tone="slate">{masked} 列脱敏</Badge>
              </button>
            );
          })}
        </div>

        <div className="table-meta">
          <Badge tone="indigo">PK {table.primary_key.join(" + ")}</Badge>
          {table.foreign_keys.map((fk, index) => (
            <Badge key={index} tone="cyan">
              FK {fk.columns.join(" + ")} → {fk.references.table}
            </Badge>
          ))}
          <span className="table-meta-note">
            {maskedCount} / {columns.length} 列使用脱敏策略
          </span>
        </div>

        <div className="rule-list">
          {columns.map((column) => {
            const rule = table.columns[column] || { strategy: "passthrough" };
            const schema = tableSchema.columns.find((item) => item.name === column);
            return (
              <div key={column} className={`rule-row strategy-${rule.strategy}`}>
                <div className="rule-ident">
                  <code>{column}</code>
                  <span className="rule-type">{schema?.type}</span>
                  {schema?.nulls > 0 && <Badge tone="amber">{schema.nulls} 空值</Badge>}
                </div>
                <div className="rule-strategy">
                  <select
                    value={rule.strategy}
                    onChange={(event) =>
                      setColumn(
                        column,
                        defaultRule(event.target.value, column, table, columns),
                      )
                    }
                  >
                    {STRATEGIES.map(([value, label, hint]) => (
                      <option key={value} value={value}>
                        {label} — {hint}
                      </option>
                    ))}
                  </select>
                  <Badge tone={STRATEGY_TONE[rule.strategy]}>{rule.strategy}</Badge>
                </div>
                <ColumnControls
                  rule={rule}
                  column={column}
                  tableName={active}
                  tableRules={table}
                  columns={columns}
                  onChange={(next) => setColumn(column, next)}
                />
              </div>
            );
          })}
        </div>
      </Section>

      <div className="wizard-footer">
        <div className="footer-note">
          {validation?.valid
            ? "规则已通过完整性校验，可以生成样例预览。"
            : "生成前会再次执行完整性、外键策略一致性和种子检查；任何失败都不会发布半套结果。"}
        </div>
        <button className="primary-button" onClick={onNext} type="button">
          样例预览 <span className="arrow">→</span>
        </button>
      </div>
    </div>
  );
}
