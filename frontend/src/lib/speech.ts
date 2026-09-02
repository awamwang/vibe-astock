/**
 * 浏览器自带语音播报（Web Speech API / speechSynthesis）。
 * 不支持的环境需先用 isSpeechSupported 判断。
 */

let speakGeneration = 0;

/** 当前环境是否支持语音合成 */
export function isSpeechSupported(): boolean {
  return (
    typeof window !== "undefined"
    && typeof window.speechSynthesis !== "undefined"
    && typeof window.SpeechSynthesisUtterance !== "undefined"
  );
}

/** 触发 voices 列表加载（部分浏览器需异步 voiceschanged） */
export function warmSpeechVoices(): void {
  if (!isSpeechSupported()) return;
  void window.speechSynthesis.getVoices();
}

/** 等待中文或其他可用音色就绪 */
export function ensureVoicesLoaded(): Promise<SpeechSynthesisVoice[]> {
  if (!isSpeechSupported()) return Promise.resolve([]);
  const existing = window.speechSynthesis.getVoices();
  if (existing.length) return Promise.resolve(existing);
  return new Promise((resolve) => {
    const finish = () => {
      window.speechSynthesis.removeEventListener("voiceschanged", finish);
      resolve(window.speechSynthesis.getVoices());
    };
    window.speechSynthesis.addEventListener("voiceschanged", finish);
    window.setTimeout(finish, 800);
  });
}

function pickVoice(voices: SpeechSynthesisVoice[], lang: string): SpeechSynthesisVoice | null {
  const normalized = lang.toLowerCase().replace(/_/g, "-");
  const exact = voices.find((v) => v.lang.toLowerCase().replace(/_/g, "-") === normalized);
  if (exact) return exact;
  const prefix = normalized.split("-")[0] || "zh";
  return voices.find((v) => v.lang.toLowerCase().replace(/_/g, "-").startsWith(prefix)) || null;
}

export type SpeakTextsOptions = {
  lang?: string;
  rate?: number;
  onProgress?: (index: number, total: number) => void;
  onDone?: () => void;
};

/** 停止当前播报队列 */
export function stopSpeech(): void {
  if (!isSpeechSupported()) return;
  speakGeneration += 1;
  window.speechSynthesis.cancel();
}

/**
 * 依次播报多段文本；再次调用会取消上一次队列。
 * 返回 stop 以便外部中断。
 */
export function speakTexts(
  texts: string[],
  opts?: SpeakTextsOptions,
): { stop: () => void } {
  const cleaned = texts.map((t) => String(t || "").trim()).filter(Boolean);
  if (!isSpeechSupported() || !cleaned.length) {
    opts?.onDone?.();
    return { stop: () => undefined };
  }

  const generation = ++speakGeneration;
  const lang = opts?.lang ?? "zh-CN";
  const rate = opts?.rate ?? 1.05;
  window.speechSynthesis.cancel();

  let index = 0;
  let voices: SpeechSynthesisVoice[] = window.speechSynthesis.getVoices();

  const speakNext = () => {
    if (generation !== speakGeneration) return;
    if (index >= cleaned.length) {
      opts?.onDone?.();
      return;
    }
    const text = cleaned[index];
    opts?.onProgress?.(index, cleaned.length);
    const utter = new SpeechSynthesisUtterance(text);
    utter.lang = lang;
    utter.rate = rate;
    const voice = pickVoice(voices, lang);
    if (voice) utter.voice = voice;
    utter.onend = () => {
      if (generation !== speakGeneration) return;
      index += 1;
      speakNext();
    };
    utter.onerror = () => {
      if (generation !== speakGeneration) return;
      index += 1;
      speakNext();
    };
    window.speechSynthesis.speak(utter);
  };

  void ensureVoicesLoaded().then((loaded) => {
    if (generation !== speakGeneration) return;
    voices = loaded.length ? loaded : window.speechSynthesis.getVoices();
    // Chrome 偶发 pause：恢复后再开播
    try {
      window.speechSynthesis.resume();
    } catch {
      /* ignore */
    }
    speakNext();
  });

  return {
    stop: () => {
      if (generation === speakGeneration) {
        speakGeneration += 1;
        window.speechSynthesis.cancel();
        opts?.onDone?.();
      }
    },
  };
}
