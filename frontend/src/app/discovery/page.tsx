"use client";
import { useState, useEffect } from "react";
import { Search, Database, Phone, Mail, Linkedin, Globe, RefreshCw } from "lucide-react";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

export default function DiscoveryPage() {
  const [leads, setLeads]       = useState<any[]>([]);
  const [total, setTotal]       = useState(0);
  const [loading, setLoading]   = useState(true);
  const [search, setSearch]     = useState("");
  const [category, setCategory] = useState("");

  const fetchLeads = async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search)   params.set("search",   search);
      if (category) params.set("category", category);
      params.set("limit", "200");
      const res  = await fetch(`${API_BASE}/api/discovery/?${params}`);
      const data = await res.json();
      setLeads(data.leads  || []);
      setTotal(data.total || 0);
    } catch {
      toast.error("Failed to load discovery data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLeads(); }, []);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-bold flex items-center gap-3">
            <Search className="text-primary" size={28} /> Discovery
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Partners with status &quot;Yet to Start&quot; — {total.toLocaleString()} total
          </p>
        </div>
        <button onClick={fetchLeads} className="border border-border bg-card hover:bg-muted p-2 rounded-lg transition-all">
          <RefreshCw size={14} />
        </button>
      </div>

      {/* Filters */}
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
        <input
          value={category}
          onChange={e => setCategory(e.target.value)}
          onKeyDown={e => e.key === "Enter" && fetchLeads()}
          placeholder="Category filter…"
          className="bg-card border border-border rounded-lg px-4 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary/50 w-52"
        />
        <button onClick={fetchLeads} className="bg-primary text-primary-foreground px-4 py-2 rounded-lg text-sm font-bold hover:bg-primary/90 transition-colors">
          Search
        </button>
      </div>

      {/* Table */}
      <div className="bg-card border border-border rounded-xl shadow-sm overflow-hidden">
        <div className="p-4 border-b border-border">
          <span className="font-bold">Discovery Pool ({leads.length})</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-xs text-muted-foreground uppercase bg-background/30 border-b border-border">
              <tr>
                <th className="px-4 py-3 text-left font-medium">Partner</th>
                <th className="px-4 py-3 text-left font-medium">Category</th>
                <th className="px-4 py-3 text-left font-medium">Subcategories</th>
                <th className="px-4 py-3 text-left font-medium">Region</th>
                <th className="px-4 py-3 text-left font-medium">Source</th>
                <th className="px-4 py-3 text-left font-medium">Website</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {loading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i}>
                    {Array.from({ length: 6 }).map((_, j) => (
                      <td key={j} className="px-4 py-3"><div className="h-4 shimmer rounded w-3/4" /></td>
                    ))}
                  </tr>
                ))
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-muted-foreground">No discovery leads found.</td>
                </tr>
              ) : leads.map((p, i) => (
                <tr key={i} className="hover:bg-muted/30 transition-colors">
                  <td className="px-4 py-3 font-medium">{p.partner_name || "—"}</td>
                  <td className="px-4 py-3">
                    <span className="bg-secondary text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded uppercase">{p.category || "—"}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-muted-foreground max-w-[200px] truncate">{p.subcategories || "—"}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">{p.region || "—"}</td>
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
