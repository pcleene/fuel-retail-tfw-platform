<script lang="ts">
	import '../app.css';
	import { page } from '$app/state';

	let { children } = $props();

	const navItems = [
		{ href: '/', label: 'Dashboard', icon: 'grid' },
		{ href: '/screening', label: 'Name Screening', icon: 'search' },
		{ href: '/analytics', label: 'Analytics Chatbot', icon: 'chat' },
		{ href: '/fraud', label: 'Fraud Detection', icon: 'bolt' },
	];

	let currentPath = $derived(page.url.pathname);

	function isActive(href: string): boolean {
		if (href === '/') return currentPath === '/';
		return currentPath.startsWith(href);
	}
</script>

<svelte:head>
	<link rel="preconnect" href="https://fonts.googleapis.com" />
	<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin="anonymous" />
	<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet" />
	<title>FuelRetail Demo</title>
</svelte:head>

<div class="flex h-screen overflow-hidden">
	<!-- Sidebar -->
	<nav class="w-60 flex-shrink-0 bg-FuelRetail-charcoal border-r border-gray-800 flex flex-col">
		<!-- Logo -->
		<div class="p-5 border-b border-gray-800">
			<div class="flex items-center gap-3">
				<div class="w-8 h-8 rounded-lg bg-gradient-to-br from-FuelRetail-red to-FuelRetail-orange flex items-center justify-center text-white font-bold text-sm">S</div>
				<div>
					<div class="text-sm font-semibold text-white tracking-wide">FuelRetail</div>
					<div class="text-[10px] text-gray-500 uppercase tracking-widest">Technical Field Workshop</div>
				</div>
			</div>
		</div>

		<!-- Nav -->
		<div class="flex-1 p-3 space-y-1">
			{#each navItems as item}
				<a
					href={item.href}
					class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-colors duration-150
						{isActive(item.href)
							? 'bg-FuelRetail-red/10 text-FuelRetail-red border border-FuelRetail-red/20'
							: 'text-gray-400 hover:text-gray-200 hover:bg-white/5 border border-transparent'}"
				>
					{#if item.icon === 'grid'}
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M3.75 6A2.25 2.25 0 016 3.75h2.25A2.25 2.25 0 0110.5 6v2.25a2.25 2.25 0 01-2.25 2.25H6a2.25 2.25 0 01-2.25-2.25V6zM3.75 15.75A2.25 2.25 0 016 13.5h2.25a2.25 2.25 0 012.25 2.25V18a2.25 2.25 0 01-2.25 2.25H6A2.25 2.25 0 013.75 18v-2.25zM13.5 6a2.25 2.25 0 012.25-2.25H18A2.25 2.25 0 0120.25 6v2.25A2.25 2.25 0 0118 10.5h-2.25a2.25 2.25 0 01-2.25-2.25V6zM13.5 15.75a2.25 2.25 0 012.25-2.25H18a2.25 2.25 0 012.25 2.25V18A2.25 2.25 0 0118 20.25h-2.25a2.25 2.25 0 01-2.25-2.25v-2.25z" />
						</svg>
					{:else if item.icon === 'search'}
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z" />
						</svg>
					{:else if item.icon === 'chat'}
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M7.5 8.25h9m-9 3H12m-9.75 1.51c0 1.6 1.123 2.994 2.707 3.227 1.129.166 2.27.293 3.423.379.35.026.67.21.865.501L12 21l2.755-4.133a1.14 1.14 0 01.865-.501 48.172 48.172 0 003.423-.379c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z" />
						</svg>
					{:else if item.icon === 'bolt'}
						<svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
							<path d="M3.75 13.5l10.5-11.25L12 10.5h8.25L9.75 21.75 12 13.5H3.75z" />
						</svg>
					{/if}
					<span class="text-xs">{item.label}</span>
				</a>
			{/each}
		</div>

		<!-- Status -->
		<div class="p-4 border-t border-gray-800 space-y-2">
			<div class="flex items-center gap-2 text-xs text-gray-500">
				<div class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></div>
				<span>MongoDB Atlas</span>
			</div>
			<div class="flex items-center gap-2 text-xs text-gray-500">
				<div class="w-2 h-2 rounded-full bg-FuelRetail-orange animate-pulse"></div>
				<span>Amazon MSK</span>
			</div>
		</div>
	</nav>

	<!-- Main content -->
	<main class="flex-1 overflow-y-auto bg-FuelRetail-dark">
		{@render children()}
	</main>
</div>
