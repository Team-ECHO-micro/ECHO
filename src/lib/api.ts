const API_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export interface Customer {
  id: string;
  name: string;
  company: string;
  plan: string;
  email: string;
  integrations: string[];
  created_at: string;
}

export interface MemoryItem {
  id: string;
  text: string;
  scores?: { final: number };
}

export interface ChatEventData {
  text?: string;
  memories?: MemoryItem[];
  error?: string;
  reply?: string;
  sentiment?: string;
  commitments?: unknown[];
  issue_type?: string | null;
  fix_applied?: string | null;
  outcome?: string | null;
  recalled_memories?: MemoryItem[];
  degraded?: boolean;
  model?: string | null;
}

export interface Commitment {
  text: string;
  due_date: string;
  overdue?: boolean;
  days_overdue?: number;
}

export interface TimeJumpResult {
  customer_id: string;
  virtual_now: string;
  days_advanced: number;
  overdue_commitments: Commitment[];
  total_commitments: number;
}

export interface HealthStatus {
  status: string;
  virtual_now: string;
  groq_configured: boolean;
  hindsight_configured: boolean;
}

export interface DemoResetResult {
  reset: boolean;
  virtual_now: string;
  memories_forgotten: string[];
  eval_files_removed: number;
}

export interface EvalResult {
  ran_at: string;
  total_scenarios: number;
  results: Array<{
    scenario: string;
    memory_on: boolean;
    reply: string;
    sentiment: string;
    commitments: Commitment[];
    memories_recalled: number;
    degraded: boolean;
    model: string | null;
    check_description: string;
    elapsed_seconds: number;
    error: string | null;
  }>;
  summary: {
    memory_on_avg_memories_recalled: number;
    memory_off_avg_memories_recalled: number;
    scenarios_with_errors: number;
    total_elapsed_seconds: number;
  };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(body?.detail || `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export function fetchCustomers(): Promise<Customer[]> {
  return request<Customer[]>("/api/customers");
}

export function fetchBrief(customerId: string): Promise<{
  tickets: Array<{ id: string; subject: string; status: string; opened_at: string }>;
  open_commitments: Commitment[];
  overdue_commitments: Commitment[];
}> {
  return request(`/api/customers/${customerId}/brief`);
}

export function addCustomer(data: Omit<Customer, "id" | "created_at">): Promise<Customer> {
  return request<Customer>("/api/customers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function seedMemory(customerId: string): Promise<number> {
  const result = await request<{ notes_retained: number }>(`/api/customers/${customerId}/seed-memory`, {
    method: "POST",
  });
  return result.notes_retained;
}

export async function fetchMemories(customerId: string): Promise<MemoryItem[]> {
  const result = await request<{ memories: MemoryItem[] }>(`/api/customers/${customerId}/memories`);
  return result.memories;
}

export async function forgetMemory(customerId: string): Promise<void> {
  await request(`/api/customers/${customerId}/memory`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Virtual clock
// ---------------------------------------------------------------------------

export function fetchHealth(): Promise<HealthStatus> {
  return request<HealthStatus>("/api/health");
}

export function timeJump(customerId: string, days: number): Promise<TimeJumpResult> {
  return request<TimeJumpResult>(`/api/customers/${customerId}/time-jump`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ days }),
  });
}

// ---------------------------------------------------------------------------
// Demo reset
// ---------------------------------------------------------------------------

export function demoReset(): Promise<DemoResetResult> {
  return request<DemoResetResult>("/api/demo/reset", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Evaluation
// ---------------------------------------------------------------------------

export function runEvaluation(
  scenarios?: string[],
  memoryOn = true,
): Promise<EvalResult> {
  return request<EvalResult>("/api/eval/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenarios: scenarios || null, memory_on: memoryOn }),
  });
}

// ---------------------------------------------------------------------------
// Chat SSE
// ---------------------------------------------------------------------------

export function streamChat(
  customerId: string,
  message: string,
  memoryEnabled: boolean,
  now: string,
  onEvent: (event: string, data: ChatEventData) => void,
  onError: (err: string) => void,
  onDone: () => void,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const response = await fetch(`${API_URL}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          customer_id: customerId,
          message,
          memory_enabled: memoryEnabled,
          now,
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) {
        throw new Error(`Request failed (${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let eventName = "";
      let dataLines: string[] = [];

      const dispatch = () => {
        if (eventName && dataLines.length) {
          try {
            onEvent(eventName, JSON.parse(dataLines.join("\n")));
          } catch {
            onError("The backend returned an invalid event.");
          }
        }
        eventName = "";
        dataLines = [];
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const rawLine of lines) {
          const line = rawLine.replace(/\r$/, "");
          if (!line) dispatch();
          else if (line.startsWith("event: ")) eventName = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
        }
      }
      if (buffer) {
        if (buffer.startsWith("event: ")) eventName = buffer.slice(7).trim();
        else if (buffer.startsWith("data: ")) dataLines.push(buffer.slice(6));
      }
      dispatch();
    } catch (error) {
      if (!(error instanceof Error && error.name === "AbortError")) {
        onError(error instanceof Error ? error.message : String(error));
      }
    } finally {
      onDone();
    }
  })();

  return controller;
}