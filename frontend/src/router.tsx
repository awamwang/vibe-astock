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
import { MessageDetailPopup } from "@/pages/MessageDetailPopup";
import { MessageStockPopup } from "@/pages/MessageStockPopup";
import { TradeBudgetPopout, VerificationPopout } from "@/pages/popout/AgentReviewPopouts";
import { ShortBoardPopout } from "@/pages/popout/ShortBoardPopout";
import { ThsBlocks } from "@/pages/ThsBlocks";
import { Settings } from "@/pages/Settings";
import { DataBackup } from "@/pages/DataBackup";
import { ZtKeywordsSettings } from "@/pages/ZtKeywordsSettings";
import { ExperienceMemory } from "@/pages/ExperienceMemory";
import { Articles } from "@/pages/Articles";
import { PluginManagement } from "@/pages/PluginManagement";
import { About } from "@/pages/About";
import { SystemSettings } from "@/pages/SystemSettings";

// basename 跟着构建时的 --base 走，这样挂在子路径下内部跳转才不会掉回站点根目录
export const router = createBrowserRouter([
  // 独立弹窗页：无侧栏布局，可单独打开或由 window.open 弹出
  { path: "/messages/pip", element: <MessageStockPopup /> },
  { path: "/messages/:id", element: <MessageDetailPopup /> },
  { path: "/popout/agent/trade-budget", element: <TradeBudgetPopout /> },
  { path: "/popout/agent/verification", element: <VerificationPopout /> },
  { path: "/popout/short-board/:section", element: <ShortBoardPopout /> },
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
      { path: "/blocks", element: <ThsBlocks /> },
      { path: "/experience", element: <ExperienceMemory /> },
      { path: "/articles", element: <Articles /> },
      { path: "/settings", element: <Settings /> },
      { path: "/settings/keywords", element: <ZtKeywordsSettings /> },
      { path: "/settings/plugins", element: <PluginManagement /> },
      { path: "/settings/data", element: <DataBackup /> },
      { path: "/settings/backup", element: <DataBackup /> },
      { path: "/settings/system", element: <SystemSettings /> },
      { path: "/settings/about", element: <About /> },
      { path: "*", element: <Navigate to="/agent/review" replace /> },
    ],
  },
], { basename: import.meta.env.BASE_URL });
