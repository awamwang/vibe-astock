import { useEffect, useRef, useState } from "react";
import { Swords, Play, Square, Save, CheckCircle2, Circle, AlertTriangle, RotateCcw } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { GlassCard } from "@/components/ui/GlassCard";
import { debateStream, type DebateStage } from "@/lib/agents";
import { addNote } from "@/lib/notes";
import { ApiError } from "@/lib/api";
import {
  clearDebateCache, loadDebateCache, saveDebateCache, type DebateStageBox,
} from "./stockCache";

// 多方用品牌橙、空方用蓝灰、主持用中性——刻意不用红绿，
// 免得和 A 股「红涨绿跌」撞车被读成涨跌信号。
const STAGE_TONE: Record<DebateStage, string> = {
  bull: "border-primary/50 bg-primary/[0.06]",
  bull_rebut: "border-primary/30 bg-primary/[0.03]",
  bear: "border-sky-500/40 bg-sky-500/[0.06]",
  bear_rebut: "border-sky-500/25 bg-sky-500/[0.03]",
  referee: "border-border bg-background/40",
};

const DOSSIER_HINT = "多空双方拿到的是同一份接口实时拉取的数据，谁也不能靠编数字赢。";

interface Props {
  code: string;
  name?: string;
}

export function DebatePanel({ code, name }: Props) {
  const c = code.trim();
  const [rounds, setRounds] = useState(1);
  const [running, setRunning] = useState(false);
  const [status, setStatus] = useState("");
  const [progress, setProgress] = useState<{ title: string; ok: boolean }[]>([]);
  const [missing, setMissing] = useState<string[]>([]);
  const [stages, setStages] = useState<DebateStageBox[]>([]);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [fromCache, setFromCache] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  // 切换标的：恢复该标的缓存；不自动开跑
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setRunning(false);
    setSaved(false);
    const cached = loadDebateCache(c);
    if (cached && cached.stages.length > 0) {
      setRounds(cached.rounds || 1);
      setStatus(cached.status || "已载入缓存结果");
      setProgress(cached.progress || []);
      setMissing(cached.missing || []);
      setStages(cached.stages);
      setError(cached.error || "");
      setFromCache(true);
    } else {
      setRounds(1);
      setStatus("");
      setProgress([]);
      setMissing([]);
      setStages([]);
      setError("");
      setFromCache(false);
    }
  }, [c]);

  // 进行中或完成后写缓存
  useEffect(() => {
    if (!/^\d{6}$/.test(c)) return;
    if (!stages.length && !progress.length && !status && !error) return;
    saveDebateCache({
      code: c,
      name,
      rounds,
      status,
      progress,
      missing,
      stages,
      error,
      finishedAt: stages.length > 0 && stages.every((s) => s.done) ? Date.now() : null,
    });
  }, [c, name, rounds, status, progress, missing, stages, error]);

  const resetUi = () => {
    setStatus(""); setProgress([]); setMissing([]); setStages([]); setError(""); setSaved(false); setFromCache(false);
  };

  async function start() {
    if (!/^\d{6}$/.test(c)) { setError("代码须为 6 位 A 股代码"); return; }
    resetUi();
    setRunning(true);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      await debateStream(c, rounds, {
        onStatus: setStatus,
        onDossierProgress: (title, ok, loaded, total) => {
          setStatus(`正在拉取客观事实底稿… ${loaded}/${total}`);
          setProgress((p) => [...p, { title, ok }]);
        },
        onDossierReady: (_sections, miss) => { setMissing(miss); setStatus("底稿就绪，辩论开始"); },
        onStageStart: (stage, label) =>
          setStages((s) => [...s, { stage, label, content: "", done: false }]),
        onDelta: (stage, text) =>
          setStages((s) => s.map((b) => (b.stage === stage && !b.done ? { ...b, content: b.content + text } : b))),
        onStageDone: (stage, _label, content) =>
          setStages((s) => s.map((b) => (b.stage === stage && !b.done ? { ...b, content, done: true } : b))),
        onError: (message, stage) => setError(stage ? `${stage}：${message}` : message),
      }, ctrl.signal);
      setStatus("辩论完成");
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") setStatus("已中止");
      else setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setRunning(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
    setRunning(false);
  }

  function reanalyze() {
    clearDebateCache(c);
    void start();
  }

  function save() {
    const body = stages.map((s) => `## ${s.label}\n\n${s.content}`).join("\n\n---\n\n");
    const label = name ? `${name}（${c}）` : c;
    addNote("多空辩论", `多空辩论 · ${label}`, body);
    setSaved(true);
  }

  const finished = stages.length > 0 && stages.every((s) => s.done);

  return (
    <div>
      <p className="mb-3 text-xs leading-relaxed text-muted-foreground">
        同一份客观数据，多方与空方各自立论、互相质疑，最后由中立主持归纳分歧点与验证清单——不给买卖结论。
      </p>

      <GlassCard>
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">股票代码</label>
            <input
              value={c}
              readOnly
              className="w-36 rounded-lg border border-border/60 bg-muted/30 px-3 py-2 font-mono text-sm text-foreground outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-muted-foreground">辩论深度</label>
            <select
              value={rounds}
              onChange={(e) => setRounds(Number(e.target.value))}
              disabled={running}
              className="rounded-lg border border-border/60 bg-background/60 px-3 py-2 text-sm outline-none focus:border-primary/60"
            >
              <option value={1}>一轮 · 各自陈述</option>
              <option value={2}>两轮 · 加交叉反驳</option>
            </select>
          </div>
          {running ? (
            <button type="button" onClick={stop}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-4 py-2 text-sm hover:text-destructive">
              <Square className="h-4 w-4" /> 中止
            </button>
          ) : (
            <>
              <button type="button" onClick={() => void start()}
                className="inline-flex items-center gap-1.5 rounded-lg bg-primary/90 px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary">
                <Play className="h-4 w-4" /> 开始辩论
              </button>
              {(fromCache || finished) && (
                <button type="button" onClick={reanalyze}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-3 py-2 text-sm text-muted-foreground hover:text-foreground">
                  <RotateCcw className="h-4 w-4" /> 重新分析
                </button>
              )}
            </>
          )}
          {finished && !running && (
            <button type="button" onClick={save} disabled={saved}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 px-4 py-2 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
              <Save className="h-4 w-4" /> {saved ? "已存入沉淀" : "存入沉淀"}
            </button>
          )}
        </div>

        {!running && !status && (
          <p className="mt-3 text-[11px] leading-relaxed text-muted-foreground/70">
            ⏱ {rounds === 2
              ? "两轮约 3 分钟 · 5 次模型调用 · 约 6 万字进上下文"
              : "一轮约 100 秒 · 3 次模型调用 · 约 3.5 万字进上下文"}
            （每个角色都会带上完整底稿）。拉底稿约 35 秒、走公开数据接口，不消耗 token。
            点「开始辩论」后才会真正拉取与分析。
          </p>
        )}

        {fromCache && !running && finished && (
          <p className="mt-2 text-[11px] text-muted-foreground/70">已显示本标的缓存结果，可改深度后重新分析。</p>
        )}

        {status && <p className="mt-3 text-xs text-muted-foreground">{status}</p>}
        {error && (
          <p className="mt-3 flex items-start gap-1.5 text-xs text-destructive">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {error}
          </p>
        )}

        {progress.length > 0 && (
          <div className="mt-4 border-t border-border/40 pt-3">
            <p className="mb-2 text-[11px] text-muted-foreground">{DOSSIER_HINT}</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {progress.map((p) => (
                <span key={p.title} className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  {p.ok
                    ? <CheckCircle2 className="h-3 w-3 text-primary/70" />
                    : <Circle className="h-3 w-3 text-muted-foreground/40" />}
                  {p.title}
                </span>
              ))}
            </div>
            {missing.length > 0 && (
              <p className="mt-2 text-[11px] text-warning">
                未取到：{missing.join("、")}（双方立论时不得臆测这部分）
              </p>
            )}
          </div>
        )}
      </GlassCard>

      <div className="mt-4 space-y-4">
        {stages.map((s) => (
          <div key={s.stage} className={`rounded-xl border p-4 ${STAGE_TONE[s.stage]}`}>
            <div className="mb-2 flex items-center gap-2">
              <Swords className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-semibold">{s.label}</span>
              {!s.done && <span className="animate-pulse text-[11px] text-muted-foreground">生成中…</span>}
            </div>
            <div className="prose prose-sm dark:prose-invert max-w-none text-foreground prose-table:text-sm">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{s.content || "…"}</ReactMarkdown>
            </div>
          </div>
        ))}
      </div>

      {stages.length === 0 && !running && (
        <GlassCard className="mt-4">
          <p className="py-6 text-center text-sm text-muted-foreground">
            选择辩论深度后点击「开始辩论」。结果会按标的缓存，下次打开可直接查看。
          </p>
        </GlassCard>
      )}
    </div>
  );
}
