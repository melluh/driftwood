<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { HTMLButtonAttributes } from 'svelte/elements';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		variant = 'primary',
		icon,
		children,
		...rest
	}: HTMLButtonAttributes & {
		variant?: 'primary' | 'secondary';
		icon?: IconName;
		children: Snippet;
	} = $props();
</script>

<button type="button" class="button {variant}" {...rest}>
	{#if icon}<Icon name={icon} />{/if}
	{@render children()}
</button>

<style>
	.button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-6);
		border: none;
		border-radius: var(--radius-md);
		font: inherit;
		font-weight: 600;
		cursor: pointer;
		transition:
			background var(--duration-fast),
			transform var(--duration-fast);
	}

	.button:active:not(:disabled) {
		transform: scale(0.98);
	}

	.button:disabled {
		opacity: 0.6;
		cursor: default;
	}

	.primary {
		background: var(--color-accent);
		color: var(--color-accent-contrast);
	}

	.primary:hover:not(:disabled) {
		background: var(--color-accent-strong);
	}

	.secondary {
		background: var(--color-surface-raised);
		color: var(--color-text);
		border: 1px solid var(--color-border);
	}

	.secondary:hover:not(:disabled) {
		background: var(--color-surface-hover);
	}
</style>
