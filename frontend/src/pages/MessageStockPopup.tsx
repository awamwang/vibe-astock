import { useEffect } from "react";
import { MessageStockLinkPanel, useMessageStockLinkList } from "@/components/MessageStockPip";
import { useDarkMode } from "@/hooks/useDarkMode";
import { getDefaultEndDays } from "@/lib/messages";
import { attachPopupGeometryPersistence } from "@/lib/sectionPopup";

/** 独立路由页：/messages/pip，可单独打开或由「独立弹窗」按钮弹出 */
export function MessageStockPopup() {
  useDarkMode();
  const defaultEndDays = getDefaultEndDays();
  const { items, total, loading, code, stockName, status, error } = useMessageStockLinkList(
    true,
    defaultEndDays,
  );

  useEffect(() => {
    document.title = code ? `${code} · 消息联动` : "消息联动";
  }, [code]);

  useEffect(() => attachPopupGeometryPersistence(), []);

  return (
    <MessageStockLinkPanel
      key={code ?? "none"}
      items={items}
      loading={loading}
      code={code}
      stockName={stockName}
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
