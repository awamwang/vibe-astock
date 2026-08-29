import { useEffect } from "react";
import { MessageStockLinkPanel, useMessageStockLinkList } from "@/components/MessageStockPip";
import { useDarkMode } from "@/hooks/useDarkMode";
import { getDefaultEndDays } from "@/lib/messages";

/** 独立路由页：/messages/pip，可单独打开或由「独立弹窗」按钮弹出 */
export function MessageStockPopup() {
  useDarkMode();
  const defaultEndDays = getDefaultEndDays();
  const { items, total, loading, code, status, error } = useMessageStockLinkList(true, defaultEndDays);

  useEffect(() => {
    document.title = code ? `${code} · 消息联动` : "消息联动";
  }, [code]);

  return (
    <MessageStockLinkPanel
      items={items}
      loading={loading}
      code={code}
      status={status}
      error={error}
      total={total}
      title="消息联动"
      onClose={() => {
        try {
          window.close();
        } catch {
          /* 非脚本打开的窗口可能关不掉 */
        }
      }}
    />
  );
}
