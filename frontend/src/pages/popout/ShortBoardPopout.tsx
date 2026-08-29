import { useParams } from "react-router-dom";
import { PopupShell } from "@/components/PopupShell";
import {
  ShortBoard,
  SHORT_BOARD_POPOUT_TITLES,
  type ShortBoardPopoutSection,
} from "@/pages/ShortBoard";

const SECTIONS = new Set<string>(Object.keys(SHORT_BOARD_POPOUT_TITLES));

/** 短线盘面分区独立弹窗 */
export function ShortBoardPopout() {
  const { section } = useParams<{ section: string }>();
  const valid = section && SECTIONS.has(section)
    ? (section as ShortBoardPopoutSection)
    : null;

  if (!valid) {
    return (
      <PopupShell title="短线盘面">
        <p className="text-sm text-muted-foreground">未知分区：{section || "—"}</p>
      </PopupShell>
    );
  }

  return (
    <PopupShell
      title={SHORT_BOARD_POPOUT_TITLES[valid]}
      bodyClassName="p-3"
    >
      <ShortBoard popoutSection={valid} />
    </PopupShell>
  );
}
