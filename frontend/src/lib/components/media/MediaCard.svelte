<!--
	A poster card linking to the media's page, for rows and grids. With
	`onmylistchange` it also gets a My list toggle in the poster's top-right
	corner.
-->
<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { mediaHref } from '#lib/media/format.ts';
	import { ASPECT_RATIO } from '#lib/tmdb/images.ts';
	import { expandFrom, isPlainClick } from '#lib/transitions/media-expand.ts';
	import MyListButton from './MyListButton.svelte';
	import PosterImage from './PosterImage.svelte';

	let {
		media,
		sizes,
		inMyList = false,
		onmylistchange
	}: {
		media: MediaSummary;
		/** Rendered poster width, for image size selection. */
		sizes: string;
		inMyList?: boolean;
		onmylistchange?: (media: MediaSummary, inList: boolean) => void;
	} = $props();

	let link: HTMLAnchorElement | undefined = $state();

	function handleClick(event: MouseEvent) {
		if (link && isPlainClick(event)) expandFrom(link);
	}
</script>

<div class="card">
	<!-- eslint-disable svelte/no-navigation-without-resolve -- mediaHref() resolves the route -->
	<a
		href={mediaHref(media.media_type, media.id)}
		class="link"
		bind:this={link}
		onclick={handleClick}
	>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
		<div class="poster lifts">
			<PosterImage path={media.poster_path} title={media.title} {sizes} />
		</div>
		<span class="title truncate">{media.title}</span>
		{#if media.year}<span class="year">{media.year}</span>{/if}
	</a>
	{#if onmylistchange}
		<!-- A button can't sit inside the link, so this overlays the poster and lifts with it. -->
		<div
			class="poster-overlay lifts"
			class:saved={inMyList}
			style:aspect-ratio={ASPECT_RATIO.poster}
		>
			<MyListButton {media} inList={inMyList} onchange={onmylistchange} size="sm" />
		</div>
	{/if}
</div>

<style>
	.card {
		position: relative;
	}

	.link {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.lifts {
		transition:
			transform var(--duration-slow) var(--ease-out),
			box-shadow var(--duration-fast);
	}

	.card:hover .lifts,
	.card:has(.link:focus-visible) .lifts {
		transform: translateY(-0.25rem) scale(1.03);
	}

	.poster {
		margin-bottom: var(--space-2);
		border-radius: var(--radius-md);
	}

	.card:hover .poster,
	.link:focus-visible .poster {
		box-shadow: 0 0 0 2px var(--color-accent);
	}

	.link:focus-visible {
		outline: none;
	}

	.poster-overlay {
		position: absolute;
		top: 0;
		left: 0;
		width: 100%;
		display: flex;
		justify-content: flex-end;
		align-items: flex-start;
		padding: var(--space-2);
		pointer-events: none;
	}

	/* Hidden until the card is hovered or focused, unless the title is saved. */
	.poster-overlay > :global(*) {
		opacity: 0;
		transition: opacity var(--duration-fast);
	}

	.card:hover .poster-overlay > :global(*),
	.card:focus-within .poster-overlay > :global(*),
	.poster-overlay.saved > :global(*) {
		opacity: 1;
		pointer-events: auto;
	}

	/* Without hover there's nothing to reveal it: always there, to tap. */
	@media (hover: none) {
		.poster-overlay > :global(*) {
			opacity: 1;
			pointer-events: auto;
		}
	}

	.title {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.year {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}

	@media (prefers-reduced-motion: reduce) {
		.lifts {
			transition: none;
		}
	}
</style>
