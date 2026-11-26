<script lang="ts">
	import { api, type MediaType, type ReleaseSearch } from '#lib/api/client.ts';
	import { formatBytes, formatTimestamp } from '#lib/media/format.ts';
	import Button from '../ui/Button.svelte';
	import FreeleechBadge from '../watch/FreeleechBadge.svelte';
	import InlineAlert from '../ui/InlineAlert.svelte';
	import Spinner from '../ui/Spinner.svelte';

	/**
	 * Debug tool: asks the backend's indexers (TorrentLeech for now) which
	 * torrents exist for this title and lists them as-is.
	 */
	let { mediaType, mediaId }: { mediaType: MediaType; mediaId: number } = $props();

	let loading = $state(false);
	let error = $state<string | null>(null);
	let result = $state<ReleaseSearch | null>(null);

	async function search() {
		loading = true;
		error = null;
		try {
			const { data, response } = await api.GET('/api/media/{media_type}/{media_id}/releases', {
				params: { path: { media_type: mediaType, media_id: mediaId } }
			});
			if (data) result = data;
			else error = `Request failed (HTTP ${response.status})`;
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}
</script>

<div class="panel">
	<div class="actions">
		<Button variant="secondary" icon="search" onclick={search} disabled={loading}>
			{result ? 'Search again' : 'Find torrents'}
		</Button>
		{#if loading}<Spinner label="Searching indexers" />{/if}
	</div>

	{#if error}
		<InlineAlert>{error}</InlineAlert>
	{/if}

	{#if result}
		<p class="meta">
			<code>{result.query}</code>
			· {result.indexers.length ? result.indexers.join(', ') : 'no indexers'}
			· {result.releases.length} result{result.releases.length === 1 ? '' : 's'}
		</p>

		{#if !result.indexers.length}
			<p class="message">
				No indexers are configured. Set <code>DRIFTWOOD_INDEXERS__TORRENTLEECH__USERNAME</code> and
				<code>__PASSWORD</code> in the backend's <code>.env</code>.
			</p>
		{/if}

		{#each result.failures as failure (failure.indexer + failure.message)}
			<InlineAlert>{failure.indexer}: {failure.message}</InlineAlert>
		{/each}

		{#if result.releases.length}
			<div class="table-scroll">
				<table>
					<thead>
						<tr>
							<th>Title</th>
							<th class="num">Size</th>
							<th class="num" title="Seeders / leechers">S / L</th>
							<th class="num">Grabs</th>
							<th>Added</th>
							<th>Categories</th>
						</tr>
					</thead>
					<tbody>
						{#each result.releases as release (release.indexer + release.guid)}
							<tr>
								<td class="title">
									{#if release.details_url}
										<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- external link -->
										<a href={release.details_url} target="_blank" rel="noreferrer">
											{release.title}
										</a>
									{:else}
										{release.title}
									{/if}
									{#if release.freeleech}<FreeleechBadge />{/if}
								</td>
								<td class="num">{formatBytes(release.size) ?? '–'}</td>
								<td class="num">{release.seeders ?? '?'} / {release.leechers ?? '?'}</td>
								<td class="num">{release.grabs ?? '–'}</td>
								<td>{formatTimestamp(release.published) ?? '–'}</td>
								<td class="faint">{release.categories.join(', ')}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{:else if result.indexers.length && !result.failures.length}
			<p class="message">No torrents found.</p>
		{/if}
	{/if}
</div>

<style>
	.panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-width: 0;
	}

	.actions {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.meta,
	.message {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
	}

	.message {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-1);
	}

	code {
		font-size: var(--text-xs);
		color: var(--color-text);
		overflow-wrap: anywhere;
	}

	.table-scroll {
		overflow-x: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--text-sm);
	}

	th,
	td {
		padding: var(--space-2) var(--space-3);
		text-align: left;
		vertical-align: top;
		white-space: nowrap;
	}

	th {
		font-size: var(--text-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--color-text-faint);
		background: var(--color-surface);
	}

	tbody tr {
		border-top: 1px solid var(--color-border);
	}

	tbody tr:hover {
		background: var(--color-surface);
	}

	.title {
		white-space: normal;
		overflow-wrap: anywhere;
		min-width: 18rem;
	}

	.title a {
		color: var(--color-text);
		margin-right: var(--space-2);
	}

	.title a:hover {
		color: var(--color-accent-strong);
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.faint {
		color: var(--color-text-faint);
	}
</style>
