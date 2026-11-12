import React from "react";
import { Badge, Empty, Section, Spinner, Stat, StatusPill } from "./ui.jsx";

function PassTable({ rows, columns, empty = "无" }) {
  if (!rows?.length) return <Empty title={empty} text="没有可展示的检查项。" />;
  return (
    <div className="table-scroll compact">
      <table className="report-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
            <th>结果</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render ? column.render(row[column.key], row) : String(row[column.key] ?? "—")}
                </td>
              ))}
            <td>
              <StatusPill passed={row.passed} />
            </td>
          </tr>
        ))}
        </tbody>
      </table>
    </div>
  );
}

function DownloadRow({ downloads }) {
  if (!downloads?.length) return null;
  return (
    <div className="download-grid">
      {downloads.map((item) => (
        <a key={item.name} className="download-chip" href={item.url} download>
          <span className="download-icon">↓</span>
          <span>{item.name}</span>
        </a>
      ))}
    </div>
  );
}

function FailurePanel({ failure }) {
  if (!failure) return null;
  const checks = failure.detail?.checks;
  const errors = failure.detail?.errors || [failure.message];
  return (
    <div className="failure-card">
      <div className="failure-head">
        <Badge tone="red" dot>
          未发布
        </Badge>
        <h3>校验失败，导出目录没有产生任何文件</h3>
      </div>
      <ul className="issue-list">
        {errors.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
      {checks && (
        <div className="failure-checks">
          {(checks.blocking_failures || []).map((name) => (
            <Badge key={name} tone="red">
              {name}
            </Badge>
          ))}
        </div>
      )}
      <p className="failure-note">
        生成采用暂存目录 + 原子替换：只有全部关联、空值、日期、残留和业务查询校验通过，
        数据文件才会出现在导出目录。
      </p>
    </div>
  );
}

export default function ReportPanel({
  report,
  generate,
  busy,
  failure,
  jobs,
  loadJob,
  seed,
  goRules,
}) {
  const checks = report?.checks;
  const totals = report?.totals;

  return (
    <div className="panel-stack">
      <Section
        title="生成与发布"
        subtitle="规则、种子与数据均通过校验后，才会原子发布整套文件"
        actions={
          <button className="primary-button" onClick={generate} disabled={busy || !seed?.configured} type="button">
            {busy ? <Spinner label="脱敏生成中" /> : "生成新数据文件"}
          </button>
        }
      >
        {!seed?.configured ? (
          <div className="alert alert-warn">
            <strong>本地种子未配置。</strong>
            <span>导出必须由本地种子驱动。</span>
            <code>python scripts/setup_local.py</code>
          </div>
        ) : (
          <div className="generate-note">
            <div>
              <strong>同版本 + 同种子 = 同内容</strong>
              <span>种子只参与 HMAC 计算，不写入 CSV、manifest 或报告。</span>
            </div>
            <div>
              <strong>失败不出半套</strong>
              <span>校验失败时只保留失败日志，导出目录保持为空。</span>
            </div>
            <div>
              <strong>可核对业务查询</strong>
              <span>订单数分布、销售额、售后关联与金额明细逐项比对。</span>
            </div>
          </div>
        )}
        {failure && <FailurePanel failure={failure} />}
      </Section>

      {!report ? (
        <Section title="报告" subtitle="生成后在此查看替换数量、碰撞处理与全部校验">
          <Empty
            title="尚未生成"
            text="点击“生成新数据文件”后会展示完整报告和下载入口。也可从历史任务中载入旧报告。"
          />
        </Section>
      ) : (
        <>
          <section className="success-card">
            <div className="success-head">
              <div>
                <Badge tone="green" dot>
                  已原子发布
                </Badge>
                <h2>脱敏数据文件已生成</h2>
                <p>
                  任务 <code>{report.job_id}</code> · 规则版本{" "}
                  <code>{report.rule_version}</code> · 内容指纹{" "}
                  <code>{report.content_fingerprint}</code>
                </p>
              </div>
              <StatusPill passed={checks?.passed} label={checks?.passed ? "全部校验通过" : "存在失败项"} />
            </div>
            <DownloadRow downloads={report.downloads} />
          </section>

          <div className="stats-row">
            <Stat label="源数据行数" value={totals?.source_rows ?? 0} sub={`${totals?.tables ?? 0} 张表`} />
            <Stat label="替换值数量" value={totals?.replaced_values ?? 0} sub="非空字段出现次数" />
            <Stat label="映射值" value={totals?.distinct_mapping_values ?? 0} sub={`碰撞 ${totals?.collisions ?? 0}`} tone="good" />
            <Stat
              label="原敏感值残留"
              value={totals?.residual_hits ?? 0}
              sub="精确 + 子串扫描"
              tone={(totals?.residual_hits ?? 0) === 0 ? "good" : "bad"}
            />
            <Stat
              label="业务查询"
              value={`${checks?.business_queries?.filter((item) => item.passed).length ?? 0}/${checks?.business_queries?.length ?? 0}`}
              sub="源/脱敏结果一致"
              tone="good"
            />
          </div>

          <Section
            title="替换数量"
            subtitle="按表、列统计被替换的非空值数量与保留的空值"
          >
            <div className="table-scroll compact">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>表</th>
                    <th>列</th>
                    <th>策略</th>
                    <th className="num">替换数量</th>
                    <th className="num">保留空值</th>
                    <th className="num">输出去重值</th>
                  </tr>
                </thead>
                <tbody>
                  {report.replacements.map((item) => (
                    <tr key={`${item.table}.${item.column}`}>
                      <td><code>{item.table}</code></td>
                      <td><code>{item.column}</code></td>
                      <td>{item.strategy_label}</td>
                      <td className="num">{item.replaced}</td>
                      <td className="num">{item.preserved_nulls}</td>
                      <td className="num">{item.distinct_output_values}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section
            title="碰撞处理"
            subtitle="按命名空间与租户统计；碰撞用确定性探测解决，原值集合预先禁用"
          >
            <div className="table-scroll compact">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>命名空间</th>
                    <th>租户</th>
                    <th>类型</th>
                    <th className="num">分配值</th>
                    <th className="num">碰撞</th>
                    <th className="num">残留规避</th>
                    <th className="num">最大尝试</th>
                  </tr>
                </thead>
                <tbody>
                  {report.mapping.namespaces.flatMap((namespace) =>
                    (namespace.tenants && Object.keys(namespace.tenants).length
                      ? Object.entries(namespace.tenants)
                      : [[null, { values: namespace.values, collisions: namespace.collisions, residual_avoided: namespace.residual_avoided }]]
                    ).map(([tenant, stats]) => (
                      <tr key={`${namespace.namespace}-${tenant || "all"}`}>
                        <td><code>{namespace.namespace}</code></td>
                        <td>{tenant || "—"}</td>
                        <td>{namespace.kind}</td>
                        <td className="num">{stats.values}</td>
                        <td className="num">{stats.collisions}</td>
                        <td className="num">{stats.residual_avoided}</td>
                        <td className="num">{namespace.max_attempts}</td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="关联与完整性校验" subtitle="主键、外键、行数与空值保持">
            <div className="check-block">
              <h4>主键唯一</h4>
              <PassTable
                rows={checks?.primary_keys}
                columns={[
                  { key: "table", label: "表", render: (value) => <code>{value}</code> },
                  { key: "columns", label: "主键", render: (value) => value.join(" + ") },
                  { key: "rows", label: "行数" },
                  { key: "duplicate_keys", label: "重复键" },
                  { key: "null_keys", label: "空键" },
                ]}
              />
            </div>
            <div className="check-block">
              <h4>外键完整</h4>
              <PassTable
                rows={checks?.foreign_keys}
                columns={[
                  { key: "table", label: "子表", render: (value) => <code>{value}</code> },
                  { key: "columns", label: "外键列", render: (value) => value.join(" + ") },
                  { key: "references", label: "引用" },
                  { key: "checked", label: "检查行" },
                  { key: "violations", label: "违规" },
                ]}
              />
            </div>
            <div className="check-block">
              <h4>行数与空值</h4>
              <PassTable
                rows={checks?.row_counts}
                columns={[
                  { key: "table", label: "表", render: (value) => <code>{value}</code> },
                  { key: "source_rows", label: "源行数" },
                  { key: "output_rows", label: "输出行数" },
                ]}
              />
              <div className="spacer" />
              <PassTable
                rows={checks?.null_preservation}
                columns={[
                  { key: "table", label: "表.列", render: (value, row) => `${row.table}.${row.column}` },
                  { key: "source_nulls", label: "源空值" },
                  { key: "output_nulls", label: "输出空值" },
                  { key: "non_null_to_null", label: "非空变空" },
                ]}
              />
            </div>
          </Section>

          <Section title="日期整体平移" subtitle="同一客户的所有业务时间共用同一偏移，先后顺序与间隔不变">
            <div className="date-summary">
              <Badge tone="amber">客户 {checks?.date_shift?.customers}</Badge>
              <Badge tone="amber">
                偏移 {checks?.date_shift?.min_days} ~ {checks?.date_shift?.max_days} 天
              </Badge>
              <Badge tone="slate">{checks?.date_shift?.distinct_offsets} 种偏移</Badge>
              <Badge tone={checks?.date_shift?.range_ok ? "green" : "red"}>
                范围检查 {checks?.date_shift?.range_ok ? "通过" : "失败"}
              </Badge>
            </div>
            <PassTable
              rows={checks?.date_shift_columns}
              columns={[
                { key: "table", label: "表.列", render: (value, row) => `${row.table}.${row.column}` },
                { key: "identity", label: "身份列" },
                { key: "non_null_to_null", label: "非空变空" },
                { key: "null_to_non_null", label: "空变非空" },
                { key: "offset_violations", label: "偏移不一致" },
              ]}
            />
            <div className="check-block">
              <h4>先后顺序与间隔</h4>
              <PassTable
                rows={checks?.date_invariants}
                columns={[
                  { key: "table", label: "表", render: (value) => <code>{value}</code> },
                  { key: "description", label: "约束" },
                  { key: "checked", label: "检查行" },
                  { key: "violations", label: "违规" },
                ]}
              />
              <div className="spacer" />
              <PassTable
                rows={checks?.intervals}
                columns={[
                  { key: "table", label: "表", render: (value) => <code>{value}</code> },
                  { key: "interval", label: "间隔" },
                  { key: "checked", label: "检查行" },
                  { key: "mismatched", label: "间隔变化" },
                ]}
              />
              <div className="spacer" />
              <PassTable
                rows={checks?.sequences}
                columns={[
                  { key: "table", label: "表", render: (value) => <code>{value}</code> },
                  { key: "event_key", label: "事件键" },
                  { key: "order_by", label: "排序", render: (value) => value.join(", ") },
                  { key: "checked", label: "检查行" },
                  { key: "mismatched", label: "次序变化" },
                ]}
              />
            </div>
          </Section>

          <Section
            title="原敏感值残留检查"
            subtitle="生成值不会等于任何原始敏感值；手机号与邮箱额外做子串扫描"
          >
            <PassTable
              rows={checks?.residual}
              columns={[
                { key: "namespace", label: "命名空间", render: (value) => <code>{value}</code> },
                { key: "kind", label: "类型" },
                { key: "original_values", label: "原值数" },
                { key: "masked_columns", label: "覆盖列" },
                { key: "exact_hits", label: "精确命中" },
                { key: "substring_hits", label: "子串命中" },
                { key: "mode", label: "模式" },
              ]}
            />
          </Section>

          <Section
            title="业务查询等价性"
            subtitle="在源表与脱敏表上分别执行相同查询，比较结果签名"
          >
            <div className="table-scroll compact">
              <table className="report-table">
                <thead>
                  <tr>
                    <th>查询</th>
                    <th>说明</th>
                    <th className="num">源分组</th>
                    <th className="num">脱敏分组</th>
                    <th>源签名</th>
                    <th>脱敏签名</th>
                    <th>结果</th>
                  </tr>
                </thead>
                <tbody>
                  {checks?.business_queries?.map((item) => (
                    <tr key={item.id}>
                      <td><code>{item.id}</code></td>
                      <td>{item.description}</td>
                      <td className="num">{item.source_groups}</td>
                      <td className="num">{item.masked_groups}</td>
                      <td><code className="sig">{item.source_signature}</code></td>
                      <td><code className="sig">{item.masked_signature}</code></td>
                      <td><StatusPill passed={item.passed} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="输出文件" subtitle="导出目录只包含数据、报告和清单，不含种子、原始敏感值或内部映射表">
            <div className="file-list">
              {report.files?.map((file) => (
                <div key={file.name} className="file-row">
                  <div>
                    <strong>{file.name}</strong>
                    <span>{file.rows != null ? `${file.rows} 行` : "报告文件"}</span>
                  </div>
                  <code>{file.sha256}</code>
                </div>
              ))}
            </div>
          </Section>
        </>
      )}

      <Section title="历史任务" subtitle="已发布任务可从磁盘重新载入报告">
        {!jobs?.length ? (
          <Empty title="暂无历史任务" text="成功生成的任务会出现在这里。" />
        ) : (
          <div className="job-list">
            {jobs.map((job) => (
              <button
                key={job.job_id}
                className="job-row"
                type="button"
                onClick={() => loadJob(job.job_id)}
              >
                <div className="job-main">
                  <code>{job.job_id}</code>
                  <span>{job.created_at}</span>
                </div>
                <div className="job-meta">
                  <Badge tone="indigo">v{job.rule_version}</Badge>
                  <code>{job.content_fingerprint}</code>
                  <span className="job-load">载入 →</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </Section>

      <div className="wizard-footer">
        <div className="footer-note">规则调整后重新生成会得到另一套可复现的内容。</div>
        <button className="ghost-button" onClick={goRules} type="button">
          ← 返回规则
        </button>
      </div>
    </div>
  );
}
