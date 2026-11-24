<script lang="ts">
	import type { Snippet } from 'svelte';

	let { title, children }: { title?: string; children: Snippet } = $props();
</script>

<section class="page-section">
	{#if title}<h2>{title}</h2>{/if}
	{@render children()}
</section>

<style>
	.page-section {
		padding: var(--space-6) var(--content-inset);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	h2 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
	}
</style>
