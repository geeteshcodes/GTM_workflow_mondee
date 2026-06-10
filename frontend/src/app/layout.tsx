import type { Metadata } from "next";
import { Syne, DM_Sans } from "next/font/google";
import "./globals.css";
import { Toaster } from "sonner";
import Link from "next/link";
import {
  LayoutDashboard,
  Search,
  Database,
  Send,
  Users,
  BarChart3,
  Zap,
  Settings,
} from "lucide-react";

const syne   = Syne({   subsets: ["latin"], variable: "--font-syne" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });

export const metadata: Metadata = {
  title: "GTM UAE Pipeline",
  description: "Agentic Partner Acquisition Pipeline — Discovery · Enrichment · Outreach",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className={`${syne.variable} ${dmSans.variable} font-sans bg-background text-foreground flex h-screen overflow-hidden`}>

        {/* ── Sidebar ────────────────────────────────────────────────── */}
        <aside className="w-64 border-r border-border bg-card flex flex-col shrink-0">
          {/* Logo */}
          <div className="p-6 flex items-center gap-3 border-b border-border">
            <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
              <Zap className="text-primary w-4 h-4" fill="currentColor" />
            </div>
            <div>
              <span className="font-display font-bold text-sm tracking-tight block">GTM UAE</span>
              <span className="text-[10px] text-muted-foreground">Partner Pipeline</span>
            </div>
          </div>

          {/* Nav */}
          <nav className="flex-1 overflow-y-auto p-4 space-y-1 text-sm font-medium">
            <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest px-3 pb-2 pt-1">Pipeline</p>
            <NavItem href="/"           icon={<Zap size={16} />}           label="Run Pipeline"  />
            <NavItem href="/discovery"  icon={<Search size={16} />}        label="Discovery"     />
            <NavItem href="/enrichment" icon={<Database size={16} />}      label="Enrichment"    />
            <NavItem href="/outreach"   icon={<Send size={16} />}          label="Outreach"      />

            <p className="text-[10px] text-muted-foreground font-bold uppercase tracking-widest px-3 pb-2 pt-4">Data</p>
            <NavItem href="/partners"   icon={<Users size={16} />}         label="All Partners"  />
            <NavItem href="/analytics"  icon={<BarChart3 size={16} />}     label="Analytics"     />
          </nav>

          {/* Footer */}
          <div className="p-4 border-t border-border">
            <NavItem href="/settings" icon={<Settings size={16} />} label="Settings" />
            <div className="mt-4 flex items-center gap-3 px-3">
              <div className="w-7 h-7 rounded-full bg-primary/20 flex items-center justify-center text-primary text-xs font-bold">CM</div>
              <div className="flex flex-col">
                <span className="text-xs font-bold">CMO Profile</span>
                <span className="text-[10px] text-muted-foreground">Admin</span>
              </div>
            </div>
          </div>
        </aside>

        {/* ── Main ───────────────────────────────────────────────────── */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Top bar */}
          <header className="h-14 border-b border-border bg-card/50 backdrop-blur flex items-center px-6 gap-4 shrink-0">
            <div className="flex-1" />
            <span className="flex items-center gap-1.5 bg-success/15 text-success text-[11px] font-bold px-2.5 py-1 rounded-full">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
              LIVE
            </span>
            <span className="text-xs text-muted-foreground">GTM UAE Pipeline v1.0</span>
          </header>

          {/* Page content */}
          <main className="flex-1 overflow-y-auto p-6 bg-background/50">
            {children}
          </main>
        </div>

        <Toaster theme="dark" position="top-right" />
      </body>
    </html>
  );
}

function NavItem({ href, icon, label, badge }: { href: string; icon: React.ReactNode; label: string; badge?: number }) {
  return (
    <Link
      href={href}
      className="flex items-center justify-between px-3 py-2 rounded-md hover:bg-primary/10 hover:text-primary transition-colors text-muted-foreground group"
    >
      <div className="flex items-center gap-3">
        {icon}
        <span>{label}</span>
      </div>
      {badge && (
        <span className="bg-primary/20 text-primary text-[10px] font-bold px-2 py-0.5 rounded-full">{badge}</span>
      )}
    </Link>
  );
}
