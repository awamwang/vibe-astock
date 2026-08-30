import type { ReactNode } from "react";
import {
  BookOpen, Bug, ExternalLink, Github, Info, Mail, MessageSquarePlus, Sparkles,
} from "lucide-react";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";

const APP_VERSION = "v0.1.3";
const REPO_URL = "https://github.com/awamwang/vibe-astock";
const ISSUES_URL = `${REPO_URL}/issues`;
const NEW_ISSUE_URL = `${REPO_URL}/issues/new`;

const ORIGINAL_AUTHOR = {
  name: "Simon 林",
  github: "https://github.com/simonlin1212",
  x: "https://x.com/linsizhen",
  xHandle: "@linsizhen",
  repo: "https://github.com/simonlin1212/Vibe-Astock",
};

const MAINTAINER = {
  name: "AwamMWang",
  github: "https://github.com/awamwang",
  bilibili: "https://space.bilibili.com/345916320",
  email: "wangnew2013@126.com",
};

function SectionTitle({
  icon: Icon,
  title,
  hint,
}: {
  icon: typeof Info;
  title: string;
  hint?: string;
}) {
  return (
    <div className="mb-4 flex items-start gap-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary/15 text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p>}
      </div>
    </div>
  );
}

function LinkRow({
  href,
  label,
  desc,
  icon: Icon,
  external = true,
}: {
  href: string;
  label: string;
  desc?: string;
  icon: typeof Github;
  external?: boolean;
}) {
  return (
    <a
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
      className="group flex items-center gap-3 rounded-xl border border-border/60 bg-muted/20 px-3.5 py-3 transition-colors hover:border-primary/40 hover:bg-primary/5"
    >
      <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-background/60 text-muted-foreground transition-colors group-hover:text-primary">
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-sm font-medium text-foreground">
          {label}
          {external && (
            <ExternalLink className="h-3 w-3 text-muted-foreground/70 opacity-0 transition-opacity group-hover:opacity-100" />
          )}
        </div>
        {desc && <p className="mt-0.5 truncate text-xs text-muted-foreground">{desc}</p>}
      </div>
    </a>
  );
}

function ContactChip({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex items-center gap-1.5 rounded-lg border border-border/60 bg-background/40 px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:text-primary"
    >
      {children}
    </a>
  );
}

export function About() {
  return (
    <div>
      <PageHeader
        title="关于项目"
        subtitle="版本说明、仓库地址与反馈渠道"
      />

      <div className="space-y-5">
        {/* 版本简介 */}
        <GlassCard>
          <SectionTitle icon={Sparkles} title="版本简介" hint="当前构建与产品定位" />
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-md bg-primary/15 px-2.5 py-1 text-xs font-semibold text-primary">
              {APP_VERSION}
            </span>
            <span className="text-xs text-muted-foreground">A 股短线工具</span>
          </div>
          <p className="mt-4 text-sm leading-relaxed text-foreground/90">
            Vibe-Astock 面向短线盯盘、操作与复盘：做好数据获取与处理、风险控制，
            并逐步做出色的荐股与量化能力。AI 用于把多路盘面与消息串成可读叙述，
            硬指标层以计算直出，辅助日常决策与复盘。
          </p>
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
            本页展示的为当前发行说明。文档链接区暂留空，后续会补齐使用说明与开发文档入口。
          </p>
        </GlassCard>

        {/* 文档 */}
        <GlassCard>
          <SectionTitle icon={BookOpen} title="文档" hint="使用说明与开发文档（暂未挂载）" />
          <div className="rounded-xl border border-dashed border-border/70 bg-muted/10 px-4 py-8 text-center">
            <p className="text-sm text-muted-foreground">文档链接暂空</p>
            <p className="mt-1 text-xs text-muted-foreground/70">后续将在此放置用户手册、教学大纲与架构说明入口</p>
          </div>
        </GlassCard>

        {/* 仓库与反馈 */}
        <GlassCard>
          <SectionTitle
            icon={Github}
            title="仓库与反馈"
            hint="源码、建议与 Bug 请走 GitHub Issues"
          />
          <div className="grid gap-2.5 sm:grid-cols-1 md:grid-cols-3">
            <LinkRow
              href={REPO_URL}
              icon={Github}
              label="项目仓库"
              desc="awamwang/vibe-astock"
            />
            <LinkRow
              href={NEW_ISSUE_URL}
              icon={Bug}
              label="提交 Bug / 建议"
              desc="打开 New Issue（最便捷）"
            />
            <LinkRow
              href={ISSUES_URL}
              icon={MessageSquarePlus}
              label="查看已有 Issues"
              desc="搜索后再提，避免重复"
            />
          </div>
          <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 px-4 py-3">
            <p className="text-sm font-medium text-foreground">推荐反馈方式</p>
            <ol className="mt-2 list-decimal space-y-1.5 pl-4 text-xs leading-relaxed text-muted-foreground">
              <li>
                打开{" "}
                <a href={NEW_ISSUE_URL} target="_blank" rel="noreferrer" className="text-primary hover:underline">
                  New Issue
                </a>
                ，选 Bug / Feature 并写清复现步骤或期望行为
              </li>
              <li>标题尽量具体（页面、操作、期望结果）；可附截图或控制台报错</li>
              <li>提之前先在 Issues 列表搜一下，减少重复单</li>
            </ol>
          </div>
        </GlassCard>

        {/* 作者与维护 */}
        <GlassCard>
          <SectionTitle icon={Info} title="作者与维护" hint="原作者与本仓库维护者" />
          <div className="grid gap-4 md:grid-cols-2">
            <div className="rounded-xl border border-border/60 bg-muted/15 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-muted-foreground/70">
                原作者 / 上游项目
              </div>
              <div className="mt-2 text-base font-semibold">{ORIGINAL_AUTHOR.name}</div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Vibe-Astock 原项目作者。本仓库在其工作基础上继续演进。
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <ContactChip href={ORIGINAL_AUTHOR.github}>
                  <Github className="h-3 w-3" /> GitHub
                </ContactChip>
                <ContactChip href={ORIGINAL_AUTHOR.x}>
                  X {ORIGINAL_AUTHOR.xHandle}
                </ContactChip>
                <ContactChip href={ORIGINAL_AUTHOR.repo}>
                  上游仓库
                </ContactChip>
              </div>
            </div>

            <div className="rounded-xl border border-primary/25 bg-primary/5 p-4">
              <div className="text-[11px] font-medium uppercase tracking-[0.14em] text-primary/80">
                本仓库维护
              </div>
              <div className="mt-2 text-base font-semibold">{MAINTAINER.name}</div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                当前 fork 维护者。功能建议与缺陷反馈优先走上方 GitHub Issues。
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <ContactChip href={MAINTAINER.github}>
                  <Github className="h-3 w-3" /> GitHub
                </ContactChip>
                <ContactChip href={MAINTAINER.bilibili}>
                  B 站空间
                </ContactChip>
                <ContactChip href={`mailto:${MAINTAINER.email}`}>
                  <Mail className="h-3 w-3" /> {MAINTAINER.email}
                </ContactChip>
              </div>
            </div>
          </div>
        </GlassCard>

        <p className="pb-2 text-center text-[11px] text-muted-foreground/60">
          {APP_VERSION} · AI 生成 · 仅供参考 · 非投资建议
        </p>
      </div>
    </div>
  );
}
