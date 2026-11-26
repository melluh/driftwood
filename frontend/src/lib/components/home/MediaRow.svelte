<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import MediaCard from '../media/MediaCard.svelte';
	import { isSameMedia } from '#lib/my-list/my-list.ts';
	import HorizontalScroller from '../ui/HorizontalScroller.svelte';

	let {
		title,
		items,
		myList,
		onmylistchange
	}: {
		title: string;
		items: MediaSummary[];
		/** Saved titles, to mark the cards that are on the list. */
		myList: MediaSummary[];
		onmylistchange: (media: MediaSummary, inList: boolean) => void;
	} = $props();
</script>

<section class="row">
	<h2 class="section-title">{title}</h2>
	<HorizontalScroller
		{items}
		key={(media: MediaSummary) => `${media.media_type}-${media.id}`}
		label={title}
		itemWidth="var(--row-card-width)"
		gutter="var(--content-inset)"
	>
		{#snippet item(media: MediaSummary)}
			<MediaCard
				{media}
				sizes="(min-width: 48rem) 11rem, 8rem"
				inMyList={myList.some((saved) => isSameMedia(saved, media))}
				{onmylistchange}
			/>
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
	}

	@media (min-width: 48rem) {
		.row {
			--row-card-width: 11rem;
		}
	}
</style>
