<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { mediaHref } from '#lib/media/format.ts';
	import { isPlainClick } from '#lib/transitions/media-expand.ts';
	import MediaMeta from '../media/MediaMeta.svelte';
	import MyListButton from '../media/MyListButton.svelte';
	import LinkButton from '../ui/LinkButton.svelte';

	let {
		media,
		inMyList,
		onmylistchange,
		onselect
	}: {
		media: MediaSummary;
		inMyList: boolean;
		onmylistchange: (media: MediaSummary, inList: boolean) => void;
		/** A plain click on "More info", which the router is about to follow. */
		onselect?: (link: HTMLAnchorElement) => void;
	} = $props();

	function handleClick(event: MouseEvent & { currentTarget: HTMLAnchorElement }) {
		if (isPlainClick(event)) onselect?.(event.currentTarget);
	}
</script>

<div class="info">
	<div class="text">
		<MediaMeta {media} />
		<h2>{media.title}</h2>
		{#if media.overview}
			<p class="overview">{media.overview}</p>
		{/if}
	</div>
	<div class="actions">
		<LinkButton href={mediaHref(media.media_type, media.id)} icon="info" onclick={handleClick}>
			More info
		</LinkButton>
		<MyListButton {media} inList={inMyList} onchange={onmylistchange} />
	</div>
</div>

<style>
	/* Text on the left, actions pinned to the right; stacked on narrow screens */
	.info {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-4);
	}

	.text {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-4);
		max-width: 40rem;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	@media (min-width: 48rem) {
		.info {
			flex-direction: row;
			justify-content: space-between;
			align-items: flex-end;
			gap: var(--space-8);
		}

		.actions {
			flex-wrap: nowrap;
			flex-shrink: 0;
		}
	}

	h2 {
		font-family: var(--font-display);
		font-size: clamp(2.25rem, 5vw + 1rem, 4.5rem);
		line-height: 1.05;
		text-wrap: balance;
		text-shadow: 0 0.125rem 1.5rem oklch(0% 0 0 / 0.5);
	}

	.overview {
		display: -webkit-box;
		-webkit-line-clamp: 3;
		line-clamp: 3;
		-webkit-box-orient: vertical;
		overflow: hidden;
		color: var(--color-text);
		font-size: var(--text-md);
		line-height: 1.6;
		text-shadow: 0 0.0625rem 0.5rem oklch(0% 0 0 / 0.6);
	}
</style>
