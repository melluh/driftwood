<script lang="ts">
	import { goto } from '$app/navigation';
	import { api, type RankedRelease, type Rejected, type WatchPlan } from '#lib/api/client.ts';
	import SelectedRelease from '#lib/components/watch/SelectedRelease.svelte';
	import UpgradeOptions from '#lib/components/watch/UpgradeOptions.svelte';
	import WatchLoading from '#lib/components/watch/WatchLoading.svelte';
	import WatchStage from '#lib/components/watch/WatchStage.svelte';
	import Button from '#lib/components/ui/Button.svelte';
	import Icon from '#lib/components/ui/Icon.svelte';
	import { mediaHref } from '#lib/media/format.ts';
	import { episodeCode } from '#lib/watch/labels.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const media = $derived(data.media);
	const episodeLabel = $derived(
		data.episode ? episodeCode(data.episode.season, data.episode.episode) : null
	);

	let status = $state<'loading' | 'ready' | 'error'>('loading');
	let plan = $state<WatchPlan | null>(null);
	let errorMessage = $state('');
	/** An upgrade the user picked instead of the recommendation. */
	let chosen = $state<RankedRelease | null>(null);
	let attempt = $state(0);

	const shown = $derived(chosen ?? plan?.pick ?? null);
	const others = $derived(plan?.options ?? []);
	/** "9 not the requested episode, 1 too few seeders" */
	const rejectedSummary = $derived(
		(plan?.rejected ?? []).map((r: Rejected) => `${r.count} ${r.reason}`).join(', ')
	);

	$effect(() => {
		const controller = new AbortController();
		const { media_type, id } = media;
		const episode = data.episode;
		void attempt; // re-run on retry

		status = 'loading';
		chosen = null;
		api
			.GET('/api/media/{media_type}/{media_id}/watch', {
				params: { path: { media_type, media_id: id }, query: episode ?? {} },
				signal: controller.signal
			})
			.then(({ data: result, response }) => {
				if (result) {
					plan = result;
					status = 'ready';
				} else {
					errorMessage = `The search failed (HTTP ${response.status}).`;
					status = 'error';
				}
			})
			.catch((err: unknown) => {
				if (controller.signal.aborted) return;
				errorMessage = err instanceof Error ? err.message : String(err);
				status = 'error';
			});
		return () => controller.abort();
	});

	function choose(option: RankedRelease) {
		chosen = option;
	}

	function close() {
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- mediaHref resolves
		void goto(mediaHref(media.media_type, media.id));
	}
</script>

<svelte:head>
	<title>Watch {media.title}{episodeLabel ? ` ${episodeLabel}` : ''} · Driftwood</title>
</svelte:head>

<WatchStage
	title={media.title}
	year={media.year}
	detail={episodeLabel}
	backdropPath={media.backdrop_path}
	onclose={close}
>
	{#if status === 'loading'}
		<WatchLoading title={media.title} detail={episodeLabel} />
	{:else if status === 'error'}
		<div class="message">
			<Icon name="alert" size="2rem" />
			<h1>Couldn't check for torrents</h1>
			<p>{errorMessage}</p>
			<Button onclick={() => attempt++}>Try again</Button>
		</div>
	{:else if plan}
		{#if shown}
			<SelectedRelease
				ranked={shown}
				isRecommended={!chosen || chosen.release.guid === plan.pick?.release.guid}
				onreset={() => (chosen = null)}
			/>
		{:else}
			<div class="message">
				<Icon name="info" size="2rem" />
				<h1>Nothing good to watch yet</h1>
				<p>
					{#if !plan.indexers.length}
						No indexers are configured. Set <code>DRIFTWOOD_INDEXERS__TORRENTLEECH__USERNAME</code>
						and <code>__PASSWORD</code> in the backend's <code>.env</code>.
					{:else if plan.considered}
						The indexers found {plan.considered} release{plan.considered === 1 ? '' : 's'}, but none
						is good to watch{#if rejectedSummary}&nbsp;({rejectedSummary}){/if}.
					{:else}
						The indexers didn't find any releases for this title.
					{/if}
				</p>
				<Button variant="secondary" onclick={() => attempt++}>Search again</Button>
			</div>
		{/if}

		{#each plan.failures as failure (failure.indexer + failure.message)}
			<p class="failure"><Icon name="alert" /> {failure.indexer}: {failure.message}</p>
		{/each}

		{#if others.length > 1 || (others.length === 1 && !plan.pick)}
			<UpgradeOptions
				options={others}
				selectedGuid={shown?.release.guid ?? null}
				onselect={choose}
			/>
		{/if}

		<details class="search-details">
			<summary>Search details</summary>
			<dl>
				<dt>Query</dt>
				<dd><code>{plan.query}</code></dd>
				<dt>Indexers</dt>
				<dd>{plan.indexers.join(', ') || 'none'}</dd>
				<dt>Releases found</dt>
				<dd>{plan.considered}</dd>
				{#each plan.rejected as rejection (rejection.reason)}
					<dt>Skipped: {rejection.reason}</dt>
					<dd>{rejection.count}</dd>
				{/each}
			</dl>
		</details>
	{/if}
</WatchStage>

<style>
	.message {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		text-align: center;
		color: var(--color-text-muted);
	}

	.message h1 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
		color: var(--color-text);
	}

	.message p {
		max-width: 32rem;
		margin-bottom: var(--space-2);
	}

	.failure {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-danger);
		overflow-wrap: anywhere;
	}

	code {
		font-size: var(--text-xs);
		color: var(--color-text);
		overflow-wrap: anywhere;
	}

	.search-details {
		font-size: var(--text-sm);
		color: var(--color-text-faint);
	}

	.search-details summary {
		cursor: pointer;
	}

	.search-details dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-1) var(--space-4);
		margin: var(--space-3) 0 0;
	}

	.search-details dd {
		margin: 0;
		color: var(--color-text-muted);
	}
</style>
