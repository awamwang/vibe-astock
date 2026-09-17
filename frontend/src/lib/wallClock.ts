/** Unix 墙钟槽：短线盘面 live / 短线风格 / 短线精灵随盘拍对齐。 */

export const SPRITE_SLOT_MS = 20_000;

/** 严格晚于 now 的下一拍还要等多久。已落在槽点则再等一整槽。 */
export function delayUntilNextUnixSlot(now = Date.now(), slotMs = SPRITE_SLOT_MS): number {
  const rem = now % slotMs;
  return rem === 0 ? slotMs : slotMs - rem;
}
