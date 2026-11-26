<!--
	One movie or episode in the watch history: a thumbnail that plays it again,
	what it is, when it was watched, and whether it was finished or how far it got.
-->
<script lang="ts">
	import type { WatchHistoryItem } from '#lib/api/client.ts';
	import TmdbImage from '../media/TmdbImage.svelte';
	import Icon from '../ui/Icon.svelte';
	import { mediaHref } from '#lib/media/format.ts';
	import { continueHref, progressFraction, timeLeft } from '#lib/progress/progress.ts';
	import { episodeCode } from '#lib/watch/labels.ts';

	let { item }: { item: WatchHistoryItem } = $props();

	const isEpisode = $derived(item.season != null && item.episode != null);
	const code = $derived(
		item.season != null && item.episode != null ? episodeCode(item.season, item.episode) : null
	);
	const detail = $derived(
		isEpisode
			? [code, item.episode_title].filter(Boolean).join(' · ')
			: ['Movie', item.media.year].filter(Boolean).join(' · ')
	);
	const percent = $derived(Math.round(progressFraction(item) * 100));
	const left = $derived(timeLeft(item));
	const time = $derived(
		new Date(item.watched_at).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
	);
	const playLabel = $derived(
		`${item.finished || item.resume_at === 0 ? 'Watch again' : 'Resume'}: ${item.media.title}${code ? ` ${code}` : ''}`
	);
	const image = $derived(
		isEpisode && item.still_path
			? { path: item.still_path, kind: 'still' as const }
			: { path: item.media.backdrop_path ?? item.media.poster_path, kind: 'backdrop' as const }
	);
</script>

<article class="row">
	<!-- eslint-disable svelte/no-navigation-without-resolve -- continueHref() / mediaHref() resolve -->
	<a href={continueHref(item)} class="thumb" aria-label={playLabel} title={playLabel}>
		<TmdbImage
			path={image.path}
			kind={image.kind}
			alt=""
			sizes="(min-width: 40rem) 11rem, 7.5rem"
		/>
		<span class="play" aria-hidden="true"><Icon name="play" size="1rem" /></span>
		{#if !item.finished && percent > 0}
			<span class="track" aria-hidden="true"><span style:width="{percent}%"></span></span>
		{/if}
	</a>

	<div class="body">
		<h3 class="truncate">
			<a href={mediaHref(item.media.media_type, item.media.id)}>{item.media.title}</a>
		</h3>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
		{#if detail}<p class="detail truncate">{detail}</p>{/if}
		<p class="status">
			{#if item.finished}
				<span class="finished"><Icon name="check" size="1rem" /> Finished</span>
			{:else}
				<span class="meter" aria-hidden="true"><span style:width="{percent}%"></span></span>
				<span>{percent}% watched{left ? ` · ${left}` : ''}</span>
			{/if}
			{#if item.completed && !item.finished}
				<span class="before">Finished before</span>
			{/if}
		</p>
	</div>

	<time class="when" datetime={item.watched_at}>{time}</time>
</article>

<style>
	.row {
		display: grid;
		grid-template-columns: 11rem minmax(0, 1fr) auto;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-3);
		border-radius: var(--radius-lg);
		transition: background var(--duration-fast);
	}

	.row:hover,
	.row:focus-within {
		background: var(--color-surface);
	}

	.thumb {
		position: relative;
		display: block;
		overflow: hidden;
		border-radius: var(--radius-md);
		box-shadow: 0 0 0 1px var(--color-border);
	}

	.thumb:focus-visible {
		outline: none;
		box-shadow: 0 0 0 2px var(--color-accent);
	}

	.play {
		position: absolute;
		inset: 0;
		margin: auto;
		display: grid;
		place-items: center;
		width: 2.5rem;
		height: 2.5rem;
		padding-left: 0.1rem;
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

	.thumb:hover .play,
	.thumb:focus-visible .play {
		opacity: 1;
		transform: none;
	}

	.track {
		position: absolute;
		inset: auto 0 0;
		height: 0.2rem;
		background: oklch(100% 0 0 / 0.3);
	}

	.track span,
	.meter span {
		display: block;
		height: 100%;
		border-radius: inherit;
		background: var(--color-accent);
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	h3 {
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
	}

	h3 a:hover,
	h3 a:focus-visible {
		color: var(--color-accent-strong);
	}

	.detail {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}

	.status {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1) var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.finished {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-accent-strong);
		font-weight: 600;
	}

	.meter {
		width: 6rem;
		height: 0.25rem;
		overflow: hidden;
		border-radius: var(--radius-full);
		background: var(--color-surface-hover);
	}

	.before {
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-surface-hover);
		font-size: var(--text-xs);
	}

	.when {
		align-self: start;
		padding-top: var(--space-1);
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
		color: var(--color-text-faint);
	}

	@media (max-width: 40rem) {
		.row {
			grid-template-columns: 7.5rem minmax(0, 1fr);
			gap: var(--space-3);
			padding: var(--space-2);
		}

		.thumb {
			grid-row: span 2;
		}

		h3 {
			font-size: var(--text-md);
		}

		.meter {
			display: none;
		}

		.when {
			grid-column: 2;
			margin-top: calc(-1 * var(--space-2));
			padding-top: 0;
			font-size: var(--text-xs);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.play {
			transition: none;
		}
	}
</style>
