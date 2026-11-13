const API = import.meta.env.VITE_API_URL || "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) }
  });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || body.error || message;
    } catch { /* keep fallback */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export type GraphNode = {
  id: string;
  node_type: string;
  label?: string;
  title?: string;
  normalized_claim?: string;
  original_text?: string;
  sentence?: string;
  source_paper_id?: string;
  relationship?: string;
  similarity?: number;
  strength?: number | string;
  reason?: string;
  [key: string]: unknown;
};

export type GraphEdge = {
  id?: string;
  source: string | { id: string };
  target: string | { id: string };
  relationship?: string;
  [key: string]: unknown;
};

export type Dashboard = {
  available: boolean;
  stats: { papers: number; claims: number; evidence: number; relationships: number; supported_links: number };
  node_types: Record<string, number>;
  papers: GraphNode[];
  insights: Record<string, unknown>;
  report: Record<string, unknown>;
  updated_at: string | null;
};

export type Claim = GraphNode & {
  paper_title: string;
  evidence: GraphNode[];
  evidence_count: number;
};

export type Job = {
  id: string;
  topic: string;
  status: "queued" | "running" | "completed" | "failed";
  stage: string;
  progress: number;
  message: string;
  error?: string;
  result?: Record<string, unknown>;
};

export const api = {
  health: () => request<{ status: string; graph_available: boolean }>("/api/health"),
  dashboard: () => request<Dashboard>("/api/dashboard"),
  graph: () => request<{ nodes: GraphNode[]; edges: GraphEdge[]; total_nodes: number; total_edges: number }>("/api/graph"),
  papers: (search = "") => request<{ items: GraphNode[]; total: number }>(`/api/papers?search=${encodeURIComponent(search)}`),
  claims: (search = "", relationship = "all") => request<{ items: Claim[]; total: number }>(`/api/claims?search=${encodeURIComponent(search)}&relationship=${relationship}`),
  startResearch: (topic: string, max_results: number) => request<Job>("/api/research", {
    method: "POST", body: JSON.stringify({ topic, max_results })
  }),
  job: (id: string) => request<Job>(`/api/jobs/${id}`)
};