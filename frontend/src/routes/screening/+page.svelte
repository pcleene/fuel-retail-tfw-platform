<script lang="ts">
	import { onMount } from 'svelte';
	import { screening } from '$lib/api';

	let stats = $state<any>(null);
	let flaggedUsers = $state<any[]>([]);

	// Check User (Flow 1)
	let checkName = $state('');
	let checkDob = $state('');
	let checkMaxEdits = $state(2);
	let checking = $state(false);
	let checkResults = $state<any>(null);

	// Autocomplete
	let acSuggestions = $state<any[]>([]);
	let acLoading = $state(false);
	let acVisible = $state(false);
	let acHighlight = $state(-1);
	let acTimer: ReturnType<typeof setTimeout> | null = null;
	let inputEl: HTMLInputElement | undefined = $state(undefined);

	// Batch Sweep (Flow 2)
	let sweeping = $state(false);
	let sweepResults = $state<any>(null);

	// UI state
	let activeTab = $state<'check' | 'sweep'>('check');
	let showFlagged = $state(true);
	let showPipeline = $state(false);
	let expandedUsers = $state<Record<string, boolean>>({});

	const sourceColors: Record<string, string> = {
		'OFAC': 'bg-red-500/20 text-red-400',
		'UN Security Council': 'bg-orange-500/20 text-orange-400',
		'EU Sanctions': 'bg-blue-500/20 text-blue-400',
		'Bank Negara Malaysia': 'bg-emerald-500/20 text-emerald-400',
		'FATF': 'bg-amber-500/20 text-amber-400',
		'AUSTRAC': 'bg-purple-500/20 text-purple-400',
		'Interpol': 'bg-cyan-500/20 text-cyan-400',
	};

	const categoryColors: Record<string, string> = {
		'Financial fraud': 'bg-red-500/20 text-red-400',
		'Money laundering': 'bg-orange-500/20 text-orange-400',
		'Terrorism financing': 'bg-rose-500/20 text-rose-400',
		'Sanctions evasion': 'bg-amber-500/20 text-amber-400',
		'Corruption': 'bg-purple-500/20 text-purple-400',
	};

	async function loadAll() {
		try {
			const [s, f] = await Promise.all([
				screening.stats(),
				screening.flaggedUsers(),
			]);
			stats = s;
			flaggedUsers = f;
		} catch (err) {
			console.error('Load failed:', err);
		}
	}

	function onNameInput() {
		const q = checkName.trim();
		acHighlight = -1;
		if (q.length < 2) {
			acSuggestions = [];
			acVisible = false;
			return;
		}
		if (acTimer) clearTimeout(acTimer);
		acTimer = setTimeout(async () => {
			acLoading = true;
			try {
				acSuggestions = await screening.autocompleteSanctioned(q);
				acVisible = acSuggestions.length > 0;
			} catch {
				acSuggestions = [];
				acVisible = false;
			} finally {
				acLoading = false;
			}
		}, 200);
	}

	function selectSuggestion(name: string) {
		checkName = name;
		acVisible = false;
		acSuggestions = [];
		runCheck();
	}

	function onNameKeydown(e: KeyboardEvent) {
		if (!acVisible || acSuggestions.length === 0) {
			if (e.key === 'Enter') runCheck();
			return;
		}
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			acHighlight = Math.min(acHighlight + 1, acSuggestions.length - 1);
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			acHighlight = Math.max(acHighlight - 1, -1);
		} else if (e.key === 'Enter') {
			e.preventDefault();
			if (acHighlight >= 0 && acHighlight < acSuggestions.length) {
				selectSuggestion(acSuggestions[acHighlight].fullName);
			} else {
				acVisible = false;
				runCheck();
			}
		} else if (e.key === 'Escape') {
			acVisible = false;
		}
	}

	function onNameBlur() {
		// Small delay so click on suggestion registers before hiding
		setTimeout(() => { acVisible = false; }, 150);
	}

	async function runCheck() {
		if (!checkName.trim()) return;
		checking = true;
		checkResults = null;
		try {
			checkResults = await screening.checkUser(
				checkName.trim(),
				checkMaxEdits,
				10,
				checkDob || undefined,
			);
		} catch (err: any) {
			checkResults = { error: err.message };
		} finally {
			checking = false;
		}
	}

	async function runSweep() {
		sweeping = true;
		sweepResults = null;
		try {
			sweepResults = await screening.batchSweep();
			// Refresh stats and flagged users after sweep
			const [s, f] = await Promise.all([
				screening.stats(),
				screening.flaggedUsers(),
			]);
			stats = s;
			flaggedUsers = f;
		} catch (err: any) {
			sweepResults = { error: err.message };
		} finally {
			sweeping = false;
		}
	}



	function formatDate(ts: string) {
		if (!ts) return '\u2014';
		const d = new Date(ts);
		return d.toLocaleDateString('en-MY', { year: 'numeric', month: 'short', day: 'numeric' }) + ' ' +
			d.toLocaleTimeString('en-MY', { hour: '2-digit', minute: '2-digit' });
	}

	function formatAmount(val: any) {
		if (val == null) return '\u2014';
		return `RM ${Number(val).toLocaleString('en-MY', { minimumFractionDigits: 2 })}`;
	}

	function scoreColor(score: number): string {
		if (score >= 8) return 'text-red-400';
		if (score >= 4) return 'text-orange-400';
		if (score >= 2) return 'text-amber-400';
		return 'text-gray-400';
	}

	function scoreBg(score: number): string {
		if (score >= 8) return 'bg-red-500/10 border-red-500/30';
		if (score >= 4) return 'bg-orange-500/10 border-orange-500/30';
		return '';
	}

	onMount(loadAll);
</script>

<div class="p-6 space-y-4">
	<!-- Header -->
	<div class="flex items-start justify-between mb-1">
		<div>
			<h1 class="text-2xl font-semibold text-white">Name Screening</h1>
			<p class="text-sm text-gray-400 mt-1">Atlas Search — Bi-directional sanctions compliance screening</p>
		</div>
	</div>

	<!-- Stats -->
	{#if stats}
		<div class="grid grid-cols-5 gap-4">
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Total Profiles</div>
				<div class="text-2xl font-bold text-white mt-1">{stats.totalProfiles?.toLocaleString() ?? 0}</div>
			</div>
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Sanctioned Entries</div>
				<div class="text-2xl font-bold text-white mt-1">{stats.sanctionedEntries ?? 0}</div>
			</div>
			<div class="card border-red-500/30!">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Flagged Users</div>
				<div class="text-2xl font-bold text-red-400 mt-1">{stats.flaggedUsers ?? 0}</div>
			</div>
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Last Screened</div>
				<div class="text-sm font-semibold text-white mt-1.5">{stats.lastRun ? formatDate(stats.lastRun) : 'Never'}</div>
			</div>
			<div class="card">
				<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Sources</div>
				<div class="text-2xl font-bold text-white mt-1">{Object.keys(stats.sourceBreakdown ?? {}).length}</div>
				{#if stats.sourceBreakdown}
					<div class="flex flex-wrap gap-1 mt-1.5">
						{#each Object.entries(stats.sourceBreakdown) as [src, count]}
							<span class="font-mono text-[9px] px-1 py-0.5 rounded {sourceColors[src] ?? 'bg-gray-500/20 text-gray-400'}">{count}</span>
						{/each}
					</div>
				{/if}
			</div>
		</div>
	{/if}

	<!-- Screening Panel -->
	<div class="card p-0!">
		<!-- Tabs -->
		<div class="flex border-b border-gray-700/50">
			<button
				class="flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors {activeTab === 'check' ? 'text-emerald-400 border-b-2 border-emerald-400' : 'text-gray-400 hover:text-gray-200'}"
				onclick={() => activeTab = 'check'}
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
				</svg>
				Check User
			</button>
			<button
				class="flex items-center gap-2 px-5 py-3 text-sm font-medium transition-colors {activeTab === 'sweep' ? 'text-emerald-400 border-b-2 border-emerald-400' : 'text-gray-400 hover:text-gray-200'}"
				onclick={() => activeTab = 'sweep'}
			>
				<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
				</svg>
				Batch Sweep
			</button>
			<button
				class="ml-auto flex items-center gap-1.5 px-3 py-2 mr-2 my-1 text-[11px] font-mono text-gray-500 hover:text-emerald-400 hover:bg-emerald-500/10 rounded-md transition-colors"
				onclick={() => showPipeline = true}
				title="View Atlas Search pipeline & index definition"
			>
				<svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
				</svg>
				&lt;-&gt;
			</button>
		</div>

		<!-- Tab A: Check User -->
		{#if activeTab === 'check'}
			<div class="p-4">
				<div class="flex items-center gap-2 mb-3">
					<svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
					</svg>
					<h2 class="text-sm font-semibold text-white">Flow 1: Onboarding Check</h2>
					<span class="text-[10px] text-gray-500 font-mono">user name &rarr; sanctioned_list</span>
				</div>
				<p class="text-xs text-gray-500 mb-4">Search a new user's name against the sanctioned watchlist. Uses Atlas Search fuzzy matching with the Malaysian name analyzer.</p>

				<div class="flex items-end gap-3">
					<div class="flex-1 relative">
						<label for="checkName" class="block text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">
							Full Name
							{#if acLoading}
								<span class="ml-1 inline-block w-2.5 h-2.5 border border-gray-500 border-t-emerald-400 rounded-full animate-spin align-middle"></span>
							{/if}
						</label>
						<input
							id="checkName"
							type="text"
							bind:value={checkName}
							bind:this={inputEl}
							placeholder="Start typing a name... (e.g. Ahm, Ism, Rav, Tan)"
							autocomplete="off"
							class="w-full bg-gray-800/80 border border-gray-700/50 rounded-md px-3 py-2 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-emerald-500/50 transition-colors"
							oninput={onNameInput}
							onkeydown={onNameKeydown}
							onblur={onNameBlur}
							onfocus={() => { if (acSuggestions.length > 0) acVisible = true; }}
						/>

						<!-- Autocomplete dropdown -->
						{#if acVisible && acSuggestions.length > 0}
							<div class="absolute z-50 left-0 right-0 top-full mt-1 bg-FuelRetail-slate border border-gray-700/50 rounded-lg shadow-xl overflow-hidden">
								{#each acSuggestions as suggestion, i}
									<button
										class="w-full flex items-center gap-3 px-3 py-2.5 text-left text-sm transition-colors
											{i === acHighlight ? 'bg-emerald-500/10 text-white' : 'text-gray-300 hover:bg-white/[0.04]'}
											{i > 0 ? 'border-t border-gray-700/20' : ''}"
										onmousedown={(e) => { e.preventDefault(); selectSuggestion(suggestion.fullName); }}
										onmouseenter={() => acHighlight = i}
									>
										<div class="w-6 h-6 rounded bg-red-500/15 flex items-center justify-center text-red-400 text-[10px] font-bold flex-shrink-0">
											{suggestion.fullName?.charAt(0)}
										</div>
										<div class="flex-1 min-w-0">
											<div class="font-medium truncate">{suggestion.fullName}</div>
											{#if suggestion.aliases?.length}
												<div class="text-[10px] text-gray-500 truncate">aka {suggestion.aliases.slice(0, 2).join(', ')}</div>
											{/if}
										</div>
										<div class="flex items-center gap-1.5 flex-shrink-0">
											<span class="badge text-[9px] {sourceColors[suggestion.source] ?? 'bg-gray-500/20 text-gray-400'}">{suggestion.source}</span>
											{#if suggestion.country}
												<span class="text-[10px] text-gray-600">{suggestion.country}</span>
											{/if}
										</div>
									</button>
								{/each}
								<div class="px-3 py-1.5 text-[10px] text-gray-600 bg-gray-900/50 border-t border-gray-700/30">
									Atlas Search <code class="text-emerald-500/50">autocomplete</code> &middot; edgeGram tokenization &middot; fuzzy maxEdits=1
								</div>
							</div>
						{/if}
					</div>
					<div class="w-40">
						<label for="checkDob" class="block text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">DOB (optional)</label>
						<input
							id="checkDob"
							type="date"
							bind:value={checkDob}
							class="w-full bg-gray-800/80 border border-gray-700/50 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-emerald-500/50 transition-colors"
						/>
					</div>
					<div class="w-28">
						<label for="maxEdits" class="block text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-1">Max Edits</label>
						<select
							id="maxEdits"
							bind:value={checkMaxEdits}
							class="w-full bg-gray-800/80 border border-gray-700/50 rounded-md px-3 py-2 text-sm text-gray-200 focus:outline-none focus:border-emerald-500/50 transition-colors"
						>
							<option value={0}>0 (exact)</option>
							<option value={1}>1</option>
							<option value={2}>2 (fuzzy)</option>
						</select>
					</div>
					<button class="btn-red text-sm flex items-center gap-2 whitespace-nowrap" onclick={runCheck} disabled={checking || !checkName.trim()}>
						{#if checking}
							<div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
							Checking...
						{:else}
							Check Watchlist
						{/if}
					</button>
				</div>

				<!-- Check results -->
				{#if checkResults}
					<div class="mt-4">
						{#if checkResults.error}
							<div class="px-3 py-2.5 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-300">
								<strong>Error:</strong> {checkResults.error}
							</div>
						{:else if checkResults.matches?.length === 0}
							<div class="px-3 py-2.5 rounded-lg text-sm bg-emerald-500/10 border border-emerald-500/20 text-emerald-300">
								No watchlist matches found for "<strong>{checkResults.query}</strong>"
							</div>
						{:else}
							<div class="px-3 py-2.5 rounded-lg text-sm bg-orange-500/10 border border-orange-500/20 text-orange-300 mb-3">
								Found <strong>{checkResults.matches?.length}</strong> potential watchlist match{checkResults.matches?.length === 1 ? '' : 'es'} for "<strong>{checkResults.query}</strong>"
							</div>
							<div class="overflow-hidden rounded-lg border border-gray-700/50">
								<table class="w-full text-xs">
									<thead>
										<tr class="bg-gray-800/50">
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">#</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Score</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Sanctioned Name</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Aliases</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">DOB</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Country</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Source</th>
											<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Category</th>
										</tr>
									</thead>
									<tbody>
										{#each checkResults.matches as match, i}
											<tr class="border-t border-gray-700/20 hover:bg-white/[0.02] transition-colors {scoreBg(match.score)}">
												<td class="px-3 py-2 text-gray-600 tabular-nums">{i + 1}</td>
												<td class="px-3 py-2 font-bold tabular-nums {scoreColor(match.score)}">{match.score?.toFixed(2)}</td>
												<td class="px-3 py-2 text-white font-medium">{match.fullName}</td>
												<td class="px-3 py-2 text-gray-400">
													{#if match.aliases?.length}
														<div class="flex flex-wrap gap-1">
															{#each match.aliases.slice(0, 3) as alias}
																<span class="font-mono text-[10px] px-1 py-0.5 rounded bg-gray-800 text-gray-500">{alias}</span>
															{/each}
														</div>
													{:else}
														<span class="text-gray-600">&mdash;</span>
													{/if}
												</td>
												<td class="px-3 py-2 text-gray-400 tabular-nums">{match.dateOfBirth ? new Date(match.dateOfBirth).toLocaleDateString('en-MY') : '\u2014'}</td>
												<td class="px-3 py-2 text-gray-400">{match.country ?? '\u2014'}</td>
												<td class="px-3 py-2"><span class="badge text-[10px] {sourceColors[match.source] ?? 'bg-gray-500/20 text-gray-400'}">{match.source}</span></td>
												<td class="px-3 py-2"><span class="badge text-[10px] {categoryColors[match.category] ?? 'bg-gray-500/20 text-gray-400'}">{match.category}</span></td>
											</tr>
										{/each}
									</tbody>
								</table>
							</div>
						{/if}
					</div>
				{/if}
			</div>

		<!-- Tab B: Batch Sweep -->
		{:else}
			<div class="p-4">
				<div class="flex items-center gap-2 mb-3">
					<svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z" />
					</svg>
					<h2 class="text-sm font-semibold text-white">Flow 2: Batch Watchlist Sweep</h2>
					<span class="text-[10px] text-gray-500 font-mono">sanctioned_list &rarr; user_profiles</span>
				</div>
				<p class="text-xs text-gray-500 mb-4">Sweep all sanctioned names against {stats?.totalProfiles?.toLocaleString() ?? '...'} user profiles. Matches are flagged directly in the user's embedded <code class="font-mono text-[10px] text-emerald-400/60 bg-emerald-500/5 px-1 py-0.5 rounded">screening</code> sub-document.</p>

				<div class="flex items-center gap-4">
					<button class="btn-red text-sm flex items-center gap-2" onclick={runSweep} disabled={sweeping}>
						{#if sweeping}
							<div class="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin"></div>
							Running Sweep...
						{:else}
							<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
								<path d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
							</svg>
							Run Watchlist Sweep
						{/if}
					</button>
					{#if sweeping}
						<span class="text-xs text-gray-500">Searching {stats?.sanctionedEntries ?? '...'} sanctioned names against {stats?.totalProfiles?.toLocaleString() ?? '...'} profiles...</span>
					{/if}
				</div>

				<!-- Sweep results -->
				{#if sweepResults}
					<div class="mt-4">
						{#if sweepResults.error}
							<div class="px-3 py-2.5 rounded-lg text-sm bg-red-500/10 border border-red-500/20 text-red-300">
								<strong>Error:</strong> {sweepResults.error}
							</div>
						{:else}
							<div class="px-3 py-2.5 rounded-lg text-sm bg-emerald-500/10 border border-emerald-500/20 text-emerald-300 mb-3">
								Sweep complete. Checked <strong>{sweepResults.sanctionedChecked}</strong> sanctioned entries &rarr;
								<strong>{sweepResults.totalMatches}</strong> matches across <strong>{sweepResults.flaggedUsers}</strong> users flagged.
							</div>

							{#if sweepResults.matches?.length}
								<div class="overflow-hidden rounded-lg border border-gray-700/50">
									<table class="w-full text-xs">
										<thead>
											<tr class="bg-gray-800/50">
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">#</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Score</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">User</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">User ID</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Sanctioned Name</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Matched Against</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Type</th>
												<th class="text-left px-3 py-2 text-gray-500 font-medium uppercase tracking-wider">Source</th>
											</tr>
										</thead>
										<tbody>
											{#each sweepResults.matches as match, i}
												<tr class="border-t border-gray-700/20 hover:bg-white/[0.02] transition-colors {scoreBg(match.score)}">
													<td class="px-3 py-2 text-gray-600 tabular-nums">{i + 1}</td>
													<td class="px-3 py-2 font-bold tabular-nums {scoreColor(match.score)}">{match.score?.toFixed(2)}</td>
													<td class="px-3 py-2 text-white font-medium">{match.userFullName}</td>
													<td class="px-3 py-2 font-mono text-[10px] text-gray-500">{match.userId}</td>
													<td class="px-3 py-2 text-gray-300">{match.sanctionedName}</td>
													<td class="px-3 py-2 text-gray-400">{match.matchedAgainst}</td>
													<td class="px-3 py-2"><span class="badge text-[10px] {match.matchType === 'primary' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}">{match.matchType}</span></td>
													<td class="px-3 py-2"><span class="badge text-[10px] {sourceColors[match.source] ?? 'bg-gray-500/20 text-gray-400'}">{match.source}</span></td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}
						{/if}
					</div>
				{/if}
			</div>
		{/if}
	</div>

	<!-- Flagged Users -->
	<div class="card p-0!">
		<button class="flex items-center justify-between w-full px-4 py-3 text-left hover:bg-white/[0.02] transition-colors" onclick={() => showFlagged = !showFlagged}>
			<div class="flex items-center gap-2">
				<svg class="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
					<path d="M3 3v1.5M3 21v-6m0 0l2.77-.693a9 9 0 016.208.682l.108.054a9 9 0 006.086.71l3.114-.732a48.524 48.524 0 01-.005-10.499l-3.11.732a9 9 0 01-6.085-.711l-.108-.054a9 9 0 00-6.208-.682L3 4.5M3 15V4.5" />
				</svg>
				<h2 class="text-sm font-semibold text-white">Flagged Users</h2>
				<span class="font-mono text-[10px] text-red-400">({flaggedUsers.length})</span>
			</div>
			<svg class="w-4 h-4 text-gray-500 transition-transform duration-200 {showFlagged ? 'rotate-180' : ''}" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
				<path d="M19 9l-7 7-7-7" />
			</svg>
		</button>
		{#if showFlagged}
			<div class="p-4 space-y-3">
				{#each flaggedUsers as user}
					<div class="bg-gray-900/50 border border-gray-700/50 rounded-lg p-4">
						<!-- Header -->
						<div class="flex items-center justify-between">
							<div class="flex items-center gap-3">
								<div class="w-8 h-8 rounded-lg bg-red-500/20 flex items-center justify-center text-red-400 font-bold text-xs">
									{user.fullName?.charAt(0) ?? '?'}
								</div>
								<div>
									<div class="text-sm font-semibold text-white">{user.fullName}</div>
									<div class="font-mono text-[10px] text-gray-600">{user.userId}</div>
								</div>
							</div>
							<div class="flex items-center gap-1.5">
								<span class="badge bg-red-500/20 text-red-400">Flagged</span>
								{#each user.screening?.matches ?? [] as match}
									<span class="badge text-[10px] {sourceColors[match.source] ?? 'bg-gray-500/20 text-gray-400'}">{match.source}</span>
								{/each}
							</div>
						</div>

						<!-- Quick stats -->
						<div class="flex gap-4 mt-3 text-xs text-gray-500">
							<span>Status: <strong class="text-gray-300">{user.status ?? '\u2014'}</strong></span>
							<span>KYC: <strong class="text-gray-300">{user.kyc?.status ?? '\u2014'}</strong></span>
							<span>Wallet: <strong class="text-gray-300">{user.wallet?.tier ?? '\u2014'}</strong> ({formatAmount(user.wallet?.balance)})</span>
							<span>Cards: <strong class="text-gray-300">{user.linkedCards?.length ?? 0}</strong></span>
							<span>Matches: <strong class="text-red-400">{user.screening?.matches?.length ?? 0}</strong></span>
						</div>

						<!-- Screening matches preview -->
						{#if user.screening?.matches?.length}
							<div class="mt-3 space-y-1.5">
								{#each user.screening.matches as match}
									<div class="flex items-center gap-2 text-xs bg-red-500/5 border border-red-500/10 rounded-lg px-3 py-2">
										<span class="font-bold tabular-nums {scoreColor(match.score)}">{match.score?.toFixed(2)}</span>
										<span class="text-gray-300">{match.sanctionedName}</span>
										<span class="text-gray-600">&rarr;</span>
										<span class="text-gray-400">{match.matchedAgainst}</span>
										<span class="badge text-[10px] {match.matchType === 'primary' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}">{match.matchType}</span>
										<span class="badge text-[10px] {sourceColors[match.source] ?? 'bg-gray-500/20 text-gray-400'} ml-auto">{match.source}</span>
									</div>
								{/each}
							</div>
						{/if}

						<!-- Expand/Collapse -->
						<div class="flex gap-2 mt-3">
							<button class="btn-ghost text-[11px] py-1 px-3" onclick={() => expandedUsers[user.userId] = !expandedUsers[user.userId]}>
								{expandedUsers[user.userId] ? 'Collapse' : 'Expand Profile'}
							</button>
						</div>

						<!-- Expanded profile — showcases MongoDB embedded document model -->
						{#if expandedUsers[user.userId]}
							<div class="mt-4 pt-4 border-t border-gray-700/50">
								<div class="grid grid-cols-3 gap-4 mb-4">
									<div>
										<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Identity</h4>
										<div class="space-y-1 text-xs">
											<div class="flex justify-between"><span class="text-gray-500">Full Name</span><span class="text-gray-300">{user.fullName}</span></div>
											<div class="flex justify-between"><span class="text-gray-500">IC</span><span class="font-mono text-gray-300">{user.ic ?? '\u2014'}</span></div>
											<div class="flex justify-between"><span class="text-gray-500">DOB</span><span class="text-gray-300">{user.dateOfBirth ? new Date(user.dateOfBirth).toLocaleDateString('en-MY') : '\u2014'}</span></div>
											<div class="flex justify-between"><span class="text-gray-500">Email</span><span class="text-gray-300 truncate max-w-[150px]">{user.email ?? '\u2014'}</span></div>
											<div class="flex justify-between"><span class="text-gray-500">Phone</span><span class="font-mono text-gray-300">{user.phone ?? '\u2014'}</span></div>
										</div>
									</div>
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
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">Activity Summary</h4>
									<div class="flex gap-4 text-xs">
										<span class="text-gray-500">Transactions: <strong class="text-gray-300">{user.activitySummary?.totalTransactions}</strong></span>
										<span class="text-gray-500">Total Spend: <strong class="text-gray-300">{formatAmount(user.activitySummary?.totalSpend)}</strong></span>
										<span class="text-gray-500">Monthly Avg: <strong class="text-gray-300">{formatAmount(user.activitySummary?.monthlyAvgSpend)}</strong></span>
										<span class="text-gray-500">Favourite: <strong class="text-gray-300">{user.activitySummary?.favouriteStation}</strong></span>
									</div>
								</div>

								<div>
									<h4 class="text-[10px] text-gray-500 uppercase tracking-wider font-medium mb-2">
										Screening <span class="font-mono text-gray-600 bg-gray-800 px-1 py-0.5 rounded ml-1">user_profiles.screening</span>
									</h4>
									<div class="flex gap-4 text-xs mb-2">
										<span class="text-gray-500">Risk Flag: <strong class="{user.screening?.riskFlag ? 'text-red-400' : 'text-emerald-400'}">{user.screening?.riskFlag ? 'Yes' : 'No'}</strong></span>
										<span class="text-gray-500">Last Screened: <strong class="text-gray-300">{formatDate(user.screening?.lastScreenedAt)}</strong></span>
									</div>
									{#if user.screening?.matches?.length}
										<div class="space-y-2">
											{#each user.screening.matches as match}
												<div class="bg-red-500/5 border border-red-500/10 rounded-lg p-3">
													<div class="flex items-center gap-2 flex-wrap">
														<span class="font-bold tabular-nums text-sm {scoreColor(match.score)}">{match.score?.toFixed(2)}</span>
														<span class="text-xs text-gray-300">{match.sanctionedName}</span>
														<span class="badge text-[10px] {match.matchType === 'primary' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'}">{match.matchType}</span>
														<span class="badge text-[10px] {sourceColors[match.source] ?? 'bg-gray-500/20 text-gray-400'}">{match.source}</span>
														<span class="text-[10px] text-gray-600 ml-auto">{formatDate(match.detectedAt)}</span>
													</div>
													<div class="text-[10px] text-gray-500 mt-1">Matched against: <span class="text-gray-400">{match.matchedAgainst}</span></div>
												</div>
											{/each}
										</div>
									{/if}
								</div>
							</div>
						{/if}
					</div>
				{:else}
					<div class="py-12 text-center text-sm text-gray-600">No flagged users — run a batch sweep to detect matches</div>
				{/each}
			</div>
		{/if}
	</div>


	<!-- Pipeline Viewer Modal -->
	{#if showPipeline}
		<!-- svelte-ignore a11y_no_static_element_interactions -->
		<div
			class="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 backdrop-blur-sm"
			onclick={() => showPipeline = false}
			onkeydown={(e) => { if (e.key === 'Escape') showPipeline = false; }}
		>
			<!-- svelte-ignore a11y_no_static_element_interactions -->
			<div
				class="bg-FuelRetail-slate border border-gray-700/50 rounded-xl shadow-2xl w-[820px] max-h-[85vh] flex flex-col"
				onclick={(e) => e.stopPropagation()}
			>
				<!-- Modal header -->
				<div class="flex items-center justify-between px-5 py-3.5 border-b border-gray-700/50">
					<div class="flex items-center gap-2">
						<svg class="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
						</svg>
						<h3 class="text-sm font-semibold text-white">
							{activeTab === 'check' ? 'Flow 1: Check User Pipeline' : 'Flow 2: Batch Sweep Pipeline'}
						</h3>
						<span class="badge text-[10px] {activeTab === 'check' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-blue-500/20 text-blue-400'}">
							{activeTab === 'check' ? 'sanctions_fuzzy' : 'profiles_fuzzy'}
						</span>
					</div>
					<button class="text-gray-500 hover:text-white transition-colors p-1" onclick={() => showPipeline = false}>
						<svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M6 18L18 6M6 6l12 12" />
						</svg>
					</button>
				</div>

				<!-- Modal body -->
				<div class="overflow-y-auto p-5 space-y-5">
					<!-- Aggregation pipeline -->
					<div>
						<div class="flex items-center gap-2 mb-2">
							<span class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Aggregation Pipeline</span>
							<span class="text-[10px] font-mono text-gray-600">
								{activeTab === 'check' ? 'db.sanctioned_list.aggregate(...)' : 'db.user_profiles.aggregate(...)'}
							</span>
						</div>

						{#if activeTab === 'check'}
<pre class="mql-code text-[11px] max-h-[320px] overflow-auto">db.sanctioned_list.aggregate([
  {'{'} <span class="text-emerald-400">$search</span>: {'{'}
    index: <span class="text-amber-300">"sanctions_fuzzy"</span>,
    compound: {'{'}
      should: [
        {'{'} text: {'{'}
          query: <span class="text-amber-300">"&lt;user_name&gt;"</span>,
          path: <span class="text-amber-300">"fullName"</span>,
          fuzzy: {'{'} maxEdits: <span class="text-blue-300">2</span>, prefixLength: <span class="text-blue-300">1</span> {'}'},
          score: {'{'} boost: {'{'} value: <span class="text-blue-300">2</span> {'}'} {'}'}
        {'}'} {'}'},
        {'{'} text: {'{'}
          query: <span class="text-amber-300">"&lt;user_name&gt;"</span>,
          path: <span class="text-amber-300">"aliases"</span>,
          fuzzy: {'{'} maxEdits: <span class="text-blue-300">2</span>, prefixLength: <span class="text-blue-300">1</span> {'}'}
        {'}'} {'}'}
      ],
      minimumShouldMatch: <span class="text-blue-300">1</span>,
      <span class="text-gray-500">// Optional DOB filter:</span>
      <span class="text-gray-500">// filter: [{'{'} equals: {'{'} path: "dateOfBirth", value: ISODate(...) {'}'} {'}'}]</span>
    {'}'}
  {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$addFields</span>: {'{'} score: {'{'} $meta: <span class="text-amber-300">"searchScore"</span> {'}'} {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$limit</span>: <span class="text-blue-300">10</span> {'}'},
  {'{'} <span class="text-emerald-400">$project</span>: {'{'}
    _id: <span class="text-blue-300">0</span>, fullName: <span class="text-blue-300">1</span>, aliases: <span class="text-blue-300">1</span>,
    dateOfBirth: <span class="text-blue-300">1</span>, country: <span class="text-blue-300">1</span>,
    source: <span class="text-blue-300">1</span>, category: <span class="text-blue-300">1</span>, score: <span class="text-blue-300">1</span>
  {'}'} {'}'}
])</pre>
						{:else}
<pre class="mql-code text-[11px] max-h-[320px] overflow-auto"><span class="text-gray-500">// For each sanctioned entry (sequential):</span>
db.user_profiles.aggregate([
  {'{'} <span class="text-emerald-400">$search</span>: {'{'}
    index: <span class="text-amber-300">"profiles_fuzzy"</span>,
    compound: {'{'}
      must: [
        {'{'} text: {'{'}
          query: <span class="text-amber-300">"&lt;sanctioned_name_or_alias&gt;"</span>,
          path: <span class="text-amber-300">"fullName"</span>,
          fuzzy: {'{'} maxEdits: <span class="text-blue-300">2</span>, prefixLength: <span class="text-blue-300">1</span> {'}'}
        {'}'} {'}'}
      ]
    {'}'}
  {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$addFields</span>: {'{'} score: {'{'} $meta: <span class="text-amber-300">"searchScore"</span> {'}'} {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$limit</span>: <span class="text-blue-300">10</span> {'}'},
  {'{'} <span class="text-emerald-400">$project</span>: {'{'}
    _id: <span class="text-blue-300">0</span>, userId: <span class="text-blue-300">1</span>, fullName: <span class="text-blue-300">1</span>,
    dateOfBirth: <span class="text-blue-300">1</span>, score: <span class="text-blue-300">1</span>,
    email: <span class="text-blue-300">1</span>, phone: <span class="text-blue-300">1</span>,
    status: <span class="text-blue-300">1</span>, kyc: <span class="text-blue-300">1</span>,
    wallet: <span class="text-blue-300">1</span>, screening: <span class="text-blue-300">1</span>
  {'}'} {'}'}
])

<span class="text-gray-500">// Matches with score &gt; 0.5 are flagged in-place:</span>
db.user_profiles.updateOne(
  {'{'} userId: <span class="text-amber-300">"&lt;matched_userId&gt;"</span> {'}'},
  {'{'}
    $set: {'{'}
      <span class="text-amber-300">"screening.lastScreenedAt"</span>: <span class="text-blue-300">ISODate()</span>,
      <span class="text-amber-300">"screening.riskFlag"</span>: <span class="text-blue-300">true</span>
    {'}'},
    $push: {'{'} <span class="text-amber-300">"screening.matches"</span>: matchDoc {'}'}
  {'}'}
)</pre>
						{/if}
					</div>

					<!-- Autocomplete pipeline -->
					<div>
						<div class="flex items-center gap-2 mb-2">
							<span class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Autocomplete Pipeline</span>
							<span class="text-[10px] font-mono text-gray-600">
								{activeTab === 'check' ? 'db.sanctioned_list.aggregate(...)' : 'db.user_profiles.aggregate(...)'}
							</span>
						</div>
						{#if activeTab === 'check'}
<pre class="mql-code text-[11px] max-h-[180px] overflow-auto">db.sanctioned_list.aggregate([
  {'{'} <span class="text-emerald-400">$search</span>: {'{'}
    index: <span class="text-amber-300">"sanctions_fuzzy"</span>,
    compound: {'{'}
      should: [
        {'{'} autocomplete: {'{'}
          query: <span class="text-amber-300">"&lt;partial_input&gt;"</span>,
          path: <span class="text-amber-300">"fullName"</span>,
          fuzzy: {'{'} maxEdits: <span class="text-blue-300">1</span>, prefixLength: <span class="text-blue-300">1</span> {'}'}
        {'}'} {'}'},
        {'{'} autocomplete: {'{'}
          query: <span class="text-amber-300">"&lt;partial_input&gt;"</span>,
          path: <span class="text-amber-300">"aliases"</span>,
          fuzzy: {'{'} maxEdits: <span class="text-blue-300">1</span>, prefixLength: <span class="text-blue-300">1</span> {'}'}
        {'}'} {'}'}
      ],
      minimumShouldMatch: <span class="text-blue-300">1</span>
    {'}'}
  {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$addFields</span>: {'{'} score: {'{'} $meta: <span class="text-amber-300">"searchScore"</span> {'}'} {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$limit</span>: <span class="text-blue-300">8</span> {'}'},
  {'{'} <span class="text-emerald-400">$project</span>: {'{'} _id: <span class="text-blue-300">0</span>, fullName: <span class="text-blue-300">1</span>, aliases: <span class="text-blue-300">1</span>, source: <span class="text-blue-300">1</span>, country: <span class="text-blue-300">1</span>, category: <span class="text-blue-300">1</span>, score: <span class="text-blue-300">1</span> {'}'} {'}'}
])</pre>
						{:else}
<pre class="mql-code text-[11px] max-h-[180px] overflow-auto">db.user_profiles.aggregate([
  {'{'} <span class="text-emerald-400">$search</span>: {'{'}
    index: <span class="text-amber-300">"profiles_fuzzy"</span>,
    autocomplete: {'{'}
      query: <span class="text-amber-300">"&lt;partial_input&gt;"</span>,
      path: <span class="text-amber-300">"fullName"</span>,
      fuzzy: {'{'} maxEdits: <span class="text-blue-300">1</span>, prefixLength: <span class="text-blue-300">1</span> {'}'}
    {'}'}
  {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$addFields</span>: {'{'} score: {'{'} $meta: <span class="text-amber-300">"searchScore"</span> {'}'} {'}'} {'}'},
  {'{'} <span class="text-emerald-400">$limit</span>: <span class="text-blue-300">8</span> {'}'},
  {'{'} <span class="text-emerald-400">$project</span>: {'{'} _id: <span class="text-blue-300">0</span>, userId: <span class="text-blue-300">1</span>, fullName: <span class="text-blue-300">1</span>, status: <span class="text-blue-300">1</span>, score: <span class="text-blue-300">1</span> {'}'} {'}'}
])</pre>
						{/if}
					</div>

					<!-- Index definition -->
					<div>
						<div class="flex items-center gap-2 mb-2">
							<span class="text-[10px] text-gray-500 uppercase tracking-wider font-medium">Index Definition</span>
							<span class="badge text-[10px] {activeTab === 'check' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-blue-500/20 text-blue-400'}">
								{activeTab === 'check' ? 'sanctions_fuzzy' : 'profiles_fuzzy'}
							</span>
							<span class="text-[10px] text-gray-600 font-mono">on {activeTab === 'check' ? 'sanctioned_list' : 'user_profiles'}</span>
						</div>
						{#if activeTab === 'check'}
<pre class="mql-code text-[11px] max-h-[280px] overflow-auto">{'{'}
  <span class="text-emerald-400">"name"</span>: <span class="text-amber-300">"sanctions_fuzzy"</span>,
  <span class="text-emerald-400">"definition"</span>: {'{'}
    <span class="text-emerald-400">"analyzers"</span>: [{'{'}
      <span class="text-emerald-400">"name"</span>: <span class="text-amber-300">"malay_name_analyzer"</span>,
      <span class="text-emerald-400">"charFilters"</span>: [{'{'}
        <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"mapping"</span>,
        <span class="text-emerald-400">"mappings"</span>: {'{'}
          <span class="text-amber-300">" bin "</span>: <span class="text-amber-300">" "</span>,  <span class="text-amber-300">" binti "</span>: <span class="text-amber-300">" "</span>,
          <span class="text-amber-300">" a/l "</span>: <span class="text-amber-300">" "</span>,  <span class="text-amber-300">" a/p "</span>: <span class="text-amber-300">" "</span>,
          <span class="text-gray-500">// + uppercase variants...</span>
        {'}'}
      {'}'}],
      <span class="text-emerald-400">"tokenizer"</span>: {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"standard"</span> {'}'},
      <span class="text-emerald-400">"tokenFilters"</span>: [{'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"lowercase"</span> {'}'}]
    {'}'}],
    <span class="text-emerald-400">"mappings"</span>: {'{'}
      <span class="text-emerald-400">"dynamic"</span>: <span class="text-blue-300">false</span>,
      <span class="text-emerald-400">"fields"</span>: {'{'}
        <span class="text-emerald-400">"fullName"</span>: [
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"string"</span>, <span class="text-emerald-400">"analyzer"</span>: <span class="text-amber-300">"malay_name_analyzer"</span> {'}'},
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"autocomplete"</span>, <span class="text-emerald-400">"tokenization"</span>: <span class="text-amber-300">"edgeGram"</span>,
            <span class="text-emerald-400">"minGrams"</span>: <span class="text-blue-300">2</span>, <span class="text-emerald-400">"maxGrams"</span>: <span class="text-blue-300">15</span> {'}'}
        ],
        <span class="text-emerald-400">"aliases"</span>: [
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"string"</span>, <span class="text-emerald-400">"analyzer"</span>: <span class="text-amber-300">"malay_name_analyzer"</span> {'}'},
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"autocomplete"</span>, <span class="text-emerald-400">"tokenization"</span>: <span class="text-amber-300">"edgeGram"</span>,
            <span class="text-emerald-400">"minGrams"</span>: <span class="text-blue-300">2</span>, <span class="text-emerald-400">"maxGrams"</span>: <span class="text-blue-300">15</span> {'}'}
        ],
        <span class="text-emerald-400">"dateOfBirth"</span>: {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"date"</span> {'}'}
      {'}'}
    {'}'}
  {'}'}
{'}'}</pre>
						{:else}
<pre class="mql-code text-[11px] max-h-[280px] overflow-auto">{'{'}
  <span class="text-emerald-400">"name"</span>: <span class="text-amber-300">"profiles_fuzzy"</span>,
  <span class="text-emerald-400">"definition"</span>: {'{'}
    <span class="text-emerald-400">"analyzers"</span>: [{'{'}
      <span class="text-emerald-400">"name"</span>: <span class="text-amber-300">"malay_name_analyzer"</span>,
      <span class="text-emerald-400">"charFilters"</span>: [{'{'}
        <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"mapping"</span>,
        <span class="text-emerald-400">"mappings"</span>: {'{'}
          <span class="text-amber-300">" bin "</span>: <span class="text-amber-300">" "</span>,  <span class="text-amber-300">" binti "</span>: <span class="text-amber-300">" "</span>,
          <span class="text-amber-300">" a/l "</span>: <span class="text-amber-300">" "</span>,  <span class="text-amber-300">" a/p "</span>: <span class="text-amber-300">" "</span>,
          <span class="text-gray-500">// + uppercase variants...</span>
        {'}'}
      {'}'}],
      <span class="text-emerald-400">"tokenizer"</span>: {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"standard"</span> {'}'},
      <span class="text-emerald-400">"tokenFilters"</span>: [{'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"lowercase"</span> {'}'}]
    {'}'}],
    <span class="text-emerald-400">"mappings"</span>: {'{'}
      <span class="text-emerald-400">"dynamic"</span>: <span class="text-blue-300">false</span>,
      <span class="text-emerald-400">"fields"</span>: {'{'}
        <span class="text-emerald-400">"fullName"</span>: [
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"string"</span>, <span class="text-emerald-400">"analyzer"</span>: <span class="text-amber-300">"malay_name_analyzer"</span> {'}'},
          {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"autocomplete"</span>, <span class="text-emerald-400">"tokenization"</span>: <span class="text-amber-300">"edgeGram"</span>,
            <span class="text-emerald-400">"minGrams"</span>: <span class="text-blue-300">2</span>, <span class="text-emerald-400">"maxGrams"</span>: <span class="text-blue-300">15</span> {'}'}
        ],
        <span class="text-emerald-400">"dateOfBirth"</span>: {'{'} <span class="text-emerald-400">"type"</span>: <span class="text-amber-300">"date"</span> {'}'}
      {'}'}
    {'}'}
  {'}'}
{'}'}</pre>
						{/if}
					</div>

					<!-- Analyzer note -->
					<div class="px-3 py-2.5 bg-gray-900/50 border border-gray-700/30 rounded-lg">
						<div class="text-[10px] text-gray-500">
							<strong class="text-gray-400">malay_name_analyzer</strong> — Custom analyzer that strips Malaysian name connectors
							(<code class="text-emerald-400/50">bin</code>, <code class="text-emerald-400/50">binti</code>,
							<code class="text-emerald-400/50">a/l</code>, <code class="text-emerald-400/50">a/p</code>)
							via charFilter mappings before tokenization. This ensures "Ahmad bin Ibrahim" and "Ahmad Ibrahim" produce the same tokens, enabling accurate fuzzy matching across naming conventions.
						</div>
					</div>
				</div>
			</div>
		</div>
	{/if}
</div>
