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
  open_commitments: Array<{ text: string; due_date: string }>;
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