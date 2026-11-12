import React from "react";

export function StepNav({ steps, active, onSelect }) {
  return (
    <nav className="step-nav" aria-label="工作流程">
      {steps.map((step, index) => {
        const isActive = step.id === active;
        const isDone = step.done;
        return (
          <button
            key={step.id}
            className={`step-item ${isActive ? "active" : ""} ${isDone ? "done" : ""}`}
            onClick={() => onSelect(step.id)}
            type="button"
          >
            <span className="step-index">
              {isDone ? "✓" : String(index + 1).padStart(2, "0")}
            </span>
            <span className="step-copy">
              <strong>{step.label}</strong>
              <small>{step.hint}</small>
            </span>
          </button>
        );
      })}
    </nav>
  );
}

export function Badge({ children, tone = "slate", dot = false }) {
  return (
    <span className={`badge tone-${tone}`}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

export function Stat({ label, value, sub, tone = "default" }) {
  return (
    <div className={`stat-tile tone-${tone}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {sub && <span className="stat-sub">{sub}</span>}
    </div>
  );
}

export function NullValue() {
  return <span className="null-value">NULL</span>;
}

export function StatusPill({ passed, label }) {
  return (
    <span className={`status-pill ${passed ? "pass" : "fail"}`}>
      <span className="status-dot" />
      {label || (passed ? "通过" : "失败")}
    </span>
  );
}

export function Section({ title, subtitle, actions, children, className = "" }) {
  return (
    <section className={`card section ${className}`}>
      <div className="section-head">
        <div>
          <h3>{title}</h3>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {actions && <div className="section-actions">{actions}</div>}
      </div>
      {children}
    </section>
  );
}

export function Spinner({ label = "处理中" }) {
  return (
    <span className="spinner-wrap">
      <span className="spinner" />
      {label}
    </span>
  );
}

export function Empty({ title, text }) {
  return (
    <div className="empty-state">
      <div className="empty-mark">∅</div>
      <h4>{title}</h4>
      <p>{text}</p>
    </div>
  );
}

export function RenderValue({ value }) {
  if (value === null || value === undefined) return <NullValue />;
  if (value === "") return <span className="empty-string">""</span>;
  return <span>{String(value)}</span>;
}
