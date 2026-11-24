<script lang="ts">
	import '#lib/styles/base.css';
	import AppHeader from '#lib/components/layout/AppHeader.svelte';
	import SearchOverlay from '#lib/components/search/SearchOverlay.svelte';
	import { SearchOverlayState, setSearchOverlay } from '#lib/search/overlay.svelte.ts';
	import { setupMediaExpandTransition } from '#lib/transitions/media-expand.ts';
	import type { LayoutProps } from './$types';

	let { children, data }: LayoutProps = $props();

	const overlay = setSearchOverlay(new SearchOverlayState());
	setupMediaExpandTransition();
</script>

<svelte:head>
	<title>Driftwood</title>
</svelte:head>

{#if data.user}
	<AppHeader user={data.user} onsearch={overlay.open} />
{/if}

<main>
	{@render children()}
</main>

{#if data.user && overlay.isOpen}
	<SearchOverlay onclose={overlay.close} />
{/if}
