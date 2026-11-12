import React, { useEffect, useState } from "react";
import { api } from "./api.js";
import DataPanel from "./components/DataPanel.jsx";
import PreviewPanel from "./components/PreviewPanel.jsx";
import ReportPanel from "./components/ReportPanel.jsx";
import RulesEditor from "./components/RulesEditor.jsx";
import { Badge, Spinner, StepNav } from "./components/ui.jsx";

const STEP_IDS = ["data", "rules", "preview", "report"];

export default function App() {
  const [bootstrap, setBootstrap] = useState(null);
  const [active, setActive] = useState("data");
  const [rules, setRules] = useState(null);
  const [validation, setValidation] = useState(null);
  const [preview, setPreview] = useState(null);
  const [previewLimit, setPreviewLimit] = useState(5);
  const [report, setReport] = useState(null);
  const [failure, setFailure] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(null);
  const [toast, setToast] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    api
      .bootstrap()
      .then((data) => {
        if (!mounted) return;
        setBootstrap(data);
        setRules(structuredClone(data.default_rules));
        setJobs(data.jobs || []);
      })
      .catch((error) => {
        if (mounted) setToast(error.message);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const dataset = bootstrap?.dataset;
  const seed = bootstrap?.seed;
  const steps = [
    { id: "data", label: "数据源", hint: "三张合成表", done: Boolean(dataset) },
    { id: "rules", label: "脱敏规则", hint: "字段与策略", done: Boolean(validation?.valid) },
    { id: "preview", label: "样例预览", hint: "原文 / 脱敏对照", done: Boolean(preview) },
    { id: "report", label: "生成报告", hint: "校验与下载", done: Boolean(report) },
  ];

  function handleRulesUpdate(next) {
    setRules(next);
    setValidation(null);
    setPreview(null);
    setFailure(null);
  }

  function handleSelect(step) {
    setActive(step);
  }

  async function validateRules() {
    if (!rules) return;
    setBusy("validate");
    setToast(null);
    try {
      const result = await api.validate(rules);
      setValidation(result);
      if (!result.valid) setToast("规则校验未通过，请查看下方问题列表。");
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(null);
    }
  }

  async function runPreview() {
    if (!rules) return;
    setBusy("preview");
    setToast(null);
    try {
      const result = await api.preview(rules, previewLimit);
      setPreview(result);
      setValidation({
        valid: true,
        errors: [],
        warnings: [],
        coverage: {
          tables: result.tables.length,
          columns: result.tables.reduce((sum, table) => sum + table.columns.length, 0),
          masked_columns: result.replacements.length,
        },
        rules_hash: result.rules_hash,
      });
    } catch (error) {
      if (error.detail?.kind === "rules") {
        setValidation(error.detail);
        setActive("rules");
      } else {
        setToast(error.message);
      }
    } finally {
      setBusy(null);
    }
  }

  async function generateReport() {
    if (!rules) return;
    setBusy("generate");
    setToast(null);
    setFailure(null);
    try {
      const result = await api.generate(rules);
      setReport(result);
      setFailure(null);
      setActive("report");
      setPreview(result.preview || preview);
      const jobData = await api.jobs();
      setJobs(Array.isArray(jobData) ? jobData : jobData.jobs || []);
    } catch (error) {
      if (error.detail?.kind === "checks") {
        setFailure({ message: error.message, detail: error.detail });
        setActive("report");
      } else if (error.detail?.kind === "rules") {
        setValidation(error.detail);
        setActive("rules");
      } else {
        setToast(error.message);
      }
    } finally {
      setBusy(null);
    }
  }

  async function loadJob(jobId) {
    setBusy("job");
    setToast(null);
    try {
      const result = await api.job(jobId);
      setReport(result);
      setFailure(null);
      setActive("report");
    } catch (error) {
      setToast(error.message);
    } finally {
      setBusy(null);
    }
  }

  function resetRules() {
    if (!bootstrap) return;
    handleRulesUpdate(structuredClone(bootstrap.default_rules));
  }

  if (loading) {
    return (
      <div className="boot-screen">
        <div className="brand-mark large">M</div>
        <Spinner label="正在加载 MaskFlow 工作台" />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">M</div>
          <div>
            <div className="brand-name">MaskFlow</div>
            <div className="brand-sub">确定性跨表数据脱敏工作台</div>
          </div>
        </div>
        <div className="header-status">
          {dataset?.facts?.tenants?.map((tenant) => (
            <Badge key={tenant} tone="slate">
              {tenant}
            </Badge>
          ))}
          <Badge tone={seed?.configured ? "green" : "red"} dot>
            {seed?.configured ? "种子：本地配置" : "种子缺失"}
          </Badge>
          {validation?.rules_hash && (
            <Badge tone="indigo">rules #{validation.rules_hash}</Badge>
          )}
        </div>
      </header>

      <StepNav steps={steps} active={active} onSelect={handleSelect} />

      {toast && (
        <div className="toast" role="alert">
          <span>{toast}</span>
          <button type="button" onClick={() => setToast(null)}>
            ×
          </button>
        </div>
      )}

      <main className="app-main">
        {active === "data" && (
          <DataPanel dataset={dataset} seed={seed} onNext={() => setActive("rules")} />
        )}
        {active === "rules" && rules && (
          <RulesEditor
            rules={rules}
            dataset={dataset}
            validation={validation}
            onUpdate={handleRulesUpdate}
            onValidate={validateRules}
            onReset={resetRules}
            onNext={() => setActive("preview")}
            busy={busy === "validate" || busy === "preview"}
            seed={seed}
          />
        )}
        {active === "preview" && rules && (
          <PreviewPanel
            preview={preview}
            runPreview={runPreview}
            limit={previewLimit}
            setLimit={setPreviewLimit}
            busy={busy === "preview"}
            onNext={() => setActive("report")}
            seed={seed}
          />
        )}
        {active === "report" && rules && (
          <ReportPanel
            report={report}
            generate={generateReport}
            busy={busy === "generate" || busy === "job"}
            failure={failure}
            jobs={jobs}
            loadJob={loadJob}
            seed={seed}
            goRules={() => setActive("rules")}
          />
        )}
      </main>

      <footer className="app-footer">
        <span>Python + DuckDB 脱敏引擎 · FastAPI · React</span>
        <span>导出采用暂存目录 + 原子替换；种子不进入任何导出文件。</span>
      </footer>
    </div>
  );
}
