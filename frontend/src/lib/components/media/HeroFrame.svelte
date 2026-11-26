<!--
	The shared full-bleed hero: a faded backdrop with a legibility scrim, and
	page-width content anchored to the bottom.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import FadedBackdrop from './FadedBackdrop.svelte';

	let {
		backdropPath,
		backdropOpacity = 0.55,
		backdropFadeMs,
		tall = false,
		children
	}: {
		backdropPath: string | null | undefined;
		backdropOpacity?: number;
		/** Cross-fade duration when the backdrop changes. */
		backdropFadeMs?: number;
		/** Taller variant for featured content. */
		tall?: boolean;
		children: Snippet;
	} = $props();
</script>

<section class="hero" class:tall>
	<FadedBackdrop path={backdropPath} opacity={backdropOpacity} fadeMs={backdropFadeMs} eager />
	<div class="content">
		{@render children()}
	</div>
</section>

<style>
	.hero {
		position: relative;
		isolation: isolate;
		display: flex;
		align-items: flex-end;
		min-height: min(80vh, 44rem);
		padding: calc(var(--header-height) + var(--space-12)) var(--content-inset) var(--space-8);
	}

	.tall {
		min-height: min(64vh, 40rem);
		padding-bottom: var(--space-12);
	}

	.hero :global(.backdrop) {
		z-index: -1;
	}

	/* Scrim: keeps text legible over bright backdrops */
	.hero::before {
		content: '';
		position: absolute;
		inset: 0;
		z-index: -1;
		background: linear-gradient(
			to top right,
			oklch(from var(--fade-to) l c h / 0.85) 15%,
			transparent 65%
		);
	}

	/* Top scrim: darkens the backdrop behind the header so it stays legible.
	   Comes after .backdrop in tree order, so it paints over it. */
	.hero::after {
		content: '';
		position: absolute;
		inset: 0 0 auto;
		z-index: -1;
		height: calc(var(--header-height) + var(--space-12));
		background: linear-gradient(
			to bottom,
			oklch(from var(--fade-to) l c h / 0.8),
			oklch(from var(--fade-to) l c h / 0.45) 50%,
			transparent
		);
		pointer-events: none;
	}

	.content {
		width: 100%;
	}
</style>
