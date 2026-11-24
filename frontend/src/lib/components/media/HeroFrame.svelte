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
		tall = false,
		children
	}: {
		backdropPath: string | null | undefined;
		backdropOpacity?: number;
		/** Taller variant for featured content. */
		tall?: boolean;
		children: Snippet;
	} = $props();
</script>

<section class="hero" class:tall>
	<FadedBackdrop path={backdropPath} opacity={backdropOpacity} eager />
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
		min-height: min(92vh, 58rem);
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

	.content {
		width: 100%;
	}
</style>
