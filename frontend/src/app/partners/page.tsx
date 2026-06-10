"use client";
import { useState, useEffect } from "react";
import { Users, Search, Globe, RefreshCw, ChevronDown } from "lucide-react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const STATUS_COLORS: Record<string, string> = {
  "Yet to Start":     "bg-muted text-muted-foreground",
  "Partner Outreach": "bg-amber-500/15 text-amber-400",
  "Onboarding":       "bg-blue-500/15 text-blue-400",
  "Fully Onboarded":  "bg-success/15 text-success",
  "Rejected":         "bg-destructive/15 text-destructive",
};

export default function PartnersPage() {
  const [partners, setPartners] = useState<any[]>([]);
  const [total, setTotal]       = useState(0);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState("");
  const [status, setStatus]     = useState("");
  const [category, setCategory] = useState("");

  const fetchPartners = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search)   params.set("search",   search);
      if (status)   params.set("status",   status);
      if (category) params.set("category", category);
      params.set("limit", "300");
      const res  = await fetch(`${API_BASE}/api/partners/?${params}`);
      const data = await res.json();
      setPartners(data.partners || []);
      setTotal(data.total || 0);
    } catch {
      toast.error("Failed to load partners");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchPartners(); }, []);

  const updateStatus = async (id: number, newStatus: string) => {
    try {
      await fetch(`${API_BASE}/api/partners/${id}/status`, {
        method:  "PATCH",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ status: newStatus }),
      });
      toast.success(`Status updated to "${newStatus}"`);
      fetchPartners();
    } catch {
      toast.error("Failed to update status");
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Users className="text-primary" size={28} /> All Partners
          </h1>
          <p className="text-sm text-muted-foreground mt-1">{total.toLocaleString()} total partners across Track 1 & Track 2</p>
        </div>
        <button onClick={fetchPartners} className="border border-border bg-card hover:bg-muted p-2 rounded-lg transition-all">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            onKeyDown={e => e.key === "Enter" && fetchPartners()}
            placeholder="Search partner name…"
            className="bg-card border border-border rounded-lg pl-8 pr-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-52"
          />
        </div>
        <select
          value={status}
          onChange={e => { setStatus(e.target.value); }}
          className="bg-card border border-border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 appearance-none pr-8"
        >
          <option value="">All Statuses</option>
          <option value="Yet to Start">Yet to Start</option>
          <option value="Partner Outreach">Partner Outreach</option>
          <option value="Onboarding">Onboarding</option>
          <option value="Fully Onboarded">Fully Onboarded</option>
          <option value="Rejected">Rejected</option>
        </select>
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchPartners()}
          placeholder="Category…"
          className="bg-card border border-border rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-40"
        />
        <button onClick={fetchPartners} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-bold hover:bg-primary/90 transition-colors">
          Filter
        </button>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
        <div className="p-4 border-b border-border">
          <span className="font-bold">Partners ({partners.length})</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground uppercase bg-background/30 border-b border-border">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Partner</th>
                <th className="px-4 py-3 text-left font-medium">Category</th>
                <th className="px-4 py-3 text-left font-medium">Region</th>
                <th className="px-4 py-3 text-left font-medium">Digitisation</th>
                <th className="px-4 py-3 text-left font-medium">Status</th>
                <th className="px-4 py-3 text-left font-medium">Source</th>
                <th className="px-4 py-3 text-left font-medium">Website</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading ? (
                Array.from({ length: 10 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 7 }).map((_, j) => (
                      <td key={j} className="px-4 py-3"><div className="h-4 shimmer rounded w-3/4" /></td>
                    ))}
                  </tr>
                ))
              ) : partners.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-muted-foreground">No partners found.</td>
                </tr>
              ) : partners.map((p, i) => (
                <tr key={i} className="hover:bg-muted/30 transition-colors group">
                  <td className="px-4 py-3 font-medium">{p.partner_name || "—"}</td>
                  <td className="px-4 py-3">
                    <span className="bg-secondary text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded uppercase">{p.category || "—"}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{p.region || "—"}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{p.digitisation || "—"}</td>
                  <td className="px-4 py-3">
                    <div className="relative group/status">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold cursor-pointer ${STATUS_COLORS[p.status] || "bg-muted text-muted-foreground"}`}>
                        {p.status || "—"}
                      </span>
                      {/* Status dropdown on hover */}
                      <div className="absolute top-full left-0 mt-1 z-20 bg-card border border-border rounded-lg shadow-xl py-1 hidden group-hover/status:block min-w-[160px]">
                        {["Yet to Start", "Partner Outreach", "Onboarding", "Fully Onboarded", "Rejected"].map(s => (
                          <button
                            key={s}
                            onClick={() => updateStatus(p.id, s)}
                            className="w-full text-left px-3 py-1.5 text-xs hover:bg-primary/10 hover:text-primary transition-colors"
                          >
                            {s}
                          </button>
                        ))}
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className={`text-[10px] px-2 py-0.5 rounded-full font-bold ${p.sheet_source === "track1" ? "bg-blue-500/15 text-blue-400" : "bg-purple-500/15 text-purple-400"}`}>
                      {p.sheet_source || "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {p.website ? (
                      <a href={p.website.startsWith("http") ? p.website : `https://${p.website}`} target="_blank" rel="noopener noreferrer" className="text-primary text-xs hover:underline flex items-center gap-1">
                        <Globe size={11} /> {p.website.replace(/^https?:\/\//, "").split("/")[0]}
                      </a>
                    ) : "—"}
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
