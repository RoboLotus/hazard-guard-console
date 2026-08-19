import { useEffect } from "react";

export default function SettingsConfirmDialog({ confirmation, onCancel, onConfirm }) {
  useEffect(() => {
    if (!confirmation) return undefined;
    const closeOnEscape = (event) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [confirmation, onCancel]);

  if (!confirmation) return null;
  return (
    <div className="settings-dialog-backdrop" role="presentation">
      <section
        className="settings-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-confirm-title"
      >
        <h2 id="settings-confirm-title">{confirmation.title}</h2>
        <p>{confirmation.description}</p>
        {confirmation.impact && <small>{confirmation.impact}</small>}
        <div className="settings-dialog-actions">
          <button type="button" className="button ghost" onClick={onCancel} autoFocus>취소</button>
          <button
            type="button"
            className={`button ${confirmation.danger ? "danger" : "primary"}`}
            onClick={onConfirm}
          >
            {confirmation.confirmLabel || "확인"}
          </button>
        </div>
      </section>
    </div>
  );
}
