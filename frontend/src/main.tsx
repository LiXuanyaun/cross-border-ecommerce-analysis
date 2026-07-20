import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AppStateProvider } from "./state/app";
import { OverviewPage } from "./pages/OverviewPage";
import { AnalyticsPage } from "./pages/AnalyticsPage";
import { DataHubPage } from "./pages/DataHubPage";
import { AiAnalystPage } from "./pages/AiAnalystPage";
import "./styles.css";

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } } });
const router = createBrowserRouter([{ element: <AppShell/>, children: [
  { path: "/", element: <OverviewPage/> },
  { path: "/analytics", element: <AnalyticsPage/> },
  { path: "/data", element: <DataHubPage/> },
  { path: "/ai", element: <AiAnalystPage/> },
]}]);

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><QueryClientProvider client={queryClient}><AppStateProvider><RouterProvider router={router}/></AppStateProvider></QueryClientProvider></React.StrictMode>);
