<div class="p-6">
	<!-- Header -->
	<div class="mb-6">
		<h1 class="text-2xl font-semibold text-white">FuelRetail Technical Field Workshop</h1>
		<p class="text-sm text-gray-400 mt-1">MongoDB Atlas — Three use cases for Malaysia's leading e-wallet platform</p>
	</div>

	<!-- Stats row -->
	<div class="grid grid-cols-3 gap-4 mb-6">
		<div class="card">
			<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Use Cases</div>
			<div class="text-2xl font-bold text-white mt-1">3</div>
			<div class="text-xs text-gray-500 mt-1">Screening · Analytics · Fraud</div>
		</div>
		<div class="card">
			<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">Stack</div>
			<div class="text-2xl font-bold text-white mt-1">MongoDB</div>
			<div class="text-xs text-gray-500 mt-1">Atlas + MSK + Stream Processing</div>
		</div>
		<div class="card">
			<div class="text-xs text-gray-400 uppercase tracking-wider font-medium">AI</div>
			<div class="text-2xl font-bold text-white mt-1">Voyage</div>
			<div class="text-xs text-gray-500 mt-1">Embeddings + Vector Search</div>
		</div>
	</div>

	<!-- Use case cards -->
	<div class="grid grid-cols-1 xl:grid-cols-3 gap-5">
		<a href="/screening" class="card-hover group block">
			<div class="flex items-center gap-3 mb-3">
				<div class="w-9 h-9 rounded-lg bg-blue-500/20 flex items-center justify-center">
					<svg class="w-4.5 h-4.5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
					</svg>
				</div>
				<div>
					<div class="text-xs text-gray-500 uppercase tracking-wider font-medium">UC1</div>
					<h2 class="text-base font-semibold text-white">Name Screening</h2>
				</div>
			</div>
			<p class="text-sm text-gray-400 leading-relaxed mb-4">Atlas Search with fuzzy matching for AML/KYC compliance against sanctioned lists. Malay name handling with bin/binti/a-l/a-p conventions.</p>
			<div class="flex flex-wrap gap-1.5">
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/10 text-blue-400">Atlas Search</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/10 text-blue-400">Fuzzy Match</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/10 text-blue-400">AML/KYC</span>
			</div>
		</a>

		<a href="/analytics" class="card-hover group block">
			<div class="flex items-center gap-3 mb-3">
				<div class="w-9 h-9 rounded-lg bg-emerald-500/20 flex items-center justify-center">
					<svg class="w-4.5 h-4.5 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155" />
					</svg>
				</div>
				<div>
					<div class="text-xs text-gray-500 uppercase tracking-wider font-medium">UC2</div>
					<h2 class="text-base font-semibold text-white">Analytics Chatbot</h2>
				</div>
			</div>
			<p class="text-sm text-gray-400 leading-relaxed mb-4">Natural language querying over transaction data with Atlas Vector Search. Ask questions, get MQL and results.</p>
			<div class="flex flex-wrap gap-1.5">
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400">Vector Search</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400">LangGraph</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-500/10 text-emerald-400">NL → MQL</span>
			</div>
		</a>

		<a href="/fraud" class="card-hover group block border-FuelRetail-red/20!">
			<div class="flex items-center gap-3 mb-3">
				<div class="w-9 h-9 rounded-lg bg-red-500/20 flex items-center justify-center">
					<svg class="w-4.5 h-4.5 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
						<path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
					</svg>
				</div>
				<div>
					<div class="text-xs text-gray-500 uppercase tracking-wider font-medium">UC3</div>
					<h2 class="text-base font-semibold text-white">Fraud Detection</h2>
				</div>
			</div>
			<p class="text-sm text-gray-400 leading-relaxed mb-4">Real-time transaction monitoring with MSK + Atlas Stream Processing. Configurable signal rules, fraud similarity via Voyage AI embeddings.</p>
			<div class="flex flex-wrap gap-1.5">
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-500/10 text-red-400">Stream Processing</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-500/10 text-red-400">MSK</span>
				<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-500/10 text-red-400">Voyage AI</span>
			</div>
		</a>
	</div>

	<!-- Architecture summary -->
	<div class="card mt-6">
		<div class="flex items-center gap-2 mb-3">
			<svg class="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
				<path d="M5.25 14.25h13.5m-13.5 0a3 3 0 01-3-3m3 3a3 3 0 100 6h13.5a3 3 0 100-6m-16.5-3a3 3 0 013-3h13.5a3 3 0 013 3m-19.5 0a4.5 4.5 0 01.9-2.7L5.737 5.1a3.375 3.375 0 012.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 01.9 2.7m0 0a3 3 0 01-3 3m0 3h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008zm-3 6h.008v.008h-.008v-.008zm0-6h.008v.008h-.008v-.008z" />
			</svg>
			<h3 class="text-sm font-semibold text-white">Technology Stack</h3>
		</div>
		<div class="flex flex-wrap items-center gap-3">
			{#each ['MongoDB Atlas', 'Atlas Search', 'Atlas Vector Search', 'Atlas Stream Processing', 'Amazon MSK', 'Voyage AI', 'LangGraph', 'FastAPI', 'SvelteKit'] as tech}
				<span class="font-mono text-xs px-2.5 py-1 rounded-md bg-gray-800/80 text-gray-400 border border-gray-700/50">{tech}</span>
			{/each}
		</div>
	</div>
</div>
