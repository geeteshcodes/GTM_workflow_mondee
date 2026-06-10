"use client";
import { useState, useEffect } from "react";
import { Database, Phone, Mail, Linkedin, RefreshCw, Search } from "lucide-react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export default function EnrichmentPage() {
  const [leads, setLeads]   = useState<any[]>([]);
  const [stats, setStats]   = useState<any>({ total: 0, verified: 0, pending: 0, phone_count: 0, email_count: 0, linkedin_count: 0 });
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const fetchLeads = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set("search", search);
      params.set("limit", "200");
      const res  = await fetch(`${API_BASE}/api/enrichment/?${params}`);
      const data = await res.json();
      setLeads(data.leads || []);
      setStats(data.stats || {});
    } catch {
      toast.error("Failed to load enrichment data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLeads(); }, []);

  const total = stats.total || 0;

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Database className="text-primary" size={28} /> Enrichment
          </h1>
          <p className="text-sm text-muted-foreground mt-1">Partners with at least one contact detail resolved</p>
        </div>
        <button onClick={fetchLeads} className="border border-border bg-card hover:bg-muted p-2 rounded-lg transition-all">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Stats cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Enriched" value={total} color="text-blue-400" bg="bg-blue-500/10" />
        <StatCard label="Phone Found"    value={stats.phone_count   || 0} color="text-emerald-400" bg="bg-emerald-500/10" sub={total > 0 ? `${Math.round((stats.phone_count || 0) / total * 100)}%` : "—"} />
        <StatCard label="Email Found"    value={stats.email_count   || 0} color="text-amber-400"   bg="bg-amber-500/10"   sub={total > 0 ? `${Math.round((stats.email_count || 0) / total * 100)}%` : "—"} />
        <StatCard label="LinkedIn Found" value={stats.linkedin_count || 0} color="text-blue-400"   bg="bg-blue-500/10"    sub={total > 0 ? `${Math.round((stats.linkedin_count || 0) / total * 100)}%` : "—"} />
      </div>

      {/* Search */}
      <div className="flex gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && fetchLeads()}
            placeholder="Search partner name…"
            className="w-full bg-card border border-border rounded-lg pl-8 pr-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
          />
        </div>
        <button onClick={fetchLeads} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-bold hover:bg-primary/90 transition-colors">
          Search
        </button>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
        <div className="p-4 border-b border-border flex items-center justify-between">
          <span className="font-bold">Enriched Partners ({leads.length})</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground uppercase bg-background/30 border-b border-border">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Partner</th>
                <th className="px-4 py-3 text-left font-medium">Category</th>
                <th className="px-4 py-3 text-left font-medium">Region</th>
                <th className="px-4 py-3 text-center font-medium">Phone</th>
                <th className="px-4 py-3 text-center font-medium">Email</th>
                <th className="px-4 py-3 text-center font-medium">LinkedIn</th>
                <th className="px-4 py-3 text-left font-medium">Fill %</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3"><div className="h-4 shimmer rounded w-3/4" /></td>
                    ))}
                  </tr>
                ))
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">
                    No enriched partners yet. Run the pipeline first.
                  </td>
                </tr>
              ) : leads.map((p, i) => (
                <tr key={i} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3 font-medium">{p.partner_name || "—"}</td>
                  <td className="px-4 py-3">
                    <span className="bg-secondary text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded uppercase">
                      {p.category || "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{p.region || "—"}</td>
                  <td className="px-4 py-3 text-center">
                    {p.has_phone
                      ? <Phone size={13} className="text-emerald-400 mx-auto" title={p.phone_number} />
                      : <span className="text-muted-foreground/30 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {p.has_email
                      ? <Mail size={13} className="text-amber-400 mx-auto" title={p.email_id} />
                      : <span className="text-muted-foreground/30 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3 text-center">
                    {p.has_linkedin
                      ? <a href={p.linkedin_profile} target="_blank" rel="noopener noreferrer" title={p.linkedin_profile}><Linkedin size={13} className="text-blue-400 mx-auto" /></a>
                      : <span className="text-muted-foreground/30 text-xs">—</span>}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 w-16 bg-muted rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-primary transition-all duration-500"
                          style={{ width: `${p.fill_rate || 0}%` }}
                        />
                      </div>
                      <span className="text-xs text-muted-foreground">{p.fill_rate || 0}%</span>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color, bg, sub }: any) {
  return (
    <div className="bg-card border border-border rounded-xl p-4 shadow-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{label}</span>
        <div className={`w-7 h-7 rounded-lg ${bg} ${color} flex items-center justify-center`}>
          <Database size={13} />
        </div>
      </div>
      <div className="text-2xl font-bold tabular-nums">{Number(value || 0).toLocaleString()}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1">{sub} fill rate</div>}
    </div>
  );
}
