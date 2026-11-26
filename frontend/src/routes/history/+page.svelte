<script lang="ts">
	import type { WatchHistoryItem } from '#lib/api/client.ts';
	import HistoryRow from '#lib/components/history/HistoryRow.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import LinkButton from '#lib/components/ui/LinkButton.svelte';
	import { resolve } from '$app/paths';
	import { loadHistory } from '#lib/progress/progress.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	// Later pages are appended here; a fresh load (navigating back) starts over.
	let items = $derived<WatchHistoryItem[]>(data.history?.items ?? []);
	let hasMore = $derived(data.history?.has_more ?? false);
	let offset = $derived(data.history?.next_offset ?? 0);
	let loading = $state(false);
	let failed = $state(false);

	type Day = { key: string; label: string; items: WatchHistoryItem[] };

	function dayKey(date: Date): string {
		return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
	}

	function dayLabel(date: Date): string {
		const today = new Date();
		const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
		if (dayKey(date) === dayKey(today)) return 'Today';
		if (dayKey(date) === dayKey(yesterday)) return 'Yesterday';
		return date.toLocaleDateString(undefined, {
			weekday: 'long',
			day: 'numeric',
			month: 'long',
			year: date.getFullYear() === today.getFullYear() ? undefined : 'numeric'
		});
	}

	const days = $derived.by(() => {
		const grouped: Day[] = [];
		for (const item of items) {
			const date = new Date(item.watched_at);
			const key = dayKey(date);
			const last = grouped.at(-1);
			if (last?.key === key) last.items.push(item);
			else grouped.push({ key, label: dayLabel(date), items: [item] });
		}
		return grouped;
	});

	function itemKey(item: WatchHistoryItem): string {
		return `${item.media.media_type}-${item.media.id}-${item.season ?? ''}-${item.episode ?? ''}`;
	}

	async function loadMore() {
		loading = true;
		failed = false;
		const page = await loadHistory(offset);
		loading = false;
		if (!page) {
			failed = true;
			return;
		}
		offset = page.next_offset;
		// Something watched meanwhile shifts the pages: skip what's already listed.
		const seen = new Set(items.map(itemKey));
		items = [...items, ...page.items.filter((item) => !seen.has(itemKey(item)))];
		hasMore = page.has_more;
	}
</script>

<svelte:head>
	<title>Watch history · Driftwood</title>
</svelte:head>

<div class="page">
	<header>
		<h1>Watch history</h1>
		<p>Everything you've watched, newest first.</p>
	</header>

	{#if !data.history}
		<div class="empty" role="alert">
			<Icon name="alert" size="2rem" />
			<p>Couldn't load your watch history.</p>
		</div>
	{:else if !items.length}
		<div class="empty">
			<Icon name="history" size="2rem" />
			<p>Nothing here yet. Movies and episodes you watch will show up here.</p>
			<LinkButton href={resolve('/')} variant="secondary">Find something to watch</LinkButton>
		</div>
	{:else}
		{#each days as day (day.key)}
			<section class="day">
				<h2>{day.label}</h2>
				<ul role="list">
					{#each day.items as item (itemKey(item))}
						<li><HistoryRow {item} /></li>
					{/each}
				</ul>
			</section>
		{/each}

		{#if hasMore || failed}
			<div class="more">
				{#if failed}<p class="failure">Couldn't load more.</p>{/if}
				<Button variant="secondary" onclick={() => void loadMore()} disabled={loading}>
					{loading ? 'Loading…' : failed ? 'Try again' : 'Show more'}
				</Button>
			</div>
		{/if}
	{/if}
</div>

<style>
	.page {
		display: flex;
		flex-direction: column;
		gap: var(--space-8);
		max-width: 56rem;
		margin: 0 auto;
		padding: calc(var(--header-height) + var(--space-6)) var(--page-gutter) var(--space-12);
	}

	header h1 {
		font-family: var(--font-display);
		font-size: var(--text-2xl);
	}

	header p {
		color: var(--color-text-muted);
	}

	.day {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h2 {
		position: sticky;
		top: var(--header-height);
		z-index: 1;
		padding: var(--space-2) var(--space-3);
		background: var(--color-bg);
		font-size: var(--text-sm);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--color-text-muted);
	}

	ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-12) 0;
		text-align: center;
		color: var(--color-text-muted);
	}

	.more {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
	}

	.failure {
		font-size: var(--text-sm);
		color: var(--color-danger);
	}
</style>
