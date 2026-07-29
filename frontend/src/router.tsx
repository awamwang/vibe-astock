import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { AgentReview } from "@/pages/AgentReview";
import { DailyReview } from "@/pages/DailyReview";
import { FirstBoard } from "@/pages/FirstBoard";
import { AgentWeekly } from "@/pages/AgentWeekly";
import { Settings } from "@/pages/Settings";

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/agent/review" replace /> },
      { path: "/agent/review", element: <AgentReview /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/first-board", element: <FirstBoard /> },
      { path: "/heat", element: <AgentWeekly /> },
      { path: "/settings", element: <Settings /> },
      { path: "*", element: <Navigate to="/agent/review" replace /> },
    ],
  },
]);
