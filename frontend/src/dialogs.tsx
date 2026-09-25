import { useEffect, useMemo, useState } from "react";
import { Dialog, Icon, formatDate, formatSize, plural } from "./components";
import { HELP, STATUS_HELP, STATUS_LABEL } from "./help";
import type { AppConfig, Card, Replacement } from "./types";

/* ------------------------------------------------------------------- move */
export function MoveDialog({ ready, onConfirm, onClose, busy }: {
  ready: Card[];
  onConfirm: () => void;
  onClose: () => void;
  busy: boolean;
}) {
  const folders = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of ready) m.set(c.folder, (m.get(c.folder) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [ready]);
  return (
    <Dialog
      title="Move ready photos"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="secondary" onClick={onClose}>Cancel</button>
          <button type="button" className="primary" disabled={!ready.length || busy} onClick={onConfirm} data-autofocus>
            <Icon name="move" /> Create folders &amp; move {plural(ready.length, "photo")}
          </button>
        </>
      }
    >
      {ready.length ? (
        <>
          <p>
            {plural(ready.length, "photo")} will be moved into {plural(folders.length, "folder")}. Cards that need
            review, duplicates and cards still processing stay in the inbox.
          </p>
          <ul className="folder-list">
            {folders.map(([f, n]) => (
              <li key={f}>
                <span className="folder-name">{f}</span>
                <span className="count">{n}</span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>No cards are marked Ready. Approve cards or set their folder first.</p>
      )}
    </Dialog>
  );
}

/* ----------------------------------------------------------------- delete */
export function DeleteDialog({ cards, mode, onConfirm, onClose }: {
  cards: Card[];
  mode: "permanent" | "trash";
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [step, setStep] = useState(1);
  const [typed, setTyped] = useState("");
  const size = cards.reduce((s, c) => s + c.size, 0);
  return (
    <Dialog
      tone="danger"
      title={step === 1 ? `Delete ${plural(cards.length, "photo")}?` : "Final confirmation"}
      onClose={onClose}
      footer={
        step === 1 ? (
          <>
            <button type="button" className="secondary" onClick={onClose} data-autofocus>Cancel</button>
            <button type="button" className="danger" onClick={() => setStep(2)}>Yes, continue…</button>
          </>
        ) : (
          <>
            <button type="button" className="secondary" onClick={onClose}>Cancel</button>
            <button type="button" className="danger" disabled={typed !== "DELETE"} onClick={onConfirm}>
              <Icon name="trash" /> Delete {plural(cards.length, "photo")}
            </button>
          </>
        )
      }
    >
      {step === 1 ? (
        <>
          <p>
            You are about to delete <strong>{plural(cards.length, "photo")}</strong> ({formatSize(size)}) from the
            inbox.{" "}
            {mode === "trash"
              ? "They will be moved to the .photosorter-trash folder inside the inbox."
              : "This cannot be undone: files are deleted permanently."}
          </p>
          <div className="thumb-strip">
            {cards.slice(0, 12).map((c) =>
              c.thumb ? <img key={c.id} src={c.thumb} alt={c.name} /> : <span key={c.id} className="mini-ph" />,
            )}
            {cards.length > 12 && <span className="more">+{cards.length - 12}</span>}
          </div>
        </>
      ) : (
        <label className="field">
          <span>
            Type <strong>DELETE</strong> to confirm
          </span>
          <input
            autoComplete="off"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && typed === "DELETE" && onConfirm()}
            data-autofocus
            aria-label="Type DELETE to confirm"
          />
        </label>
      )}
    </Dialog>
  );
}

/* ---------------------------------------------------------------- replace */
export function ReplaceDialog({ folders, replacements, suggestions, initialFrom, onAdd, onRemove, onClose }: {
  folders: [string, number][];
  replacements: Replacement[];
  suggestions: string[];
  initialFrom?: string;
  onAdd: (from: string, to: string) => Promise<boolean>;
  onRemove: (id: number) => void;
  onClose: () => void;
}) {
  const [from, setFrom] = useState(initialFrom ?? folders[0]?.[0] ?? "");
  const [to, setTo] = useState(initialFrom ?? "");
  const count = folders.find(([f]) => f === from)?.[1] ?? 0;
  const submit = async () => {
    if (from && to.trim() && (await onAdd(from, to.trim()))) setTo("");
  };
  return (
    <Dialog
      wide
      title="Replace a proposed folder"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="secondary" onClick={onClose}>Close</button>
          <button type="button" className="primary" disabled={!from || !to.trim() || to.trim() === from}
            onClick={submit}>
            <Icon name="replace" /> Replace on {plural(count, "card")}
          </button>
        </>
      }
    >
      <p className="muted">{HELP.replace}</p>
      <div className="form-grid">
        <label className="field">
          <span>Current folder</span>
          <select value={from} onChange={(e) => { setFrom(e.target.value); setTo(e.target.value); }}>
            {folders.map(([f, n]) => (
              <option key={f} value={f}>
                {f} ({n})
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>New folder name</span>
          <input list="folder-suggestions" value={to} onChange={(e) => setTo(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && void submit()} placeholder="{date} - Kraków - Park Jordana"
            data-autofocus />
        </label>
      </div>
      <datalist id="folder-suggestions">
        {suggestions.map((s) => <option key={s} value={s} />)}
      </datalist>
      <h3>Active rules</h3>
      {replacements.length ? (
        <ul className="rules">
          {replacements.map((r) => (
            <li key={r.id}>
              <span className="folder-name">{r.from_folder}</span>
              <Icon name="right" size={16} />
              <span className="folder-name strong">{r.to_folder}</span>
              <button type="button" className="ghost icon-only" aria-label="Remove rule" title="Remove rule"
                onClick={() => onRemove(r.id)}>
                <Icon name="close" size={16} />
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="muted">No rules yet.</p>
      )}
    </Dialog>
  );
}

/* ------------------------------------------------------------ edit folder */
export function EditDialog({ card, suggestions, onSave, onReset, onApprove, onClose }: {
  card: Card;
  suggestions: string[];
  onSave: (folder: string) => void;
  onReset: () => void;
  onApprove: () => void;
  onClose: () => void;
}) {
  const [value, setValue] = useState(card.manual_folder ?? card.folder);
  return (
    <Dialog
      title="Destination folder"
      onClose={onClose}
      footer={
        <>
          {(card.manual || card.approved) && (
            <button type="button" className="secondary" onClick={onReset}>
              <Icon name="undo" /> Use automatic
            </button>
          )}
          {card.status !== "ready" && !!card.folder && (
            <button type="button" className="secondary" onClick={onApprove}>
              <Icon name="check" /> Approve as is
            </button>
          )}
          <button type="button" className="primary" disabled={!value.trim()} onClick={() => onSave(value.trim())}>
            Save
          </button>
        </>
      }
    >
      <p className="muted">
        <strong>{card.name}</strong> · {formatDate(card.taken_at)}
        <br />
        Automatic proposal: {card.auto_folder || "—"}
      </p>
      <label className="field">
        <span>Folder name ({"{date}"} = photo date)</span>
        <input list="edit-suggestions" value={value} onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && value.trim() && onSave(value.trim())} data-autofocus />
      </label>
      <datalist id="edit-suggestions">
        {suggestions.map((s) => <option key={s} value={s} />)}
      </datalist>
    </Dialog>
  );
}

/* ---------------------------------------------------------------- preview */
export function PreviewDialog({ card, onClose, onPrev, onNext, onEdit }: {
  card: Card;
  onClose: () => void;
  onPrev?: () => void;
  onNext?: () => void;
  onEdit: () => void;
}) {
  const [loaded, setLoaded] = useState(false);
  useEffect(() => setLoaded(false), [card.id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft" && onPrev) onPrev();
      if (e.key === "ArrowRight" && onNext) onNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onPrev, onNext]);
  const osm = card.lat != null && card.lon != null
    ? `https://www.openstreetmap.org/?mlat=${card.lat}&mlon=${card.lon}#map=18/${card.lat}/${card.lon}`
    : null;
  return (
    <Dialog wide title={card.name} onClose={onClose}>
      <div className="preview">
        <div className="preview-image">
          {!loaded && card.thumb && <img className="blur" src={card.thumb} alt="" />}
          <img src={`/api/preview/${card.id}`} alt={card.name} onLoad={() => setLoaded(true)}
            style={{ opacity: loaded ? 1 : 0 }} />
          {onPrev && (
            <button type="button" className="nav prev" aria-label="Previous photo" onClick={onPrev}>
              <Icon name="left" />
            </button>
          )}
          {onNext && (
            <button type="button" className="nav next" aria-label="Next photo" onClick={onNext}>
              <Icon name="right" />
            </button>
          )}
        </div>
        <dl className="details">
          <dt>Status</dt>
          <dd><span className={`badge inline ${card.status}`}>{STATUS_LABEL[card.status]}</span> {card.reason}</dd>
          <dt>Folder</dt>
          <dd>
            {card.folder || "—"}{" "}
            <button type="button" className="link" onClick={onEdit}>change</button>
          </dd>
          <dt>Taken</dt>
          <dd>{formatDate(card.taken_at)} {card.taken_source === "mtime" && <em>(file date, no EXIF)</em>}</dd>
          <dt>Location</dt>
          <dd>
            {card.location?.display || [card.location?.place, card.location?.city].filter(Boolean).join(", ") || "—"}
            {osm && (
              <>
                {" "}
                <a href={osm} target="_blank" rel="noreferrer noopener">map</a>
              </>
            )}
          </dd>
          {card.lat != null && (
            <>
              <dt>GPS</dt>
              <dd>{card.lat.toFixed(6)}, {card.lon?.toFixed(6)}</dd>
            </>
          )}
          <dt>Camera</dt>
          <dd>{card.camera || "—"}</dd>
          <dt>File</dt>
          <dd className="break">{card.path} · {formatSize(card.size)}{card.width ? ` · ${card.width}×${card.height}` : ""}</dd>
        </dl>
      </div>
    </Dialog>
  );
}

/* ------------------------------------------------------------------- help */
export function HelpDialog({ config, version, onClose }: { config: AppConfig | null; version: string; onClose: () => void }) {
  const rows: [string, string][] = [
    ["Scan inbox", HELP.scan],
    ["Move ready photos", HELP.move],
    ["Replace folder", HELP.replace],
    ["Selecting cards", HELP.selection],
    ["Clear selection", HELP.clear],
    ["Predefined folder", HELP.predefined],
    ["Custom folder", HELP.custom],
    ["Approve", HELP.approve],
    ["Reset to automatic", HELP.reset],
    ["Delete", HELP.delete],
  ];
  return (
    <Dialog wide title="How PhotoSorter works" onClose={onClose}>
      <h3>Buttons</h3>
      <dl className="help-list">
        {rows.map(([k, v]) => (
          <div key={k}>
            <dt>{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <h3>Statuses</h3>
      <dl className="help-list">
        {Object.entries(STATUS_HELP).map(([k, v]) => (
          <div key={k}>
            <dt><span className={`badge inline ${k}`}>{STATUS_LABEL[k]}</span></dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      <h3>Keyboard</h3>
      <p className="muted">
        Esc – clear selection / close dialog · Ctrl+A – select all shown · Space – tick focused card · Enter – preview
        · ←/→ – previous/next in preview
      </p>
      {config && (
        <>
          <h3>Configuration</h3>
          <p className="muted break">
            Version {version} · config {config.loaded ? config.file : "built-in defaults"}
            {config.error ? ` (error: ${config.error})` : ""} · inbox {config.inbox} · output {config.sorted} ·
            custom places: {config.places.length ? config.places.join(", ") : "none"} · delete mode {config.delete_mode}
          </p>
        </>
      )}
    </Dialog>
  );
}
