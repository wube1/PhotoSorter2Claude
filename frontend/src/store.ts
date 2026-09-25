import { useCallback, useEffect, useReducer, useRef } from "react";
import { api } from "./api";
import type { AppConfig, AppState, Card, Job, Replacement } from "./types";

export interface Store {
  loaded: boolean;
  connected: boolean;
  version: string;
  cards: Map<number, Card>;
  replacements: Replacement[];
  predefined: string[];
  job: Job;
  config: AppConfig | null;
  error: string | null;
}

type Action =
  | { type: "state"; state: AppState }
  | { type: "cards"; cards: Card[] }
  | { type: "removed"; ids: number[] }
  | { type: "job"; job: Job }
  | { type: "replacements"; replacements: Replacement[] }
  | { type: "connected"; connected: boolean }
  | { type: "error"; error: string | null };

const idleJob: Job = {
  running: false,
  kind: null,
  phase: "idle",
  done: 0,
  total: 0,
  message: "",
  started_at: null,
  finished_at: null,
  result: null,
};

const initial: Store = {
  loaded: false,
  connected: false,
  version: __APP_VERSION__,
  cards: new Map(),
  replacements: [],
  predefined: [],
  job: idleJob,
  config: null,
  error: null,
};

function reducer(state: Store, action: Action): Store {
  switch (action.type) {
    case "state":
      return {
        ...state,
        loaded: true,
        error: null,
        version: action.state.version,
        cards: new Map(action.state.cards.map((c) => [c.id, c])),
        replacements: action.state.replacements,
        predefined: action.state.predefined_folders,
        job: action.state.job,
        config: action.state.config,
      };
    case "cards": {
      if (!action.cards.length) return state;
      const cards = new Map(state.cards);
      for (const c of action.cards) cards.set(c.id, c);
      return { ...state, cards };
    }
    case "removed": {
      const cards = new Map(state.cards);
      for (const id of action.ids) cards.delete(id);
      return { ...state, cards };
    }
    case "job":
      return { ...state, job: action.job };
    case "replacements":
      return { ...state, replacements: action.replacements };
    case "connected":
      return { ...state, connected: action.connected };
    case "error":
      return { ...state, error: action.error };
  }
}

/** Loads the full state once, then keeps it live through Server-Sent Events. */
export function useStore(onJobFinished: (job: Job) => void) {
  const [store, dispatch] = useReducer(reducer, initial);
  const reloadTimer = useRef<number | undefined>(undefined);
  const lastJobRunning = useRef(false);
  const finishedCb = useRef(onJobFinished);
  finishedCb.current = onJobFinished;

  const reload = useCallback(async () => {
    try {
      dispatch({ type: "state", state: await api.state() });
    } catch (e) {
      dispatch({ type: "error", error: (e as Error).message });
    }
  }, []);

  const scheduleReload = useCallback(() => {
    window.clearTimeout(reloadTimer.current);
    reloadTimer.current = window.setTimeout(reload, 150);
  }, [reload]);

  useEffect(() => {
    void reload();
    const es = new EventSource("/api/events");
    let first = true;
    es.addEventListener("hello", () => {
      dispatch({ type: "connected", connected: true });
      if (!first) scheduleReload(); // reconnected: resync everything
      first = false;
    });
    es.addEventListener("cards", (e) => dispatch({ type: "cards", cards: JSON.parse((e as MessageEvent).data).cards }));
    es.addEventListener("removed", (e) => dispatch({ type: "removed", ids: JSON.parse((e as MessageEvent).data).ids }));
    es.addEventListener("replacements", (e) =>
      dispatch({ type: "replacements", replacements: JSON.parse((e as MessageEvent).data).replacements }),
    );
    es.addEventListener("reload", scheduleReload);
    es.addEventListener("job", (e) => {
      const job = JSON.parse((e as MessageEvent).data) as Job;
      dispatch({ type: "job", job });
      if (lastJobRunning.current && !job.running) finishedCb.current(job);
      lastJobRunning.current = job.running;
    });
    es.onerror = () => dispatch({ type: "connected", connected: false });
    return () => {
      es.close();
      window.clearTimeout(reloadTimer.current);
    };
  }, [reload, scheduleReload]);

  const applyCards = useCallback((cards: Card[]) => dispatch({ type: "cards", cards }), []);
  return { store, reload, applyCards };
}
