"use client";
import { useState, useEffect } from "react";
import {
  BarChart3, TrendingUp, Target, Users, Send, Zap,
  CheckCircle2, RefreshCw, Clock,
} from "lucide-react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const CATEGORY_COLORS: Record<string, string> = {
  "Stays":        "#3b82f6",
  "Activities":   "#f59e0b",
  "Food":         "#ef4444",
  "Travel":       "#8b5cf6",
  "Wellness":     "#10b981",
  "Attractions":  "#06b6d4",
  "Uncategorised":"#6b7280",
};

function getColor(name: string) {
  return CATEGORY_COLORS[name] || `hsl(${Math.abs(name.charCodeAt(0) * 47) % 360}, 65%, 55%)`;
}

export default function AnalyticsPage() {
  const [data, setData]       = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const fetchData = async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/analytics/dashboard`);
      const d = await res.json();
      setData(d);
      setLastRefresh(new Date());
    } catch {
      if (!silent) toast.error("Failed to load analytics");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
    const t = setInterval(() => fetchData(true), 15000);
    return () => clearInterval(t);
  }, []);

  const stats  = data?.stats  || { total_leads: 0, discovered_today: 0, qualified: 0, outreach: 0, onboarding: 0, live: 0 };
  const funnel = data?.funnel || [];
  const cats   = data?.categories || [];
  const feed   = data?.activity_feed || [];
  const trends = data?.trends || {};
  const conv   = stats.total_leads > 0 ? ((stats.live / stats.total_leads) * 100).toFixed(1) : "0";

  return (
    <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex justify-between items-end">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <h1 className="text-3xl font-bold tracking-tight">Analytics</h1>
            <span className="flex items-center gap-1.5 bg-success/15 text-success text-[11px] font-bold px-2.5 py-1 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
              LIVE
            </span>
          </div>
          <p className="text-sm text-muted-foreground">Pipeline metrics · Auto-refreshes every 15s</p>
          {!data && !loading && <p className="text-destructive text-sm font-bold mt-2">⚠ Backend disconnected.</p>}
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-[11px] text-muted-foreground bg-muted/50 px-2.5 py-1 rounded-md">
              Updated {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button onClick={() => fetchData()} className="border border-border bg-card hover:bg-muted p-2 rounded-lg transition-all hover:scale-105 active:scale-95">
            <RefreshCw size={14} />
          </button>
        </div>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard title="Total"      value={stats.total_leads}      trend={trends.total_leads || "+0"}      icon={<Target size={18}/>}       color="text-blue-400"   bg="bg-blue-500/10" />
        <StatCard title="Discovery"  value={stats.discovered_today} trend={trends.discovered_today || "+0"} icon={<TrendingUp size={18}/>}   color="text-cyan-400"   bg="bg-cyan-500/10" />
        <StatCard title="Enriched"   value={stats.qualified}        trend={trends.qualified || "0%"}        icon={<CheckCircle2 size={18}/>} color="text-emerald-400" bg="bg-emerald-500/10" />
        <StatCard title="Outreach"   value={stats.outreach}         trend={trends.outreach || "0"}          icon={<Send size={18}/>}         color="text-amber-400"  bg="bg-amber-500/10" />
        <StatCard title="Onboarding" value={stats.onboarding}       trend={trends.onboarding || "—"}        icon={<Users size={18}/>}        color="text-violet-400" bg="bg-violet-500/10" />
        <StatCard title="Go-Live"    value={stats.live}             trend={trends.live || "+0"}             icon={<Zap size={18}/>}          color="text-green-400"  bg="bg-green-500/10" />
      </div>

      {/* Conversion highlight */}
      <div className="bg-gradient-to-r from-primary/10 via-primary/5 to-transparent border border-primary/20 rounded-xl p-5 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-primary/20 flex items-center justify-center">
            <TrendingUp size={22} className="text-primary" />
          </div>
          <div>
            <div className="text-sm font-medium text-muted-foreground">End-to-End Conversion</div>
            <div className="text-2xl font-bold">{conv}%</div>
          </div>
        </div>
        <div className="text-right">
          <div className="text-sm text-muted-foreground">Discovery → Go-Live</div>
          <div className="text-sm font-bold text-primary">{stats.total_leads.toLocaleString()} → {stats.live}</div>
        </div>
      </div>

      {/* Funnel + Categories */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-card border border-border rounded-xl p-6 shadow-sm">
          <div className="flex items-center justify-between mb-5">
            <div>
              <h2 className="text-lg font-bold">Pipeline Funnel</h2>
              <p className="text-xs text-muted-foreground mt-0.5">Lead progression across all stages</p>
            </div>
            <span className="text-[11px] bg-muted px-2 py-1 rounded-md text-muted-foreground font-medium">5 stages</span>
          </div>
          <div className="h-64 w-full">
            {loading ? (
              <div className="h-full shimmer rounded-lg" />
            ) : funnel.length > 0 ? (
              <CssFunnel data={funnel} />
            ) : (
              <div className="h-full flex items-center justify-center text-muted-foreground text-sm">No data yet — run the pipeline first.</div>
            )}
          </div>
        </div>

        <div className="bg-card border border-border rounded-xl p-6 shadow-sm flex flex-col">
          <div className="mb-5">
            <h2 className="text-lg font-bold">Categories</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Partner distribution by vertical</p>
          </div>
          <div className="flex-1 overflow-y-auto pr-1 space-y-2.5">
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="h-8 shimmer rounded" />
              ))
            ) : cats.length > 0 ? cats.map((cat: { name: string; count: number }) => {
              const max = Math.max(...cats.map((c: any) => c.count));
              const pct = max > 0 ? (cat.count / max) * 100 : 0;
              const color = getColor(cat.name);
              return (
                <div key={cat.name} className="group cursor-pointer">
                  <div className="flex items-center justify-between mb-1.5">
                    <div className="flex items-center gap-2">
                      <span className="w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: color }} />
                      <span className="text-sm font-medium group-hover:text-primary transition-colors">{cat.name}</span>
                    </div>
                    <span className="text-sm font-bold tabular-nums">{cat.count}</span>
                  </div>
                  <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all duration-700 ease-out" style={{ width: `${pct}%`, backgroundColor: color }} />
                  </div>
                </div>
              );
            }) : (
              <div className="text-muted-foreground text-sm">No category data.</div>
            )}
          </div>
        </div>
      </div>

      {/* Activity feed */}
      <div className="bg-card border border-border rounded-xl shadow-sm flex flex-col h-[360px]">
        <div className="p-5 pb-0">
          <div className="flex items-center justify-between mb-1">
            <h2 className="text-lg font-bold flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
              Live Activity Feed
            </h2>
            <span className="text-[11px] text-muted-foreground bg-muted px-2 py-1 rounded-md">{feed.length} events</span>
          </div>
          <p className="text-xs text-muted-foreground mb-4">Recent pipeline actions</p>
        </div>
        <div className="flex-1 overflow-y-auto px-5 pb-5 space-y-1">
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => <div key={i} className="h-12 shimmer rounded-lg" />)
          ) : feed.length > 0 ? feed.map((act: any, i: number) => (
            <div key={i} className="flex gap-3 py-2.5 border-b border-border/50 last:border-0 hover:bg-muted/30 rounded-lg px-2 transition-colors">
              <div className="w-9 h-9 shrink-0 bg-muted rounded-lg flex items-center justify-center text-base">{act.icon}</div>
              <div className="flex flex-col justify-center min-w-0">
                <span className="text-sm text-foreground leading-snug">{act.text}</span>
                <span className="text-[11px] text-muted-foreground flex items-center gap-1 mt-0.5">
                  <Clock size={10} /> {act.time}
                </span>
              </div>
            </div>
          )) : (
            <div className="flex items-center justify-center h-full text-muted-foreground text-sm">No activity yet.</div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Custom CSS Funnel (no Recharts FunnelChart needed) ─────────────────────
function CssFunnel({ data }: { data: { name: string; value: number; fill: string }[] }) {
  const max = Math.max(...data.map(d => d.value));
  return (
    <div className="flex flex-col justify-center gap-2 h-full py-2">
      {data.map((d, i) => {
        const pct = max > 0 ? (d.value / max) * 100 : 0;
        const indent = ((100 - pct) / 2).toFixed(1);
        return (
          <div key={d.name} className="flex items-center gap-3">
            <div className="w-24 text-right text-xs text-muted-foreground shrink-0">{d.name}</div>
            <div className="flex-1 relative h-7">
              <div
                className="h-full rounded transition-all duration-700 ease-out flex items-center justify-end pr-2"
                style={{
                  width: `${pct}%`,
                  marginLeft: `${indent}%`,
                  backgroundColor: d.fill,
                  opacity: 0.85,
                }}
              />
            </div>
            <div className="w-16 text-xs font-bold tabular-nums text-right shrink-0">
              {Number(d.value).toLocaleString()}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function StatCard({ title, value, trend, icon, color, bg }: any) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm flex flex-col gap-3 hover:shadow-md hover:border-primary/30 transition-all">
      <div className="flex justify-between items-start">
        <span className="text-[12px] font-medium text-muted-foreground uppercase tracking-wider">{title}</span>
        <div className={`w-8 h-8 rounded-lg ${bg} flex items-center justify-center ${color}`}>{icon}</div>
      </div>
      <div>
        <div className="text-2xl font-bold tabular-nums">{Number(value || 0).toLocaleString()}</div>
        <div className="text-[11px] text-muted-foreground mt-1">{trend}</div>
      </div>
    </div>
  );
}
