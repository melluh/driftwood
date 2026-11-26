<script lang="ts">
	import ContinueWatchingRow from '#lib/components/home/ContinueWatchingRow.svelte';
	import FeaturedCarousel from '#lib/components/home/FeaturedCarousel.svelte';
	import MediaRow from '#lib/components/home/MediaRow.svelte';
	import type { MediaSummary } from '#lib/api/client.ts';
	import { withMedia } from '#lib/my-list/my-list.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	// Toggling from the hero or a card updates the shelf and every card right away.
	let myList = $derived(data.myList);

	function setInMyList(media: MediaSummary, inList: boolean) {
		myList = withMedia(myList, media, inList);
	}
</script>

<FeaturedCarousel items={data.home.featured} {myList} onmylistchange={setInMyList} />

<div class="rows">
	{#if data.continueWatching.length}
		<ContinueWatchingRow items={data.continueWatching} />
	{/if}
	{#if myList.length}
		<MediaRow title="My list" items={myList} {myList} onmylistchange={setInMyList} />
	{/if}
	{#each data.home.rows as row (row.id)}
		<MediaRow title={row.title} items={row.items} {myList} onmylistchange={setInMyList} />
	{/each}
</div>

<style>
	.rows {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-8);
		margin-top: var(--space-6);
		padding-bottom: var(--space-12);
	}
</style>
