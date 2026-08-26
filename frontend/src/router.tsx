import { createBrowserRouter, Navigate } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";
import { AgentReview } from "@/pages/AgentReview";
import { DailyReview } from "@/pages/DailyReview";
import { ShortBoard } from "@/pages/ShortBoard";
import { FirstBoard } from "@/pages/FirstBoard";
import { AgentWeekly } from "@/pages/AgentWeekly";
import { TradeBudgetPage } from "@/pages/TradeBudgetPage";
import { Watchlist } from "@/pages/Watchlist";
import { MessageAnalysis } from "@/pages/MessageAnalysis";
import { Settings } from "@/pages/Settings";
import { DataBackup } from "@/pages/DataBackup";
import { ZtKeywordsSettings } from "@/pages/ZtKeywordsSettings";
import { ExperienceMemory } from "@/pages/ExperienceMemory";
import { PluginManagement } from "@/pages/PluginManagement";

// basename 跟着构建时的 --base 走，这样挂在子路径下内部跳转才不会掉回站点根目录
export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: <Navigate to="/agent/review" replace /> },
      { path: "/agent/review", element: <AgentReview /> },
      { path: "/short-board", element: <ShortBoard /> },
      { path: "/daily-review", element: <DailyReview /> },
      { path: "/first-board", element: <FirstBoard /> },
      { path: "/heat", element: <AgentWeekly /> },
      { path: "/trade", element: <TradeBudgetPage /> },
      { path: "/watchlist", element: <Watchlist /> },
      { path: "/messages", element: <MessageAnalysis /> },
      { path: "/experience", element: <ExperienceMemory /> },
      { path: "/settings", element: <Settings /> },
      { path: "/settings/keywords", element: <ZtKeywordsSettings /> },
      { path: "/settings/plugins", element: <PluginManagement /> },
      { path: "/settings/data", element: <DataBackup /> },
      { path: "/settings/backup", element: <DataBackup /> },
      { path: "*", element: <Navigate to="/agent/review" replace /> },
    ],
  },
], { basename: import.meta.env.BASE_URL });
