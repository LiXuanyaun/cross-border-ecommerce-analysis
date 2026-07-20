import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

interface AppState {
  datasetId: string;
  setDatasetId: (value: string) => void;
  start: string;
  end: string;
  setRange: (start: string, end: string) => void;
}

const Context = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [datasetId, setDatasetId] = useState("demo-all");
  const [start, setStart] = useState("2023-09-01");
  const [end, setEnd] = useState("2025-08-31");
  const value = useMemo(() => ({ datasetId, setDatasetId, start, end, setRange: (nextStart: string, nextEnd: string) => { setStart(nextStart); setEnd(nextEnd); } }), [datasetId, start, end]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState() {
  const value = useContext(Context);
  if (!value) throw new Error("AppStateProvider missing");
  return value;
}
