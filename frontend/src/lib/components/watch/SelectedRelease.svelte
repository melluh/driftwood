<script lang="ts">
	import type { RankedRelease } from '#lib/api/client.ts';
	import {
		factorLabel,
		formatPoints,
		languageName,
		qualityTags,
		sizeSummary,
		subtitleSummary
	} from '#lib/watch/labels.ts';
	import Button from '../ui/Button.svelte';
	import Chip from '../ui/Chip.svelte';
	import Icon from '../ui/Icon.svelte';
	import FreeleechBadge from './FreeleechBadge.svelte';
	import NfoViewer from './NfoViewer.svelte';

	let {
		ranked,
		isRecommended,
		wantedSubtitles,
		canDownload,
		starting = false,
		ondownload,
		onreset
	}: {
		ranked: RankedRelease;
		/** False when the user swapped in a higher-quality option. */
		isRecommended: boolean;
		/** Wanted subtitle languages (ISO codes). */
		wantedSubtitles: string[];
		/** A download client is configured. */
		canDownload: boolean;
		/** The download is being handed to qBittorrent. */
		starting?: boolean;
		ondownload: () => void;
		onreset: () => void;
	} = $props();

	const release = $derived(ranked.release);
	const subtitles = $derived(subtitleSummary(ranked, wantedSubtitles));
</script>

<article class="card">
	<header>
		<p class="eyebrow">
			{isRecommended ? 'Best to watch now' : 'Your pick'}
			{#if ranked.slot_label}<Chip tone="accent">{ranked.slot_label}</Chip>{/if}
			{#if release.freeleech}<FreeleechBadge />{/if}
		</p>
		<h1>{release.title}</h1>
		<ul class="tags" aria-label="Quality">
			{#each qualityTags(ranked) as tag (tag)}
				<li><Chip>{tag}</Chip></li>
			{/each}
		</ul>
	</header>

	<dl class="stats">
		<div>
			<dt>Size</dt>
			<dd>{sizeSummary(ranked)}</dd>
		</div>
		<div>
			<dt>Peers</dt>
			<dd>{release.seeders ?? '?'} seeding · {release.leechers ?? '?'} leeching</dd>
		</div>
		<div>
			<dt>Indexer</dt>
			<dd>{release.indexer}</dd>
		</div>
		{#if ranked.attributes.release_group}
			<div>
				<dt>Group</dt>
				<dd>{ranked.attributes.release_group}</dd>
			</div>
		{/if}
		{#if subtitles}
			<div class="wide">
				<dt>Subtitles</dt>
				<dd class="subtitles {subtitles.tone}">
					{#if subtitles.tone === 'bad'}<Icon name="alert" size="1em" />{/if}
					{subtitles.text}
				</dd>
			</div>
		{/if}
		{#if ranked.audio_languages.length}
			<div>
				<dt>Audio</dt>
				<dd>{ranked.audio_languages.map(languageName).join(', ')}</dd>
			</div>
		{/if}
	</dl>

	<div class="actions">
		<Button
			icon="download"
			disabled={!canDownload || starting}
			title={canDownload ? undefined : 'No download client is configured'}
			onclick={ondownload}
		>
			{starting ? 'Starting download…' : 'Download & play'}
		</Button>
		{#if release.details_url}
			<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- external link -->
			<a class="external" href={release.details_url} target="_blank" rel="noreferrer">
				<Icon name="external" /> View on indexer
			</a>
		{/if}
		{#if !isRecommended}
			<button type="button" class="reset" onclick={onreset}>Back to the recommended release</button>
		{/if}
	</div>
	{#if !canDownload}
		<p class="note">
			Set <code>DRIFTWOOD_DOWNLOADS__QBITTORRENT__URL</code> in the backend's <code>.env</code> to download
			through qBittorrent.
		</p>
	{/if}

	<details>
		<summary>Why this release · score {ranked.score}</summary>
		<ul class="factors">
			{#each ranked.factors as factor (factor.name)}
				<li>
					<span>{factorLabel(factor.name)}</span>
					<span class="points" class:negative={factor.points < 0}>
						{formatPoints(factor.points)}
					</span>
				</li>
			{/each}
		</ul>
		<p class="note">Scores only compare releases within the same quality slot.</p>
	</details>

	{#key release.indexer + release.guid}
		<NfoViewer indexer={release.indexer} guid={release.guid} />
	{/key}
</article>

<style>
	.card {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		padding: var(--space-8);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: oklch(from var(--color-surface) l c h / 0.82);
		backdrop-filter: blur(16px);
		box-shadow: var(--shadow-lg);
	}

	header {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.eyebrow {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--color-accent);
	}

	h1 {
		font-size: var(--text-lg);
		font-weight: 600;
		line-height: 1.35;
		overflow-wrap: anywhere;
	}

	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.stats {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(9rem, 1fr));
		gap: var(--space-4);
		margin: 0;
	}

	dt {
		font-size: var(--text-xs);
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-faint);
	}

	dd {
		margin: 0;
		font-variant-numeric: tabular-nums;
	}

	.wide {
		grid-column: 1 / -1;
	}

	.subtitles {
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}

	.subtitles.good {
		color: var(--color-text);
	}

	.subtitles.bad {
		color: var(--color-danger);
	}

	.subtitles.neutral {
		color: var(--color-text-muted);
	}

	.points.negative {
		color: var(--color-danger);
	}

	details + :global(details) {
		border-top: none;
		padding-top: 0;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-4);
	}

	.external,
	.reset {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: 0;
		border: none;
		background: none;
		font: inherit;
		color: var(--color-text-muted);
		cursor: pointer;
	}

	.external:hover,
	.reset:hover {
		color: var(--color-accent-strong);
	}

	.note code {
		font-size: var(--text-xs);
		color: var(--color-text);
		overflow-wrap: anywhere;
	}

	.note {
		margin-top: calc(-1 * var(--space-3));
		font-size: var(--text-sm);
		color: var(--color-text-faint);
	}

	details {
		border-top: 1px solid var(--color-border);
		padding-top: var(--space-4);
	}

	details .note {
		margin-top: var(--space-2);
	}

	summary {
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.factors {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: var(--space-3) 0 0;
		padding: 0;
		list-style: none;
		font-size: var(--text-sm);
	}

	.factors li {
		display: flex;
		justify-content: space-between;
		gap: var(--space-4);
	}

	.points {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	@media (max-width: 32rem) {
		.card {
			padding: var(--space-6) var(--space-4);
		}
	}
</style>
