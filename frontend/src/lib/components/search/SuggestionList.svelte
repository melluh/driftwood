<script lang="ts">
	import { suggestionOptionId, type MediaSearch } from '#lib/search/media-search.svelte.ts';
	import SearchMessage from './SearchMessage.svelte';
	import SuggestionItem from './SuggestionItem.svelte';

	let {
		search,
		id,
		onselect
	}: {
		search: MediaSearch;
		id: string;
		onselect: (link: HTMLAnchorElement) => void;
	} = $props();
</script>

{#if search.phase === 'error'}
	<SearchMessage icon="alert">Search failed. Is the Driftwood server running?</SearchMessage>
{:else if search.phase === 'ready' && search.results.length === 0}
	{#if search.indexStatus?.status === 'building'}
		<SearchMessage>The title index is still being built; try again in a minute.</SearchMessage>
	{:else}
		<SearchMessage>Nothing found for “{search.trimmedQuery}”.</SearchMessage>
	{/if}
{/if}

<ul {id} role="listbox" aria-label="Search results" class:stale={search.phase === 'loading'}>
	{#each search.results as item, index (`${item.media_type}-${item.id}`)}
		<SuggestionItem
			{item}
			id={suggestionOptionId(id, index)}
			highlighted={index === search.highlightedIndex}
			{onselect}
			onhover={() => (search.highlightedIndex = index)}
		/>
	{/each}
</ul>

<style>
	ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
		transition: opacity var(--duration-fast);
	}

	.stale {
		opacity: 0.7;
	}
</style>
