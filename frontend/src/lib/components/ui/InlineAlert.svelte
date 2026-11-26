<!-- One line saying something failed, next to whatever it's about. -->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';

	let { children }: { children: Snippet } = $props();
</script>

<p class="inline-alert">
	<Icon name="alert" />
	<span>{@render children()}</span>
</p>

<style>
	.inline-alert {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--text-sm);
		color: var(--color-danger);
		overflow-wrap: anywhere;
	}
</style>
