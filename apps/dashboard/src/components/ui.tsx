import type { ReactNode } from "react";
import { fileUrl, useDownloadToken } from "../api";
import { stateLabel } from "../lib";

export function StatusBadge({ state }: { state: string }) {
  return <span className={`badge st-${state}`}>{stateLabel(state)}</span>;
}

export function Progress({ value, tone }: { value: number; tone?: string }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <div className="progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
      <div className={`progress-bar ${tone ?? ""}`} style={{ width: `${pct}%` }} />
      <span className="progress-text">{pct}%</span>
    </div>
  );
}

export function Meter({ label, value, max, unit, na }: { label: string; value: number | null; max?: number | null; unit?: string; na?: string }) {
  const hasValue = value !== null && value !== undefined;
  const pct = hasValue ? (max ? (value / max) * 100 : value) : 0;
  return (
    <div className="meter">
      <div className="meter-head">
        <span>{label}</span>
        <span className="mono">{hasValue ? (max ? `${Math.round(value)} / ${Math.round(max)} ${unit ?? ""}` : `${value.toFixed(0)}${unit ?? "%"}`) : (na ?? "sem dados")}</span>
      </div>
      <div className="meter-track">
        <div className={`meter-fill ${pct > 85 ? "hot" : ""}`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}

export function Stat({ label, value, tone, hint }: { label: string; value: ReactNode; tone?: string; hint?: string }) {
  return (
    <div className={`stat ${tone ?? ""}`}>
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

export function Panel({ title, actions, children, className }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel ${className ?? ""}`}>
      {(title || actions) && (
        <header className="panel-head">
          <h3>{title}</h3>
          <div className="panel-actions">{actions}</div>
        </header>
      )}
      <div className="panel-body">{children}</div>
    </section>
  );
}

export function Thumb({ assetId, version, alt, hasThumb = true }: { assetId: string; version?: number; alt: string; hasThumb?: boolean }) {
  const token = useDownloadToken();
  if (!hasThumb) return <div className="thumb empty">sem miniatura</div>;
  if (!token) return <div className="thumb skeleton" />;
  return <img className="thumb" loading="lazy" alt={alt} src={fileUrl(assetId, "thumbnail.png", token, version)} />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}

export function ErrorNote({ error }: { error: unknown }) {
  if (!error) return null;
  return <div className="error-note">{(error as Error).message ?? String(error)}</div>;
}
