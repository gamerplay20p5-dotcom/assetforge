import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Boxes, Cpu, Gauge, ImagePlus, Layers, ListChecks, LogOut, Moon, Pause, Play, Sparkles, Sun, Triangle } from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { api, getToken, setToken, useDownloadToken } from "./api";
import { Dashboard } from "./pages/Dashboard";
import { Generator } from "./pages/Generator";
import { Studio } from "./pages/Studio";
import { BatchStudio } from "./pages/BatchStudio";
import { QueueManager } from "./pages/QueueManager";
import { Library } from "./pages/Library";
import { WorkersManager } from "./pages/WorkersManager";
import { AiSettings } from "./pages/AiSettings";
import { Login } from "./pages/Login";

function useTheme() {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("assetforge.theme") ?? "dark";
    } catch {
      return "dark";
    }
  });
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem("assetforge.theme", theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))] as const;
}

/** Real-time updates: Server-Sent Events invalidate the cached queries they affect. */
function useLiveEvents(enabled: boolean) {
  const qc = useQueryClient();
  const token = useDownloadToken();
  const [live, setLive] = useState(false);
  useEffect(() => {
    if (!enabled || !token) return;
    const es = new EventSource(`/api/v1/events?token=${encodeURIComponent(token)}`);
    es.onopen = () => setLive(true);
    es.onerror = () => setLive(false);
    const handler = (e: MessageEvent) => {
      const type = (JSON.parse(e.data) as { type: string }).type;
      if (type.startsWith("job.") || type.startsWith("batch.") || type.startsWith("queue.")) {
        qc.invalidateQueries({ queryKey: ["jobs"] });
        qc.invalidateQueries({ queryKey: ["job"] });
        qc.invalidateQueries({ queryKey: ["batches"] });
        qc.invalidateQueries({ queryKey: ["summary"] });
        qc.invalidateQueries({ queryKey: ["queue"] });
      }
      if (type.startsWith("asset.")) {
        qc.invalidateQueries({ queryKey: ["assets"] });
        qc.invalidateQueries({ queryKey: ["asset"] });
        qc.invalidateQueries({ queryKey: ["summary"] });
      }
      if (type.startsWith("worker.")) qc.invalidateQueries({ queryKey: ["workers"] });
    };
    for (const t of ["job.created", "job.started", "job.succeeded", "job.failed", "job.cancelled", "job.cancelling", "job.requeued", "job.updated",
      "batch.created", "queue.paused", "queue.resumed", "asset.created", "asset.updated", "asset.version_created", "worker.registered", "worker.updated"]) {
      es.addEventListener(t, handler as EventListener);
    }
    return () => es.close();
  }, [enabled, token, qc]);
  return live;
}

const NAV = [
  { to: "/", label: "Imagem → 3D", icon: ImagePlus, end: true },
  { to: "/generator", label: "Procedural", icon: Sparkles },
  { to: "/library", label: "Biblioteca", icon: Boxes },
  { to: "/queue", label: "Fila", icon: ListChecks },
  { to: "/batch", label: "Lotes", icon: Layers },
  { to: "/workers", label: "Workers", icon: Cpu },
  { to: "/ai", label: "IA na nuvem", icon: Bot },
  { to: "/dashboard", label: "Painel", icon: Gauge },
];

export function App() {
  const [authed, setAuthed] = useState<boolean>(!!getToken());
  const [theme, toggleTheme] = useTheme();
  const flush = useLocation().pathname === "/";
  const qc = useQueryClient();
  useEffect(() => {
    const off = () => setAuthed(false);
    window.addEventListener("assetforge:logout", off);
    return () => window.removeEventListener("assetforge:logout", off);
  }, []);
  const live = useLiveEvents(authed);
  const queue = useQuery({ queryKey: ["queue"], queryFn: () => api<{ paused: boolean }>("/queue/state"), enabled: authed, refetchInterval: 8000 });
  const me = useQuery({ queryKey: ["me"], queryFn: () => api<{ username: string; role: string }>("/auth/me"), enabled: authed });

  if (!authed) {
    return (
      <Login
        onDone={() => {
          setAuthed(true);
          qc.clear();
        }}
      />
    );
  }
  const canOperate = me.data?.role === "admin" || me.data?.role === "operator";
  const togglePause = async () => {
    await api(queue.data?.paused ? "/queue/resume" : "/queue/pause", { method: "POST" });
    qc.invalidateQueries({ queryKey: ["queue"] });
  };
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Triangle size={15} fill="currentColor" />
          </div>
        </div>
        <nav className="nav">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => (isActive ? "active" : "")}>
              <Icon size={17} />
              <span className="label">{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">v0.1</div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span className="topbrand">AssetForge</span>
          <span className="pill" title="Atualizações em tempo real (SSE)">
            <span className={`dot ${live ? "ok" : "warn"}`} />
            {live ? "ao vivo" : "reconectando"}
          </span>
          <div className="spacer" />
          {canOperate && (
            <button onClick={togglePause} title="Pausar/retomar o despacho de novos jobs">
              {queue.data?.paused ? <Play size={14} /> : <Pause size={14} />}
              {queue.data?.paused ? "Fila pausada — retomar" : "Pausar despacho"}
            </button>
          )}
          <button className="icon ghost" onClick={toggleTheme} aria-label="Alternar tema">
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <span className="muted">{me.data?.username}</span>
          <button
            className="icon ghost"
            aria-label="Sair"
            onClick={() => {
              setToken(null);
              setAuthed(false);
            }}
          >
            <LogOut size={16} />
          </button>
        </header>
        <main className={`content ${flush ? "flush" : ""}`}>
          <Routes>
            <Route path="/" element={<Studio />} />
            <Route path="/image3d" element={<Navigate to="/" replace />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/generator" element={<Generator />} />
            <Route path="/batch" element={<BatchStudio />} />
            <Route path="/queue" element={<QueueManager />} />
            <Route path="/library" element={<Library />} />
            <Route path="/library/:assetId" element={<Library />} />
            <Route path="/workers" element={<WorkersManager />} />
            <Route path="/ai" element={<AiSettings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}
