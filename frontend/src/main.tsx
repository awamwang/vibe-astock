import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { router } from "./router";
import { primeCliAvailability } from "./lib/ai-models";
import { authHeaders } from "./lib/api";
import "./index.css";

// 先把"哪些订阅 CLI 能用"拉到全局缓存 —— `loadLlm()` 是同步的、全站都在调，
// 没法在里面 await。不阻塞首屏：拉不到就按"还不知道"处理，由服务端 400 兜底。
void primeCliAvailability(authHeaders());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <RouterProvider router={router} />
      <Toaster position="bottom-right" theme="dark" richColors closeButton duration={3500} />
    </ErrorBoundary>
  </StrictMode>
);
