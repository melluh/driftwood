<script lang="ts">
	import type { Snippet } from 'svelte';

	let { children, tone = 'neutral' }: { children: Snippet; tone?: 'neutral' | 'accent' } = $props();
</script>

<span class="chip {tone}">{@render children()}</span>

<style>
	.chip {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		padding: 0.125rem var(--space-2);
		border-radius: var(--radius-full);
		font-size: var(--text-xs);
		font-weight: 500;
		white-space: nowrap;
	}

	.neutral {
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
		border: 1px solid var(--color-border);
	}

	.accent {
		background: var(--color-accent-soft);
		color: var(--color-accent-strong);
	}
</style>
