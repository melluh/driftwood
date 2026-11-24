<script lang="ts">
	import type { MediaDetails } from '#lib/api/client.ts';
	import { formatDate, formatRating, formatRuntime } from '#lib/media/format.ts';
	import Icon from '../ui/Icon.svelte';
	import Chip from '../ui/Chip.svelte';

	let { media }: { media: MediaDetails } = $props();

	const isTv = $derived(media.media_type === 'tv');
	const rating = $derived(formatRating(media.vote_average));

	const facts = $derived(
		[
			{ label: isTv ? 'First aired' : 'Released', value: formatDate(media.release_date) },
			{ label: 'Last aired', value: isTv ? formatDate(media.last_air_date) : null },
			{ label: isTv ? 'Episode runtime' : 'Runtime', value: formatRuntime(media.runtime) },
			{
				label: 'Seasons',
				value: media.number_of_seasons
					? `${media.number_of_seasons} (${media.number_of_episodes ?? '?'} episodes)`
					: null
			},
			{ label: 'Status', value: media.status },
			{ label: 'Language', value: media.original_language?.toUpperCase() }
		].filter((fact): fact is { label: string; value: string } => !!fact.value)
	);
</script>

<div class="facts">
	{#if rating}
		<p class="rating">
			<Icon name="star" />
			<strong>{rating}</strong>
			<span>/ 10 · {media.vote_count?.toLocaleString()} votes</span>
		</p>
	{/if}

	{#if media.genres.length}
		<ul class="genres" aria-label="Genres">
			{#each media.genres as genre (genre.id)}
				<li><Chip tone="accent">{genre.name}</Chip></li>
			{/each}
		</ul>
	{/if}

	<dl>
		{#each facts as fact (fact.label)}
			<div>
				<dt>{fact.label}</dt>
				<dd>{fact.value}</dd>
			</div>
		{/each}
	</dl>
</div>

<style>
	.facts {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.rating {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		color: var(--color-accent);
	}

	.rating strong {
		color: var(--color-text);
		font-size: var(--text-lg);
	}

	.rating span {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}

	.genres {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	dl {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
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
		color: var(--color-text);
	}
</style>
