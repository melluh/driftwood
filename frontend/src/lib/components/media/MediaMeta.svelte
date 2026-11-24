<!-- One line of at-a-glance facts: media type, year and rating. -->
<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { formatRating } from '#lib/media/format.ts';
	import Icon from '../ui/Icon.svelte';
	import MediaTypeChip from './MediaTypeChip.svelte';

	let {
		media,
		showRating = true
	}: {
		media: Pick<MediaSummary, 'media_type' | 'year' | 'vote_average'>;
		showRating?: boolean;
	} = $props();

	const rating = $derived(showRating ? formatRating(media.vote_average) : null);
</script>

<span class="meta">
	<MediaTypeChip type={media.media_type} />
	{#if media.year}<span>{media.year}</span>{/if}
	{#if rating}
		<span class="rating" aria-label="Rated {rating} out of 10">
			<Icon name="star" size="1em" />
			{rating}
		</span>
	{/if}
</span>

<style>
	.meta {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		color: var(--color-text-muted);
	}

	.rating {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}

	.rating :global(svg) {
		color: var(--color-accent);
	}
</style>
