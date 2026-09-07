import { useEffect } from "react";
import { MessageDiaryPanel, useMessageDiaryList } from "@/components/MessageStockDiary";
import { useDarkMode } from "@/hooks/useDarkMode";
import { getDefaultEndDays } from "@/lib/messages";
import { attachPopupGeometryPersistence } from "@/lib/sectionPopup";

/** 独立路由页：/messages/diary，可单独打开或由「个股日记」按钮弹出 */
export function MessageDiaryPopup() {
  useDarkMode();
  const defaultEndDays = getDefaultEndDays();
  const { items, total, loading, code, stockName, status, error, reload } = useMessageDiaryList(
    true,
    defaultEndDays,
  );

  useEffect(() => {
    document.title = code ? `${code} · 个股日记` : "个股日记";
  }, [code]);

  useEffect(() => attachPopupGeometryPersistence(), []);

  return (
    <MessageDiaryPanel
      key={code ?? "none"}
      items={items}
      loading={loading}
      code={code}
      stockName={stockName}
      status={status}
      error={error}
      total={total}
      onAdded={() => void reload()}
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
