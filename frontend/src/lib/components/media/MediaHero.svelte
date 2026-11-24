<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { MediaDetails } from '#lib/api/client.ts';
	import { alternateTitle } from '#lib/media/format.ts';
	import HeroFrame from './HeroFrame.svelte';
	import MediaTypeChip from './MediaTypeChip.svelte';
	import PosterImage from './PosterImage.svelte';

	let { media, children }: { media: MediaDetails; children?: Snippet } = $props();

	const originalTitle = $derived(alternateTitle(media));
</script>

<HeroFrame backdropPath={media.backdrop_path}>
	<div class="layout">
		<div class="poster">
			<PosterImage
				path={media.poster_path}
				title={media.title}
				sizes="(min-width: 48rem) 16rem, 10rem"
				eager
			/>
		</div>
		<div class="info">
			<MediaTypeChip type={media.media_type} />
			<h1>
				{media.title}
				{#if media.year}<span class="year">({media.year})</span>{/if}
			</h1>
			{#if originalTitle}
				<p class="original">{originalTitle}</p>
			{/if}
			{#if media.tagline}
				<p class="tagline">{media.tagline}</p>
			{/if}
			{@render children?.()}
		</div>
	</div>
</HeroFrame>

<style>
	.layout {
		display: grid;
		grid-template-columns: 10rem 1fr;
		gap: var(--space-8);
		align-items: end;
	}

	.info {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
		min-width: 0;
	}

	h1 {
		font-family: var(--font-display);
		font-size: var(--text-2xl);
		line-height: 1.1;
		text-wrap: balance;
	}

	.year {
		color: var(--color-text-muted);
		font-weight: 400;
	}

	.original {
		color: var(--color-text-muted);
	}

	.tagline {
		font-style: italic;
		color: var(--color-accent-strong);
	}

	@media (min-width: 48rem) {
		.layout {
			grid-template-columns: 16rem 1fr;
		}
	}

	@media (max-width: 32rem) {
		.layout {
			grid-template-columns: 1fr;
		}

		.poster {
			width: 9rem;
		}
	}
</style>
