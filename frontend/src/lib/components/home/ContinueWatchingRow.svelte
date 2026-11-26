<script lang="ts">
	import type { ContinueWatching } from '#lib/api/client.ts';
	import HorizontalScroller from '../ui/HorizontalScroller.svelte';
	import ContinueCard from './ContinueCard.svelte';

	let { items }: { items: ContinueWatching[] } = $props();
	const title = 'Continue watching';
</script>

<section class="row">
	<h2 class="section-title">{title}</h2>
	<HorizontalScroller
		{items}
		key={(item: ContinueWatching) => `${item.media.media_type}-${item.media.id}`}
		label={title}
		itemWidth="var(--row-card-width)"
		gutter="var(--content-inset)"
	>
		{#snippet item(entry: ContinueWatching)}
			<ContinueCard item={entry} sizes="(min-width: 48rem) 18rem, 14rem" />
		{/snippet}
	</HorizontalScroller>
</section>

<style>
	.row {
		--row-card-width: 14rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h2 {
		padding: 0 var(--content-inset);
	}

	@media (min-width: 48rem) {
		.row {
			--row-card-width: 18rem;
		}
	}
</style>
