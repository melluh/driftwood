<!--
	A wide card that resumes a movie or episode straight in the player: the
	backdrop with how far along it is, the title, and the episode or time left.
-->
<script lang="ts">
	import type { ContinueWatching } from '#lib/api/client.ts';
	import Icon from '../ui/Icon.svelte';
	import TmdbImage from '../media/TmdbImage.svelte';
	import { continueHref, progressFraction, timeLeft } from '#lib/progress/progress.ts';
	import { episodeCode } from '#lib/watch/labels.ts';

	let { item, sizes }: { item: ContinueWatching; sizes: string } = $props();

	const progress = $derived(progressFraction(item));
	const left = $derived(timeLeft(item));
	const episode = $derived(
		item.season != null && item.episode != null ? episodeCode(item.season, item.episode) : null
	);
	const detail = $derived(
		[item.up_next && !left ? 'Up next' : null, episode, item.episode_title]
			.filter(Boolean)
			.join(' · ')
	);
	const label = $derived(
		[item.up_next ? 'Watch' : 'Continue', item.media.title, episode, item.episode_title, left]
			.filter(Boolean)
			.join(', ')
	);
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- continueHref() resolves the route -->
<a href={continueHref(item)} class="card" aria-label={label}>
	<div class="frame">
		<TmdbImage
			path={item.media.backdrop_path ?? item.media.poster_path}
			kind="backdrop"
			alt=""
			{sizes}
			radius="md"
		/>
		<span class="play" aria-hidden="true"><Icon name="play" size="1.25rem" /></span>
		{#if progress > 0}
			<span class="track" aria-hidden="true">
				<span class="bar" style:width="{progress * 100}%"></span>
			</span>
		{/if}
	</div>
	<span class="title truncate">{item.media.title}</span>
	<span class="meta">
		{#if detail}<span class="truncate">{detail}</span>{/if}
		{#if left}<span class="left">{left}</span>{/if}
	</span>
</a>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.card:focus-visible {
		outline: none;
	}

	.frame {
		position: relative;
		margin-bottom: var(--space-2);
		border-radius: var(--radius-md);
		box-shadow:
			0 0 0 1px var(--color-border),
			var(--shadow-lg);
		transition:
			transform var(--duration-slow) var(--ease-out),
			box-shadow var(--duration-fast);
	}

	.card:hover .frame,
	.card:focus-visible .frame {
		transform: translateY(-0.25rem) scale(1.03);
		box-shadow:
			0 0 0 2px var(--color-accent),
			var(--shadow-lg);
	}

	.play {
		position: absolute;
		inset: 0;
		margin: auto;
		display: grid;
		place-items: center;
		width: 3rem;
		height: 3rem;
		padding-left: 0.15rem;
		border-radius: var(--radius-full);
		background: oklch(from var(--color-accent) l c h / 0.9);
		color: var(--color-accent-contrast);
		opacity: 0;
		transform: scale(0.9);
		transition:
			opacity var(--duration-fast),
			transform var(--duration-fast) var(--ease-out);
	}

	.play :global(svg) {
		fill: currentColor;
	}

	.card:hover .play,
	.card:focus-visible .play {
		opacity: 1;
		transform: none;
	}

	.track {
		position: absolute;
		inset: auto var(--space-2) var(--space-2);
		height: 0.25rem;
		overflow: hidden;
		border-radius: var(--radius-full);
		background: oklch(100% 0 0 / 0.3);
	}

	.bar {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--color-accent);
	}

	.title {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	.meta {
		display: flex;
		gap: var(--space-2);
		justify-content: space-between;
		min-width: 0;
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}

	.left {
		flex-shrink: 0;
		color: var(--color-text-faint);
	}

	@media (prefers-reduced-motion: reduce) {
		.frame,
		.play {
			transition: none;
		}
	}
</style>
