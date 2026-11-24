<script lang="ts">
	import '#lib/styles/base.css';
	import AppHeader from '#lib/components/layout/AppHeader.svelte';
	import SearchOverlay from '#lib/components/search/SearchOverlay.svelte';
	import { SearchOverlayState, setSearchOverlay } from '#lib/search/overlay.svelte.ts';
	import type { LayoutProps } from './$types';

	let { children }: LayoutProps = $props();

	const overlay = setSearchOverlay(new SearchOverlayState());
</script>

<svelte:head>
	<title>Driftwood</title>
</svelte:head>

<AppHeader onsearch={overlay.open} />

<main>
	{@render children()}
</main>

{#if overlay.isOpen}
	<SearchOverlay onclose={overlay.close} />
{/if}
