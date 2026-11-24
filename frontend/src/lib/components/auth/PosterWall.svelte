<!--
	A still wall of posters filling the login screen. Purely decorative: hidden
	from assistive tech, and simply absent when there are no posters.
-->
<script lang="ts">
	import { tmdbImageUrl } from '#lib/tmdb/images.ts';

	let { posters }: { posters: string[] } = $props();

	// Enough cells to fill a 2560×1440 screen; the grid clips whatever doesn't fit.
	const CELLS = 96;

	const cells = $derived(
		posters.length === 0 ? [] : Array.from({ length: CELLS }, (_, i) => posters[i % posters.length])
	);

	function reveal(event: Event) {
		(event.currentTarget as HTMLImageElement).classList.add('loaded');
	}
</script>

{#if cells.length}
	<div class="wall" aria-hidden="true">
		{#each cells as path, i (i)}
			<img
				src={tmdbImageUrl(path, 185)}
				srcset="{tmdbImageUrl(path, 185)} 185w, {tmdbImageUrl(path, 342)} 342w"
				sizes="clamp(8rem, 7vw, 11rem)"
				alt=""
				decoding="async"
				onload={reveal}
			/>
		{/each}
	</div>
{/if}

<style>
	/* Bleeds past every edge so the wall reads as continuing beyond the screen */
	.wall {
		position: absolute;
		inset: -3rem;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(clamp(8rem, 7vw, 11rem), 1fr));
		grid-auto-rows: max-content;
		align-content: start;
		gap: var(--space-4);
		overflow: hidden;
		opacity: 0.55;
		filter: saturate(0.85);
	}

	img {
		width: 100%;
		aspect-ratio: 2 / 3;
		border-radius: var(--radius-md);
		background: var(--color-surface);
		object-fit: cover;
		opacity: 0;
		transition: opacity 1.2s var(--ease-out);
	}

	img:global(.loaded) {
		opacity: 1;
	}
</style>
