import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { FactCapability } from "../types";

const DATASET_STORAGE_KEY = "crossborder.current-dataset";

function storedDatasetId() {
  return typeof localStorage !== "undefined" && typeof localStorage.getItem === "function" ? localStorage.getItem(DATASET_STORAGE_KEY) ?? "" : "";
}

function persistDatasetId(value: string) {
  if (typeof localStorage === "undefined") return;
  if (value && typeof localStorage.setItem === "function") localStorage.setItem(DATASET_STORAGE_KEY, value);
  if (!value && typeof localStorage.removeItem === "function") localStorage.removeItem(DATASET_STORAGE_KEY);
}

interface AppState {
  datasetId: string;
  setDatasetId: (value: string) => void;
  start: string;
  end: string;
  rangeSource: "AUTO" | "USER";
  rangeFact: FactCapability["fact"] | null;
  datasetRevision: number;
  setRange: (start: string, end: string) => void;
  setAutomaticRange: (start: string, end: string, fact: FactCapability["fact"]) => void;
}

const Context = createContext<AppState | null>(null);

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [datasetId, setDatasetIdState] = useState(storedDatasetId);
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [rangeSource, setRangeSource] = useState<"AUTO" | "USER">("AUTO");
  const [rangeFact, setRangeFact] = useState<FactCapability["fact"] | null>(null);
  const [datasetRevision, setDatasetRevision] = useState(0);
  const value = useMemo(() => ({
    datasetId,
    setDatasetId: (value: string) => {
      setDatasetIdState(value);
      persistDatasetId(value);
      setStart("");
      setEnd("");
      setRangeSource("AUTO");
      setRangeFact(null);
      if (value !== datasetId) setDatasetRevision(current => current + 1);
    },
    start,
    end,
    rangeSource,
    rangeFact,
    datasetRevision,
    setRange: (nextStart: string, nextEnd: string) => {
      setStart(nextStart);
      setEnd(nextEnd);
      setRangeSource("USER");
      setRangeFact(null);
    },
    setAutomaticRange: (nextStart: string, nextEnd: string, fact: FactCapability["fact"]) => {
      setStart(nextStart);
      setEnd(nextEnd);
      setRangeSource("AUTO");
      setRangeFact(fact);
    },
  }), [datasetId, datasetRevision, end, rangeFact, rangeSource, start]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function useAppState() {
  const value = useContext(Context);
  if (!value) throw new Error("AppStateProvider missing");
  return value;
}
