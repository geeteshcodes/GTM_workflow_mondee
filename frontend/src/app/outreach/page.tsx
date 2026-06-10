"use client";
import { useState, useEffect, useRef } from "react";
import {
  Send, MessageSquare, Mail, Link2, Zap, CheckCircle2,
  Clock, XCircle, Loader2, X, RefreshCw,
} from "lucide-react";
import { FaInstagram } from "react-icons/fa";
import { toast } from "sonner";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

// ─────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────

interface OutreachLead {
  id: string;
  business_name: string;
  category: string;
  score: number;
  score_tier: string;
  phone: string | null;
  email: string | null;
  linkedin_url: string | null;
  instagram: string | null;
  attempts: number;
  last_channel: string;
  last_status: string;
}

interface ChannelStat { channel: string; count: number; }

// ─────────────────────────────────────────────────────────────────
// CHANNEL CONFIG
// ─────────────────────────────────────────────────────────────────

const CHANNELS = [
  { id: "whatsapp", label: "WhatsApp",    description: "Send via Twilio",         icon: MessageSquare, color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", activeBg: "bg-emerald-500/20 border-emerald-400", field: "phone" },
  { id: "linkedin", label: "LinkedIn DM", description: "Send via Unipile",        icon: Link2,         color: "text-blue-400",   bg: "bg-blue-500/10 border-blue-500/30",       activeBg: "bg-blue-500/20 border-blue-400",       field: "linkedin_url" },
  { id: "email",    label: "Email",       description: "Send via SendGrid",        icon: Mail,          color: "text-amber-400",  bg: "bg-amber-500/10 border-amber-500/30",     activeBg: "bg-amber-500/20 border-amber-400",     field: "email" },
  { id: "instagram",label: "Instagram",   description: "Auto-discover via Tavily", icon: FaInstagram,  color: "text-pink-400",   bg: "bg-pink-500/10 border-pink-500/30",       activeBg: "bg-pink-500/20 border-pink-400",       field: "instagram" },
] as const;

// ─────────────────────────────────────────────────────────────────
// CHANNEL MODAL
// ─────────────────────────────────────────────────────────────────

function ChannelModal({ lead, onClose, onLaunch, launching }: {
  lead: OutreachLead | null;
  onClose: () => void;
  onLaunch: (partnerName: string | null, channels: string[], msg: string) => void;
  launching: boolean;
}) {
  const [selected, setSelected] = useState<string[]>(["whatsapp"]);
  const [message,  setMessage]  = useState("");
  const backdropRef = useRef<HTMLDivElement>(null);

  const toggle = (id: string) =>
    setSelected(prev => prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]);

  const isAvailable = (ch: typeof CHANNELS[number]) => {
    if (!lead) return true;
    if (ch.id === "instagram") return true;
    return !!(lead as any)[ch.field];
  };

  return (
    <div
      ref={backdropRef}
      onClick={e => e.target === backdropRef.current && onClose()}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-150"
    >
      <div className="bg-card border border-border rounded-2xl shadow-2xl w-full max-w-md mx-4 animate-in zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-border">
          <div>
            <h2 className="text-base font-bold flex items-center gap-2">
              <Zap size={16} className="text-primary" /> Launch Outreach Sequence
            </h2>
            {lead && (
              <p className="text-xs text-muted-foreground mt-0.5">
                {lead.business_name}
                <span className="ml-2 bg-secondary text-secondary-foreground px-1.5 py-0.5 rounded text-[10px] uppercase">{lead.category}</span>
              </p>
            )}
            {!lead && <p className="text-xs text-muted-foreground mt-0.5">All filtered leads (bulk)</p>}
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground p-1 rounded-md hover:bg-muted transition-colors">
            <X size={16} />
          </button>
        </div>

        {/* Channels */}
        <div className="p-5 space-y-3">
          <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider mb-3">
            Select channels — messages sent in this order
          </p>
          {CHANNELS.map(ch => {
            const Icon      = ch.icon;
            const active    = selected.includes(ch.id);
            const available = isAvailable(ch);
            const order     = selected.indexOf(ch.id) + 1;
            return (
              <button
                key={ch.id}
                onClick={() => available && toggle(ch.id)}
                disabled={!available}
                className={`w-full flex items-center gap-3 p-3 rounded-xl border transition-all text-left
                  ${active ? ch.activeBg : ch.bg}
                  ${!available ? "opacity-40 cursor-not-allowed" : "cursor-pointer hover:opacity-90"}`}
              >
                <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0 transition-all ${active ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
                  {active ? order : <div className="w-2 h-2 rounded-full bg-current opacity-40" />}
                </div>
                <Icon size={16} className={ch.color} />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-medium">{ch.label}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {available ? ch.description : (ch.id === "instagram" ? ch.description : `${ch.field} — not on record`)}
                  </div>
                </div>
                {active && <CheckCircle2 size={16} className="text-primary flex-shrink-0" />}
              </button>
            );
          })}
        </div>

        {/* Custom message */}
        <div className="px-5 pb-3">
          <label className="text-xs text-muted-foreground font-medium uppercase tracking-wider block mb-2">
            Custom message <span className="normal-case font-normal">(optional — leave blank to auto-generate)</span>
          </label>
          <textarea
            value={message}
            onChange={e => setMessage(e.target.value)}
            placeholder="Hi [Name], we'd love to explore a partnership…"
            rows={3}
            className="w-full bg-background border border-border rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-1 focus:ring-primary placeholder:text-muted-foreground/50"
          />
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-5 pt-3 border-t border-border">
          <span className="text-xs text-muted-foreground">
            {selected.length === 0 ? "Select at least one channel" : `${selected.length} channel${selected.length > 1 ? "s" : ""} selected`}
          </span>
          <div className="flex gap-2">
            <button onClick={onClose} className="px-4 py-2 rounded-lg text-sm border border-border hover:bg-muted transition-colors">
              Cancel
            </button>
            <button
              onClick={() => onLaunch(lead?.business_name ?? null, selected, message)}
              disabled={selected.length === 0 || launching}
              className="px-4 py-2 rounded-lg text-sm bg-primary text-primary-foreground font-bold hover:bg-primary/90 transition-colors disabled:opacity-50 flex items-center gap-2"
            >
              {launching ? <><Loader2 size={14} className="animate-spin" /> Launching…</> : <><Zap size={14} /> Launch</>}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────

export default function OutreachPage() {
  const [leads,        setLeads]        = useState<OutreachLead[]>([]);
  const [channels,     setChannels]     = useState<ChannelStat[]>([]);
  const [loading,      setLoading]      = useState(true);
  const [filter,       setFilter]       = useState("all");
  const [modalOpen,    setModalOpen]    = useState(false);
  const [selectedLead, setSelectedLead] = useState<OutreachLead | null>(null);
  const [launching,    setLaunching]    = useState(false);
  const [search,       setSearch]       = useState("");

  const fetchLeads = async () => {
    setLoading(true);
    try {
      const res  = await fetch(`${API_BASE}/api/outreach/`);
      const data = await res.json();
      setLeads(data.leads    || []);
      setChannels(data.channels || []);
    } catch {
      toast.error("Failed to load outreach data");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchLeads(); }, []);

  const openLeadModal = (lead: OutreachLead) => { setSelectedLead(lead); setModalOpen(true); };
  const openBulkModal = () => { setSelectedLead(null); setModalOpen(true); };

  const handleLaunch = async (partnerName: string | null, selectedChannels: string[], customMsg: string) => {
    setLaunching(true);
    const tid = "outreach-launch";
    toast.loading("Launching outreach sequence…", { id: tid });
    try {
      if (partnerName) {
        const res  = await fetch(`${API_BASE}/api/outreach/launch`, {
          method:  "POST",
          headers: { "Content-Type": "application/json" },
          body:    JSON.stringify({ partner_name: partnerName, channels: selectedChannels, custom_message: customMsg }),
        });
        const data = await res.json();
        toast.dismiss(tid);
        const summary = (data.results || []).map((r: any) => {
          const st  = r.result?.status ?? "unknown";
          const ico = st.includes("sent") || st.includes("found") ? "✅" : "⏭️";
          return `${ico} ${r.channel}: ${st}`;
        }).join("  |  ");
        toast.success(`Outreach launched for ${partnerName}`, { description: summary, duration: 6000 });
      } else {
        for (const lead of filteredLeads) {
          await fetch(`${API_BASE}/api/outreach/launch`, {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body:    JSON.stringify({ partner_name: lead.business_name, channels: selectedChannels, custom_message: customMsg }),
          });
        }
        toast.dismiss(tid);
        toast.success(`Bulk outreach launched for ${filteredLeads.length} leads`);
      }
      setModalOpen(false);
      fetchLeads();
    } catch {
      toast.error("Outreach launch failed", { id: tid });
    } finally {
      setLaunching(false);
    }
  };

  const channelIcon = (ch: string) => {
    const m: Record<string, React.ReactNode> = {
      whatsapp:  <MessageSquare size={14} className="text-emerald-400" />,
      email:     <Mail size={14} className="text-amber-400" />,
      linkedin:  <Link2 size={14} className="text-blue-400" />,
      instagram: <FaInstagram size={14} className="text-pink-400" />,
    };
    return m[ch?.toLowerCase()] || <Send size={14} />;
  };

  const statusIcon = (s: string) => {
    const sl = s?.toLowerCase() ?? "";
    if (sl.includes("sent") || sl.includes("responded") || sl.includes("delivered"))
      return <CheckCircle2 size={12} className="text-emerald-400" />;
    if (sl.includes("pending") || sl.includes("skipped"))
      return <Clock size={12} className="text-amber-400" />;
    return <XCircle size={12} className="text-destructive" />;
  };

  const filteredLeads = leads.filter(l => {
    if (filter === "responded" && !l.last_status.toLowerCase().includes("responded")) return false;
    if (filter === "no_reply"  &&  l.last_status.toLowerCase().includes("responded")) return false;
    if (search) {
      const t = search.toLowerCase();
      return l.business_name?.toLowerCase().includes(t) || l.category?.toLowerCase().includes(t);
    }
    return true;
  });

  return (
    <>
      {modalOpen && (
        <ChannelModal
          lead={selectedLead}
          onClose={() => setModalOpen(false)}
          onLaunch={handleLaunch}
          launching={launching}
        />
      )}

      <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-200">
        {/* Header */}
        <div className="flex justify-between items-center">
          <div>
            <h1 className="text-3xl font-bold flex items-center gap-3">
              <Send className="text-primary" /> Outreach Command
            </h1>
            <p className="text-sm text-muted-foreground mt-1">
              Multi-channel outreach: WhatsApp → LinkedIn → Email → Instagram
            </p>
          </div>
          <div className="flex gap-2">
            <button onClick={fetchLeads} className="border border-border bg-card hover:bg-muted p-2 rounded-lg transition-all">
              <RefreshCw size={14} />
            </button>
            <button
              onClick={openBulkModal}
              className="bg-primary hover:bg-primary/90 text-primary-foreground px-4 py-2 rounded-md font-bold text-sm flex items-center gap-2 transition-colors"
            >
              <Zap size={16} /> Launch Sequence
            </button>
          </div>
        </div>

        {/* Channel stats */}
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          {["whatsapp", "email", "linkedin", "voice", "instagram"].map(ch => {
            const stat = channels.find(c => c.channel === ch);
            return (
              <div key={ch} className="bg-card border border-border rounded-xl p-4 shadow-sm flex items-center gap-3">
                {channelIcon(ch)}
                <div>
                  <div className="text-xs text-muted-foreground capitalize">{ch}</div>
                  <div className="text-lg font-bold">{stat?.count || 0}</div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Table */}
        <div className="bg-card border border-border rounded-xl shadow-sm">
          <div className="p-4 border-b border-border flex justify-between items-center">
            <div className="flex items-center gap-3">
              <span className="font-bold">Outreach Ready ({filteredLeads.length})</span>
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search…"
                className="bg-background border border-border rounded-lg px-3 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-primary/50 w-40"
              />
            </div>
            <div className="flex gap-2 text-xs">
              {["all", "responded", "no_reply"].map(f => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`border border-border px-3 py-1.5 rounded transition-colors ${filter === f ? "bg-primary/20 text-primary font-bold" : "hover:bg-muted"}`}
                >
                  {f === "all" ? "All" : f === "responded" ? "Responded" : "No Reply"}
                </button>
              ))}
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground uppercase bg-background/30 border-b border-border">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Business</th>
                  <th className="px-4 py-3 text-left font-medium">Category</th>
                  <th className="px-4 py-3 text-left font-medium">Channels</th>
                  <th className="px-4 py-3 text-left font-medium">Last Channel</th>
                  <th className="px-4 py-3 text-left font-medium">Status</th>
                  <th className="px-4 py-3 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  Array.from({ length: 6 }).map((_, i) => (
                    <tr key={i}>
                      {Array.from({ length: 6 }).map((_, j) => (
                        <td key={j} className="px-4 py-3"><div className="h-4 shimmer rounded w-3/4" /></td>
                      ))}
                    </tr>
                  ))
                ) : filteredLeads.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center text-muted-foreground">
                      No outreach leads found. Run the pipeline to enrich partners first.
                    </td>
                  </tr>
                ) : filteredLeads.map(lead => (
                  <tr key={lead.id} className="hover:bg-muted/50 transition-colors group">
                    <td className="px-4 py-3 font-medium">{lead.business_name}</td>
                    <td className="px-4 py-3">
                      <span className="bg-secondary text-secondary-foreground text-[10px] px-1.5 py-0.5 rounded uppercase">{lead.category}</span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1.5">
                        {lead.phone    && <MessageSquare size={13} className="text-emerald-400" title="WhatsApp" />}
                        {lead.email    && <Mail size={13} className="text-amber-400" title="Email" />}
                        {lead.linkedin_url && <Link2 size={13} className="text-blue-400" title="LinkedIn" />}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1.5">{channelIcon(lead.last_channel)} {lead.last_channel}</span>
                    </td>
                    <td className="px-4 py-3">
                      <span className="flex items-center gap-1.5">{statusIcon(lead.last_status)} {lead.last_status}</span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-3 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => openLeadModal(lead)}
                          className="text-primary text-xs font-bold hover:underline flex items-center gap-1"
                        >
                          <Zap size={11} /> Launch
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
