<script lang="ts">
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		icon,
		label,
		size = 'md',
		...rest
	}: HTMLButtonAttributes & {
		icon: IconName;
		label: string;
		size?: 'md' | 'lg';
	} = $props();
</script>

<button type="button" class="icon-button {size}" aria-label={label} title={label} {...rest}>
	<Icon name={icon} />
</button>

<style>
	.icon-button {
		display: inline-grid;
		place-items: center;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface);
		color: var(--color-text-muted);
		cursor: pointer;
		transition:
			background var(--duration-fast),
			color var(--duration-fast),
			border-color var(--duration-fast);
	}

	.icon-button:hover {
		background: var(--color-surface-hover);
		color: var(--color-text);
		border-color: var(--color-accent-soft);
	}

	.md {
		width: 2.5rem;
		height: 2.5rem;
		font-size: 1.125rem;
	}

	.lg {
		width: 3rem;
		height: 3rem;
		font-size: 1.375rem;
	}
</style>
