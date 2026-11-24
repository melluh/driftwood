<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import MediaCard from '../media/MediaCard.svelte';
	import HorizontalScroller from '../ui/HorizontalScroller.svelte';

	let { title, items }: { title: string; items: MediaSummary[] } = $props();
</script>

<section class="row">
	<h2>{title}</h2>
	<HorizontalScroller
		{items}
		key={(media: MediaSummary) => `${media.media_type}-${media.id}`}
		label={title}
		itemWidth="var(--row-card-width)"
		gutter="var(--content-inset)"
	>
		{#snippet item(media)}
			<MediaCard {media} sizes="(min-width: 48rem) 11rem, 8rem" />
		{/snippet}
	</HorizontalScroller>
</section>

<style>
	.row {
		--row-card-width: 8rem;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h2 {
		padding: 0 var(--content-inset);
		font-family: var(--font-display);
		font-size: var(--text-xl);
	}

	@media (min-width: 48rem) {
		.row {
			--row-card-width: 11rem;
		}
	}
</style>
