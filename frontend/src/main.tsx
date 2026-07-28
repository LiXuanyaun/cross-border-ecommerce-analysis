import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { AppStateProvider } from "./state/app";
import { Skeleton } from "./components/ui";
import "./styles.css";

const OverviewPage = React.lazy(() => import("./pages/OverviewPage").then((module) => ({ default: module.OverviewPage })));
const AnalyticsPage = React.lazy(() => import("./pages/AnalyticsPage").then((module) => ({ default: module.AnalyticsPage })));
const DataHubPage = React.lazy(() => import("./pages/DataHubPage").then((module) => ({ default: module.DataHubPage })));
const AiAnalystPage = React.lazy(() => import("./pages/AiAnalystPage").then((module) => ({ default: module.AiAnalystPage })));

function PageLoader() {
  return <div className="p-6"><Skeleton className="h-8 w-48" /><Skeleton className="mt-4 h-64 w-full" /></div>;
}

const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: 60_000, retry: 1, refetchOnWindowFocus: false } } });
const router = createBrowserRouter([{ element: <AppShell/>, children: [
  { path: "/", element: <React.Suspense fallback={<PageLoader />}><OverviewPage/></React.Suspense> },
  { path: "/analytics", element: <React.Suspense fallback={<PageLoader />}><AnalyticsPage/></React.Suspense> },
  { path: "/data", element: <React.Suspense fallback={<PageLoader />}><DataHubPage/></React.Suspense> },
  { path: "/ai", element: <React.Suspense fallback={<PageLoader />}><AiAnalystPage/></React.Suspense> },
]}]);

ReactDOM.createRoot(document.getElementById("root")!).render(<React.StrictMode><QueryClientProvider client={queryClient}><AppStateProvider><RouterProvider router={router}/></AppStateProvider></QueryClientProvider></React.StrictMode>);
