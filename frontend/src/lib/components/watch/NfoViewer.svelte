<!-- The release's NFO, fetched from the indexer when first opened. -->
<script lang="ts">
	import { api, type ReleaseNfo } from '#lib/api/client.ts';
	import Spinner from '../ui/Spinner.svelte';

	let { indexer, guid }: { indexer: string; guid: string } = $props();

	let nfo = $state<ReleaseNfo | null>(null);
	let error = $state<string | null>(null);
	let loading = $state(false);

	async function load() {
		if (nfo || loading) return;
		loading = true;
		error = null;
		try {
			const { data, response } = await api.GET('/api/releases/{indexer}/{guid}/nfo', {
				params: { path: { indexer, guid } }
			});
			if (data) nfo = data;
			else error = `Couldn't load the NFO (HTTP ${response.status})`;
		} catch (err) {
			error = err instanceof Error ? err.message : String(err);
		} finally {
			loading = false;
		}
	}

	function ontoggle(event: Event) {
		if ((event.currentTarget as HTMLDetailsElement).open) void load();
	}
</script>

<details {ontoggle}>
	<summary>NFO</summary>
	{#if loading}
		<p class="note"><Spinner size="1em" label="Loading NFO" /> Loading…</p>
	{:else if error}
		<p class="note danger">{error}</p>
	{:else if nfo && nfo.text === null}
		<p class="note">This release has no NFO.</p>
	{:else if nfo}
		<pre>{nfo.text}</pre>
	{/if}
</details>

<style>
	summary {
		cursor: pointer;
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.note {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin-top: var(--space-3);
		font-size: var(--text-sm);
		color: var(--color-text-faint);
	}

	.danger {
		color: var(--color-danger);
	}

	pre {
		max-height: 28rem;
		margin: var(--space-3) 0 0;
		padding: var(--space-4);
		overflow: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: oklch(from var(--color-bg) l c h / 0.7);
		color: var(--color-text-muted);
		/* NFO box-drawing art needs a monospace font with those glyphs */
		font-family: ui-monospace, 'Cascadia Mono', 'DejaVu Sans Mono', Menlo, Consolas, monospace;
		font-size: 0.75rem;
		line-height: 1.25;
		white-space: pre;
	}
</style>
