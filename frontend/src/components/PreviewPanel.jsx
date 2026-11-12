import React from "react";
import { Badge, Empty, RenderValue, Section, Stat, Spinner } from "./ui.jsx";

const STRATEGY_TONE = {
  passthrough: "slate",
  surrogate_id: "indigo",
  fake_name: "violet",
  fake_phone: "cyan",
  fake_email: "teal",
  date_shift: "amber",
};

export default function PreviewPanel({ preview, runPreview, limit, setLimit, busy, onNext, seed }) {
  const mapping = preview?.mapping;
  const dateShift = preview?.date_shift;
  const replacedCount = preview?.replacements?.reduce((sum, item) => sum + item.replaced, 0);

  return (
    <div className="panel-stack">
      <Section
        title="样例预览"
        subtitle="先对全量数据计算映射与碰撞，再截取样例行；预览中的值就是最终导出的值"
        actions={
          <div className="inline-actions">
            <label className="field inline">
              <span>每表行数</span>
              <select value={limit} onChange={(event) => setLimit(Number(event.target.value))}>
                {[3, 5, 10, 20].map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="primary-button"
              onClick={runPreview}
              disabled={busy || !seed?.configured}
              type="button"
            >
              {busy ? <Spinner label="生成预览" /> : "运行预览"}
            </button>
          </div>
        }
      >
        {!seed?.configured && (
          <div className="alert alert-warn">
            <strong>无法预览：本地种子未配置。</strong>
            <code>python scripts/setup_local.py</code>
          </div>
        )}

        {!preview ? (
          <Empty
            title="尚无预览"
            text="点击“运行预览”后，会展示原文与脱敏值对照，同时给出映射、碰撞与日期偏移统计。"
          />
        ) : (
          <>
            <div className="stats-row">
              <Stat label="映射值" value={mapping?.totals?.values ?? 0} sub="跨表共享" />
              <Stat
                label="替换出现次数"
                value={replacedCount ?? 0}
                sub="含重复出现的字段"
              />
              <Stat
                label="碰撞处理"
                value={mapping?.totals?.collisions ?? 0}
                sub={`残留规避 ${mapping?.totals?.residual_avoided ?? 0}`}
                tone={(mapping?.totals?.collisions ?? 0) > 0 ? "warn" : "good"}
              />
              <Stat
                label="日期偏移"
                value={`${dateShift?.min_days ?? 0} ~ ${dateShift?.max_days ?? 0}`}
                sub={`${dateShift?.customers ?? 0} 位客户 / ${dateShift?.distinct_offsets ?? 0} 种偏移`}
              />
            </div>

            <div className="namespace-strip">
              {mapping?.namespaces?.map((namespace) => (
                <div key={namespace.namespace} className="namespace-chip">
                  <span className="mono">{namespace.namespace}</span>
                  <Badge tone="slate">{namespace.kind}</Badge>
                  <span>{namespace.values} 值</span>
                  <span className="muted">{namespace.collisions} 碰撞</span>
                </div>
              ))}
            </div>

            {preview.tables.map((table) => (
              <div key={table.name} className="preview-table-card">
                <div className="preview-table-head">
                  <div>
                    <h3>
                      <code>{table.name}</code>
                    </h3>
                    <p>
                      展示 {table.rows.length} / {table.row_count} 行 · PK{" "}
                      {table.primary_key.join(" + ")}
                    </p>
                  </div>
                  <Badge tone="slate">{table.columns.length} 列</Badge>
                </div>
                <div className="table-scroll">
                  <table className="preview-table">
                    <thead>
                      <tr>
                        <th className="row-number">#</th>
                        {table.columns.map((column) => (
                          <th key={column.name}>
                            <div className="th-name">
                              <code>{column.name}</code>
                              {column.masked && (
                                <Badge tone={STRATEGY_TONE[column.strategy]}>
                                  {column.strategy_label}
                                </Badge>
                              )}
                            </div>
                          </th>
                        ))}
                        <th className="offset-col">日期偏移</th>
                      </tr>
                    </thead>
                    <tbody>
                      {table.rows.map((row, index) => (
                        <tr key={index}>
                          <td className="row-number">{index + 1}</td>
                          {table.columns.map((column) => {
                            const cell = row.cells[column.name] || {};
                            return (
                              <td
                                key={column.name}
                                className={cell.changed ? "changed-cell" : ""}
                              >
                                <div className="masked-value">
                                  <RenderValue value={cell.masked} />
                                </div>
                                {cell.changed && (
                                  <div className="raw-value">
                                    <span className="raw-tag">原</span>
                                    <RenderValue value={cell.raw} />
                                  </div>
                                )}
                              </td>
                            );
                          })}
                          <td className="offset-col">
                            {row.meta?.date_offset_days != null ? (
                              <Badge tone={row.meta.date_offset_days >= 0 ? "amber" : "cyan"}>
                                {row.meta.date_offset_days >= 0 ? "+" : ""}
                                {row.meta.date_offset_days} 天
                              </Badge>
                            ) : (
                              <span className="muted">—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))}
          </>
        )}
      </Section>

      <div className="wizard-footer">
        <div className="footer-note">
          预览不会写入文件。正式生成时仍会执行主键、外键、空值、日期、残留和业务查询校验。
        </div>
        <button
          className="primary-button"
          onClick={onNext}
          disabled={!preview}
          type="button"
        >
          生成并发布 <span className="arrow">→</span>
        </button>
      </div>
    </div>
  );
}
