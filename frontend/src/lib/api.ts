const BASE_FRAUD = 'http://localhost:8000';
const BASE_SCREENING = 'http://localhost:8003';
const BASE_ANALYTICS = 'http://localhost:8002';

async function fetchFrom<T = any>(base: string, path: string, init?: RequestInit): Promise<T> {
	const res = await fetch(`${base}${path}`, {
		headers: { 'Content-Type': 'application/json', ...init?.headers },
		...init,
	});
	if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
	return res.json();
}

function fetchJSON<T = any>(path: string, init?: RequestInit): Promise<T> {
	return fetchFrom<T>(BASE_FRAUD, path, init);
}

// SSE types
export type SSEEventType = 'connected' | 'new_alert' | 'investigation_status' | 'investigation_complete';
export type SSECallback = (event: SSEEventType, data: any) => void;

/**
 * Connect to the fraud SSE stream. Returns a cleanup function.
 */
export function connectFraudSSE(onMessage: SSECallback): () => void {
	const source = new EventSource(`${BASE_FRAUD}/api/fraud/events/stream`);

	source.addEventListener('connected', (e: MessageEvent) => {
		onMessage('connected', JSON.parse(e.data));
	});
	source.addEventListener('new_alert', (e: MessageEvent) => {
		onMessage('new_alert', JSON.parse(e.data));
	});
	source.addEventListener('investigation_status', (e: MessageEvent) => {
		onMessage('investigation_status', JSON.parse(e.data));
	});
	source.addEventListener('investigation_complete', (e: MessageEvent) => {
		onMessage('investigation_complete', JSON.parse(e.data));
	});

	source.onerror = () => {
		console.warn('SSE connection error, will auto-reconnect...');
	};

	return () => source.close();
}

// Fraud Detection (UC3)
export const fraud = {
	stats: () => fetchJSON('/api/fraud/stats'),
	recentEvents: (limit = 50) => fetchJSON(`/api/fraud/events/recent?limit=${limit}`),
	alerts: (limit = 50) => fetchJSON(`/api/fraud/alerts?limit=${limit}`),
	signalRules: () => fetchJSON('/api/fraud/signal-rules'),
	updateSignalRule: (key: string, updates: Record<string, any>) =>
		fetchJSON(`/api/fraud/signal-rules/${key}`, {
			method: 'PUT',
			body: JSON.stringify({ updates }),
		}),
	simulate: (scenario: string, userId?: string) =>
		fetchJSON('/api/fraud/simulate', {
			method: 'POST',
			body: JSON.stringify({ scenario, userId }),
		}),
	flaggedUsers: () => fetchJSON('/api/fraud/users/flagged'),
	similarUsers: (userId: string, topK = 10) =>
		fetchJSON(`/api/fraud/users/${userId}/similar?top_k=${topK}`),
	backfillEmbeddings: () =>
		fetchJSON('/api/fraud/users/backfill-embeddings', { method: 'POST' }),
	pipelineDefinitions: () => fetchJSON('/api/fraud/pipeline-definitions'),
	investigate: (userId: string) =>
		fetchJSON(`/api/fraud/investigate/${userId}`, { method: 'POST' }),
	investigations: (limit = 20) => fetchJSON(`/api/fraud/investigations?limit=${limit}`),
	userInvestigations: (userId: string, limit = 5) =>
		fetchJSON(`/api/fraud/investigations/${userId}?limit=${limit}`),
};

// Screening (UC1) — runs on separate port
export const screening = {
	autocompleteSanctioned: (q: string, limit = 8) =>
		fetchFrom(BASE_SCREENING, `/api/screening/autocomplete/sanctioned?q=${encodeURIComponent(q)}&limit=${limit}`),
	autocompleteProfiles: (q: string, limit = 8) =>
		fetchFrom(BASE_SCREENING, `/api/screening/autocomplete/profiles?q=${encodeURIComponent(q)}&limit=${limit}`),
	checkUser: (name: string, maxEdits = 2, limit = 10, dob?: string) =>
		fetchFrom(BASE_SCREENING, '/api/screening/check-user', {
			method: 'POST',
			body: JSON.stringify({ name, max_edits: maxEdits, limit, dob: dob || null }),
		}),
	batchSweep: (limit = 0) =>
		fetchFrom(BASE_SCREENING, '/api/screening/batch-sweep', {
			method: 'POST',
			body: JSON.stringify({ limit }),
		}),
	flaggedUsers: (limit = 100) => fetchFrom(BASE_SCREENING, `/api/screening/flagged-users?limit=${limit}`),
	stats: () => fetchFrom(BASE_SCREENING, '/api/screening/stats'),
	indexDefinitions: () => fetchFrom(BASE_SCREENING, '/api/screening/index-definitions'),
	sanctioned: (limit = 100, skip = 0) => fetchFrom(BASE_SCREENING, `/api/screening/sanctioned?limit=${limit}&skip=${skip}`),
};

// Analytics Chatbot (UC2b — MCP)
export interface MemoryTraceEntry {
	tool: string;
	input: Record<string, any>;
	output: string;
}

export interface AnalyticsAskResponse {
	answer: string;
	mql: string | null;
	latency_ms: number;
	session_id: string;
	memory_trace: MemoryTraceEntry[];
}

export interface TerminologyEntry {
	term: string;
	aliases: string[];
	meaning: string;
	field: string;
}

export interface ChatStats {
	totalQueries: number;
	activeSessions: number;
	avgLatencyMs: number;
}

export interface HistoryEntry {
	id: string;
	question: string;
	content: string;
	answer?: string;
	mql: string | null;
	latency_ms: number;
	timestamp: string;
}

// ─── Conversation Search Types ──────────────────────────────────

export interface HighlightText {
	value: string;
	type: 'hit' | 'text';
}

export interface HighlightEntry {
	path: string;
	texts: HighlightText[];
}

export interface FacetBucket {
	value: string;
	count: number;
}

export interface Facet {
	field: string;
	label: string;
	buckets: FacetBucket[];
}

export interface PaginationInfo {
	hasMore: boolean;
	nextCursor: string | null;
	totalEstimate: number | null;
}

export interface ConversationSearchResult {
	threadId: string;
	title: string;
	summary: string;
	lastQuestion: string;
	category: string;
	complexity: string;
	intent: string;
	topics: string[];
	collections: string[];
	turnCount: number;
	createdAt: string | null;
	updatedAt: string | null;
	score: number;
	highlights: HighlightEntry[];
}

export interface ConversationSearchResponse {
	results: ConversationSearchResult[];
	facets: Facet[];
	pagination: PaginationInfo;
	debugPipeline?: Record<string, any>[];
	debugFacetPipeline?: Record<string, any>[];
}

export interface ConversationDetail {
	threadId: string;
	userId: string;
	title: string;
	summary: string;
	category: string;
	complexity: string;
	intent: string;
	topics: string[];
	entities: string[];
	queryTypes: string[];
	collections: string[];
	turnCount: number;
	messages: HistoryEntry[];
	createdAt: string | null;
	updatedAt: string | null;
	hasCheckpoint: boolean;
}

export interface ResumeResponse extends ConversationDetail {}

export interface MemoryItem {
	key: string;
	value: Record<string, any>;
	namespace: string[];
}

export interface AppUser {
	userId: string;
	name: string;
	role: string;
	avatar: string;
	department: string;
}

// ─── Analytics API ──────────────────────────────────────────────

export const analytics = {
	ask: (question: string, sessionId?: string, userId?: string): Promise<AnalyticsAskResponse> =>
		fetchFrom(BASE_ANALYTICS, '/api/analytics/ask', {
			method: 'POST',
			body: JSON.stringify({ question, session_id: sessionId, user_id: userId }),
		}),
	history: (sessionId: string): Promise<HistoryEntry[]> =>
		fetchFrom(BASE_ANALYTICS, `/api/analytics/history/${sessionId}`),
	terminology: (): Promise<TerminologyEntry[]> =>
		fetchFrom(BASE_ANALYTICS, '/api/analytics/terminology'),
	stats: (): Promise<ChatStats> =>
		fetchFrom(BASE_ANALYTICS, '/api/analytics/stats'),
	users: (): Promise<AppUser[]> =>
		fetchFrom(BASE_ANALYTICS, '/api/analytics/users'),
	memories: (userId: string): Promise<MemoryItem[]> =>
		fetchFrom(BASE_ANALYTICS, `/api/analytics/memories/${userId}`),
};

// ─── Conversation History API ───────────────────────────────────

export const conversations = {
	search: (params: {
		query?: string;
		filters?: Record<string, string[]>;
		cursor?: string;
		limit?: number;
		use_facets?: boolean;
		debug?: boolean;
	}): Promise<ConversationSearchResponse> =>
		fetchFrom(BASE_ANALYTICS, '/api/analytics/conversations/search', {
			method: 'POST',
			body: JSON.stringify({
				query: params.query ?? '',
				filters: params.filters ?? {},
				cursor: params.cursor ?? null,
				limit: params.limit ?? 10,
				use_facets: params.use_facets ?? true,
				debug: params.debug ?? false,
			}),
		}),

	get: (threadId: string): Promise<ConversationDetail> =>
		fetchFrom(BASE_ANALYTICS, `/api/analytics/conversations/${threadId}`),

	resume: (threadId: string): Promise<ResumeResponse> =>
		fetchFrom(BASE_ANALYTICS, `/api/analytics/conversations/${threadId}/resume`),
};
