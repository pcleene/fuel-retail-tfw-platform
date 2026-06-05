<script lang="ts">
	import { onMount } from 'svelte';
	import { fraud, connectFraudSSE } from '$lib/api';
	import type { SSEEventType } from '$lib/api';

	// Data
	let stats = $state<any>(null);
	let events = $state<any[]>([]);
	let alerts = $state<any[]>([]);
	let signalRules = $state<any[]>([]);
	let flaggedUsers = $state<any[]>([]);
	let similarResults = $state<Record<string, any[]>>({});
	let loadingSimilar = $state<Record<string, boolean>>({});

	// Simulator
	let selectedScenario = $state('signal_1');
	let customUserId = $state('');
	let simulating = $state(false);
	let simResult = $state<any>(null);

	// UI toggles
	let activeTab = $state<'stream' | 'investigations' | 'users' | 'config'>('stream');
	let expandedAlerts = $state<Record<string, boolean>>({});
	let expandedUsers = $state<Record<string, boolean>>({});
	let editingRule = $state<Record<string, Record<string, boolean>>>({});
	let editValues = $state<Record<string, Record<string, any>>>({});

	// SSE + Investigation
	let sseConnected = $state(false);
	let activeInvestigations = $state<Record<string, any>>({});
	let completedInvestigations = $state<any[]>([]);
	let expandedInvestigation = $state<Record<string, boolean>>({});
	let showQueries = $state<Record<string, boolean>>({});
	let investigating = $state<Record<string, boolean>>({});

	const scenarios = [
		{ value: 'signal_1', label: 'S01', desc: '2x auto top-up >= RM500 + InstantTransfer transfer out' },
		{ value: 'signal_2', label: 'S02', desc: 'InstantTransfer payment > RM500 after top-up' },
		{ value: 'signal_3', label: 'S03', desc: '2x fund-out > RM500 after top-up' },
		{ value: 'signal_4', label: 'S04', desc: '3+ cards linked in 1 hour' },
		{ value: 'clean', label: 'Clean', desc: 'Normal low-value transactions' },
	];

	const signalColors: Record<string, string> = {
		S01: 'bg-red-500/20 text-red-400', S02: 'bg-orange-500/20 text-orange-400',
		S03: 'bg-amber-500/20 text-amber-400', S04: 'bg-purple-500/20 text-purple-400'
	};
	const severityColors: Record<string, string> = {
		critical: 'bg-red-500/20 text-red-400', high: 'bg-orange-500/20 text-orange-400',
		medium: 'bg-amber-500/20 text-amber-400', low: 'bg-emerald-500/20 text-emerald-400'
	};
	const eventColors: Record<string, string> = {
		auto_topup: 'bg-blue-500/20 text-blue-400', manual_topup: 'bg-blue-500/20 text-blue-400',
		InstantTransfer_transfer_out: 'bg-emerald-500/20 text-emerald-400', InstantTransfer_payment: 'bg-emerald-500/20 text-emerald-400',
		card_linked: 'bg-purple-500/20 text-purple-400',
		fund_out_transfer: 'bg-orange-500/20 text-orange-400',
		fuel_purchase: 'bg-gray-500/20 text-gray-400',
	};

	const stageLabels: Record<string, string> = {
		fraud_analysis: 'Analyzing', similar_cases: 'Similar Cases',
		recommendation: 'Recommending', persist: 'Saving'
	};
	const stages = ['fraud_analysis', 'similar_cases', 'recommendation', 'persist'];

	const tabs = [
		{ id: 'stream' as const, label: 'Live Stream', icon: 'M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z' },
		{ id: 'investigations' as const, label: 'Investigations', icon: 'M9.75 3.104v5.714a2.25 2.25 0 01-.659 1.591L5 14.5M9.75 3.104c-.251.023-.501.05-.75.082m.75-.082a24.301 24.301 0 014.5 0m0 0v5.714c0 .597.237 1.17.659 1.591L19.8 15.3M14.25 3.104c.251.023.501.05.75.082M19.8 15.3l-1.57.393A9.065 9.065 0 0112 15a9.065 9.065 0 00-6.23.693L5 14.5m14.8.8l1.402 1.402c1.232 1.232.65 3.318-1.067 3.611A48.309 48.309 0 0112 21c-2.773 0-5.491-.235-8.135-.687-1.718-.293-2.3-2.379-1.067-3.61L5 14.5' },
		{ id: 'users' as const, label: 'Flagged Users', icon: 'M18 18.72a9.094 9.094 0 003.741-.479 3 3 0 00-4.682-2.72m.94 3.198l.001.031c0 .225-.012.447-.037.666A11.944 11.944 0 0112 21c-2.17 0-4.207-.576-5.963-1.584A6.062 6.062 0 016 18.719m12 0a5.971 5.971 0 00-.941-3.197m0 0A5.995 5.995 0 0012 12.75a5.995 5.995 0 00-5.058 2.772m0 0a3 3 0 00-4.681 2.72 8.986 8.986 0 003.74.477m.94-3.197a5.971 5.971 0 00-.94 3.197M15 6.75a3 3 0 11-6 0 3 3 0 016 0zm6 3a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0zm-13.5 0a2.25 2.25 0 11-4.5 0 2.25 2.25 0 014.5 0z' },
		{ id: 'config' as const, label: 'Configuration', icon: 'M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 011.37.49l1.296 2.247a1.125 1.125 0 01-.26 1.431l-1.003.827c-.293.241-.438.613-.43.992a7.723 7.723 0 010 .255c-.008.378.137.75.43.991l1.004.827c.424.35.534.955.26 1.43l-1.298 2.247a1.125 1.125 0 01-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.47 6.47 0 01-.22.128c-.331.183-.581.495-.644.869l-.213 1.281c-.09.543-.56.94-1.11.94h-2.594c-.55 0-1.019-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 01-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 01-1.369-.49l-1.297-2.247a1.125 1.125 0 01.26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 010-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 01-.26-1.43l1.297-2.247a1.125 1.125 0 011.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.086.22-.128.332-.183.582-.495.644-.869l.214-1.28z' },
	];

	async function loadAll() {
		try {
			const [s, e, a, r, f, inv] = await Promise.all([
				fraud.stats(), fraud.recentEvents(50), fraud.alerts(50),
				fraud.signalRules(), fraud.flaggedUsers(), fraud.investigations(20),
			]);
			stats = s; events = e; alerts = a; signalRules = r; flaggedUsers = f;
			completedInvestigations = inv;
		} catch (err) { console.error('Load failed:', err); }
	}

	async function refresh() {
		try {
			const [s, e, a] = await Promise.all([
				fraud.stats(), fraud.recentEvents(50), fraud.alerts(50),
			]);
			stats = s; events = e; alerts = a;
		} catch (err) { console.error('Refresh failed:', err); }
	}

	async function runSimulation() {
		simulating = true;
		simResult = null;
		try {
			simResult = await fraud.simulate(selectedScenario, customUserId || undefined);
			setTimeout(async () => {
				await refresh();
				flaggedUsers = await fraud.flaggedUsers();
			}, 2000);
			setTimeout(refresh, 5000);
		} catch (err: any) {
			simResult = { error: err.message };
		} finally { simulating = false; }
	}

	async function saveRule(key: string, field: string, value: any) {
		try {
			await fraud.updateSignalRule(key, { [field]: Number(value) });
			signalRules = await fraud.signalRules();
			editingRule[key] = { ...editingRule[key], [field]: false };
		} catch (err) { console.error('Save rule failed:', err); }
	}

	async function findSimilar(userId: string) {
		loadingSimilar[userId] = true;
		try {
			similarResults[userId] = await fraud.similarUsers(userId);
		} catch (err) {
			console.error('Similarity search failed:', err);
			similarResults[userId] = [];
		} finally { loadingSimilar[userId] = false; }
	}

	function handleSSE(event: SSEEventType, data: any) {
		if (event === 'connected') {
			sseConnected = true;
		} else if (event === 'new_alert') {
			alerts = [data, ...alerts.slice(0, 49)];
			fraud.stats().then(s => stats = s);
		} else if (event === 'investigation_status') {
			activeInvestigations = { ...activeInvestigations, [data.userId]: data };
		} else if (event === 'investigation_complete') {
			const { [data.userId]: _, ...rest } = activeInvestigations;
			activeInvestigations = rest;
			investigating = { ...investigating, [data.userId]: false };
			expandedInvestigation = { ...expandedInvestigation, [data.investigationId]: true };
			// Reload from DB to get the full persisted investigation
			fraud.investigations(20).then(inv => completedInvestigations = inv);
			fraud.flaggedUsers().then(f => flaggedUsers = f);
		}
	}

	async function triggerInvestigation(userId: string) {
		investigating = { ...investigating, [userId]: true };
		try {
			await fraud.investigate(userId);
		} catch (err: any) {
			console.error('Investigation trigger failed:', err);
			investigating = { ...investigating, [userId]: false };
		}
	}

	function formatTime(ts: string) {
		if (!ts) return '\u2014';
		return new Date(ts).toLocaleTimeString('en-MY', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
	}
	function formatDate(ts: string) {
		if (!ts) return '\u2014';
		const d = new Date(ts);
		return d.toLocaleDateString('en-MY', { month: 'short', day: 'numeric' }) + ' ' + formatTime(ts);
	}
	function formatAmount(val: any) {
		if (val == null) return '\u2014';
		return `RM ${Number(val).toLocaleString('en-MY', { minimumFractionDigits: 2 })}`;
	}

	onMount(() => {
		loadAll();
		const interval = setInterval(refresh, 3000);
		const closeSSE = connectFraudSSE(handleSSE);
		return () => {
			clearInterval(interval);
			closeSSE();
		};
	});
</script>

<div class="p-6 space-y-4">
	<!-- Header -->
	<div class="flex items-start justify-between mb-1">
		<div>
			<h1 class="text-2xl font-semibold text-white">Fraud Detection</h1>
			<p class="text-sm text-gray-400 mt-1">MSK + Atlas Stream Processing — Real-time fraud signal detection</p>
		</div>
		<div class="flex items-center gap-2">
			<div class="w-2 h-2 rounded-full {sseConnected ? 'bg-emerald-400 animate-pulse' : 'bg-gray-600'}"></div>
			<span class="text-[10px] text-gray-500">{sseConnected ? 'Live' : 'Connecting...'}</span>
		</div>
	</div>

	<!-- Stats -->
	{#if stats}
		<div class="grid grid-cols-5 gap-4">
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Total Events</div>
				<div class="text-2xl font-bold text-white mt-1">{stats.totalEvents?.toLocaleString() ?? 0}</div>
			</div>
			<div class="card border-red-500/30!">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Total Alerts</div>
				<div class="text-2xl font-bold text-red-400 mt-1">{stats.totalAlerts?.toLocaleString() ?? 0}</div>
			</div>
			<div class="card border-orange-500/30!">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Flagged Users</div>
				<div class="text-2xl font-bold text-orange-400 mt-1">{stats.flaggedUsers ?? 0}</div>
			</div>
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Events Last Hour</div>
				<div class="text-2xl font-bold text-white mt-1">{stats.eventsLastHour ?? 0}</div>
			</div>
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Alerts Today</div>
				<div class="text-2xl font-bold text-white mt-1">{stats.alertsToday ?? 0}</div>
			</div>
		</div>
	{/if}

	<!-- Tab Bar -->
	<div class="flex border-b border-gray-700/50">
		{#each tabs as tab}
			<button
				class="flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px {activeTab === tab.id ? 'border-FuelRetail-red text-white' : 'border-transparent text-gray-500 hover:text-gray-300'}"
				onclick={() => activeTab = tab.id}
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d={tab.icon} />
				</svg>
				{tab.label}
				{#if tab.id === 'investigations' && (Object.keys(activeInvestigations).length > 0 || completedInvestigations.length > 0)}
					<span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse"></span>
				{/if}
				{#if tab.id === 'users'}
					<span class="font-mono text-[10px] text-gray-600">({flaggedUsers.length})</span>
				{/if}
			</button>
		{/each}
	</div>

	<!-- ========== TAB 1: LIVE STREAM ========== -->
	{#if activeTab === 'stream'}
		<!-- Simulator -->
		<div class="card border-orange-500/30!">
			<div class="flex items-center justify-between mb-3">
				<div class="flex items-center gap-2">
					<svg class="w-4 h-4 text-orange-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
					</svg>
					<h2 class="text-sm font-semibold text-white">Event Simulator</h2>
				</div>
				<div class="flex items-center gap-1.5 text-[10px] font-mono">
					<span class="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">Events</span>
					<span class="text-gray-600">&rarr;</span>
					<span class="px-1.5 py-0.5 rounded bg-orange-500/10 text-orange-400">MSK</span>
					<span class="text-gray-600">&rarr;</span>
					<span class="px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">ASP</span>
					<span class="text-gray-600">&rarr;</span>
					<span class="px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400">MongoDB</span>
					<span class="text-gray-600">&rarr;</span>
					<span class="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400">Agent</span>
					<span class="text-gray-600">&rarr;</span>
					<span class="px-1.5 py-0.5 rounded bg-gray-800 text-gray-400">UI</span>
				</div>
			</div>
			<div class="flex items-end gap-3">
				<div class="flex-1">
					<label for="scenario" class="block text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">Scenario</label>
					<select id="scenario" bind:value={selectedScenario}
						class="w-full bg-gray-800/80 border border-gray-700/50 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-FuelRetail-red/50 transition-colors">
						{#each scenarios as s}
							<option value={s.value}>{s.label} — {s.desc}</option>
						{/each}
					</select>
				</div>
				<div class="w-48">
					<label for="userId" class="block text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">User ID (optional)</label>
					<input id="userId" type="text" bind:value={customUserId} placeholder="Auto-generated"
						class="w-full bg-gray-800/80 border border-gray-700/50 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-FuelRetail-red/50 transition-colors" />
				</div>
				<button class="btn-red text-sm flex items-center gap-2" onclick={runSimulation} disabled={simulating}>
					{#if simulating}
						<div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
						Producing...
					{:else}
						Produce Events
					{/if}
				</button>
			</div>
			{#if simResult}
				<div class="mt-3 px-3 py-2.5 rounded-lg text-sm {simResult.error ? 'bg-red-500/10 border border-red-500/20 text-red-300' : 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-300'}">
					{#if simResult.error}
						<strong>Error:</strong> {simResult.error}
					{:else}
						Produced <strong>{simResult.eventsProduced}</strong> events for <span class="font-mono text-xs text-gray-400">{simResult.userId}</span>
						{#if simResult.mode}<span class="font-mono text-[10px] text-gray-600 ml-2">via {simResult.mode}</span>{/if}
						{#if simResult.events?.length}
							<div class="flex gap-1.5 mt-2 flex-wrap">
								{#each simResult.events as evt}
									<span class="font-mono text-[10px] px-1.5 py-0.5 rounded {eventColors[evt.name] ?? 'bg-gray-500/20 text-gray-400'}">{evt.name}</span>
								{/each}
							</div>
						{/if}
					{/if}
				</div>
			{/if}
		</div>

		<!-- Two columns: Events + Alerts -->
		<div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
			<!-- Live Events -->
			<div class="card p-0!">
				<div class="flex items-center justify-between px-4 py-3 border-b border-gray-700/50">
					<div class="flex items-center gap-2">
						<div class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
						<h2 class="text-sm font-semibold text-white">Live Events</h2>
					</div>
					<span class="font-mono text-[10px] text-gray-500">{events.length}</span>
				</div>
				<div class="max-h-[460px] overflow-y-auto">
					{#each events as evt}
						<div class="flex items-center gap-2 px-4 py-2 text-xs border-b border-gray-700/20 hover:bg-white/[0.02] transition-colors">
							<span class="font-mono text-[11px] text-gray-600 min-w-[65px] tabular-nums">{formatTime(evt.timestamp)}</span>
							<span class="font-mono text-[10px] font-medium px-1.5 py-0.5 rounded whitespace-nowrap {eventColors[evt.name] ?? 'bg-gray-500/20 text-gray-400'}">{evt.name}</span>
							<span class="text-gray-500 truncate">{evt.user_id}</span>
							{#if evt.properties?.amount}
								<span class="text-white font-medium ml-auto tabular-nums">{formatAmount(evt.properties.amount)}</span>
							{/if}
							{#if evt.properties?.last4}
								<span class="text-gray-600">****{evt.properties.last4}</span>
							{/if}
							{#if evt.properties?.recipient}
								<span class="text-gray-600">&rarr; {evt.properties.recipient}</span>
							{/if}
						</div>
					{:else}
						<div class="py-16 text-center text-sm text-gray-600">No events yet — run the simulator above</div>
					{/each}
				</div>
			</div>

			<!-- Fraud Alerts -->
			<div class="card p-0!">
				<div class="flex items-center justify-between px-4 py-3 border-b border-gray-700/50">
					<div class="flex items-center gap-2">
						<div class="w-2 h-2 rounded-full bg-red-400 animate-pulse"></div>
						<h2 class="text-sm font-semibold text-white">Fraud Alerts</h2>
					</div>
					<span class="font-mono text-[10px] text-red-400">{alerts.length}</span>
				</div>
				<div class="max-h-[460px] overflow-y-auto">
					{#each alerts as alert}
						<div class="px-4 py-3 border-b border-gray-700/20 hover:bg-white/[0.02] transition-colors">
							<div class="flex items-center gap-2 flex-wrap">
								<span class="badge {signalColors[alert.signal] ?? 'bg-gray-500/20 text-gray-400'}">{alert.signal}</span>
								<span class="badge text-[10px] uppercase {severityColors[alert.severity] ?? 'bg-gray-500/20 text-gray-400'}">{alert.severity}</span>
								<span class="font-mono text-xs text-gray-500">{alert.userId}</span>
								<span class="text-[11px] text-gray-600 ml-auto tabular-nums">{formatDate(alert.createdAt)}</span>
							</div>
							<p class="text-xs text-gray-400 mt-1.5">{alert.details}</p>
							<div class="flex items-center gap-2 mt-2">
								{#if alert.events?.length}
									<button class="text-[11px] text-gray-500 hover:text-gray-300 transition-colors" onclick={() => expandedAlerts[alert.alertId] = !expandedAlerts[alert.alertId]}>
										{expandedAlerts[alert.alertId] ? 'Hide' : 'Show'} {alert.events.length} events
									</button>
								{/if}
								<button
									class="px-2 py-0.5 bg-cyan-500/20 text-cyan-400 rounded text-[10px] font-medium transition-all hover:bg-cyan-500/30 disabled:opacity-50 ml-auto"
									onclick={() => triggerInvestigation(alert.userId)}
									disabled={investigating[alert.userId] || !!activeInvestigations[alert.userId]}
								>
									{#if investigating[alert.userId] || activeInvestigations[alert.userId]}
										<span class="flex items-center gap-1">
											<span class="w-2.5 h-2.5 border border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin"></span>
											{activeInvestigations[alert.userId]?.stage ? stageLabels[activeInvestigations[alert.userId].stage] ?? 'Working' : 'Starting'}
										</span>
									{:else}
										Investigate
									{/if}
								</button>
							</div>
							{#if expandedAlerts[alert.alertId]}
								<div class="mt-2 pl-3 border-l-2 border-gray-700/50 space-y-1">
									{#each alert.events as evt}
										<div class="flex items-center gap-2 text-xs">
											<span class="font-mono text-[10px] px-1.5 py-0.5 rounded {eventColors[evt.name] ?? 'bg-gray-500/20 text-gray-400'}">{evt.name}</span>
											{#if evt.properties?.amount}<span class="text-white font-medium">{formatAmount(evt.properties.amount)}</span>{/if}
											{#if evt.properties?.recipient}<span class="text-gray-600">&rarr; {evt.properties.recipient}</span>{/if}
											{#if evt.properties?.last4}<span class="text-gray-600">****{evt.properties.last4}</span>{/if}
											<span class="font-mono text-[10px] text-gray-600">{formatTime(evt.timestamp)}</span>
										</div>
									{/each}
								</div>
							{/if}
							{#if alert.ruleSnapshot}
								<div class="font-mono text-[10px] text-gray-600 mt-1.5 italic">{Object.entries(alert.ruleSnapshot).map(([k,v]) => `${k}=${v}`).join(' \u00b7 ')}</div>
							{/if}
						</div>
					{:else}
						<div class="py-16 text-center text-sm text-gray-600">No alerts detected</div>
					{/each}
				</div>
			</div>
		</div>
	{/if}

	<!-- ========== TAB 2: INVESTIGATIONS ========== -->
	{#if activeTab === 'investigations'}
		<div class="space-y-4">
			<!-- Active Investigations -->
			{#if Object.keys(activeInvestigations).length > 0}
				<div>
					<h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium mb-3">Active Investigations</h3>
					{#each Object.values(activeInvestigations) as inv (inv.userId)}
						<div class="bg-cyan-500/5 border border-cyan-500/20 rounded-lg p-4 mb-3">
							<div class="flex items-center gap-3">
								<div class="w-5 h-5 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin"></div>
								<div>
									<span class="text-sm font-medium text-white">Investigating</span>
									<span class="font-mono text-xs text-gray-500 ml-2">{inv.userId}</span>
									{#if inv.alertId}
										<span class="font-mono text-[10px] text-gray-600 ml-2">{inv.alertId}</span>
									{/if}
								</div>
							</div>
							<div class="flex items-center gap-1.5 mt-3">
								{#each stages as stage, i}
									{@const currentIdx = stages.indexOf(inv.stage ?? '')}
									{@const isComplete = i < currentIdx}
									{@const isCurrent = stage === inv.stage}
									<div class="flex-1 h-1.5 rounded-full transition-colors duration-300 {isComplete ? 'bg-cyan-400' : isCurrent ? 'bg-cyan-400 animate-pulse' : 'bg-gray-700'}"></div>
								{/each}
							</div>
							<div class="flex justify-between mt-1">
								{#each ['Analyzing', 'Similar Cases', 'Recommending', 'Saving'] as label}
									<span class="text-[9px] text-gray-600 flex-1 text-center">{label}</span>
								{/each}
							</div>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Completed Investigations -->
			<div>
				<h3 class="text-xs text-gray-500 uppercase tracking-wider font-medium mb-3">
					Completed Investigations
					{#if completedInvestigations.length > 0}
						<span class="font-mono text-gray-600">({completedInvestigations.length})</span>
					{/if}
				</h3>

				{#each completedInvestigations as inv (inv.investigationId)}
					<div class="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4 mb-3">
						<div class="flex items-center justify-between">
							<div class="flex items-center gap-2">
								<span class="badge bg-emerald-500/20 text-emerald-400">Complete</span>
								<span class="font-mono text-xs text-gray-500">{inv.userId}</span>
								<span class="font-mono text-[10px] text-gray-600">{inv.investigationId}</span>
							</div>
							<button class="btn-ghost text-[11px] py-1 px-3"
								onclick={() => expandedInvestigation[inv.investigationId] = !expandedInvestigation[inv.investigationId]}>
								{expandedInvestigation[inv.investigationId] ? 'Collapse' : 'View Results'}
							</button>
						</div>

						{#if expandedInvestigation[inv.investigationId]}
							<div class="mt-4 space-y-4">
								<!-- Fraud Analysis -->
								{#if inv.fraudAnalysis}
									<div>
										<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Fraud Analysis</h4>
										<div class="bg-gray-800/50 rounded-lg p-3">
											<div class="flex items-center gap-3 mb-2">
												<span class="text-sm font-medium text-white">{inv.fraudAnalysis.fraud_pattern ?? 'Analysis complete'}</span>
												{#if inv.fraudAnalysis.confidence != null}
													<span class="badge {inv.fraudAnalysis.confidence > 0.7 ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}">
														{Math.round(inv.fraudAnalysis.confidence * 100)}% confidence
													</span>
												{/if}
											</div>
											<div class="text-xs text-gray-400">
												{#if inv.fraudAnalysis.affected_amount_myr != null}
													Affected amount: <strong class="text-white">{formatAmount(inv.fraudAnalysis.affected_amount_myr)}</strong>
												{/if}
												{#if inv.fraudAnalysis.false_positive_likelihood != null}
													| False positive: <strong class="text-white">{Math.round(inv.fraudAnalysis.false_positive_likelihood * 100)}%</strong>
												{/if}
											</div>
											{#if inv.fraudAnalysis.timeline_analysis}
												<p class="text-xs text-gray-500 mt-2">{inv.fraudAnalysis.timeline_analysis}</p>
											{/if}
											{#if inv.fraudAnalysis.key_indicators?.length}
												<div class="mt-2 space-y-1">
													{#each inv.fraudAnalysis.key_indicators as ind}
														<div class="text-xs text-gray-500">
															<span class="text-gray-400 font-medium">{ind.indicator ?? ind}:</span> {ind.description ?? ''}
														</div>
													{/each}
												</div>
											{/if}
										</div>
									</div>
								{/if}

								<!-- Similar Cases -->
								{#if inv.similarCases}
									<div>
										<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Similar Cases <span class="text-purple-400 ml-1">Atlas Vector Search</span></h4>
										<div class="bg-gray-800/50 rounded-lg p-3">
											{#if inv.similarCases.ring_analysis}
												<div class="text-xs text-gray-400 mb-2">
													Ring detected: <strong class="{inv.similarCases.ring_analysis.likely_ring ? 'text-red-400' : 'text-gray-300'}">{inv.similarCases.ring_analysis.likely_ring ? 'Yes' : 'No'}</strong>
													{#if inv.similarCases.ring_analysis.likely_ring && inv.similarCases.ring_analysis.estimated_ring_size}
														| Est. size: <strong class="text-white">{inv.similarCases.ring_analysis.estimated_ring_size}</strong>
													{/if}
												</div>
											{/if}
											{#if inv.similarCases.similar_profiles?.length}
												<div class="space-y-1">
													{#each inv.similarCases.similar_profiles.slice(0, 3) as profile}
														<div class="text-xs text-gray-500">
															<span class="font-mono text-gray-400">{profile.user_id}</span>
															— similarity: <strong class="text-white">{Math.round((profile.similarity_score ?? 0) * 100)}%</strong>
															{#if profile.risk_assessment}— {profile.risk_assessment}{/if}
														</div>
													{/each}
												</div>
											{/if}
										</div>
									</div>
								{/if}

								<!-- Recommendation -->
								{#if inv.recommendation}
									<div>
										<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Recommendation</h4>
										<div class="bg-gray-800/50 rounded-lg p-3">
											<div class="flex items-center gap-2 mb-2">
												<span class="badge {severityColors[inv.recommendation.risk_level] ?? 'bg-gray-500/20 text-gray-400'}">{inv.recommendation.risk_level}</span>
												<span class="text-sm font-medium text-white">{(inv.recommendation.recommended_action ?? '').replace(/_/g, ' ')}</span>
											</div>
											{#if inv.recommendation.executive_summary}
												<p class="text-xs text-gray-400 mb-2">{inv.recommendation.executive_summary}</p>
											{/if}
											{#if inv.recommendation.immediate_actions?.length}
												<div class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mt-2 mb-1">Immediate Actions</div>
												<ul class="space-y-0.5">
													{#each inv.recommendation.immediate_actions as action}
														<li class="text-xs text-gray-400">- {action}</li>
													{/each}
												</ul>
											{/if}
											{#if inv.recommendation.estimated_exposure_myr != null}
												<div class="text-xs text-gray-500 mt-2">
													Estimated exposure: <strong class="text-red-400">{formatAmount(inv.recommendation.estimated_exposure_myr)}</strong>
												</div>
											{/if}
											{#if inv.recommendation.regulatory_implications}
												<div class="text-xs text-gray-500 mt-1">
													BNM STR required: <strong class="text-white">{inv.recommendation.regulatory_implications.bnm_str_required ? 'Yes' : 'No'}</strong>
													| AML review: <strong class="text-white">{inv.recommendation.regulatory_implications.aml_review_needed ? 'Yes' : 'No'}</strong>
												</div>
											{/if}
										</div>
									</div>
								{/if}

								<!-- Queries Executed -->
								{#if inv.queriesExecuted?.length}
									<div>
										<button class="text-[10px] text-gray-500 uppercase tracking-wider font-medium flex items-center gap-1"
											onclick={() => showQueries[inv.investigationId] = !showQueries[inv.investigationId]}>
											MongoDB Queries Executed ({inv.queriesExecuted.length})
											<span class="text-gray-600">{showQueries[inv.investigationId] ? '[-]' : '[+]'}</span>
										</button>
										{#if showQueries[inv.investigationId]}
											<div class="mt-2 space-y-2">
												{#each inv.queriesExecuted as q}
													<div class="bg-gray-900 rounded-lg p-3">
														<div class="flex items-center gap-2 mb-1">
															<span class="badge bg-blue-500/20 text-blue-400 text-[10px]">{q.agent}</span>
															<span class="font-mono text-[10px] text-gray-400">{q.collection}.{q.operation}()</span>
															<span class="font-mono text-[10px] text-gray-600 ml-auto">{q.execution_time_ms?.toFixed(0)}ms | {q.docs_returned} docs</span>
														</div>
														{#if q.mongodb_features?.length}
															<div class="flex gap-1 mb-1">
																{#each q.mongodb_features as feat}
																	<span class="font-mono text-[9px] px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400">{feat}</span>
																{/each}
															</div>
														{/if}
														<pre class="mql-code text-[10px] leading-relaxed overflow-x-auto max-h-32">{JSON.stringify(q.pipeline, null, 2)}</pre>
													</div>
												{/each}
											</div>
										{/if}
									</div>
								{/if}
							</div>
						{/if}
					</div>
				{:else}
					<div class="py-16 text-center text-sm text-gray-600">
						No investigations yet. Trigger one from the Live Stream or Flagged Users tab.
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- ========== TAB 3: FLAGGED USERS ========== -->
	{#if activeTab === 'users'}
		<div class="space-y-3">
			{#each flaggedUsers as user}
				<div class="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4">
					<!-- Header -->
					<div class="flex items-center justify-between">
						<div class="flex items-center gap-3">
							<div class="w-8 h-8 rounded-lg bg-FuelRetail-red/20 flex items-center justify-center text-FuelRetail-red font-bold text-xs">
								{user.fullName?.charAt(0) ?? '?'}
							</div>
							<div>
								<div class="text-sm font-semibold text-white">{user.fullName}</div>
								<div class="font-mono text-[10px] text-gray-600">{user.userId}</div>
							</div>
						</div>
						<div class="flex items-center gap-1.5">
							<span class="badge {severityColors[user.fraud?.riskLevel] ?? 'bg-gray-500/20 text-gray-400'}">{user.fraud?.riskLevel}</span>
							{#each user.fraud?.signalsSeen ?? [] as sig}
								<span class="badge text-[10px] {signalColors[sig] ?? 'bg-gray-500/20 text-gray-400'}">{sig}</span>
							{/each}
						</div>
					</div>

					<!-- Quick stats -->
					<div class="flex gap-4 mt-3 text-xs text-gray-500">
						<span>KYC: <strong class="text-gray-300">{user.kyc?.status ?? '\u2014'}</strong></span>
						<span>Wallet: <strong class="text-gray-300">{user.wallet?.tier ?? '\u2014'}</strong> ({formatAmount(user.wallet?.balance)})</span>
						<span>Cards: <strong class="text-gray-300">{user.linkedCards?.length ?? 0}</strong></span>
						<span>Alerts: <strong class="text-gray-300">{user.fraud?.alertCount ?? 0}</strong></span>
					</div>

					<!-- Actions -->
					<div class="flex gap-2 mt-3">
						<button class="btn-ghost text-[11px] py-1 px-3" onclick={() => expandedUsers[user.userId] = !expandedUsers[user.userId]}>
							{expandedUsers[user.userId] ? 'Collapse' : 'Expand Profile'}
						</button>
						<button
							class="px-3 py-1 bg-purple-500/20 text-purple-400 rounded-lg text-[11px] font-medium transition-all hover:bg-purple-500/30 active:scale-95 disabled:opacity-50"
							onclick={() => findSimilar(user.userId)}
							disabled={loadingSimilar[user.userId]}
						>
							{loadingSimilar[user.userId] ? 'Searching...' : 'Find Similar Users'}
						</button>
						<button
							class="px-3 py-1 bg-cyan-500/20 text-cyan-400 rounded-lg text-[11px] font-medium transition-all hover:bg-cyan-500/30 active:scale-95 disabled:opacity-50"
							onclick={() => triggerInvestigation(user.userId)}
							disabled={investigating[user.userId] || !!activeInvestigations[user.userId]}
						>
							{#if investigating[user.userId] || activeInvestigations[user.userId]}
								<span class="flex items-center gap-1.5">
									<span class="w-3 h-3 border-2 border-cyan-400/30 border-t-cyan-400 rounded-full animate-spin"></span>
									Investigating...
								</span>
							{:else}
								Investigate
							{/if}
						</button>
					</div>

					<!-- Expanded profile -->
					{#if expandedUsers[user.userId]}
						<div class="mt-4 pt-4 border-t border-gray-700/50">
							<div class="grid grid-cols-3 gap-4 mb-4">
								<div>
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">KYC</h4>
									<div class="space-y-1 text-xs">
										<div class="flex justify-between"><span class="text-gray-500">Status</span><span class="text-gray-300">{user.kyc?.status}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Method</span><span class="text-gray-300">{user.kyc?.method}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Document</span><span class="text-gray-300">{user.kyc?.documentType}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Risk</span><span class="text-gray-300">{user.kyc?.riskLevel}</span></div>
									</div>
								</div>
								<div>
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Wallet</h4>
									<div class="space-y-1 text-xs">
										<div class="flex justify-between"><span class="text-gray-500">Balance</span><span class="text-gray-300">{formatAmount(user.wallet?.balance)}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Tier</span><span class="text-gray-300">{user.wallet?.tier}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Daily Limit</span><span class="text-gray-300">{formatAmount(user.wallet?.dailyLimit)}</span></div>
									</div>
								</div>
								<div>
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Activity</h4>
									<div class="space-y-1 text-xs">
										<div class="flex justify-between"><span class="text-gray-500">Transactions</span><span class="text-gray-300">{user.activitySummary?.totalTransactions}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Total Spend</span><span class="text-gray-300">{formatAmount(user.activitySummary?.totalSpend)}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Monthly Avg</span><span class="text-gray-300">{formatAmount(user.activitySummary?.monthlyAvgSpend)}</span></div>
										<div class="flex justify-between"><span class="text-gray-500">Favourite</span><span class="text-gray-300">{user.activitySummary?.favouriteStation}</span></div>
									</div>
								</div>
							</div>

							{#if user.linkedCards?.length}
								<div class="mb-4">
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Linked Cards</h4>
									<div class="flex flex-wrap gap-1.5">
										{#each user.linkedCards as card}
											<span class="font-mono text-[10px] px-2 py-1 rounded bg-gray-800 text-gray-400 border border-gray-700/50">
												{card.type} ****{card.last4} ({card.bank}){card.isDefault ? ' \u2605' : ''}
											</span>
										{/each}
									</div>
								</div>
							{/if}

							<div class="mb-4">
								<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Screening</h4>
								<div class="space-y-1 text-xs">
									<div class="flex gap-4"><span class="text-gray-500">Risk Flag: <span class="text-gray-300">{user.screening?.riskFlag ? 'Yes' : 'No'}</span></span>
									<span class="text-gray-500">Last Screened: <span class="text-gray-300">{formatDate(user.screening?.lastScreenedAt)}</span></span></div>
								</div>
							</div>

							{#if user.fraud?.signals && Object.keys(user.fraud.signals).length > 0}
								<div class="mb-4">
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Detection State <span class="font-mono text-gray-600 bg-gray-800 px-1 py-0.5 rounded ml-1">fraud.signals</span></h4>
									{#if user.fraud.signals.s01}
										{@const s01 = user.fraud.signals.s01}
										<div class="bg-red-500/5 border border-red-500/10 rounded-lg p-3">
											<div class="flex items-center gap-2 mb-2">
												<span class="badge bg-red-500/20 text-red-400">S01</span>
												<span class="text-xs {s01.topupClusterDetected ? 'text-red-400 font-medium' : 'text-gray-500'}">
													{s01.topupClusterDetected ? 'Cluster Detected' : 'Monitoring'}
												</span>
											</div>
											<div class="flex gap-4 text-xs text-gray-500 mb-2">
												<span>Top-ups: <strong class="text-white">{s01.topupCount}</strong></span>
												<span>Interval: <strong class="text-white">{s01.intervalSeconds}s</strong></span>
												<span>Last cluster: <strong class="text-white">{formatDate(s01.lastClusterAt)}</strong></span>
											</div>
											{#if s01.recentHighTopups?.length}
												<div class="pl-3 border-l-2 border-red-500/20 space-y-1">
													{#each s01.recentHighTopups as topup}
														<div class="flex items-center gap-2 text-xs">
															<span class="font-mono text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400">auto_topup</span>
															<span class="text-white font-medium">{formatAmount(topup.amount)}</span>
															<span class="text-gray-600">{topup.source}</span>
															<span class="font-mono text-[10px] text-gray-600">{formatTime(topup.timestamp)}</span>
														</div>
													{/each}
												</div>
											{/if}
											<p class="text-[10px] text-gray-600 italic mt-2">Pipeline 1a (1-min tumbling window). Pipeline 1b reads via $lookup on each InstantTransfer_transfer_out.</p>
										</div>
									{/if}
								</div>
							{/if}

							<div>
								<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Fraud History ({user.fraud?.alertCount ?? 0} alerts)</h4>
								{#each user.fraud?.alerts ?? [] as alert}
									<div class="bg-gray-800/50 border border-gray-700/50 rounded-lg p-3 mb-2">
										<div class="flex items-center gap-2 flex-wrap">
											<span class="badge text-[10px] {signalColors[alert.signal] ?? 'bg-gray-500/20 text-gray-400'}">{alert.signal}</span>
											<span class="badge text-[10px] uppercase {severityColors[alert.severity] ?? 'bg-gray-500/20 text-gray-400'}">{alert.severity}</span>
											<span class="text-[11px] text-gray-600 ml-auto">{formatDate(alert.createdAt)}</span>
										</div>
										<p class="text-xs text-gray-400 mt-1">{alert.details}</p>
										{#if alert.ruleSnapshot}
											<div class="font-mono text-[10px] text-gray-600 mt-1 italic">{Object.entries(alert.ruleSnapshot).map(([k,v]) => `${k}=${v}`).join(' \u00b7 ')}</div>
										{/if}
										{#if alert.events?.length}
											<div class="mt-2 pl-3 border-l-2 border-gray-700/50 space-y-1">
												{#each alert.events as evt}
													<div class="flex items-center gap-2 text-xs">
														<span class="font-mono text-[10px] px-1.5 py-0.5 rounded {eventColors[evt.name] ?? 'bg-gray-500/20 text-gray-400'}">{evt.name}</span>
														{#if evt.properties?.amount}<span class="text-white font-medium">{formatAmount(evt.properties.amount)}</span>{/if}
														{#if evt.properties?.recipient}<span class="text-gray-600">&rarr; {evt.properties.recipient}</span>{/if}
														{#if evt.properties?.last4}<span class="text-gray-600">****{evt.properties.last4}</span>{/if}
														<span class="font-mono text-[10px] text-gray-600">{formatTime(evt.timestamp)}</span>
													</div>
												{/each}
											</div>
										{/if}
									</div>
								{/each}
							</div>
						</div>
					{/if}

					<!-- Similarity results -->
					{#if similarResults[user.userId]?.length}
						<div class="mt-4 pt-4 border-t border-purple-500/20 bg-purple-500/5 -mx-4 -mb-4 p-4 rounded-b-lg">
							<h4 class="text-xs font-semibold text-purple-400 mb-1">Similar Fraud Profiles <span class="font-normal text-gray-500 font-mono text-[10px] ml-1">Atlas Vector Search + Voyage AI</span></h4>
							<p class="text-[10px] text-gray-500 mb-3">Similarity based on fraud patterns AND behavioral profile</p>
							<div class="space-y-2">
								{#each similarResults[user.userId] as sim}
									{@const pct = Math.round((sim.similarityScore ?? 0) * 100)}
									<div class="flex items-center gap-3 bg-gray-900/50 border border-gray-700/50 rounded-lg p-3">
										<div class="text-lg font-bold tabular-nums min-w-[45px] text-center {pct > 80 ? 'text-red-400' : pct > 50 ? 'text-orange-400' : 'text-amber-400'}">
											{pct}<span class="text-[10px] font-normal">%</span>
										</div>
										<div class="flex-1">
											<div class="text-sm font-medium text-white">{sim.fullName} <span class="font-mono text-[10px] text-gray-600">{sim.userId}</span></div>
											<div class="flex gap-1 mt-1">
												<span class="badge text-[10px] {severityColors[sim.fraud?.riskLevel] ?? 'bg-gray-500/20 text-gray-400'}">{sim.fraud?.riskLevel}</span>
												{#each sim.fraud?.signalsSeen ?? [] as sig}
													<span class="badge text-[10px] {signalColors[sig] ?? 'bg-gray-500/20 text-gray-400'}">{sig}</span>
												{/each}
											</div>
											<div class="font-mono text-[10px] text-gray-600 mt-1">{sim.wallet?.tier ?? '\u2014'} \u00b7 {sim.activitySummary?.totalTransactions ?? 0} txns \u00b7 {formatAmount(sim.activitySummary?.monthlyAvgSpend)}</div>
										</div>
									</div>
								{/each}
							</div>
						</div>
					{:else if similarResults[user.userId]?.length === 0}
						<div class="mt-3 text-xs text-gray-600">No similar users found.</div>
					{/if}
				</div>
			{:else}
				<div class="py-12 text-center text-sm text-gray-600">No flagged users</div>
			{/each}
		</div>
	{/if}

	<!-- ========== TAB 4: CONFIGURATION ========== -->
	{#if activeTab === 'config'}
		<div class="space-y-4">
			<!-- Signal Rules -->
			<div>
				<div class="flex items-center gap-2 mb-3">
					<h3 class="text-sm font-semibold text-white">Signal Rules</h3>
					<span class="text-[10px] text-orange-400 bg-orange-500/10 px-2 py-0.5 rounded">Changes require pipeline restart</span>
				</div>
				<div class="grid grid-cols-1 xl:grid-cols-2 gap-3">
					{#each signalRules as rule}
						<div class="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4">
							<div class="flex items-center gap-2 mb-2">
								<span class="badge {signalColors[rule.key?.replace('ai_defence_','').replace('_signal_config','').toUpperCase()] ?? 'bg-gray-500/20 text-gray-400'}">
									{rule.key?.replace('ai_defence_','').replace('_signal_config','').toUpperCase()}
								</span>
								<span class="text-[10px] font-medium {rule.isToggled ? 'text-emerald-400' : 'text-gray-600'}">
									{rule.isToggled ? 'Active' : 'Inactive'}
								</span>
							</div>
							<p class="text-xs text-gray-500 mb-3">{rule.description}</p>
							{#if rule.variants?.Enabled?.value}
								<div class="space-y-1.5">
									{#each Object.entries(rule.variants.Enabled.value).filter(([k]) => k !== 'enabled') as [field, value]}
										<div class="flex items-center gap-2 text-xs">
											<span class="font-mono text-gray-500 min-w-[170px]">{field}</span>
											{#if editingRule[rule.key]?.[field]}
												<input
													class="bg-gray-800 border border-orange-500/40 rounded px-2 py-0.5 w-20 font-mono text-xs text-white focus:outline-none"
													type="number"
													value={editValues[rule.key]?.[field] ?? value}
													oninput={(e) => {
														if (!editValues[rule.key]) editValues[rule.key] = {};
														editValues[rule.key][field] = (e.target as HTMLInputElement).value;
													}}
													onkeydown={(e) => {
														if (e.key === 'Enter') saveRule(rule.key, field, editValues[rule.key]?.[field] ?? value);
														if (e.key === 'Escape') { editingRule[rule.key] = { ...editingRule[rule.key], [field]: false }; }
													}}
												/>
												<button class="px-2 py-0.5 bg-emerald-500 text-white rounded text-[10px] font-medium" onclick={() => saveRule(rule.key, field, editValues[rule.key]?.[field] ?? value)}>Save</button>
											{:else}
												<span
													class="font-mono text-white font-medium cursor-pointer px-2 py-0.5 rounded border border-transparent hover:border-orange-500/40 hover:bg-orange-500/5 transition-colors"
													role="button"
													tabindex="0"
													onclick={() => {
														if (!editingRule[rule.key]) editingRule[rule.key] = {};
														editingRule[rule.key][field] = true;
														if (!editValues[rule.key]) editValues[rule.key] = {};
														editValues[rule.key][field] = value;
													}}
													onkeydown={(e) => {
														if (e.key === 'Enter') {
															if (!editingRule[rule.key]) editingRule[rule.key] = {};
															editingRule[rule.key][field] = true;
														}
													}}
												>{value}</span>
											{/if}
										</div>
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			</div>

			<!-- Architecture -->
			<div>
				<h3 class="text-sm font-semibold text-white mb-3">Architecture</h3>
				<div class="space-y-6">
					<div class="card">
						<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-emerald-500/10 text-emerald-400 mb-2">Proposed</span>
						<h4 class="text-sm font-semibold text-white mb-3">MSK + Atlas Stream Processing + Change Stream Agent</h4>
						<div class="flex items-center gap-2 flex-wrap">
							{#each [{ name: 'FuelRetail App', cls: 'bg-gray-800 text-white' }, { name: 'Amazon MSK', cls: 'bg-orange-500/10 text-orange-400 border border-orange-500/20' }, { name: 'Atlas Stream Processing', cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' }, { name: 'MongoDB Atlas', cls: 'bg-blue-500/10 text-blue-400 border border-blue-500/20' }, { name: 'Change Stream', cls: 'bg-cyan-500/10 text-cyan-400 border border-cyan-500/20' }, { name: 'LangGraph Agent', cls: 'bg-purple-500/10 text-purple-400 border border-purple-500/20' }, { name: 'Dashboard', cls: 'bg-red-500/10 text-red-400 border border-red-500/20' }] as node, i}
								{#if i > 0}<span class="text-gray-600 text-xs">&rarr;</span>{/if}
								<span class="px-3 py-1.5 rounded-lg text-xs font-semibold {node.cls}">{node.name}</span>
							{/each}
						</div>
						<p class="text-xs text-gray-500 mt-3">Change stream watches fraud_alerts. New alert automatically triggers LangGraph investigation via SSE.</p>
					</div>
					<div class="card opacity-50">
						<span class="inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider bg-red-500/10 text-red-400 mb-2">Current</span>
						<h4 class="text-sm font-semibold text-white mb-3">Confluent + KSQL</h4>
						<div class="flex items-center gap-2 flex-wrap">
							{#each [{ name: 'FuelRetail App', cls: 'bg-gray-800 text-gray-400' }, { name: 'Kafka (Confluent)', cls: 'bg-red-500/10 text-red-400' }, { name: 'KSQL', cls: 'bg-red-500/10 text-red-400' }, { name: 'NestJS', cls: 'bg-red-500/10 text-red-400' }, { name: 'MongoDB', cls: 'bg-blue-500/10 text-blue-400' }] as node, i}
								{#if i > 0}<span class="text-gray-700 text-xs">&rarr;</span>{/if}
								<span class="px-3 py-1.5 rounded-lg text-xs font-semibold {node.cls}">{node.name}</span>
							{/each}
						</div>
						<p class="text-xs text-red-400 mt-3">KSQL can't run on MSK. Flink: $400 USD burned in 2 days.</p>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
