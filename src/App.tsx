import { useState, useEffect, useRef, useCallback } from "react";
import {
  Brain, Zap, FileText, Trash2, Send, AlertTriangle,
  CheckCircle2, XCircle, ChevronDown, ChevronUp, User, Bot, Loader2, Database, Plus, X,
} from "lucide-react";
import {
  fetchCustomers, fetchBrief, seedMemory,
  fetchMemories, forgetMemory, streamChat, addCustomer,
  type Customer, type MemoryItem,
} from "@/lib/api";

interface Message {
  role: "customer" | "agent";
  text: string;
  sentiment?: string;
  commitments?: any[];
  issueType?: string | null;
  fixApplied?: string | null;
  outcome?: string | null;
  memories?: any[];
  degraded?: boolean;
  model?: string | null;
  followup?: boolean;
  streaming?: boolean;
}

const SUGGESTED_MESSAGES: Record<string, string[]> = {
  "00000000-0000-4000-8000-000000000001": [
    "The webhook issue is back again. We're seeing the same delivery failures as last time.",
    "Can you check if our signing token needs to be rotated again?",
    "We're really frustrated — this is the third time this has happened.",
  ],
  "00000000-0000-4000-8000-000000000002": [
    "I was charged twice again for this billing period.",
    "Can you send me the corrected invoice?",
    "I need to talk to someone about my billing.",
  ],
  "00000000-0000-4000-8000-000000000003": [
    "SSO is sending our team back to the login screen again.",
    "We just rotated our certificates and now nobody can log in.",
    "Can someone check our SSO configuration?",
  ],
};

const sentimentColors: Record<string, string> = {
  frustrated: "bg-red-500/15 text-red-400 border-red-500/30",
  anxious: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  confused: "bg-blue-500/15 text-blue-400 border-blue-500/30",
  satisfied: "bg-green-500/15 text-green-400 border-green-500/30",
  neutral: "bg-gray-700 text-gray-400 border-gray-600",
};

const sentimentDots: Record<string, string> = {
  frustrated: "bg-red-500",
  anxious: "bg-amber-500",
  confused: "bg-blue-500",
  satisfied: "bg-green-500",
  neutral: "bg-gray-400",
};

function App() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [memoryOn, setMemoryOn] = useState(true);
  const [showTransparency, setShowTransparency] = useState(true);
  const [showBrief, setShowBrief] = useState(false);
  const [brief, setBrief] = useState<any>(null);
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [seeding, setSeeding] = useState(false);
  const [seedStatus, setSeedStatus] = useState<string | null>(null);
  const [degraded, setDegraded] = useState(false);
  const [showAddCustomer, setShowAddCustomer] = useState(false);
  const [newCustomer, setNewCustomer] = useState({ name: "", company: "", plan: "Starter", email: "", integrations: "" });
  const [followupPending, setFollowupPending] = useState(false);

  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    fetchCustomers().then(setCustomers).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const loadCustomerData = useCallback(async (customer: Customer) => {
    setSelectedCustomer(customer);
    setMessages([]);
    setError(null);
    setDegraded(false);
    setMemories([]);
    setBrief(null);
    setShowBrief(false);
    setSeedStatus(null);
    try {
      const mems = await fetchMemories(customer.id);
      setMemories(mems);
    } catch (e) {
      console.error("Failed to load customer data:", e);
    }
  }, []);

  const handleSend = async () => {
    if (!input.trim() || !selectedCustomer || loading) return;
    const text = input.trim();
    setInput("");
    setError(null);
    setDegraded(false);

    const customerMsg: Message = { role: "customer", text };
    const agentMsg: Message = { role: "agent", text: "", streaming: true };
    setMessages((prev) => [...prev, customerMsg, agentMsg]);
    setLoading(true);

    abortRef.current = streamChat(
      selectedCustomer.id,
      text,
      memoryOn,
      new Date().toISOString(),
      (event, data) => {
        if (event === "token") {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) last.text += data.text ?? "";
            return next;
          });
        } else if (event === "citations") {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) last.memories = data.memories;
            return next;
          });
        } else if (event === "degraded") {
          setDegraded(true);
        } else if (event === "done") {
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) {
              last.text = data.reply ?? "";
              last.sentiment = data.sentiment;
              last.commitments = data.commitments;
              last.issueType = data.issue_type;
              last.fixApplied = data.fix_applied;
              last.outcome = data.outcome;
              last.memories = data.recalled_memories;
              last.degraded = data.degraded;
              last.model = data.model;
              last.streaming = false;
            }
            return next;
          });
          if (data.degraded) setDegraded(true);
          if (selectedCustomer) fetchMemories(selectedCustomer.id).then(setMemories);
        } else if (event === "followup_pending") {
          setFollowupPending(true);
        } else if (event === "followup_token") {
          setFollowupPending(false);
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.role === "agent" && last.followup) {
              last.text += data.text ?? "";
            } else {
              next.push({ role: "agent", text: data.text ?? "", streaming: true, followup: true });
            }
            return next;
          });
        } else if (event === "followup_done") {
          setFollowupPending(false);
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.followup) {
              last.text = data.reply ?? "";
              last.streaming = false;
            }
            return next;
          });
          if (selectedCustomer) fetchMemories(selectedCustomer.id).then(setMemories);
        } else if (event === "error") {
          setError(data.error || "The agent request failed.");
          setMessages((prev) => {
            const next = [...prev];
            const last = next[next.length - 1];
            if (last && last.streaming) {
              last.text = "I'm having trouble connecting right now. Please try again.";
              last.streaming = false;
            }
            return next;
          });
        }
      },
      (err) => setError(err),
      () => setLoading(false)
    );
  };

  const handleSeed = async () => {
    if (!selectedCustomer) return;
    setSeeding(true);
    setSeedStatus(null);
    try {
      const count = await seedMemory(selectedCustomer.id);
      setSeedStatus(`Loaded ${count} case notes into memory`);
      const mems = await fetchMemories(selectedCustomer.id);
      setMemories(mems);
    } catch (e: any) {
      setSeedStatus(`Failed: ${e.message}`);
    }
    setSeeding(false);
  };

  const handleForget = async () => {
    if (!selectedCustomer) return;
    await forgetMemory(selectedCustomer.id);
    setMemories([]);
    setSeedStatus("Memory wiped for this customer");
  };

  const handleBrief = async () => {
    if (!selectedCustomer) return;
    const b = await fetchBrief(selectedCustomer.id);
    setBrief(b);
    setShowBrief(true);
  };

  const handleAddCustomer = async () => {
    if (!newCustomer.name.trim() || !newCustomer.company.trim()) return;
    try {
      const created = await addCustomer({
        name: newCustomer.name,
        company: newCustomer.company,
        plan: newCustomer.plan,
        email: newCustomer.email || `${newCustomer.name.toLowerCase().replace(/\s+/g, ".")}@${newCustomer.company.toLowerCase().replace(/\s+/g, "")}.com`,
        integrations: newCustomer.integrations ? newCustomer.integrations.split(",").map((s) => s.trim()) : [],
      });
      setCustomers((prev) => [...prev, created]);
      setShowAddCustomer(false);
      setNewCustomer({ name: "", company: "", plan: "Starter", email: "", integrations: "" });
      loadCustomerData(created);
    } catch (e: any) {
      setError(e.message);
    }
  };

  const formatDate = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  };

  const getInitials = (name: string) => name.split(" ").map((n) => n[0]).join("").slice(0, 2);

  return (
    <div className="h-screen flex flex-col bg-[#0f1117] text-gray-100 overflow-hidden">
      {/* Header */}
      <header className="flex-shrink-0 border-b border-gray-800 bg-[#16181f] px-6 py-3">
        <div className="flex items-center justify-between max-w-7xl mx-auto">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-teal-400 to-cyan-600 flex items-center justify-center">
              <Brain className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-semibold text-white">Echo</h1>
              <p className="text-xs text-gray-500">Memory-first AI customer support</p>
            </div>
          </div>
          <button
            onClick={() => setMemoryOn(!memoryOn)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${
              memoryOn
                ? "bg-teal-500/15 text-teal-400 border border-teal-500/30"
                : "bg-gray-800 text-gray-500 border border-gray-700"
            }`}
          >
            <Zap className="w-4 h-4" />
            {memoryOn ? "Memory ON" : "Memory OFF"}
          </button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden max-w-7xl mx-auto w-full">
        {/* Sidebar */}
        <aside className="w-64 flex-shrink-0 border-r border-gray-800 bg-[#16181f] flex flex-col overflow-hidden">
          <div className="p-4 border-b border-gray-800">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Customers</h2>
              <button
                onClick={() => setShowAddCustomer(!showAddCustomer)}
                className="text-gray-500 hover:text-teal-400 transition-colors"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>

            {/* Add customer form */}
            {showAddCustomer && (
              <div className="mb-3 p-3 bg-gray-800/50 rounded-lg border border-gray-700 flex flex-col gap-2">
                <input
                  type="text"
                  placeholder="Name"
                  value={newCustomer.name}
                  onChange={(e) => setNewCustomer({ ...newCustomer, name: e.target.value })}
                  className="bg-gray-800 text-sm text-gray-100 placeholder-gray-600 rounded px-2.5 py-1.5 border border-gray-700 focus:border-teal-500/50 focus:outline-none"
                />
                <input
                  type="text"
                  placeholder="Company"
                  value={newCustomer.company}
                  onChange={(e) => setNewCustomer({ ...newCustomer, company: e.target.value })}
                  className="bg-gray-800 text-sm text-gray-100 placeholder-gray-600 rounded px-2.5 py-1.5 border border-gray-700 focus:border-teal-500/50 focus:outline-none"
                />
                <select
                  value={newCustomer.plan}
                  onChange={(e) => setNewCustomer({ ...newCustomer, plan: e.target.value })}
                  className="bg-gray-800 text-sm text-gray-100 rounded px-2.5 py-1.5 border border-gray-700 focus:border-teal-500/50 focus:outline-none"
                >
                  <option>Starter</option>
                  <option>Growth</option>
                  <option>Business</option>
                  <option>Enterprise</option>
                </select>
                <input
                  type="text"
                  placeholder="Integrations (comma-separated)"
                  value={newCustomer.integrations}
                  onChange={(e) => setNewCustomer({ ...newCustomer, integrations: e.target.value })}
                  className="bg-gray-800 text-sm text-gray-100 placeholder-gray-600 rounded px-2.5 py-1.5 border border-gray-700 focus:border-teal-500/50 focus:outline-none"
                />
                <div className="flex gap-2">
                  <button
                    onClick={handleAddCustomer}
                    className="flex-1 text-sm bg-teal-500 hover:bg-teal-400 text-white rounded px-2 py-1.5 transition-colors"
                  >
                    Add
                  </button>
                  <button
                    onClick={() => setShowAddCustomer(false)}
                    className="text-sm bg-gray-700 hover:bg-gray-600 text-gray-300 rounded px-2 py-1.5 transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}

            <div className="flex flex-col gap-1 max-h-48 overflow-y-auto">
              {customers.map((c) => (
                <button
                  key={c.id}
                  onClick={() => loadCustomerData(c)}
                  className={`text-left p-2.5 rounded-lg transition-all ${
                    selectedCustomer?.id === c.id
                      ? "bg-teal-500/10 border border-teal-500/20"
                      : "hover:bg-gray-800 border border-transparent"
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold ${
                      selectedCustomer?.id === c.id ? "bg-teal-500/20 text-teal-300" : "bg-gray-700 text-gray-400"
                    }`}>
                      {getInitials(c.name)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium text-gray-200 truncate">{c.name}</p>
                      <p className="text-xs text-gray-500 truncate">{c.company} · {c.plan}</p>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* Memory management */}
          {selectedCustomer && (
            <div className="p-4 border-b border-gray-800">
              <div className="flex items-center gap-2 mb-3">
                <Database className="w-3.5 h-3.5 text-gray-500" />
                <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Memory</h2>
              </div>
              <div className="flex flex-col gap-2">
                <button
                  onClick={handleSeed}
                  disabled={seeding}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors disabled:opacity-50"
                >
                  {seeding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Database className="w-3.5 h-3.5" />}
                  Load ticket history
                </button>
                <button
                  onClick={handleForget}
                  className="flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm bg-gray-800 hover:bg-red-900/30 text-gray-400 hover:text-red-400 transition-colors"
                >
                  <Trash2 className="w-3.5 h-3.5" />
                  Forget all
                </button>
                {seedStatus && <p className="text-xs text-gray-500 mt-1">{seedStatus}</p>}
              </div>
              <div className="mt-3">
                <p className="text-xs text-gray-600 mb-1.5">{memories.length} memories stored</p>
                <div className="max-h-28 overflow-y-auto flex flex-col gap-1">
                  {memories.slice(-4).map((m) => (
                    <div key={m.id} className="text-xs text-gray-500 bg-gray-800/50 rounded px-2 py-1.5 line-clamp-2">
                      {m.text}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Brief button */}
          {selectedCustomer && (
            <div className="p-4">
              <button
                onClick={handleBrief}
                className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm bg-gray-800 hover:bg-gray-700 text-gray-300 transition-colors"
              >
                <FileText className="w-3.5 h-3.5" />
                Handoff brief
              </button>
            </div>
          )}
        </aside>

        {/* Main chat area */}
        <main className="flex-1 flex flex-col overflow-hidden">
          {selectedCustomer ? (
            <>
              {/* Customer context bar */}
              <div className="flex-shrink-0 border-b border-gray-800 bg-[#16181f] px-6 py-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h2 className="text-base font-semibold text-white">{selectedCustomer.name}</h2>
                    <p className="text-xs text-gray-500">
                      {selectedCustomer.company} · {selectedCustomer.plan} plan
                      {selectedCustomer.integrations.length > 0 && ` · ${selectedCustomer.integrations.join(", ")}`}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    {degraded && (
                      <div className="flex items-center gap-1.5 px-3 py-1 rounded-full bg-amber-500/10 border border-amber-500/20">
                        <AlertTriangle className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-xs text-amber-400">Memory degraded</span>
                      </div>
                    )}
                    <button
                      onClick={() => setShowTransparency(!showTransparency)}
                      className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs transition-all ${
                        showTransparency
                          ? "bg-teal-500/15 text-teal-400 border border-teal-500/20"
                          : "bg-gray-800 text-gray-500 border border-gray-700"
                      }`}
                    >
                      <Brain className="w-3.5 h-3.5" />
                      Transparency
                    </button>
                  </div>
                </div>
              </div>

              {/* Messages */}
              <div ref={scrollRef} className="flex-1 overflow-y-auto px-6 py-4">
                {messages.length === 0 ? (
                  <div className="h-full flex flex-col items-center justify-center text-center">
                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-teal-400/20 to-cyan-600/20 flex items-center justify-center mb-4">
                      <Brain className="w-8 h-8 text-teal-400" />
                    </div>
                    <h3 className="text-lg font-semibold text-gray-300 mb-1">Chat with {selectedCustomer.name}</h3>
                    <p className="text-sm text-gray-600 max-w-md mb-6">
                      {memoryOn
                        ? "Echo will recall this customer's history from memory and respond with context."
                        : "Memory is OFF — Echo will respond as if meeting this customer for the first time."}
                    </p>
                    {(SUGGESTED_MESSAGES[selectedCustomer.id] || [
                      "Hi, I have a question about my account.",
                      "Can someone help me with an integration issue?",
                      "I need to update my billing information.",
                    ]).map((msg) => (
                      <button
                        key={msg}
                        onClick={() => setInput(msg)}
                        className="block w-full max-w-lg text-left text-sm text-gray-400 hover:text-gray-200 bg-gray-800/50 hover:bg-gray-800 rounded-lg px-4 py-2.5 mb-2 transition-all border border-gray-800 hover:border-gray-700"
                      >
                        "{msg}"
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="flex flex-col gap-4 max-w-3xl mx-auto">
                    {followupPending && (
                      <div className="flex items-center gap-2 text-sm text-gray-500">
                        <Loader2 className="w-4 h-4 animate-spin text-teal-400" />
                        Echo is looking into this and will follow up shortly...
                      </div>
                    )}
                    {messages.map((msg, i) => (
                      <MessageBubble key={i} msg={msg} showTransparency={showTransparency} />
                    ))}
                  </div>
                )}
              </div>

              {/* Input */}
              <div className="flex-shrink-0 border-t border-gray-800 bg-[#16181f] px-6 py-3">
                {error && (
                  <div className="mb-2 flex items-center gap-2 text-sm text-red-400">
                    <AlertTriangle className="w-4 h-4" />
                    {error}
                  </div>
                )}
                <div className="flex items-center gap-2 max-w-3xl mx-auto">
                  <input
                    type="text"
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => e.key === "Enter" && handleSend()}
                    placeholder={`Message ${selectedCustomer.name}...`}
                    className="flex-1 bg-gray-800 text-gray-100 placeholder-gray-600 rounded-lg px-4 py-2.5 text-sm border border-gray-700 focus:border-teal-500/50 focus:outline-none transition-colors"
                    disabled={loading}
                  />
                  <button
                    onClick={handleSend}
                    disabled={!input.trim() || loading}
                    className="w-10 h-10 rounded-lg bg-teal-500 hover:bg-teal-400 text-white flex items-center justify-center transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                  </button>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex flex-col items-center justify-center text-center">
              {error && (
                <div role="alert" className="mb-6 flex max-w-xl items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-left text-sm text-amber-300">
                  <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0" />
                  <span>{error}</span>
                </div>
              )}
              <div className="w-20 h-20 rounded-3xl bg-gradient-to-br from-teal-400/20 to-cyan-600/20 flex items-center justify-center mb-6">
                <Brain className="w-10 h-10 text-teal-400" />
              </div>
              <h2 className="text-2xl font-semibold text-gray-300 mb-2">Welcome to Echo</h2>
              <p className="text-sm text-gray-600 max-w-md">
                A memory-first AI customer support agent. Select a customer to start chatting — Echo recalls their history, detects sentiment, and never re-suggests a fix that already failed.
              </p>
              <div className="mt-8 grid grid-cols-3 gap-4 max-w-2xl">
                <FeatureCard icon={<Brain className="w-5 h-5" />} title="Two-tier memory" desc="Personal + collective banks" />
                <FeatureCard icon={<Zap className="w-5 h-5" />} title="Groq-powered" desc="Fast agent replies" />
                <FeatureCard icon={<FileText className="w-5 h-5" />} title="Handoff briefs" desc="Context for human agents" />
              </div>
            </div>
          )}
        </main>

        {/* Transparency panel */}
        {selectedCustomer && showTransparency && (
          <aside className="w-72 flex-shrink-0 border-l border-gray-800 bg-[#16181f] flex flex-col overflow-hidden">
            <div className="p-4 border-b border-gray-800">
              <div className="flex items-center gap-2 mb-1">
                <Brain className="w-4 h-4 text-teal-400" />
                <h2 className="text-sm font-semibold text-gray-200">Transparency</h2>
              </div>
              <p className="text-xs text-gray-600">What Echo recalled and decided</p>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {(() => {
                const lastAgent = [...messages].reverse().find((m) => m.role === "agent" && !m.streaming);
                if (!lastAgent) {
                  return (
                    <div className="text-center py-8">
                      <p className="text-sm text-gray-600">No responses yet.</p>
                      <p className="text-xs text-gray-700 mt-1">Send a message to see what Echo recalls.</p>
                    </div>
                  );
                }
                return <TransparencyContent msg={lastAgent} />;
              })()}
            </div>
          </aside>
        )}
      </div>

      {/* Brief modal */}
      {showBrief && brief && selectedCustomer && (
        <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center p-4" onClick={() => setShowBrief(false)}>
          <div className="bg-[#1e2028] border border-gray-700 rounded-2xl shadow-2xl max-w-lg w-full p-6 max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-white">Handoff Brief</h2>
                <p className="text-xs text-gray-500">{selectedCustomer.name} · {selectedCustomer.company}</p>
              </div>
              <button onClick={() => setShowBrief(false)} className="text-gray-500 hover:text-gray-300">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-4">
              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recent tickets</h3>
                {brief.tickets.length === 0 ? (
                  <p className="text-sm text-gray-600">No tickets</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {brief.tickets.map((t: any) => (
                      <div key={t.id} className="bg-gray-800/50 rounded-lg p-3 border border-gray-800">
                        <div className="flex items-center justify-between mb-1">
                          <p className="text-sm text-gray-300">{t.subject}</p>
                          <span className={`text-xs px-2 py-0.5 rounded ${
                            t.status === "open" ? "bg-blue-500/15 text-blue-400" : "bg-gray-700 text-gray-400"
                          }`}>{t.status}</span>
                        </div>
                        <p className="text-xs text-gray-600">Opened {formatDate(t.opened_at)}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Open commitments</h3>
                {brief.open_commitments.length === 0 ? (
                  <p className="text-sm text-gray-600">No open commitments</p>
                ) : (
                  <div className="flex flex-col gap-2">
                    {brief.open_commitments.map((c: any, i: number) => (
                      <div key={i} className="bg-gray-800/50 rounded-lg p-3 border border-gray-800 flex items-start gap-2">
                        <CheckCircle2 className="w-4 h-4 text-teal-400 mt-0.5 flex-shrink-0" />
                        <div>
                          <p className="text-sm text-gray-300">{c.text}</p>
                          <p className="text-xs text-gray-600 mt-0.5">Due {formatDate(c.due_date)}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function MessageBubble({ msg, showTransparency }: { msg: Message; showTransparency: boolean }) {
  const [showDetails, setShowDetails] = useState(false);
  const isAgent = msg.role === "agent";

  return (
    <div className={`flex gap-3 ${isAgent ? "flex-row" : "flex-row-reverse"}`}>
      <div className={`w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 ${
        isAgent ? "bg-gradient-to-br from-teal-400 to-cyan-600" : "bg-gray-700"
      }`}>
        {isAgent ? <Bot className="w-4 h-4 text-white" /> : <User className="w-4 h-4 text-gray-300" />}
      </div>
      <div className={`flex-1 max-w-[80%] ${isAgent ? "" : "text-right"}`}>
        <div className={`inline-block rounded-2xl px-4 py-2.5 text-sm leading-relaxed ${
          isAgent ? "bg-gray-800 text-gray-100 rounded-tl-sm" : "bg-teal-500 text-white rounded-tr-sm"
        }`}>
          {msg.text || (msg.streaming && (
            <span className="inline-flex gap-1">
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse" />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse" style={{ animationDelay: "0.2s" }} />
              <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-pulse" style={{ animationDelay: "0.4s" }} />
            </span>
          ))}
        </div>

        {isAgent && !msg.streaming && (
          <div className="mt-1.5 flex items-center gap-2 flex-wrap">
            {msg.sentiment && (
              <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${sentimentColors[msg.sentiment] || sentimentColors.neutral}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${sentimentDots[msg.sentiment] || sentimentDots.neutral}`} />
                {msg.sentiment}
              </span>
            )}
            {msg.memories && msg.memories.length > 0 && (
              <span className="text-xs text-teal-400">{msg.memories.length} memor{msg.memories.length === 1 ? "y" : "ies"} recalled</span>
            )}
            {msg.degraded && (
              <span className="inline-flex items-center gap-1 text-xs text-amber-400">
                <AlertTriangle className="w-3 h-3" /> degraded
              </span>
            )}
            {showTransparency && msg.memories && msg.memories.length > 0 && (
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-0.5"
              >
                {showDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                details
              </button>
            )}
          </div>
        )}

        {isAgent && showDetails && msg.memories && (
          <div className="mt-2 bg-gray-800/50 rounded-lg p-3 border border-gray-800 flex flex-col gap-2">
            {msg.memories.map((m: any, i: number) => (
              <div key={i} className="flex items-start gap-2">
                <span className={`text-xs px-1.5 py-0.5 rounded ${m.source === "personal" ? "bg-teal-500/10 text-teal-400" : "bg-blue-500/10 text-blue-400"}`}>
                  {m.source}
                </span>
                <p className="text-xs text-gray-400 flex-1">{m.text}</p>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TransparencyContent({ msg }: { msg: Message }) {
  return (
    <div className="flex flex-col gap-4">
      {msg.memories && msg.memories.length > 0 ? (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recalled memories</h3>
          <div className="flex flex-col gap-2">
            {msg.memories.map((m: any, i: number) => (
              <div key={i} className="bg-gray-800/50 rounded-lg p-2.5 border border-gray-800">
                <div className="flex items-center gap-2 mb-1">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded ${m.source === "personal" ? "bg-teal-500/10 text-teal-400" : "bg-blue-500/10 text-blue-400"}`}>
                    {m.source}
                  </span>
                  <span className="text-[10px] text-gray-600">score {(m.score || 0).toFixed(2)}</span>
                </div>
                <p className="text-xs text-gray-400">{m.text}</p>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Recalled memories</h3>
          <p className="text-xs text-gray-600">
            {msg.degraded ? "Memory was unavailable (degraded mode)." : "No memories recalled for this message."}
          </p>
        </div>
      )}

      {msg.sentiment && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Sentiment</h3>
          <span className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full border ${sentimentColors[msg.sentiment] || sentimentColors.neutral}`}>
            <span className={`w-1.5 h-1.5 rounded-full ${sentimentDots[msg.sentiment] || sentimentDots.neutral}`} />
            {msg.sentiment}
          </span>
        </div>
      )}

      {msg.commitments && msg.commitments.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Commitments</h3>
          <div className="flex flex-col gap-1.5">
            {msg.commitments.map((c: any, i: number) => (
              <div key={i} className="text-xs text-gray-400 flex items-start gap-2">
                <CheckCircle2 className="w-3 h-3 text-teal-400 mt-0.5 flex-shrink-0" />
                <div>
                  <p>{c.text}</p>
                  <p className="text-[10px] text-gray-600">due {c.due_date}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function FeatureCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div className="bg-gray-800/30 border border-gray-800 rounded-xl p-4 text-center">
      <div className="w-10 h-10 rounded-lg bg-teal-500/10 flex items-center justify-center mx-auto mb-2 text-teal-400">
        {icon}
      </div>
      <h3 className="text-sm font-medium text-gray-300">{title}</h3>
      <p className="text-xs text-gray-600 mt-0.5">{desc}</p>
    </div>
  );
}

export default App;
