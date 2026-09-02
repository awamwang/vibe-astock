import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { MessageDetailPanel } from "@/components/MessageDetailPanel";
import { PopupShell } from "@/components/PopupShell";
import type { AnalyzedMessage } from "@/lib/api";
import { getDefaultEndDays } from "@/lib/messages";

/** 独立路由页：/messages/:id，可单独打开或由消息分析「详情」按钮弹出 */
export function MessageDetailPopup() {
  const { id: rawId } = useParams<{ id: string }>();
  const id = rawId ? decodeURIComponent(rawId) : "";
  const defaultEndDays = getDefaultEndDays();
  const [title, setTitle] = useState("消息详情");

  useEffect(() => {
    setTitle("消息详情");
  }, [id]);

  if (!id) {
    return (
      <PopupShell title="消息详情">
        <p className="text-sm text-muted-foreground">缺少消息 ID</p>
      </PopupShell>
    );
  }

  return (
    <PopupShell title={title} bodyClassName="p-4">
      <MessageDetailPanel
        messageId={id}
        defaultEndDays={defaultEndDays}
        emptyText="未找到该消息"
        onUpdated={(msg: AnalyzedMessage) => {
          const t = (msg.title || "").trim();
          setTitle(t ? `${t} · 消息详情` : "消息详情");
        }}
      />
    </PopupShell>
  );
}
