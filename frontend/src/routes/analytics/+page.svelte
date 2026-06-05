<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { analytics, conversations } from '$lib/api';
	import type {
		AnalyticsAskResponse, TerminologyEntry, ChatStats,
		ConversationSearchResult, ConversationSearchResponse,
		Facet, HighlightEntry, AppUser, MemoryItem, MemoryTraceEntry
	} from '$lib/api';

	// ─── State ───────────────────────────────────────────────────
	interface ChatMessage {
		role: 'user' | 'assistant';
		content: string;
		mql?: string | null;
		latency_ms?: number;
		memory_trace?: MemoryTraceEntry[];
	}

	let messages = $state<ChatMessage[]>([]);
	let inputText = $state('');
	let isLoading = $state(false);
	let sessionId = $state(crypto.randomUUID() as string);
	let terminology = $state<TerminologyEntry[]>([]);
	let chatStats = $state<ChatStats>({ totalQueries: 0, activeSessions: 0, avgLatencyMs: 0 });
	let expandedMql = $state<Record<number, boolean>>({});
	let expandedMemory = $state<Record<number, boolean>>({});
	let showTerminology = $state(false);
	let showArchitecture = $state(false);
	let showWhyMcp = $state(true);
	let showSidebar = $state(false);
	let chatContainer: HTMLDivElement;

	// ─── History Panel State ────────────────────────────────────
	let showHistory = $state(false);
	let historyQuery = $state('');
	let historyResults = $state<ConversationSearchResult[]>([]);
	let historyFacets = $state<Facet[]>([]);
	let historyFilters = $state<Record<string, string[]>>({});
	let historyLoading = $state(false);
	let historyHasMore = $state(false);
	let historyCursor = $state<string | null>(null);
	let historyTotal = $state<number | null>(null);
	let searchTimeout: ReturnType<typeof setTimeout>;

	// ─── Query Inspector State ──────────────────────────────────
	let showInspector = $state(false);
	let debugPipeline = $state<Record<string, any>[] | null>(null);
	let debugFacetPipeline = $state<Record<string, any>[] | null>(null);
	let inspectorTab = $state<'search' | 'facet' | 'flow'>('search');

	// ─── User & Memory State ───────────────────────────────────
	let currentUserId = $state('analyst-1');
	let users = $state<AppUser[]>([]);
	let userMemories = $state<MemoryItem[]>([]);
	let showUserMenu = $state(false);

	const MEMORY_CHIPS: Record<string, string[]> = {
		compliance_threshold: ['Flag all users with wallet balance above the compliance threshold', 'How many users exceed RM 10,000 in their wallet?'],
		at_risk_users_definition: ['How many at-risk users do we have right now?', 'Show me all at-risk users by category'],
		monthly_board_kpis: ['Generate this month\'s board KPI summary', 'What\'s our current MAU and churn rate?'],
		premium_user_priority: ['What percentage of premium users are flagged?', 'Compare premium vs basic wallet user metrics'],
		format_preference: [],
		segment_context_preference: [],
		reporting_context: [],
		growth_kpi_focus: ['What\'s our MAU growth rate month-over-month?', 'Show me the activation funnel conversion metrics'],
		high_value_definition: ['How many high-value users do we have?', 'What\'s the average spend of our top users?'],
		segment_interest: ['Show me the wallet tier distribution and upgrade rates', 'How many users upgraded from basic to premium this month?'],
	};

	const GENERIC_CHIPS = [
		'How many users are registered in the system?',
		'What percentage of users are active vs inactive?',
		"What's the KYC verification breakdown by status?",
		'How many users are flagged by screening?',
		"What's the average wallet balance across all users?",
		'Show me the wallet tier distribution',
		'Which banks are most linked to FuelRetail?',
		'Who are the top 10 users by total transactions?',
	];

	let exampleChips = $derived.by(() => {
		if (userMemories.length === 0) return GENERIC_CHIPS;
		const chips: string[] = [];
		for (const mem of userMemories) {
			const mapped = MEMORY_CHIPS[mem.key];
			if (mapped) chips.push(...mapped);
		}
		return chips.length > 0 ? chips : GENERIC_CHIPS;
	});

	let inputBarChips = $derived.by(() => {
		return exampleChips.slice(0, 4);
	});

	function currentUser(): AppUser | undefined {
		return users.find(u => u.userId === currentUserId);
	}

	async function loadUserMemories() {
		try {
			userMemories = await analytics.memories(currentUserId);
		} catch {
			userMemories = [];
		}
	}

	async function switchUser(userId: string) {
		if (userId === currentUserId) { showUserMenu = false; return; }
		currentUserId = userId;
		showUserMenu = false;
		newSession();
		await loadUserMemories();
	}

	// ─── Actions ─────────────────────────────────────────────────
	async function sendMessage(text?: string) {
		const question = (text ?? inputText).trim();
		if (!question || isLoading) return;
		inputText = '';

		messages = [...messages, { role: 'user', content: question }];
		isLoading = true;
		scrollToBottom();

		try {
			const res: AnalyticsAskResponse = await analytics.ask(question, sessionId, currentUserId);
			sessionId = res.session_id;
			history.replaceState({}, '', `?session=${res.session_id}`);
			messages = [...messages, {
				role: 'assistant',
				content: res.answer,
				mql: res.mql,
				latency_ms: res.latency_ms,
				memory_trace: res.memory_trace,
			}];
		} catch (err: any) {
			messages = [...messages, {
				role: 'assistant',
				content: `Error: ${err.message}. Make sure the backend is running and AWS credentials are configured.`,
			}];
		} finally {
			isLoading = false;
			scrollToBottom();
			refreshStats();
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			e.preventDefault();
			sendMessage();
		}
	}

	function scrollToBottom() {
		setTimeout(() => {
			if (chatContainer) chatContainer.scrollTop = chatContainer.scrollHeight;
		}, 50);
	}

	async function refreshStats() {
		try { chatStats = await analytics.stats(); } catch {}
	}

	function newSession() {
		messages = [];
		sessionId = crypto.randomUUID();
		expandedMql = {};
		expandedMemory = {};
		history.replaceState({}, '', window.location.pathname);
	}

	// ─── History Panel Actions ──────────────────────────────────
	async function searchHistory(append = false) {
		historyLoading = true;
		try {
			const res: ConversationSearchResponse = await conversations.search({
				query: historyQuery,
				filters: historyFilters,
				cursor: append ? (historyCursor ?? undefined) : undefined,
				limit: 10,
				use_facets: !append,
				debug: showInspector,
			});
			if (append) {
				historyResults = [...historyResults, ...res.results];
			} else {
				historyResults = res.results;
				historyFacets = res.facets;
			}
			historyHasMore = res.pagination.hasMore;
			historyCursor = res.pagination.nextCursor;
			historyTotal = res.pagination.totalEstimate ?? historyTotal;
			if (showInspector) {
				debugPipeline = res.debugPipeline ?? null;
				debugFacetPipeline = res.debugFacetPipeline ?? null;
			}
		} catch (err) {
			console.error('Search failed:', err);
		} finally {
			historyLoading = false;
		}
	}

	function onHistoryQueryInput() {
		clearTimeout(searchTimeout);
		searchTimeout = setTimeout(() => searchHistory(), 400);
	}

	function toggleFilter(field: string, value: string) {
		const current = historyFilters[field] || [];
		if (current.includes(value)) {
			historyFilters[field] = current.filter(v => v !== value);
			if (historyFilters[field].length === 0) delete historyFilters[field];
		} else {
			historyFilters[field] = [...current, value];
		}
		historyFilters = { ...historyFilters };
		searchHistory();
	}

	function removeFilter(field: string, value: string) {
		toggleFilter(field, value);
	}

	function clearAllFilters() {
		historyFilters = {};
		searchHistory();
	}

	function openHistory() {
		showHistory = true;
		searchHistory();
	}

	function closeHistory() {
		showHistory = false;
	}

	function openInspector() {
		showInspector = true;
		searchHistory();
	}

	function closeInspector() {
		showInspector = false;
		debugPipeline = null;
		debugFacetPipeline = null;
	}

	async function resumeConversation(threadId: string) {
		try {
			const data = await conversations.resume(threadId);
			// Load messages into chat
			messages = [];
			for (const msg of data.messages || []) {
				messages.push({ role: 'user', content: msg.question });
				messages.push({
					role: 'assistant',
					content: msg.content || msg.answer || '',
					mql: msg.mql,
					latency_ms: msg.latency_ms,
				});
			}
			sessionId = threadId;
			history.replaceState({}, '', `?session=${threadId}`);
			expandedMql = {};
			showHistory = false;
			scrollToBottom();
		} catch (err) {
			console.error('Resume failed:', err);
		}
	}

	// ─── Highlight Rendering ────────────────────────────────────
	function renderHighlight(highlight: HighlightEntry): string {
		return highlight.texts
			.map(t => t.type === 'hit' ? `<mark class="bg-yellow-300/50 text-yellow-200 px-0.5 rounded">${t.value}</mark>` : t.value)
			.join('');
	}

	function getBestHighlight(highlights: HighlightEntry[]): string {
		if (!highlights.length) return '';
		// Prefer summary or title highlights
		const preferred = highlights.find(h => h.path === 'summary' || h.path === 'title' || h.path === 'lastQuestion');
		return renderHighlight(preferred || highlights[0]);
	}

	// ─── Markdown-lite rendering ─────────────────────────────────
	function renderMarkdown(text: string): string {
		return text
			.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre class="mql-code my-2 overflow-x-auto"><code>$2</code></pre>')
			.replace(/\*\*(.*?)\*\*/g, '<strong class="text-white font-semibold">$1</strong>')
			.replace(/`([^`]+)`/g, '<code class="text-emerald-400 bg-gray-900 px-1 py-0.5 rounded text-xs font-mono">$1</code>')
			.replace(/\n/g, '<br>');
	}

	function formatDate(iso: string | null): string {
		if (!iso) return '';
		const d = new Date(iso);
		return d.toLocaleDateString('en-MY', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
	}

	// ─── Lifecycle ───────────────────────────────────────────────
	onMount(() => {
		const urlSession = page.url.searchParams.get('session');
		if (urlSession) {
			resumeConversation(urlSession);
		}
		analytics.terminology().then(t => terminology = t).catch(() => {});
		analytics.users().then(u => users = u).catch(() => {});
		loadUserMemories();
		refreshStats();
		const interval = setInterval(refreshStats, 30000);
		return () => clearInterval(interval);
	});

	function handleGlobalKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && showUserMenu) showUserMenu = false;
		if (e.key === 'Escape' && showInspector) closeInspector();
	}
</script>

<svelte:window onkeydown={handleGlobalKeydown} />

<div class="flex h-full">
	<!-- Main Chat Area (~70%) -->
	<div class="flex-1 flex flex-col min-w-0">
		<!-- Header -->
		<div class="px-6 py-4 border-b border-gray-700/50 flex items-center justify-between flex-shrink-0">
			<div>
				<h1 class="text-xl font-semibold text-white">Analytics Chatbot</h1>
				<p class="text-xs text-gray-500 mt-0.5">Natural language queries via MongoDB MCP Server</p>
			</div>
			<div class="flex items-center gap-3">
				<!-- User Selector -->
				<div class="relative">
					<button
						class="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-gray-700/50 hover:border-gray-600 bg-gray-800/50 transition-colors text-xs"
						onclick={() => showUserMenu = !showUserMenu}
					>
						{#if currentUser()}
							<span class="w-6 h-6 rounded-full bg-gradient-to-br from-blue-500/30 to-purple-500/30 flex items-center justify-center text-[10px] font-bold text-white/90 flex-shrink-0">{currentUser()?.avatar}</span>
							<span class="text-gray-300">{currentUser()?.name}</span>
						{:else}
							<span class="text-gray-500">Select user</span>
						{/if}
						<svg class="w-3 h-3 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path d="M19.5 8.25l-7.5 7.5-7.5-7.5" />
						</svg>
					</button>
					{#if showUserMenu}
						<div class="absolute right-0 top-full mt-1 w-64 bg-gray-800 border border-gray-700/50 rounded-lg shadow-xl z-50 overflow-hidden">
							{#each users as user}
								<button
									class="w-full flex items-center gap-3 px-3 py-2.5 text-left hover:bg-gray-700/50 transition-colors {user.userId === currentUserId ? 'bg-blue-500/10 border-l-2 border-blue-500' : ''}"
									onclick={() => switchUser(user.userId)}
								>
									<span class="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500/30 to-purple-500/30 flex items-center justify-center text-xs font-bold text-white/90 flex-shrink-0">{user.avatar}</span>
									<div class="min-w-0">
										<div class="text-xs font-medium text-white truncate">{user.name}</div>
										<div class="text-[10px] text-gray-500 truncate">{user.role} &middot; {user.department}</div>
									</div>
									{#if user.userId === currentUserId}
										<svg class="w-4 h-4 text-blue-400 ml-auto flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path d="M4.5 12.75l6 6 9-13.5" />
										</svg>
									{/if}
								</button>
							{/each}
						</div>
					{/if}
				</div>

				<!-- History Button -->
				<button
					class="btn-ghost text-xs py-1.5 px-3 flex items-center gap-1.5"
					onclick={openHistory}
				>
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
					</svg>
					History
				</button>
				<!-- Sidebar Toggle -->
				<button
					class="btn-ghost text-xs py-1.5 px-3 flex items-center gap-1.5 {showSidebar ? 'text-blue-400' : ''}"
					onclick={() => showSidebar = !showSidebar}
					title="Toggle info panel"
				>
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M11.25 4.5l7.5 7.5-7.5 7.5m-6-15l7.5 7.5-7.5 7.5" />
					</svg>
					Info
				</button>
				{#if messages.length > 0}
					<button class="btn-ghost text-xs py-1.5 px-3" onclick={newSession}>New Session</button>
				{/if}
				<div class="flex items-center gap-1.5 text-[10px] font-mono">
					<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">LangChain</span>
					<span class="text-gray-600">+</span>
					<span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">MCP</span>
					<span class="text-gray-600">+</span>
					<span class="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-400">Claude</span>
				</div>
			</div>
		</div>

		<!-- Messages -->
		<div class="flex-1 overflow-y-auto px-6 py-4 space-y-4" bind:this={chatContainer}>
			{#if messages.length === 0 && !isLoading}
				<!-- Empty state with example chips -->
				<div class="flex flex-col items-center justify-center h-full">
					<div class="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-500/20 to-purple-500/20 flex items-center justify-center mb-4">
						<svg class="w-7 h-7 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
						</svg>
					</div>
				<h2 class="text-lg font-semibold text-white mb-1">
					{currentUser() ? `Hi ${currentUser()?.name.split(' ')[0]}, ask anything` : 'Ask anything about FuelRetail\'s data'}
				</h2>
				<p class="text-sm text-gray-500 mb-6 text-center max-w-md">
					{currentUser()?.role ? `${currentUser()?.role} — ${currentUser()?.department}` : 'The MCP agent reads your MongoDB schema, generates MQL, and returns answers.'}
				</p>
					<div class="flex flex-wrap gap-2 max-w-lg justify-center">
						{#each exampleChips as chip}
							<button
								class="px-3 py-1.5 rounded-full text-xs border border-gray-600/50 text-gray-400 hover:text-white hover:border-blue-500/50 hover:bg-blue-500/10 transition-all duration-150"
								onclick={() => sendMessage(chip)}
							>
								{chip}
							</button>
						{/each}
					</div>
				</div>
			{:else}
				{#each messages as msg, i}
					{#if msg.role === 'user'}
						<!-- User message -->
						<div class="flex justify-end">
							<div class="max-w-[70%] px-4 py-2.5 rounded-2xl rounded-br-sm bg-blue-600 text-white text-sm">
								{msg.content}
							</div>
						</div>
					{:else}
						<!-- Assistant message -->
						<div class="flex justify-start">
							<div class="max-w-[85%]">
								<div class="px-4 py-3 rounded-2xl rounded-bl-sm bg-FuelRetail-slate border border-gray-700/50 text-sm text-gray-200">
									{@html renderMarkdown(msg.content)}
								</div>
								<div class="flex items-center gap-3 mt-1 ml-1">
									{#if msg.mql}
										<button
											class="text-[10px] text-gray-500 hover:text-blue-400 transition-colors"
											onclick={() => expandedMql[i] = !expandedMql[i]}
										>
											{expandedMql[i] ? 'Hide MQL' : 'View MQL'}
										</button>
									{/if}
									{#if msg.memory_trace && msg.memory_trace.length > 0}
										<button
											class="text-[10px] text-gray-500 hover:text-purple-400 transition-colors flex items-center gap-1"
											onclick={() => expandedMemory[i] = !expandedMemory[i]}
										>
											<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
												<path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
											</svg>
											{expandedMemory[i] ? 'Hide Memory' : `Memory (${msg.memory_trace.length})`}
										</button>
									{/if}
									{#if msg.latency_ms}
										<span class="text-[10px] text-gray-600 font-mono tabular-nums">
											{(msg.latency_ms / 1000).toFixed(1)}s
										</span>
									{/if}
								</div>
								{#if msg.mql && expandedMql[i]}
									<div class="mt-2 ml-1">
										<div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">Generated MQL</div>
										<pre class="mql-code text-xs overflow-x-auto"><code>{msg.mql}</code></pre>
									</div>
								{/if}
								{#if msg.memory_trace && msg.memory_trace.length > 0 && expandedMemory[i]}
									<div class="mt-2 ml-1 space-y-2">
										{#each msg.memory_trace as trace}
											<div class="rounded-lg border text-xs overflow-hidden {trace.tool === 'recall_memories' ? 'border-purple-500/20 bg-purple-500/5' : 'border-blue-500/20 bg-blue-500/5'}">
												<div class="flex items-center gap-2 px-3 py-1.5 border-b {trace.tool === 'recall_memories' ? 'border-purple-500/10' : 'border-blue-500/10'}">
													<span class="px-1.5 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider {trace.tool === 'recall_memories' ? 'bg-purple-500/15 text-purple-400' : 'bg-blue-500/15 text-blue-400'}">
														{trace.tool === 'recall_memories' ? 'Recall' : 'Save'}
													</span>
													{#if trace.tool === 'recall_memories'}
														<span class="text-gray-500">query: <span class="text-purple-300/80 font-mono">"{trace.input.query}"</span></span>
													{:else}
														<span class="text-gray-500">key: <span class="text-blue-300/80 font-mono">"{trace.input.key}"</span></span>
													{/if}
												</div>
												<div class="px-3 py-2">
													{#if trace.tool === 'recall_memories' && trace.output.includes('- ')}
														<div class="space-y-1">
															{#each trace.output.split('\n').filter(l => l.startsWith('- ')) as line}
																{@const [key, ...rest] = line.slice(2).split(': ')}
																<div class="flex items-start gap-2">
																	<span class="px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-300 text-[9px] font-mono flex-shrink-0">{key}</span>
																	<span class="text-gray-400 text-[11px]">{rest.join(': ')}</span>
																</div>
															{/each}
														</div>
													{:else if trace.tool === 'save_memory'}
														<div class="flex items-start gap-2">
															<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-300 text-[9px] font-mono flex-shrink-0">{trace.input.key}</span>
															<span class="text-gray-400 text-[11px]">{trace.input.content}</span>
														</div>
													{:else}
														<span class="text-gray-400 text-[11px]">{trace.output}</span>
													{/if}
												</div>
											</div>
										{/each}
									</div>
								{/if}
							</div>
						</div>
					{/if}
				{/each}

				{#if isLoading}
					<div class="flex justify-start">
						<div class="px-4 py-3 rounded-2xl rounded-bl-sm bg-FuelRetail-slate border border-gray-700/50">
							<div class="flex items-center gap-1.5">
								<div class="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style="animation-delay: 0ms"></div>
								<div class="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style="animation-delay: 150ms"></div>
								<div class="w-2 h-2 rounded-full bg-blue-400 animate-bounce" style="animation-delay: 300ms"></div>
							</div>
						</div>
					</div>
				{/if}
			{/if}
		</div>

		<!-- Input bar -->
		<div class="px-6 py-4 border-t border-gray-700/50 flex-shrink-0">
		{#if messages.length > 0}
			<div class="flex flex-wrap gap-1.5 mb-3">
				{#each inputBarChips as chip}
					<button
						class="px-2.5 py-1 rounded-full text-[10px] border border-gray-700/50 text-gray-500 hover:text-white hover:border-blue-500/50 hover:bg-blue-500/10 transition-all duration-150"
						onclick={() => sendMessage(chip)}
						disabled={isLoading}
					>
						{chip}
					</button>
				{/each}
			</div>
		{/if}
			<div class="flex gap-3">
				<input
					type="text"
					bind:value={inputText}
					onkeydown={handleKeydown}
					placeholder="Ask about FuelRetail's user data..."
					disabled={isLoading}
					class="flex-1 bg-gray-800/80 border border-gray-700/50 rounded-xl px-4 py-3 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 transition-colors disabled:opacity-50"
				/>
				<button
					class="px-5 py-3 bg-blue-600 hover:bg-blue-500 text-white rounded-xl text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
					onclick={() => sendMessage()}
					disabled={isLoading || !inputText.trim()}
				>
					{#if isLoading}
						<div class="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
					{:else}
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
							<path d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
						</svg>
					{/if}
					Send
				</button>
			</div>
		</div>
	</div>

	<!-- Sidebar (togglable) -->
	{#if showSidebar}
	<div class="w-80 flex-shrink-0 border-l border-gray-700/50 overflow-y-auto bg-FuelRetail-dark/50 animate-slide-in-right">
		<div class="p-4 space-y-4">
			<!-- Stats -->
			<div class="grid grid-cols-3 gap-2">
				<div class="bg-FuelRetail-slate rounded-lg p-3 border border-gray-700/50 text-center">
					<div class="text-lg font-bold text-white tabular-nums">{chatStats.totalQueries}</div>
					<div class="text-[10px] text-gray-500 uppercase tracking-wider mt-0.5">Queries</div>
				</div>
				<div class="bg-FuelRetail-slate rounded-lg p-3 border border-gray-700/50 text-center">
					<div class="text-lg font-bold text-white tabular-nums">
						{chatStats.avgLatencyMs > 0 ? (chatStats.avgLatencyMs / 1000).toFixed(1) + 's' : '--'}
					</div>
					<div class="text-[10px] text-gray-500 uppercase tracking-wider mt-0.5">Avg Time</div>
				</div>
				<div class="bg-FuelRetail-slate rounded-lg p-3 border border-gray-700/50 text-center">
					<div class="text-lg font-bold text-white tabular-nums">{chatStats.activeSessions}</div>
					<div class="text-[10px] text-gray-500 uppercase tracking-wider mt-0.5">Sessions</div>
				</div>
			</div>

			<!-- Why MCP? -->
			<div class="bg-FuelRetail-slate rounded-xl border border-gray-700/50 overflow-hidden">
				<button class="flex items-center justify-between w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors" onclick={() => showWhyMcp = !showWhyMcp}>
					<div class="flex items-center gap-2">
						<svg class="w-4 h-4 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456zM16.894 20.567L16.5 21.75l-.394-1.183a2.25 2.25 0 00-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 001.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 001.423 1.423l1.183.394-1.183.394a2.25 2.25 0 00-1.423 1.423z" />
						</svg>
						<h3 class="text-sm font-semibold text-white">Why MCP?</h3>
					</div>
					<svg class="w-3.5 h-3.5 text-gray-500 transition-transform duration-200 {showWhyMcp ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path d="M19 9l-7 7-7-7" />
					</svg>
				</button>
				{#if showWhyMcp}
					<div class="px-4 pb-4 space-y-3">
						<div class="opacity-50">
							<div class="text-[10px] text-red-400 uppercase tracking-wider font-medium mb-1.5">RAG Approach (SettleGPT)</div>
							<div class="flex items-center gap-1 flex-wrap">
								{#each ['Redshift', 'Embed', 'Vector DB', 'LLM', 'SQL', 'Execute'] as step}
									<span class="px-1.5 py-0.5 rounded text-[9px] bg-red-500/10 text-red-400 font-mono">{step}</span>
									{#if step !== 'Execute'}<span class="text-gray-700 text-[8px]">→</span>{/if}
								{/each}
							</div>
						</div>
						<div>
							<div class="text-[10px] text-emerald-400 uppercase tracking-wider font-medium mb-1.5">MCP Approach</div>
							<div class="flex items-center gap-1 flex-wrap">
								{#each ['MongoDB', 'MCP Server', 'LLM'] as step}
									<span class="px-1.5 py-0.5 rounded text-[9px] bg-emerald-500/10 text-emerald-400 font-mono">{step}</span>
									{#if step !== 'LLM'}<span class="text-gray-600 text-[8px]">→</span>{/if}
								{/each}
							</div>
						</div>
						<div class="grid grid-cols-3 gap-2 pt-1">
							<div class="text-center">
								<div class="text-sm font-bold text-emerald-400">0</div>
								<div class="text-[9px] text-gray-500">Embeddings</div>
							</div>
							<div class="text-center">
								<div class="text-sm font-bold text-emerald-400">0</div>
								<div class="text-[9px] text-gray-500">Templates</div>
							</div>
							<div class="text-center">
								<div class="text-sm font-bold text-emerald-400">Auto</div>
								<div class="text-[9px] text-gray-500">Schema</div>
							</div>
						</div>
					</div>
				{/if}
			</div>

			<!-- Terminology -->
			<div class="bg-FuelRetail-slate rounded-xl border border-gray-700/50 overflow-hidden">
				<button class="flex items-center justify-between w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors" onclick={() => showTerminology = !showTerminology}>
					<div class="flex items-center gap-2">
						<svg class="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25" />
						</svg>
						<h3 class="text-sm font-semibold text-white">Terminology</h3>
						<span class="text-[10px] text-gray-600 font-mono">({terminology.length})</span>
					</div>
					<svg class="w-3.5 h-3.5 text-gray-500 transition-transform duration-200 {showTerminology ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path d="M19 9l-7 7-7-7" />
					</svg>
				</button>
				{#if showTerminology}
					<div class="px-4 pb-3 space-y-2">
						{#each terminology as term}
							<div class="flex items-start gap-2 text-xs">
								<span class="font-medium text-blue-400 min-w-[90px] flex-shrink-0">{term.term}</span>
								<div class="flex-1">
									<span class="text-gray-400">{term.meaning}</span>
									<div class="font-mono text-[10px] text-gray-600 mt-0.5">{term.field}</div>
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Architecture -->
			<div class="bg-FuelRetail-slate rounded-xl border border-gray-700/50 overflow-hidden">
				<button class="flex items-center justify-between w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors" onclick={() => showArchitecture = !showArchitecture}>
					<div class="flex items-center gap-2">
						<svg class="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
						</svg>
						<h3 class="text-sm font-semibold text-white">Architecture</h3>
					</div>
					<svg class="w-3.5 h-3.5 text-gray-500 transition-transform duration-200 {showArchitecture ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
						<path d="M19 9l-7 7-7-7" />
					</svg>
				</button>
				{#if showArchitecture}
					<div class="px-4 pb-4 space-y-3">
						<div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Data Flow</div>
						<div class="space-y-1.5">
							{#each [
								{ label: 'User Question', cls: 'bg-gray-800 text-white' },
								{ label: 'FastAPI + LangChain Agent', cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/20' },
								{ label: 'MongoDB MCP Server (stdio)', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' },
								{ label: 'MongoDB Atlas', cls: 'bg-purple-500/10 text-purple-400 border border-purple-500/20' },
							] as node, i}
								{#if i > 0}
									<div class="flex justify-center">
										<svg class="w-3 h-3 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path d="M19 14l-7 7m0 0l-7-7m7 7V3" />
										</svg>
									</div>
								{/if}
								<div class="px-3 py-2 rounded-lg text-xs font-medium text-center {node.cls}">{node.label}</div>
							{/each}
						</div>
						<p class="text-[10px] text-gray-600 mt-2">MCP reads schema dynamically. No query templates. No vector index. New collections auto-discovered.</p>
					</div>
				{/if}
			</div>

			<!-- Session info -->
			<div class="text-[10px] text-gray-600 px-1">
				<div class="flex items-center gap-2">
					<span class="text-gray-500">Session:</span>
					<span class="font-mono truncate">{sessionId.slice(0, 8)}...</span>
				</div>
				<div class="flex items-center gap-2 mt-1">
					<span class="text-gray-500">Database:</span>
					<span class="font-mono">FuelRetail_screening</span>
				</div>
				<div class="flex items-center gap-2 mt-1">
					<span class="text-gray-500">Collection:</span>
					<span class="font-mono">user_profiles (10k docs)</span>
				</div>
			</div>
		</div>
	</div>
	{/if}
</div>

<!-- ─── History Slide-Out Panel ─────────────────────────────────── -->
{#if showHistory}
	<!-- Backdrop -->
	<button
		class="fixed inset-0 bg-black/50 z-40 animate-fade-in"
		onclick={closeHistory}
		aria-label="Close history"
	></button>

	<!-- Panel -->
	<div class="fixed top-0 right-0 h-full w-[600px] max-w-[90vw] bg-FuelRetail-dark border-l border-gray-700/50 z-50 flex flex-col animate-slide-in-right">

		<!-- ════════════════════════════════════════════════════════════ -->
		<!-- HISTORY LIST VIEW                                           -->
		<!-- ════════════════════════════════════════════════════════════ -->

		<!-- Panel Header -->
		<div class="px-5 py-4 border-b border-gray-700/50 flex items-center justify-between flex-shrink-0">
			<div>
				<h2 class="text-lg font-semibold text-white">Conversation History</h2>
				<p class="text-xs text-gray-500 mt-0.5">Search and resume past conversations</p>
			</div>
			<button class="p-1.5 rounded-lg hover:bg-white/5 text-gray-400 hover:text-white transition-colors" onclick={closeHistory} aria-label="Close history">
				<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<!-- Search Bar -->
		<div class="px-5 py-3 border-b border-gray-700/30 flex-shrink-0">
			<div class="relative">
				<svg class="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
				</svg>
				<input
					type="text"
					bind:value={historyQuery}
					oninput={onHistoryQueryInput}
					placeholder="Search conversations..."
					class="w-full bg-gray-800/80 border border-gray-700/50 rounded-lg pl-10 pr-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500/50 transition-colors"
				/>
			</div>

			<!-- Active Filter Pills -->
			{#if Object.keys(historyFilters).length > 0}
				<div class="flex flex-wrap gap-1.5 mt-2.5">
					{#each Object.entries(historyFilters) as [field, values]}
						{#each values as value}
							<button
								class="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] bg-blue-500/15 text-blue-300 hover:bg-blue-500/25 transition-colors"
								onclick={() => removeFilter(field, value)}
							>
								{value}
								<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
									<path d="M6 18L18 6M6 6l12 12" />
								</svg>
							</button>
						{/each}
					{/each}
					<button
						class="text-[10px] text-gray-500 hover:text-gray-300 transition-colors px-1"
						onclick={clearAllFilters}
					>
						Clear all
					</button>
				</div>
			{/if}
			<!-- Inspector Toggle -->
			<button
				class="flex items-center gap-1.5 mt-2.5 text-[10px] font-medium transition-colors text-gray-500 hover:text-emerald-400"
				onclick={openInspector}
			>
				<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
				</svg>
				Query Inspector
			</button>
		</div>

		<!-- Inline inspector panel removed — now a full overlay popup below -->

		<!-- Content: Facets + Results -->
		<div class="flex-1 flex overflow-hidden">
			<!-- Facet Sidebar -->
			{#if historyFacets.length > 0}
				<div class="w-48 flex-shrink-0 border-r border-gray-700/30 overflow-y-auto p-3 space-y-3">
					{#each historyFacets as facet}
						<div>
							<div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1.5">{facet.label}</div>
							<div class="space-y-0.5">
								{#each facet.buckets.slice(0, 8) as bucket}
									{@const isActive = (historyFilters[facet.field] || []).includes(bucket.value)}
									<button
										class="flex items-center justify-between w-full px-2 py-1 rounded text-xs transition-colors {isActive ? 'bg-blue-500/15 text-blue-300' : 'text-gray-400 hover:text-gray-200 hover:bg-white/[0.03]'}"
										onclick={() => toggleFilter(facet.field, bucket.value)}
									>
										<span class="truncate">{bucket.value}</span>
										<span class="text-[10px] font-mono text-gray-600 ml-1 flex-shrink-0">{bucket.count}</span>
									</button>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Results List -->
			<div class="flex-1 overflow-y-auto p-4 space-y-3">
				{#if historyLoading && historyResults.length === 0}
					<div class="flex items-center justify-center h-32">
						<div class="w-5 h-5 border-2 border-blue-400/30 border-t-blue-400 rounded-full animate-spin"></div>
					</div>
				{:else if historyResults.length === 0}
					<div class="flex flex-col items-center justify-center h-32 text-gray-500">
						<svg class="w-8 h-8 mb-2 opacity-50" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M20.25 7.5l-.625 10.632a2.25 2.25 0 01-2.247 2.118H6.622a2.25 2.25 0 01-2.247-2.118L3.75 7.5m6 4.125l2.25 2.25m0 0l2.25 2.25M12 13.875l2.25-2.25M12 13.875l-2.25 2.25M3.375 7.5h17.25c.621 0 1.125-.504 1.125-1.125v-1.5c0-.621-.504-1.125-1.125-1.125H3.375c-.621 0-1.125.504-1.125 1.125v1.5c0 .621.504 1.125 1.125 1.125z" />
						</svg>
						<p class="text-sm">No conversations found</p>
						<p class="text-xs text-gray-600 mt-1">Start chatting to build your history</p>
					</div>
				{:else}
					{#each historyResults as result}
						<div class="bg-FuelRetail-slate rounded-xl border border-gray-700/50 p-4 hover:border-gray-600/50 transition-colors">
							<!-- Title + Actions -->
							<div class="flex items-start justify-between gap-3 mb-2">
								<h3 class="text-sm font-medium text-white leading-snug">
									{result.title || 'Untitled conversation'}
								</h3>
							<button
								class="flex-shrink-0 px-2.5 py-1 rounded-lg text-[10px] font-medium bg-blue-600/20 text-blue-400 hover:bg-blue-600/30 transition-colors"
								onclick={() => resumeConversation(result.threadId)}
							>
								Resume
							</button>
							</div>

							<!-- Highlighted summary -->
							{#if getBestHighlight(result.highlights)}
								<p class="text-xs text-gray-400 mb-2 leading-relaxed line-clamp-2">
									{@html getBestHighlight(result.highlights)}
								</p>
							{:else if result.summary}
								<p class="text-xs text-gray-400 mb-2 leading-relaxed line-clamp-2">{result.summary}</p>
							{/if}

							<!-- Last question -->
							{#if result.lastQuestion}
								<div class="text-xs text-gray-500 italic border-l-2 border-gray-700 pl-2 mb-2.5 line-clamp-1">
									"{result.lastQuestion}"
								</div>
							{/if}

							<!-- Metadata chips -->
							<div class="flex items-center gap-1.5 flex-wrap">
								{#if result.category}
									<span class="px-1.5 py-0.5 rounded text-[9px] bg-purple-500/10 text-purple-400">{result.category}</span>
								{/if}
								{#if result.complexity}
									<span class="px-1.5 py-0.5 rounded text-[9px] {
										result.complexity === 'simple' ? 'bg-green-500/10 text-green-400' :
										result.complexity === 'moderate' ? 'bg-yellow-500/10 text-yellow-400' :
										'bg-red-500/10 text-red-400'
									}">{result.complexity}</span>
								{/if}
								<span class="px-1.5 py-0.5 rounded text-[9px] bg-gray-500/10 text-gray-500">{result.turnCount} turn{result.turnCount !== 1 ? 's' : ''}</span>
								{#if result.createdAt}
									<span class="text-[9px] text-gray-600 font-mono">{formatDate(result.createdAt)}</span>
								{/if}
							</div>

							<!-- Score bar -->
							{#if result.score > 0}
								<div class="mt-2.5 flex items-center gap-2">
									<div class="flex-1 h-1 bg-gray-800 rounded-full overflow-hidden">
										<div
											class="h-full bg-gradient-to-r from-blue-500 to-purple-500 rounded-full"
											style="width: {Math.min(result.score * 100, 100)}%"
										></div>
									</div>
									<span class="text-[9px] text-gray-600 font-mono">{result.score.toFixed(2)}</span>
								</div>
							{/if}
						</div>
					{/each}

					<!-- Load More -->
					{#if historyHasMore}
						<button
							class="w-full py-2.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
							onclick={() => searchHistory(true)}
							disabled={historyLoading}
						>
							{#if historyLoading}
								<div class="w-4 h-4 border-2 border-gray-500/30 border-t-gray-400 rounded-full animate-spin mx-auto"></div>
							{:else}
								Load more {#if historyTotal}({historyResults.length} of ~{historyTotal}){/if}
							{/if}
						</button>
					{/if}
				{/if}
			</div>
		</div>
	</div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- QUERY INSPECTOR OVERLAY POPUP                                      -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
{#if showInspector}
<div
	class="fixed inset-0 z-[100] flex items-center justify-center p-6"
	role="dialog"
	aria-modal="true"
	aria-label="Query Inspector"
>
	<!-- Backdrop -->
	<button class="absolute inset-0 bg-black/60 backdrop-blur-sm cursor-default" onclick={closeInspector} aria-label="Close inspector backdrop"></button>

	<!-- Modal Card -->
	<div class="relative w-full max-w-[860px] max-h-[82vh] bg-[#0c0f14] border border-gray-700/50 rounded-2xl shadow-2xl shadow-black/50 flex flex-col overflow-hidden ring-1 ring-emerald-500/10">

		<!-- Header -->
		<div class="flex items-center justify-between px-6 py-4 border-b border-gray-800/80 flex-shrink-0">
			<div class="flex items-center gap-3">
				<div class="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-500/20 via-blue-500/20 to-purple-500/20 flex items-center justify-center border border-emerald-500/20">
					<svg class="w-4.5 h-4.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
					</svg>
				</div>
				<div>
					<h2 class="text-sm font-semibold text-white">Live Query Inspector</h2>
					<div class="flex items-center gap-2 mt-0.5">
						<div class="flex items-center gap-1.5 px-2 py-0.5 rounded bg-emerald-500/10 border border-emerald-500/15">
							<svg class="w-2.5 h-2.5 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path d="M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375" />
							</svg>
							<span class="text-[9px] font-mono text-emerald-300">FuelRetail_screening.chat_conversations</span>
						</div>
						<span class="text-[9px] text-gray-600">index:</span>
						<span class="text-[9px] font-mono text-gray-400">conversation_search</span>
					</div>
				</div>
			</div>
			<button class="p-2 rounded-lg hover:bg-white/5 text-gray-500 hover:text-white transition-colors" onclick={closeInspector} aria-label="Close inspector">
				<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
					<path d="M6 18L18 6M6 6l12 12" />
				</svg>
			</button>
		</div>

		<!-- Tabs -->
		<div class="flex gap-1 px-6 pt-3 pb-0 flex-shrink-0">
			<button
				class="px-4 py-2 rounded-t-lg text-xs font-medium transition-all border border-b-0 {inspectorTab === 'search' ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'text-gray-500 hover:text-gray-300 border-transparent hover:border-gray-700/50'}"
				onclick={() => inspectorTab = 'search'}
			>
				<span class="flex items-center gap-1.5">
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
					</svg>
					$search Pipeline
				</span>
			</button>
			<button
				class="px-4 py-2 rounded-t-lg text-xs font-medium transition-all border border-b-0 {inspectorTab === 'facet' ? 'bg-purple-500/10 text-purple-400 border-purple-500/20' : 'text-gray-500 hover:text-gray-300 border-transparent hover:border-gray-700/50'}"
				onclick={() => inspectorTab = 'facet'}
			>
				<span class="flex items-center gap-1.5">
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25A2.25 2.25 0 0113.5 18v-2.25z" />
					</svg>
					$searchMeta Pipeline
				</span>
			</button>
			<button
				class="px-4 py-2 rounded-t-lg text-xs font-medium transition-all border border-b-0 {inspectorTab === 'flow' ? 'bg-blue-500/10 text-blue-400 border-blue-500/20' : 'text-gray-500 hover:text-gray-300 border-transparent hover:border-gray-700/50'}"
				onclick={() => inspectorTab = 'flow'}
			>
				<span class="flex items-center gap-1.5">
					<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5" />
					</svg>
					Data Flow
				</span>
			</button>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto px-6 py-5 border-t border-gray-800/60">

			<!-- TAB: $search Pipeline -->
			{#if inspectorTab === 'search'}
				{#if debugPipeline}
					<!-- $rankFusion annotation -->
					{@const rfStage = debugPipeline.find(s => s['$rankFusion'])}
					{#if rfStage}
						<div class="mb-4 p-3.5 rounded-lg bg-gradient-to-r from-emerald-500/5 via-blue-500/5 to-purple-500/5 border border-emerald-500/15">
							<div class="flex items-center gap-2 mb-2.5">
								<span class="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">$rankFusion</span>
								<span class="text-[10px] text-gray-400">Reciprocal Rank Fusion — two independent pipelines merged</span>
							</div>
							<div class="grid grid-cols-2 gap-2.5">
								<div class="rounded-lg bg-blue-500/5 border border-blue-500/15 p-2.5">
									<div class="flex items-center gap-1.5 mb-1">
										<span class="w-1.5 h-1.5 rounded-full bg-blue-400"></span>
										<span class="text-[9px] font-semibold text-blue-400 uppercase tracking-wider">textSearch pipeline</span>
									</div>
									<div class="text-[10px] text-gray-500 leading-relaxed"><code class="text-blue-300/80 bg-blue-500/10 px-1 rounded text-[9px]">$search</code> — fuzzy full-text across title, summary, messages, and MQL fields</div>
								</div>
								<div class="rounded-lg bg-purple-500/5 border border-purple-500/15 p-2.5">
									<div class="flex items-center gap-1.5 mb-1">
										<span class="w-1.5 h-1.5 rounded-full bg-purple-400"></span>
										<span class="text-[9px] font-semibold text-purple-400 uppercase tracking-wider">vectorSearch pipeline</span>
									</div>
									<div class="text-[10px] text-gray-500 leading-relaxed"><code class="text-purple-300/80 bg-purple-500/10 px-1 rounded text-[9px]">$vectorSearch</code> — Voyage AI embedding similarity (1024-dim cosine)</div>
								</div>
							</div>
						</div>
					{/if}

					<!-- Pipeline JSON -->
					<div class="relative group">
						<pre class="text-[11px] font-mono leading-relaxed p-4 rounded-lg bg-gray-950 border border-emerald-500/10 text-emerald-300/90 overflow-x-auto whitespace-pre-wrap break-all max-h-[50vh] overflow-y-auto"><code>{JSON.stringify(debugPipeline, null, 2)}</code></pre>
						<button
							class="absolute top-2.5 right-2.5 px-2 py-1 rounded-md bg-gray-800/90 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-all text-[10px] font-medium flex items-center gap-1"
							onclick={() => navigator.clipboard.writeText(JSON.stringify(debugPipeline, null, 2))}
							title="Copy pipeline"
						>
							<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
							</svg>
							Copy
						</button>
					</div>
				{:else}
					<div class="flex flex-col items-center justify-center h-40 text-gray-600">
						<svg class="w-10 h-10 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
							<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
						</svg>
						<p class="text-xs">Type a search query to see the pipeline</p>
						<p class="text-[10px] text-gray-700 mt-1">The pipeline updates live as you search</p>
					</div>
				{/if}

			<!-- TAB: $searchMeta Pipeline -->
			{:else if inspectorTab === 'facet'}
				{#if debugFacetPipeline}
					<div class="mb-3 flex items-center gap-2">
						<span class="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-purple-500/15 text-purple-400 border border-purple-500/20">$searchMeta</span>
						<span class="text-[10px] text-gray-500">Facet counting pipeline &mdash; text-only (rankFusion not supported in $searchMeta)</span>
					</div>
					<div class="relative group">
						<pre class="text-[11px] font-mono leading-relaxed p-4 rounded-lg bg-gray-950 border border-purple-500/10 text-purple-300/90 overflow-x-auto whitespace-pre-wrap break-all max-h-[50vh] overflow-y-auto"><code>{JSON.stringify(debugFacetPipeline, null, 2)}</code></pre>
						<button
							class="absolute top-2.5 right-2.5 px-2 py-1 rounded-md bg-gray-800/90 text-gray-500 hover:text-white opacity-0 group-hover:opacity-100 transition-all text-[10px] font-medium flex items-center gap-1"
							onclick={() => navigator.clipboard.writeText(JSON.stringify(debugFacetPipeline, null, 2))}
							title="Copy pipeline"
						>
							<svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
								<path d="M15.666 3.888A2.25 2.25 0 0013.5 2.25h-3c-1.03 0-1.9.693-2.166 1.638m7.332 0c.055.194.084.4.084.612v0a.75.75 0 01-.75.75H9.75a.75.75 0 01-.75-.75v0c0-.212.03-.418.084-.612m7.332 0c.646.049 1.288.11 1.927.184 1.1.128 1.907 1.077 1.907 2.185V19.5a2.25 2.25 0 01-2.25 2.25H6.75A2.25 2.25 0 014.5 19.5V6.257c0-1.108.806-2.057 1.907-2.185a48.208 48.208 0 011.927-.184" />
							</svg>
							Copy
						</button>
					</div>
				{:else}
					<div class="flex flex-col items-center justify-center h-40 text-gray-600">
						<svg class="w-10 h-10 mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
							<path d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6z" />
						</svg>
						<p class="text-xs">Type a search query to see the facet pipeline</p>
					</div>
				{/if}

			<!-- TAB: Data Flow -->
			{:else}
				<div class="space-y-6">
					<!-- Architecture Flow: horizontal pipeline -->
					<div>
						<div class="text-[9px] text-gray-500 uppercase tracking-wider font-semibold mb-3">Search Architecture</div>
						<div class="flex items-stretch gap-0 overflow-x-auto pb-2">
							{#each [
								{ icon: 'M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z', label: 'Search Query', sub: 'User types text', cls: 'from-blue-500/15 to-blue-600/10 border-blue-500/20 text-blue-400' },
								{ icon: 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z', label: 'Voyage AI', sub: 'Embed query → 1024d', cls: 'from-purple-500/15 to-purple-600/10 border-purple-500/20 text-purple-400' },
								{ icon: 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5', label: '$rankFusion', sub: 'RRF merge: $search + $vectorSearch', cls: 'from-emerald-500/15 to-emerald-600/10 border-emerald-500/20 text-emerald-400' },
								{ icon: 'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375', label: 'Atlas Search', sub: 'conversation_search + conversation_vector', cls: 'from-green-500/15 to-green-600/10 border-green-500/20 text-green-400' },
							] as node, i}
								{#if i > 0}
									<div class="flex items-center px-1.5 flex-shrink-0">
										<svg class="w-4 h-4 text-gray-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
											<path d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
										</svg>
									</div>
								{/if}
								<div class="flex-1 min-w-[120px] px-3.5 py-3 rounded-lg bg-gradient-to-br {node.cls} border text-center flex-shrink-0">
									<svg class="w-5 h-5 mx-auto mb-1 {node.cls.split(' ').pop()}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
										<path d={node.icon} />
									</svg>
									<div class="text-[10px] font-semibold">{node.label}</div>
									<div class="text-[8px] text-gray-500 mt-0.5">{node.sub}</div>
								</div>
							{/each}
						</div>
					</div>

					<!-- How data reaches the collection -->
					<div>
						<div class="text-[9px] text-gray-500 uppercase tracking-wider font-semibold mb-3">How Data Reaches This Collection</div>
						<div class="space-y-0">
							{#each [
								{ label: 'LangGraph Agent', sub: 'User asks a question via the analytics chatbot', bg: 'bg-purple-500/15 border-purple-500/20', text: 'text-purple-400', icon: 'M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z' },
								{ label: '_save_conversation_turn()', sub: 'Fire-and-forget task persists Q&A pair, MQL, and latency', bg: 'bg-blue-500/15 border-blue-500/20', text: 'text-blue-400', icon: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z' },
								{ label: 'chat_conversations', sub: 'MongoDB collection with threadId, messages, metadata', bg: 'bg-emerald-500/15 border-emerald-500/20', text: 'text-emerald-400', icon: 'M20.25 6.375c0 2.278-3.694 4.125-8.25 4.125S3.75 8.653 3.75 6.375m16.5 0c0-2.278-3.694-4.125-8.25-4.125S3.75 4.097 3.75 6.375m16.5 0v11.25c0 2.278-3.694 4.125-8.25 4.125s-8.25-1.847-8.25-4.125V6.375' },
								{ label: '_generate_conversation_metadata()', sub: 'LLM classifies + Voyage AI generates searchEmbedding (1024-dim)', bg: 'bg-amber-500/15 border-amber-500/20', text: 'text-amber-400', icon: 'M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z' },
								{ label: 'Atlas Search Index', sub: 'conversation_search — full-text, fuzzy, faceted, and knnVector (searchEmbedding)', bg: 'bg-cyan-500/15 border-cyan-500/20', text: 'text-cyan-400', icon: 'M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z' },
							] as step, i}
								<div class="flex items-start gap-3 relative">
									{#if i < 4}
										<div class="absolute left-[13px] top-7 bottom-0 w-px bg-gradient-to-b from-gray-700 to-transparent"></div>
									{/if}
									<div class="w-7 h-7 rounded-full {step.bg} border flex items-center justify-center flex-shrink-0">
										<svg class="w-3.5 h-3.5 {step.text}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
											<path d={step.icon} />
										</svg>
									</div>
									<div class="pb-4 min-w-0">
										<div class="text-[11px] font-mono font-semibold text-gray-200">{step.label}</div>
										<div class="text-[10px] text-gray-500 mt-0.5 leading-relaxed">{step.sub}</div>
									</div>
								</div>
							{/each}
						</div>
					</div>

					<!-- LangGraph memory integration -->
					<div class="border-t border-gray-800 pt-4">
						<div class="text-[9px] text-gray-500 uppercase tracking-wider font-semibold mb-2.5">LangGraph Memory Integration</div>
						<div class="grid grid-cols-2 gap-3">
							<div class="rounded-lg bg-purple-500/5 border border-purple-500/15 p-3">
								<div class="text-[9px] text-purple-400 font-semibold mb-1">Short-term: MongoDBSaver</div>
								<div class="text-[10px] text-gray-500 leading-relaxed">LangGraph checkpointer stores full agent state (tool calls, reasoning) per thread_id. Enables conversation resume.</div>
							</div>
							<div class="rounded-lg bg-blue-500/5 border border-blue-500/15 p-3">
								<div class="text-[9px] text-blue-400 font-semibold mb-1">Long-term: MongoDBStore</div>
								<div class="text-[10px] text-gray-500 leading-relaxed">Voyage AI embeddings store user preferences across sessions in agent_memories collection.</div>
							</div>
						</div>
						<div class="mt-2.5 px-3 py-2 rounded-lg bg-gray-800/40 border border-gray-700/30 text-[10px] text-gray-500">
							<span class="text-gray-400 font-mono">chat_conversations</span> is separate from the checkpointer &mdash; it's a denormalized copy optimized for Atlas Search with LLM-enriched metadata and vector embeddings.
						</div>
					</div>
				</div>
			{/if}

		</div>
	</div>
</div>
{/if}
