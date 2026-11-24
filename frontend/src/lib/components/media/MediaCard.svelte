<!-- A poster card linking to the media's page, for rows and grids. -->
<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { mediaHref } from '#lib/media/format.ts';
	import { expandFrom, isPlainClick } from '#lib/transitions/media-expand.ts';
	import PosterImage from './PosterImage.svelte';

	let {
		media,
		sizes
	}: {
		media: MediaSummary;
		/** Rendered poster width, for image size selection. */
		sizes: string;
	} = $props();

	let card: HTMLAnchorElement | undefined = $state();

	function handleClick(event: MouseEvent) {
		if (card && isPlainClick(event)) expandFrom(card);
	}
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- mediaHref() resolves the route -->
<a href={mediaHref(media.media_type, media.id)} class="card" bind:this={card} onclick={handleClick}>
	<!-- eslint-enable svelte/no-navigation-without-resolve -->
	<div class="poster">
		<PosterImage path={media.poster_path} title={media.title} {sizes} />
	</div>
	<span class="title truncate">{media.title}</span>
	{#if media.year}<span class="year">{media.year}</span>{/if}
</a>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.poster {
		margin-bottom: var(--space-2);
		border-radius: var(--radius-md);
		transition:
			transform var(--duration-slow) var(--ease-out),
			box-shadow var(--duration-fast);
	}

	.card:hover .poster,
	.card:focus-visible .poster {
		transform: translateY(-0.25rem) scale(1.03);
		box-shadow: 0 0 0 2px var(--color-accent);
	}

	.card:focus-visible {
		outline: none;
	}

	.title {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.year {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
</style>
