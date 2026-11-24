<script lang="ts">
	import type { RankedRelease } from '#lib/api/client.ts';
	import { qualityTags, sizeSummary } from '#lib/watch/labels.ts';
	import Icon from '../ui/Icon.svelte';

	let {
		options,
		selectedGuid,
		onselect
	}: {
		/** The best release of each slot, best quality first. */
		options: RankedRelease[];
		selectedGuid: string | null;
		onselect: (ranked: RankedRelease) => void;
	} = $props();
</script>

<section>
	<h2>Other qualities</h2>
	<p class="hint">The best release for each quality. Pick one to grab it instead.</p>
	<ul>
		{#each options as option (option.release.indexer + option.release.guid)}
			{@const selected = option.release.guid === selectedGuid}
			<li>
				<button
					type="button"
					class:selected
					onclick={() => onselect(option)}
					aria-pressed={selected}
				>
					<span class="slot">{option.slot_label}</span>
					<span class="tags">{qualityTags(option).join(' · ')}</span>
					<span class="size">{sizeSummary(option)}</span>
					<span class="seeders">
						<Icon name="arrow-up" size="1em" />{option.release.seeders ?? '?'}
					</span>
				</button>
			</li>
		{/each}
	</ul>
</section>

<style>
	section {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h2 {
		font-family: var(--font-display);
		font-size: var(--text-lg);
	}

	.hint {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	ul {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: var(--space-2) 0 0;
		padding: 0;
		list-style: none;
	}

	button {
		width: 100%;
		display: grid;
		grid-template-columns: 8rem 1fr auto 4rem;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: oklch(from var(--color-surface) l c h / 0.7);
		color: var(--color-text);
		font: inherit;
		text-align: left;
		cursor: pointer;
		transition:
			background var(--duration-fast),
			border-color var(--duration-fast);
	}

	button:hover {
		background: var(--color-surface-hover);
	}

	.selected {
		border-color: var(--color-accent);
		background: var(--color-accent-soft);
	}

	.slot {
		font-weight: 600;
	}

	.tags {
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.size,
	.seeders {
		font-size: var(--text-sm);
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.seeders {
		display: inline-flex;
		align-items: center;
		justify-content: flex-end;
		gap: var(--space-1);
		color: var(--color-text-muted);
	}

	@media (max-width: 36rem) {
		button {
			grid-template-columns: 1fr auto;
			grid-template-areas:
				'slot size'
				'tags seeders';
			gap: var(--space-1) var(--space-3);
		}

		.slot {
			grid-area: slot;
		}

		.size {
			grid-area: size;
			text-align: right;
		}

		.tags {
			grid-area: tags;
		}

		.seeders {
			grid-area: seeders;
		}
	}
</style>
