import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import ForceGraph2D from "react-force-graph-2d";
import {
  Activity, ArrowDownRight, ArrowRight, Atom, BookOpen, BrainCircuit, Check,
  ChevronDown, CircleHelp, Clock3, Command, Download, ExternalLink, FileText,
  Filter, FlaskConical, GitBranch, Layers3, LoaderCircle, Network, Plus,
  Search, ShieldCheck, Sparkles, X, Zap
} from "lucide-react";
import { api, type Claim, type Dashboard, type GraphEdge, type GraphNode, type Job } from "./api";

type Page = "overview" | "graph" | "papers" | "claims";
const stages = [
  ["retrieval", "Paper retrieval"], ["claims", "Claim extraction"], ["evidence", "Evidence analysis"],
  ["linking", "Evidence linking"], ["graph", "Knowledge graph"]
];

function App() {
  const [page, setPage] = useState<Page>("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [health, setHealth] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [topic, setTopic] = useState("");
  const [paperCount, setPaperCount] = useState(5);
  const [job, setJob] = useState<Job | null>(null);
  const [search, setSearch] = useState("");
  const [papers, setPapers] = useState<GraphNode[]>([]);
  const [claims, setClaims] = useState<Claim[]>([]);
  const [relationship, setRelationship] = useState("all");
  const [graph, setGraph] = useState<{nodes: GraphNode[]; edges: GraphEdge[]}>({nodes:[],edges:[]});
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [graphType, setGraphType] = useState("all");
  const [showResearch, setShowResearch] = useState(false);
  const graphRef = useRef<any>(null);

  const refreshDashboard = useCallback(async () => {
    try {
      const [d, h] = await Promise.all([api.dashboard(), api.health()]);
      setDashboard(d); setHealth(h.status === "ok"); setError("");
    } catch (e) { setError(e instanceof Error ? e.message : "Could not connect to Alethia API."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void refreshDashboard(); }, [refreshDashboard]);

  useEffect(() => {
    if (!job || !["queued", "running"].includes(job.status)) return;
    const timer = window.setInterval(async () => {
      try {
        const updated = await api.job(job.id);
        setJob(updated);
        if (updated.status === "completed") {
          await refreshDashboard();
          setPage("overview");
        }
      } catch (e) { setError(e instanceof Error ? e.message : "Could not read job status."); }
    }, 1800);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, refreshDashboard]);

  useEffect(() => {
    if (page === "papers") api.papers(search).then(r => setPapers(r.items)).catch(e => setError(e.message));
    if (page === "claims") api.claims(search, relationship).then(r => setClaims(r.items)).catch(e => setError(e.message));
    if (page === "graph") api.graph().then(r => setGraph({nodes:r.nodes, edges:r.edges})).catch(e => setError(e.message));
  }, [page, search, relationship]);

  const startResearch = async (event: FormEvent) => {
    event.preventDefault();
    if (topic.trim().length < 3) return;
    try {
      setError("");
      const created = await api.startResearch(topic.trim(), paperCount);
      setJob(created); setShowResearch(false);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not start investigation."); }
  };

  const activeJob = job && ["queued", "running"].includes(job.status) ? job : null;
  const title = {overview:"Research overview", graph:"Knowledge graph", papers:"Research papers", claims:"Claims & evidence"}[page];
  const filteredGraph = useMemo(() => {
    const nodes = graph.nodes.filter(n => graphType === "all" || n.node_type === graphType);
    const ids = new Set(nodes.map(n => n.id));
    const endpoint = (value: GraphEdge["source"]) => typeof value === "string" ? value : value.id;
    const edges = graph.edges.filter(edge => ids.has(endpoint(edge.source)) && ids.has(endpoint(edge.target)));
    return { nodes, edges };
  }, [graph, graphType]);

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><Atom size={21}/></div><div><span className="brand-name">alethia</span><span className="brand-caption">RESEARCH INTELLIGENCE</span></div></div>
      <div className="workspace-label">WORKSPACE</div>
      <nav className="nav-list">
        <button className={page==="overview"?"nav-item active":"nav-item"} onClick={()=>setPage("overview")}><Layers3 size={17}/> Overview</button>
        <button className={page==="graph"?"nav-item active":"nav-item"} onClick={()=>setPage("graph")}><Network size={17}/> Knowledge graph <span className="nav-count">{dashboard?.stats.relationships ?? "—"}</span></button>
        <button className={page==="papers"?"nav-item active":"nav-item"} onClick={()=>setPage("papers")}><BookOpen size={17}/> Research papers <span className="nav-count">{dashboard?.stats.papers ?? "—"}</span></button>
        <button className={page==="claims"?"nav-item active":"nav-item"} onClick={()=>setPage("claims")}><GitBranch size={17}/> Claims & evidence <span className="nav-count">{dashboard?.stats.claims ?? "—"}</span></button>
      </nav>
      <div className="sidebar-bottom">
        <div className="system-card"><div className="system-heading"><span className={health?"status-dot":"status-dot offline"}/><span>System status</span></div><strong>{health?"API connected":"API disconnected"}</strong><p>{dashboard?.available?"Knowledge graph loaded":"Waiting for graph data"}</p></div>
        <div className="sidebar-footer"><div className="avatar">HA</div><div><strong>Research workspace</strong><span>Personal instance</span></div><ChevronDown size={15}/></div>
      </div>
    </aside>

    <main className="main-area">
      <header className="topbar">
        <div className="breadcrumb"><span>Workspace</span><span className="slash">/</span><strong>{title}</strong></div>
        <div className="top-actions"><div className="connection"><span className={health?"status-dot":"status-dot offline"}/>{health?"Connected":"Disconnected"}</div><button className="icon-button" title="Help"><CircleHelp size={17}/></button><button className="new-button" onClick={()=>setShowResearch(true)}><Plus size={16}/> New investigation</button></div>
      </header>

      <div className="page-content">
        {error && <div className="error-banner"><X size={16}/>{error}<button onClick={()=>setError("")}><X size={15}/></button></div>}
        {activeJob && <div className="job-banner"><div className="job-icon"><LoaderCircle size={18}/></div><div className="job-copy"><strong>Investigating: {activeJob.topic}</strong><span>{activeJob.message}</span><div className="progress-track"><i style={{width:`${activeJob.progress}%`}}/></div></div><strong className="job-percent">{activeJob.progress}%</strong></div>}
        {job?.status==="failed" && <div className="error-banner"><X size={16}/><span>Investigation failed: {job.error}</span><button onClick={()=>setJob(null)}><X size={15}/></button></div>}
        {page==="overview" && <Overview dashboard={dashboard} loading={loading} onNew={()=>setShowResearch(true)} onNavigate={setPage}/>}
        {page==="graph" && <GraphPage graph={filteredGraph} selected={selectedNode} setSelected={setSelectedNode} graphType={graphType} setGraphType={setGraphType} graphRef={graphRef}/>}
        {page==="papers" && <PapersPage papers={papers} search={search} setSearch={setSearch}/>}
        {page==="claims" && <ClaimsPage claims={claims} search={search} setSearch={setSearch} relationship={relationship} setRelationship={setRelationship}/>}
      </div>
    </main>

    {showResearch && <div className="modal-backdrop" onMouseDown={e=>{if(e.target===e.currentTarget)setShowResearch(false);}}>
      <form className="research-modal" onSubmit={startResearch}>
        <div className="modal-top"><div className="modal-icon"><Sparkles size={20}/></div><button type="button" className="icon-button" onClick={()=>setShowResearch(false)}><X size={18}/></button></div>
        <div className="eyebrow">START AN INVESTIGATION</div><h2>What are you researching?</h2><p className="modal-description">Alethia will retrieve papers from arXiv, extract scientific claims, analyze evidence, and build a connected knowledge graph.</p>
        <label className="field-label" htmlFor="topic">Research topic</label>
        <div className="topic-input"><Search size={17}/><input id="topic" autoFocus value={topic} onChange={e=>setTopic(e.target.value)} placeholder="e.g. Retrieval-augmented generation in LLMs" minLength={3} required/></div>
        <div className="field-row"><div><label className="field-label" htmlFor="paper-count">Papers to retrieve</label><select id="paper-count" value={paperCount} onChange={e=>setPaperCount(Number(e.target.value))}>{[2,3,5,7,10].map(n=><option key={n} value={n}>{n} papers</option>)}</select></div><div className="runtime-note"><ShieldCheck size={16}/><span>Uses your configured<br/>OpenRouter + Ollama models</span></div></div>
        <div className="pipeline-preview"><span>PIPELINE</span><div>{["arXiv","Claims","Evidence","Knowledge graph"].map((s,i)=><div key={s}><i>{i+1}</i>{s}{i!==3&&<ArrowRight size={12}/>}</div>)}</div></div>
        <button className="new-button modal-submit" type="submit" disabled={topic.trim().length<3}><Sparkles size={16}/> Run investigation</button>
        <p className="modal-footnote">A research run may take several minutes. Only one run can execute at a time.</p>
      </form>
    </div>}
  </div>;
}

function Overview({dashboard,loading,onNew,onNavigate}:{dashboard:Dashboard|null;loading:boolean;onNew:()=>void;onNavigate:(p:Page)=>void}) {
  const stats = dashboard?.stats;
  const metricCards = [
    {label:"Research papers",value:stats?.papers,icon:BookOpen,sub:"Retrieved publications"},
    {label:"Scientific claims",value:stats?.claims,icon:BrainCircuit,sub:"Extracted & normalized"},
    {label:"Evidence passages",value:stats?.evidence,icon:ShieldCheck,sub:"Analyzed evidence"},
    {label:"Graph relationships",value:stats?.relationships,icon:GitBranch,sub:"Connected entities"}
  ];
  return <div className="overview-page">
    <div className="welcome-row"><div><div className="eyebrow">YOUR RESEARCH, CONNECTED</div><h1>Make sense of the <em>literature.</em></h1><p>Turn scattered scientific papers into structured, traceable knowledge.</p></div><button className="new-button" onClick={onNew}><Plus size={16}/> New investigation</button></div>
    <section className="metrics-grid">{metricCards.map(({label,value,icon:Icon,sub})=><div className="metric-card" key={label}><div className="metric-top"><span>{label}</span><Icon size={17}/></div><strong>{loading?"—":(value??0).toLocaleString()}</strong><small>{sub}</small></div>)}</section>
    <section className="overview-grid">
      <div className="panel research-panel"><div className="panel-heading"><div><span className="eyebrow">RESEARCH WORKFLOW</span><h2>Start with a question.</h2></div><span className="live-label"><span className="status-dot"/> READY</span></div><p>Explore a topic across arXiv. Alethia will extract claims, find supporting passages, classify evidence, and connect findings across papers.</p><div className="workflow-steps">{[{n:"01",t:"Retrieve",d:"Find relevant papers",icon:Search},{n:"02",t:"Analyze",d:"Extract claims & evidence",icon:FlaskConical},{n:"03",t:"Connect",d:"Build a knowledge graph",icon:Network}].map(({n,t,d,icon:Icon})=><div className="workflow-step" key={n}><span>{n}</span><Icon size={17}/><strong>{t}</strong><small>{d}</small></div>)}</div><button className="text-action" onClick={onNew}>Create an investigation <ArrowRight size={15}/></button></div>
      <div className="panel graph-summary"><div className="panel-heading"><div><span className="eyebrow">KNOWLEDGE MAP</span><h2>Connected knowledge</h2></div><button className="subtle-button" onClick={()=>onNavigate("graph")}>Explore <ArrowRight size={14}/></button></div><MiniNetwork/><div className="graph-summary-footer"><div><strong>{stats?.relationships??0}</strong><span>relationships</span></div><div><strong>{stats?.papers??0}</strong><span>source papers</span></div><div><strong>{stats?.claims??0}</strong><span>claims</span></div></div></div>
    </section>
    <section className="panel recent-panel"><div className="panel-heading"><div><span className="eyebrow">YOUR LIBRARY</span><h2>Research papers</h2></div><button className="subtle-button" onClick={()=>onNavigate("papers")}>View all <ArrowRight size={14}/></button></div>
      {dashboard?.papers?.length ? <div className="recent-list">{dashboard.papers.slice(0,5).map((paper,i)=><div className="recent-item" key={paper.id}><div className="paper-icon"><FileText size={17}/></div><div className="recent-info"><strong>{String(paper.title||paper.label||`Research paper ${i+1}`)}</strong><span>{String(paper.arxiv_id? `arXiv:${paper.arxiv_id}` : paper.source_pdf||"Imported research paper")}</span></div><span className="type-pill">PAPER</span><ArrowDownRight size={15}/></div>)}</div> : <div className="empty-state"><BookOpen size={24}/><strong>No research papers yet</strong><span>Run your first investigation to start building your library.</span><button className="text-action" onClick={onNew}>Start exploring <ArrowRight size={14}/></button></div>}
    </section>
    <div className="disclaimer"><ShieldCheck size={15}/><span>AI-generated classifications are research aids, not scientific verification. Always inspect the original papers and evidence.</span></div>
  </div>;
}

function MiniNetwork() {
  return <div className="mini-network"><svg viewBox="0 0 480 175" role="img" aria-label="Illustrative connected research graph">
    <g stroke="#4a563f" strokeWidth="1.1" opacity=".8"><path d="M240 82L118 43L55 112L168 145L240 82L355 35L425 100L310 145L240 82"/><path d="M118 43L168 145M355 35L310 145M55 112L240 82M425 100L240 82"/></g>
    {[{x:240,y:82,r:13,c:"#c8e67a"},{x:118,y:43,r:8,c:"#8ea66a"},{x:55,y:112,r:6,c:"#687d58"},{x:168,y:145,r:7,c:"#c8e67a"},{x:355,y:35,r:8,c:"#8ea66a"},{x:425,y:100,r:6,c:"#687d58"},{x:310,y:145,r:7,c:"#a8c56e"}].map((n,i)=><circle key={i} cx={n.x} cy={n.y} r={n.r} fill={n.c} opacity=".9"/>)}
    <circle cx="240" cy="82" r="24" fill="none" stroke="#c8e67a" opacity=".17"/><circle cx="240" cy="82" r="34" fill="none" stroke="#c8e67a" opacity=".08"/>
  </svg><span className="network-caption">PAPERS <i/> CLAIMS <i/> EVIDENCE</span></div>;
}

function GraphPage({graph,selected,setSelected,graphType,setGraphType,graphRef}:{graph:{nodes:GraphNode[];edges:GraphEdge[]};selected:GraphNode|null;setSelected:(n:GraphNode|null)=>void;graphType:string;setGraphType:(v:string)=>void;graphRef:any}) {
  const data = useMemo(()=>({nodes:graph.nodes.map(n=>({...n,name:String(n.normalized_claim||n.title||n.label||n.id),group:n.node_type})),links:graph.edges.map(e=>({source:typeof e.source==="string"?e.source:e.source.id,target:typeof e.target==="string"?e.target:e.target.id,relationship:e.relationship}))}),[graph]);
  const colors:Record<string,string>={paper:"#d8e8a0",claim:"#a8c57a",evidence:"#91a9c6",method:"#d9ad78",concept:"#bd9bdd",model:"#df8f88"};
  return <div className="section-page"><div className="section-intro"><div><div className="eyebrow">EXPLORE RELATIONSHIPS</div><h1>Knowledge graph</h1><p>Navigate the entities and evidence links extracted from your research.</p></div><div className="graph-controls"><select value={graphType} onChange={e=>setGraphType(e.target.value)}><option value="all">All entities</option>{["paper","claim","evidence","method","concept","model","dataset","algorithm"].map(t=><option value={t} key={t}>{t[0].toUpperCase()+t.slice(1)}s</option>)}</select><button className="subtle-button" onClick={()=>graphRef.current?.zoomToFit(500,50)}>Fit graph</button></div></div>
    <div className="graph-layout"><div className="graph-canvas"><div className="canvas-label"><span className="live-label"><span className="status-dot"/> INTERACTIVE GRAPH</span><span>{graph.nodes.length} nodes · {graph.edges.length} links</span></div>{data.nodes.length?<ForceGraph2D ref={graphRef} graphData={data} backgroundColor="#0d120f" nodeRelSize={5} nodeColor={(n:any)=>colors[n.group]||"#9aa59a"} nodeLabel={(n:any)=>n.name} linkColor={()=>"#596550"} linkWidth={.7} linkDirectionalArrowLength={3} linkDirectionalArrowRelPos={1} onNodeClick={(node:any)=>setSelected(node as GraphNode)} cooldownTicks={90} d3AlphaDecay={0.03} d3VelocityDecay={0.3} />:<div className="graph-empty"><Network size={28}/><strong>No graph data available</strong><span>Complete an investigation to build your knowledge graph.</span></div>}</div>
      <aside className="node-panel">{selected?<><div className="node-panel-head"><span className="eyebrow">SELECTED ENTITY</span><button className="icon-button" onClick={()=>setSelected(null)}><X size={16}/></button></div><span className="type-pill">{selected.node_type}</span><h3>{String(selected.normalized_claim||selected.title||selected.label||selected.id)}</h3><p>{String(selected.normalized_claim||selected.sentence||selected.original_text||"No additional description available.")}</p><div className="detail-list">{Object.entries(selected).filter(([k,v])=>!["id","label","normalized_claim","sentence","original_text","name","x","y","vx","vy","index"].includes(k)&&v!==""&&v!==null&&typeof v!=="object").slice(0,12).map(([k,v])=><div key={k}><span>{k.replace(/_/g," ")}</span><strong>{String(v)}</strong></div>)}</div></>:<div className="node-placeholder"><Network size={23}/><strong>Explore the graph</strong><span>Select any node to inspect its research details and source information.</span></div>}</aside></div>
    <div className="graph-legend">{Object.entries(colors).map(([k,c])=><span key={k}><i style={{background:c}}/>{k}</span>)}</div>
  </div>;
}

function PapersPage({papers,search,setSearch}:{papers:GraphNode[];search:string;setSearch:(v:string)=>void}) {
  return <div className="section-page"><div className="section-intro"><div><div className="eyebrow">SOURCE LIBRARY</div><h1>Research papers</h1><p>Publications retrieved and processed by Alethia.</p></div><span className="result-count">{papers.length} PAPERS</span></div><div className="search-bar"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search titles, authors or arXiv IDs..."/><Filter size={16}/></div>
    {papers.length?<div className="paper-grid">{papers.map((p,i)=><article className="paper-card" key={p.id}><div className="paper-card-top"><div className="paper-icon"><FileText size={18}/></div><span className="type-pill">ARXIV</span></div><h3>{String(p.title||p.label||`Research paper ${i+1}`)}</h3><p>{String(p.abstract||p.summary||"No abstract was stored for this publication.")}</p><div className="paper-meta"><span>{String(p.arxiv_id||p.source_pdf||"Source metadata unavailable")}</span><span>{String(p.publication_year||"")}</span></div>{Boolean(p.pdf_url)&&<a href={String(p.pdf_url)} target="_blank" rel="noreferrer">Open paper <ExternalLink size={13}/></a>}</article>)}</div>:<div className="empty-state large"><BookOpen size={28}/><strong>No papers found</strong><span>Try another search or run a new investigation.</span></div>}
  </div>;
}

function ClaimsPage({claims,search,setSearch,relationship,setRelationship}:{claims:Claim[];search:string;setSearch:(v:string)=>void;relationship:string;setRelationship:(v:string)=>void}) {
  const [selected,setSelected]=useState<Claim|null>(null);
  useEffect(()=>{setSelected(null)},[search,relationship]);
  return <div className="section-page"><div className="section-intro"><div><div className="eyebrow">EVIDENCE EXPLORER</div><h1>Claims & evidence</h1><p>Inspect extracted scientific statements and the passages linked to them.</p></div><span className="result-count">{claims.length} CLAIMS</span></div><div className="filter-row"><div className="search-bar"><Search size={17}/><input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search scientific claims..."/></div><select value={relationship} onChange={e=>setRelationship(e.target.value)}><option value="all">All relationships</option><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="insufficient">Insufficient</option><option value="irrelevant">Irrelevant</option></select></div>
    <div className="claims-layout"><div className="claim-list">{claims.map(claim=><button key={claim.id} className={selected?.id===claim.id?"claim-row selected":"claim-row"} onClick={()=>setSelected(claim)}><div className="claim-row-top"><span className="type-pill">{String(claim.claim_type||"claim")}</span><span>{claim.evidence_count} evidence</span></div><strong>{String(claim.normalized_claim||claim.original_text||claim.label||"Scientific claim")}</strong><small>{claim.paper_title}</small></button>)}{!claims.length&&<div className="empty-state"><BrainCircuit size={25}/><strong>No claims found</strong><span>Claims will appear here after a research run.</span></div>}</div>
      <div className="evidence-detail">{selected?<><div className="eyebrow">CLAIM DETAIL</div><h3>{String(selected.normalized_claim||selected.original_text||selected.label)}</h3><div className="claim-source"><BookOpen size={14}/>{selected.paper_title}</div><div className="evidence-heading"><strong>Linked evidence</strong><span>{selected.evidence.length} passages</span></div>{selected.evidence.map((ev,i)=><div className="evidence-card" key={ev.id||i}><div className="evidence-card-head"><span className={`relationship-pill ${String(ev.relationship)}`}>{String(ev.relationship)}</span><span>Similarity {typeof ev.similarity==="number"?Math.round(ev.similarity*100)+"%":"—"}</span></div><p>“{String(ev.sentence||ev.label||"Evidence passage unavailable.")}”</p><small>{String(ev.reason||"No model explanation was stored.")}</small></div>)}{!selected.evidence.length&&<div className="empty-inline">No evidence passages are linked to this claim.</div>}</>:<div className="node-placeholder"><GitBranch size={24}/><strong>Select a claim</strong><span>Choose a statement to inspect its linked evidence passages.</span></div>}</div></div>
  </div>;
}

export default App;