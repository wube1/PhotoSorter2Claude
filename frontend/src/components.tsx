import { memo, useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { STATUS_LABEL } from "./help";
import type { Card } from "./types";

/* ------------------------------------------------------------------ utils */
export function formatDate(iso: string | null): string {
  if (!iso) return "No date";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getDate())}.${pad(d.getMonth() + 1)}.${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(0)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n.toLocaleString()} ${n === 1 ? one : many}`;
}

/* ------------------------------------------------------------------ icons */
const paths: Record<string, string> = {
  scan: "M3 7V5a2 2 0 0 1 2-2h2M17 3h2a2 2 0 0 1 2 2v2M21 17v2a2 2 0 0 1-2 2h-2M7 21H5a2 2 0 0 1-2-2v-2M7 12h10",
  move: "M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM12 10v6M9 13l3 3 3-3",
  replace: "M4 7h11M11 3l4 4-4 4M20 17H9M13 13l-4 4 4 4",
  close: "M6 6l12 12M18 6L6 18",
  check: "M5 12l5 5 9-10",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13M9 7V4h6v3",
  edit: "M4 20h4L19 9l-4-4L4 16zM13 7l4 4",
  expand: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
  pin: "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  undo: "M9 14L4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3",
  sun: "M12 4V2M12 22v-2M4 12H2M22 12h-2M5.6 5.6L4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4M12 17a5 5 0 1 0 0-10 5 5 0 0 0 0 10z",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  auto: "M12 3a9 9 0 1 0 0 18V3z M12 3a9 9 0 0 1 0 18",
  help: "M9.1 9a3 3 0 0 1 5.8 1c0 2-3 3-3 3M12 17h.01M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20z",
  search: "M11 19a8 8 0 1 0 0-16 8 8 0 0 0 0 16zM21 21l-4.3-4.3",
  left: "M15 18l-6-6 6-6",
  right: "M9 18l6-6-6-6",
  doc: "M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9zM14 3v6h6M8 13h8M8 17h5",
  selectAll: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
};

export function Icon({ name, size = 18 }: { name: keyof typeof paths | string; size?: number }) {
  return (
    <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={paths[name] ?? ""} />
    </svg>
  );
}

/* ------------------------------------------------------------------- info */
/** Small "i" button; shows its text on hover, keyboard focus or tap. */
export function Info({ text, label = "More information" }: { text: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const btn = useRef<HTMLButtonElement>(null);
  const tip = useRef<HTMLDivElement>(null);
  const id = useId();
  const [pos, setPos] = useState<{ left: number; top: number; above: boolean }>({ left: 0, top: 0, above: true });

  useLayoutEffect(() => {
    if (!open || !btn.current || !tip.current) return;
    const r = btn.current.getBoundingClientRect();
    const t = tip.current.getBoundingClientRect();
    const margin = 8;
    let left = r.left + r.width / 2 - t.width / 2;
    left = Math.max(margin, Math.min(left, window.innerWidth - t.width - margin));
    const above = r.top - t.height - 10 > 0;
    const top = above ? r.top - t.height - 8 : r.bottom + 8;
    setPos({ left, top, above });
  }, [open]);

  useEffect(() => {
    if (!pinned) return;
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== "Escape") return;
      if (e.target instanceof Node && btn.current?.contains(e.target)) return;
      setPinned(false);
      setOpen(false);
    };
    window.addEventListener("pointerdown", close);
    window.addEventListener("keydown", close);
    window.addEventListener("scroll", close, true);
    return () => {
      window.removeEventListener("pointerdown", close);
      window.removeEventListener("keydown", close);
      window.removeEventListener("scroll", close, true);
    };
  }, [pinned]);

  return (
    <>
      <button
        ref={btn}
        type="button"
        className="info"
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => !pinned && setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => !pinned && setOpen(false)}
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          setPinned((p) => !p);
          setOpen(true);
        }}
      >
        i
      </button>
      {open && (
        <div ref={tip} id={id} role="tooltip" className={`tooltip ${pos.above ? "above" : "below"}`}
          style={{ left: pos.left, top: pos.top }}>
          {text}
        </div>
      )}
    </>
  );
}

/* ----------------------------------------------------------------- dialog */
export function Dialog({ title, onClose, children, footer, wide, tone }: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
  tone?: "danger";
}) {
  const ref = useRef<HTMLDivElement>(null);
  const labelId = useId();
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const first = ref.current?.querySelector<HTMLElement>("[data-autofocus], input, select, button.primary, button");
    first?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
      if (e.key === "Tab" && ref.current) {
        const items = ref.current.querySelectorAll<HTMLElement>(
          "button:not([disabled]), input:not([disabled]), select, a[href], [tabindex='0']",
        );
        if (!items.length) return;
        const firstEl = items[0];
        const lastEl = items[items.length - 1];
        if (e.shiftKey && document.activeElement === firstEl) {
          e.preventDefault();
          lastEl.focus();
        } else if (!e.shiftKey && document.activeElement === lastEl) {
          e.preventDefault();
          firstEl.focus();
        }
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      prev?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="backdrop" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} className={`dialog ${wide ? "wide" : ""} ${tone ?? ""}`} role="dialog" aria-modal="true"
        aria-labelledby={labelId}>
        <header>
          <h2 id={labelId}>{title}</h2>
          <button type="button" className="ghost icon-only" aria-label="Close" onClick={onClose}>
            <Icon name="close" />
          </button>
        </header>
        <div className="dialog-body">{children}</div>
        {footer && <footer>{footer}</footer>}
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- toasts */
export interface Toast {
  id: number;
  text: string;
  tone: "info" | "success" | "error";
}

export function useToasts() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: Toast["tone"] = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, tone }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 9000 : 5000);
  }, []);
  const dismiss = useCallback((id: number) => setToasts((t) => t.filter((x) => x.id !== id)), []);
  return { toasts, push, dismiss };
}

export function Toasts({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: number) => void }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.tone}`}>
          <span>{t.text}</span>
          <button type="button" className="ghost icon-only" aria-label="Dismiss" onClick={() => dismiss(t.id)}>
            <Icon name="close" size={16} />
          </button>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------- tile */
export interface TileHandlers {
  onPointerDown: (id: number, e: React.PointerEvent) => void;
  onPointerEnter: (id: number) => void;
  onKeyToggle: (id: number) => void;
  onOpen: (id: number) => void;
  onEdit: (id: number) => void;
}

export const Tile = memo(function Tile({ card, selected, handlers }: {
  card: Card;
  selected: boolean;
  handlers: TileHandlers;
}) {
  const place = card.location?.place || card.location?.city;
  return (
    <article
      className={`tile status-${card.status} ${selected ? "selected" : ""}`}
      tabIndex={0}
      role="checkbox"
      aria-checked={selected}
      aria-label={`${card.name}, ${STATUS_LABEL[card.status]}, folder ${card.folder || "none"}`}
      onPointerDown={(e) => handlers.onPointerDown(card.id, e)}
      onPointerEnter={() => handlers.onPointerEnter(card.id)}
      onDoubleClick={() => handlers.onOpen(card.id)}
      onKeyDown={(e) => {
        if (e.key === " ") {
          e.preventDefault();
          handlers.onKeyToggle(card.id);
        } else if (e.key === "Enter") {
          handlers.onOpen(card.id);
        }
      }}
    >
      <div className="thumb">
        {card.thumb ? (
          <img src={card.thumb} alt="" loading="lazy" decoding="async" draggable={false} />
        ) : (
          <div className="thumb-placeholder" aria-hidden="true">
            <span className="spinner" />
          </div>
        )}
        <span className={`check ${selected ? "on" : ""}`} aria-hidden="true">
          {selected && <Icon name="check" size={14} />}
        </span>
        <span className={`badge ${card.status}`} title={card.reason}>
          {card.manual ? "Manual" : STATUS_LABEL[card.status]}
        </span>
        <div className="tile-actions">
          <button type="button" className="tile-btn" aria-label="Preview" title="Preview (double-click)"
            onPointerDown={(e) => e.stopPropagation()} onClick={() => handlers.onOpen(card.id)}>
            <Icon name="expand" size={16} />
          </button>
          <button type="button" className="tile-btn" aria-label="Edit folder" title="Edit folder"
            onPointerDown={(e) => e.stopPropagation()} onClick={() => handlers.onEdit(card.id)}>
            <Icon name="edit" size={16} />
          </button>
        </div>
      </div>
      <div className="meta">
        <div className="name" title={card.path}>{card.name}</div>
        <div className="sub">
          <span>{formatDate(card.taken_at)}</span>
          {card.lat != null && place && (
            <span className="pin" title={card.location?.display || place}>
              <Icon name="pin" size={12} />
              {place}
            </span>
          )}
          {card.doc_score != null && card.doc_score >= 0.6 && (
            <span className="pin" title="Looks like a document">
              <Icon name="doc" size={12} />
            </span>
          )}
        </div>
        <div className="folder" title={`${card.folder}${card.reason ? `\n${card.reason}` : ""}`}>
          {card.folder || <em>No folder yet</em>}
        </div>
      </div>
    </article>
  );
});
