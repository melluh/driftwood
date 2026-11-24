<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from '../ui/Icon.svelte';
	import type { IconName } from '../ui/icons.ts';

	let { icon, children }: { icon?: IconName; children: Snippet } = $props();
</script>

<p class="message">
	{#if icon}<Icon name={icon} />{/if}
	{@render children()}
</p>

<style>
	.message {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-6) var(--space-3);
		color: var(--color-text-muted);
	}
</style>
