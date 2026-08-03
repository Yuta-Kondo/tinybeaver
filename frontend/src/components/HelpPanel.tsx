import { useEffect, useState } from "react";
import Icon from "./Icon";
import {
  PROVIDER_PRIVACY,
  SHORTCUTS,
  modelsForProvider,
  trainBadge,
} from "../lib/helpContent";

type Tab = "shortcuts" | "models";

interface Props {
  open: boolean;
  onClose: () => void;
  initialTab?: Tab;
}

export default function HelpPanel({ open, onClose, initialTab = "shortcuts" }: Props) {
  const [tab, setTab] = useState<Tab>(initialTab);

  useEffect(() => {
    if (open) setTab(initialTab);
  }, [open, initialTab]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div className="help-backdrop" onClick={onClose} role="presentation">
      <div
        className="help-panel"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Help"
      >
        <div className="help-header">
          <div className="help-tabs" role="tablist">
            <button
              type="button"
              role="tab"
              aria-selected={tab === "shortcuts"}
              className={`help-tab${tab === "shortcuts" ? " active" : ""}`}
              onClick={() => setTab("shortcuts")}
            >
              Shortcuts
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === "models"}
              className={`help-tab${tab === "models" ? " active" : ""}`}
              onClick={() => setTab("models")}
            >
              Models &amp; data
            </button>
          </div>
          <button type="button" className="help-close" onClick={onClose} title="Close" aria-label="Close">
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="help-body">
          {tab === "shortcuts" ? (
            <section className="help-section">
              <p className="help-lead">Keyboard shortcuts for tinybeaver.</p>
              <ul className="help-shortcut-list">
                {SHORTCUTS.map((s) => (
                  <li key={s.keys + s.label} className="help-shortcut-row">
                    <kbd className="kbd">{s.keys}</kbd>
                    <span>{s.label}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <section className="help-section">
              <p className="help-lead">
                Where each provider sends prompts, and whether API data is used for training.
                Summaries only — policies change.
              </p>
              <div className="help-provider-list">
                {PROVIDER_PRIVACY.map((p) => {
                  const badge = trainBadge(p.trainKind);
                  const models = modelsForProvider(p.id);
                  return (
                    <article key={p.id} className="help-provider-card">
                      <div className="help-provider-head">
                        <h3 className="help-provider-name">{p.name}</h3>
                        <span className={`help-train-badge help-train-badge--${badge.tone}`}>
                          {badge.label}
                        </span>
                      </div>
                      <p className="help-provider-meta">HQ: {p.hq}</p>
                      <dl className="help-provider-dl">
                        <div>
                          <dt>Data location</dt>
                          <dd>{p.dataLocation}</dd>
                        </div>
                        <div>
                          <dt>Training</dt>
                          <dd>{p.training}</dd>
                        </div>
                      </dl>
                      {models.length > 0 && (
                        <p className="help-provider-models">
                          In app:{" "}
                          {models.map((m) => `${m.name} ${m.version}`).join(" · ")}
                        </p>
                      )}
                      <p className="help-provider-note">{p.note}</p>
                    </article>
                  );
                })}
              </div>
              <p className="help-footnote">
                Self-MoA uses GLM for all proposers + synthesis. Private mode skips DB/memory writes
                but still sends the current turn to the selected model provider.
              </p>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
