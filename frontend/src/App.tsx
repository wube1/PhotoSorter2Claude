import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { Icon, Info, Tile, Toasts, plural, useToasts, type TileHandlers } from "./components";
import { DeleteDialog, EditDialog, HelpDialog, MoveDialog, PreviewDialog, ReplaceDialog } from "./dialogs";
import { HELP, STATUS_LABEL } from "./help";
import { useStore } from "./store";
import type { Card, Job, Status } from "./types";

type Filter = "all" | Status;
type Theme = "auto" | "light" | "dark";
type Modal =
  | { kind: "move" }
  | { kind: "delete"; ids: number[] }
  | { kind: "replace"; from?: string }
  | { kind: "edit"; id: number }
  | { kind: "preview"; id: number }
  | { kind: "help" }
  | null;

const STATUSES: Status[] = ["ready", "review", "duplicate", "pending"];

function readPref<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}
function writePref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* private mode */
  }
}

export default function App() {
  const { toasts, push, dismiss } = useToasts();
  const onJobFinished = useCallback(
    (job: Job) => {
      const failed = job.result && ("error" in job.result || (Array.isArray(job.result.failed) && job.result.failed.length));
      push(job.message, failed ? "error" : "success");
    },
    [push],
  );
  const { store, applyCards } = useStore(onJobFinished);
  const [filter, setFilter] = useState<Filter>(() => readPref<Filter>("ps.filter", "all"));
  const [query, setQuery] = useState("");
  const [tile, setTile] = useState<number>(() => Number(readPref("ps.tile", "180")) || 180);
  const [theme, setTheme] = useState<Theme>(() => readPref<Theme>("ps.theme", "auto"));
  const [selected, setSelected] = useState<Set<number>>(() => new Set());
  const [modal, setModal] = useState<Modal>(null);
  const [predef, setPredef] = useState("");
  const [custom, setCustom] = useState("");

  useEffect(() => writePref("ps.filter", filter), [filter]);
  useEffect(() => writePref("ps.tile", String(tile)), [tile]);
  useEffect(() => {
    writePref("ps.theme", theme);
    if (theme === "auto") document.documentElement.removeAttribute("data-theme");
    else document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const allCards = useMemo(
    () =>
      [...store.cards.values()].sort(
        (a, b) => (a.taken_at ?? "9999").localeCompare(b.taken_at ?? "9999") || a.path.localeCompare(b.path),
      ),
    [store.cards],
  );

  const counts = useMemo(() => {
    const c: Record<Filter, number> = { all: allCards.length, ready: 0, review: 0, duplicate: 0, pending: 0 };
    for (const card of allCards) c[card.status]++;
    return c;
  }, [allCards]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allCards.filter((c) => {
      if (filter !== "all" && c.status !== filter) return false;
      if (!q) return true;
      return [c.name, c.folder, c.location?.place, c.location?.city, c.camera]
        .some((v) => v && v.toLowerCase().includes(q));
    });
  }, [allCards, filter, query]);

  const groups = useMemo(() => {
    const m = new Map<string, Card[]>();
    for (const c of visible) {
      const key = c.folder || "";
      const list = m.get(key);
      if (list) list.push(c);
      else m.set(key, [c]);
    }
    return [...m.entries()];
  }, [visible]);

  const ordered = useMemo(() => groups.flatMap(([, cards]) => cards), [groups]);

  // drop selection of cards that disappeared (moved / deleted)
  useEffect(() => {
    setSelected((prev) => {
      let changed = false;
      const next = new Set<number>();
      for (const id of prev) {
        if (store.cards.has(id)) next.add(id);
        else changed = true;
      }
      return changed ? next : prev;
    });
  }, [store.cards]);

  const folderCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const c of allCards) if (c.folder) m.set(c.folder, (m.get(c.folder) ?? 0) + 1);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [allCards]);

  const suggestions = useMemo(
    () => [...new Set([...store.predefined, ...folderCounts.map(([f]) => f)])],
    [store.predefined, folderCounts],
  );

  const readyCards = useMemo(() => allCards.filter((c) => c.status === "ready"), [allCards]);
  const selectedIds = useMemo(() => [...selected], [selected]);
  const busy = store.job.running;

  /* ------------------------------------------------------ drag selection */
  const drag = useRef<{ active: boolean; mode: boolean }>({ active: false, mode: true });
  const lastClicked = useRef<number | null>(null);
  const orderedRef = useRef(ordered);
  orderedRef.current = ordered;

  const setMany = useCallback((ids: number[], on: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }, []);

  useEffect(() => {
    const end = () => {
      drag.current.active = false;
      document.body.classList.remove("dragging");
    };
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
  }, []);

  const selectedRef = useRef(selected);
  selectedRef.current = selected;

  const handlers: TileHandlers = useMemo(
    () => ({
      onPointerDown: (id, e) => {
        if (e.button !== 0) return;
        if (e.pointerType === "mouse") e.preventDefault(); // no text selection / image drag
        if (e.shiftKey && lastClicked.current != null) {
          const list = orderedRef.current.map((c) => c.id);
          const a = list.indexOf(lastClicked.current);
          const b = list.indexOf(id);
          if (a >= 0 && b >= 0) {
            setMany(list.slice(Math.min(a, b), Math.max(a, b) + 1), true);
            return;
          }
        }
        const mode = !selectedRef.current.has(id);
        drag.current = { active: true, mode };
        document.body.classList.add("dragging");
        lastClicked.current = id;
        setMany([id], mode);
      },
      onPointerEnter: (id) => {
        if (drag.current.active) setMany([id], drag.current.mode);
      },
      onKeyToggle: (id) => {
        lastClicked.current = id;
        setMany([id], !selectedRef.current.has(id));
      },
      onOpen: (id) => setModal({ kind: "preview", id }),
      onEdit: (id) => setModal({ kind: "edit", id }),
    }),
    [setMany],
  );

  /* ------------------------------------------------------------ keyboard */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (modal) return;
      const target = e.target as HTMLElement;
      if (target.closest("input, select, textarea")) return;
      if (e.key === "Escape") setSelected(new Set());
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "a") {
        e.preventDefault();
        setSelected(new Set(orderedRef.current.map((c) => c.id)));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [modal]);

  /* ------------------------------------------------------------- actions */
  const run = useCallback(
    async (fn: () => Promise<unknown>, success?: string) => {
      try {
        await fn();
        if (success) push(success, "success");
        return true;
      } catch (e) {
        push((e as Error).message, "error");
        return false;
      }
    },
    [push],
  );

  const setFolder = (ids: number[], folder: string | null, msg?: string) =>
    run(async () => applyCards((await api.setFolder(ids, folder)).cards), msg);

  const startScan = () => run(api.scan);
  const startMove = async () => {
    if (await run(() => api.move(null))) setModal(null);
  };

  const closeModal = useCallback(() => setModal(null), []);
  const previewIndex = modal?.kind === "preview" ? ordered.findIndex((c) => c.id === modal.id) : -1;
  const modalCard = modal && "id" in modal ? store.cards.get(modal.id) : undefined;

  const progress = store.job.total ? Math.min(100, (store.job.done / store.job.total) * 100) : null;

  return (
    <div className="app" style={{ ["--tile" as string]: `${tile}px` }}>
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <div>
            <h1>PhotoSorter</h1>
            <span className="version">v{store.version}</span>
          </div>
        </div>
        <div className="actions">
          <div className="btn-with-info">
            <button type="button" className="secondary" onClick={startScan} disabled={busy}>
              <Icon name="scan" /> {busy && store.job.kind === "scan" ? "Scanning…" : "Scan inbox"}
            </button>
            <Info text={HELP.scan} />
          </div>
          <div className="btn-with-info">
            <button type="button" className="secondary" onClick={() => setModal({ kind: "replace" })}
              disabled={!folderCounts.length}>
              <Icon name="replace" /> Replace folder
            </button>
            <Info text={HELP.replace} />
          </div>
          <div className="btn-with-info">
            <button type="button" className="primary" onClick={() => setModal({ kind: "move" })}
              disabled={busy || !readyCards.length}>
              <Icon name="move" /> Move {readyCards.length ? readyCards.length.toLocaleString() : ""} ready
            </button>
            <Info text={HELP.move} />
          </div>
          <button type="button" className="ghost icon-only" aria-label={`Theme: ${theme}`} title={HELP.theme}
            onClick={() => setTheme(theme === "auto" ? "light" : theme === "light" ? "dark" : "auto")}>
            <Icon name={theme === "auto" ? "auto" : theme === "light" ? "sun" : "moon"} />
          </button>
          <button type="button" className="ghost icon-only" aria-label="Help" title="Help"
            onClick={() => setModal({ kind: "help" })}>
            <Icon name="help" />
          </button>
        </div>
      </header>

      <div className={`jobbar ${busy ? "active" : ""}`} role="status" aria-live="polite">
        {busy ? (
          <>
            <div className="jobtext">
              <span className="spinner" aria-hidden="true" />
              <span>{store.job.message}</span>
              {store.job.total > 0 && <span className="muted">{store.job.done}/{store.job.total}</span>}
            </div>
            <div className="progress" aria-hidden="true">
              <div className={progress == null ? "indeterminate" : ""} style={progress != null ? { width: `${progress}%` } : {}} />
            </div>
          </>
        ) : (
          <div className="jobtext muted">
            <span className={`dot ${store.connected ? "ok" : "off"}`} aria-hidden="true" />
            {store.connected ? store.job.message || "Ready" : "Reconnecting to server…"}
          </div>
        )}
      </div>

      {store.config && (!store.config.loaded || store.config.error) && (
        <div className="notice">
          {store.config.error
            ? `config.yaml could not be read (${store.config.error}); built-in defaults are used.`
            : `No config.yaml found at ${store.config.file}; built-in defaults are used (no custom places).`}
        </div>
      )}

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Filter by status">
          {(["all", ...STATUSES] as Filter[]).map((f) => (
            <button key={f} type="button" role="tab" aria-selected={filter === f}
              className={`tab ${filter === f ? "on" : ""} ${f}`} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : STATUS_LABEL[f]}
              <span className="count">{counts[f].toLocaleString()}</span>
            </button>
          ))}
          <Info text={HELP.statusFilter} />
        </div>
        <div className="tools">
          <label className="search">
            <Icon name="search" size={16} />
            <input type="search" placeholder="Search name, folder, place…" value={query}
              onChange={(e) => setQuery(e.target.value)} aria-label="Search" />
          </label>
          <label className="size" title={HELP.tileSize}>
            <span className="sr-only">Tile size</span>
            <input type="range" min={120} max={320} step={10} value={tile} onChange={(e) => setTile(Number(e.target.value))} />
          </label>
          <div className="btn-with-info">
            <button type="button" className="ghost" onClick={() => setSelected(new Set(ordered.map((c) => c.id)))}
              disabled={!ordered.length}>
              <Icon name="selectAll" /> Select all
            </button>
            <Info text={HELP.selectAll} />
          </div>
          <Info text={HELP.selection} label="How to select" />
        </div>
      </div>

      <main className={`content ${selected.size ? "with-bar" : ""}`}>
        {!store.loaded ? (
          <div className="empty"><span className="spinner" /> Loading…</div>
        ) : !allCards.length ? (
          <div className="empty">
            <Icon name="scan" size={40} />
            <h2>{busy ? "Scanning…" : "Inbox is empty"}</h2>
            <p className="muted">
              {busy ? "Photos appear here as they are analysed." : "Put photos into the inbox folder and press Scan inbox."}
            </p>
            {!busy && (
              <button type="button" className="primary" onClick={startScan}>
                <Icon name="scan" /> Scan inbox
              </button>
            )}
          </div>
        ) : !visible.length ? (
          <div className="empty"><p className="muted">No cards match this filter.</p></div>
        ) : (
          groups.map(([folder, cards]) => {
            const allSel = cards.every((c) => selected.has(c.id));
            const statuses = STATUSES.map((s) => [s, cards.filter((c) => c.status === s).length] as const).filter(([, n]) => n);
            return (
              <section key={folder} className="group" aria-label={folder || "No folder"}>
                <div className="group-head">
                  <label className="group-check" title={HELP.selectGroup}>
                    <input type="checkbox" checked={allSel} onChange={() => setMany(cards.map((c) => c.id), !allSel)} />
                    <span className="sr-only">Select group</span>
                  </label>
                  <h2 className="group-title">{folder || <em>No folder</em>}</h2>
                  <span className="group-count">{plural(cards.length, "photo")}</span>
                  <span className="group-status">
                    {statuses.map(([s, n]) => (
                      <span key={s} className={`badge inline ${s}`}>{n} {STATUS_LABEL[s].toLowerCase()}</span>
                    ))}
                  </span>
                  {folder && (
                    <button type="button" className="ghost small" onClick={() => setModal({ kind: "replace", from: folder })}>
                      <Icon name="edit" size={14} /> Rename
                    </button>
                  )}
                </div>
                <div className="grid">
                  {cards.map((c) => (
                    <Tile key={c.id} card={c} selected={selected.has(c.id)} handlers={handlers} />
                  ))}
                </div>
              </section>
            );
          })
        )}
      </main>

      {selected.size > 0 && (
        <div className="selectionbar" role="region" aria-label="Selection actions">
          <div className="sel-count">
            <strong>{selected.size.toLocaleString()}</strong> selected
            <button type="button" className="ghost small" onClick={() => setSelected(new Set())}>
              Clear selection
            </button>
            <Info text={HELP.clear} />
          </div>
          <div className="sel-group">
            <select value={predef} onChange={(e) => setPredef(e.target.value)} aria-label="Predefined folder">
              <option value="">Predefined folder…</option>
              {store.predefined.map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <button type="button" className="secondary" disabled={!predef}
              onClick={() => setFolder(selectedIds, predef, `Folder set on ${plural(selectedIds.length, "card")}`)}>
              Apply
            </button>
            <Info text={HELP.predefined} />
          </div>
          <form className="sel-group" onSubmit={(e) => {
            e.preventDefault();
            if (custom.trim()) void setFolder(selectedIds, custom.trim(), `Folder set on ${plural(selectedIds.length, "card")}`).then((ok) => ok && setCustom(""));
          }}>
            <input list="bulk-suggestions" placeholder="Custom folder, e.g. {date} - Wawel" value={custom}
              onChange={(e) => setCustom(e.target.value)} aria-label="Custom folder name" />
            <datalist id="bulk-suggestions">
              {suggestions.map((s) => <option key={s} value={s} />)}
            </datalist>
            <button type="submit" className="secondary" disabled={!custom.trim()}>Set folder</button>
            <Info text={HELP.custom} />
          </form>
          <div className="sel-group">
            <button type="button" className="secondary"
              onClick={() => run(async () => applyCards((await api.approve(selectedIds)).cards), "Marked ready")}>
              <Icon name="check" /> Approve
            </button>
            <Info text={HELP.approve} />
            <button type="button" className="ghost"
              onClick={() => run(async () => applyCards((await api.reset(selectedIds)).cards), "Back to automatic")}>
              <Icon name="undo" /> Reset
            </button>
            <Info text={HELP.reset} />
          </div>
          <div className="sel-group end">
            <button type="button" className="danger" disabled={busy} onClick={() => setModal({ kind: "delete", ids: selectedIds })}>
              <Icon name="trash" /> Delete
            </button>
            <Info text={HELP.delete} />
          </div>
        </div>
      )}

      {modal?.kind === "move" && (
        <MoveDialog ready={readyCards} busy={busy} onClose={closeModal} onConfirm={startMove} />
      )}
      {modal?.kind === "delete" && (
        <DeleteDialog
          cards={modal.ids.map((id) => store.cards.get(id)).filter((c): c is Card => !!c)}
          mode={store.config?.delete_mode ?? "permanent"}
          onClose={closeModal}
          onConfirm={async () => {
            if (await run(() => api.remove(modal.ids))) {
              setSelected(new Set());
              setModal(null);
            }
          }}
        />
      )}
      {modal?.kind === "replace" && (
        <ReplaceDialog
          folders={folderCounts}
          replacements={store.replacements}
          suggestions={suggestions}
          initialFrom={modal.from}
          onClose={closeModal}
          onAdd={(from, to) => run(() => api.addReplacement(from, to), `Replaced “${from}”`)}
          onRemove={(id) => void run(() => api.deleteReplacement(id), "Rule removed")}
        />
      )}
      {modal?.kind === "edit" && modalCard && (
        <EditDialog
          card={modalCard}
          suggestions={suggestions}
          onClose={closeModal}
          onSave={async (folder) => (await setFolder([modalCard.id], folder)) && setModal(null)}
          onReset={() => void run(async () => applyCards((await api.reset([modalCard.id])).cards)).then(() => setModal(null))}
          onApprove={() => void run(async () => applyCards((await api.approve([modalCard.id])).cards)).then(() => setModal(null))}
        />
      )}
      {modal?.kind === "preview" && modalCard && (
        <PreviewDialog
          card={modalCard}
          onClose={closeModal}
          onEdit={() => setModal({ kind: "edit", id: modalCard.id })}
          onPrev={previewIndex > 0 ? () => setModal({ kind: "preview", id: ordered[previewIndex - 1].id }) : undefined}
          onNext={previewIndex >= 0 && previewIndex < ordered.length - 1
            ? () => setModal({ kind: "preview", id: ordered[previewIndex + 1].id }) : undefined}
        />
      )}
      {modal?.kind === "help" && <HelpDialog config={store.config} version={store.version} onClose={closeModal} />}
      <Toasts toasts={toasts} dismiss={dismiss} />
    </div>
  );
}
