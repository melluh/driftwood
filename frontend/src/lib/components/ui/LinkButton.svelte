<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		href,
		variant = 'primary',
		icon,
		onclick,
		children
	}: {
		/** An already-resolved href. */
		href: string;
		variant?: 'primary' | 'secondary';
		icon?: IconName;
		onclick?: (event: MouseEvent & { currentTarget: HTMLAnchorElement }) => void;
		children: Snippet;
	} = $props();
</script>

<!-- eslint-disable-next-line svelte/no-navigation-without-resolve -- callers pass resolved hrefs -->
<a {href} class="button {variant}" {onclick}>
	{#if icon}<Icon name={icon} />{/if}
	{@render children()}
</a>

<style>
	.button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-3) var(--space-6);
		border-radius: var(--radius-md);
		font-weight: 600;
		transition:
			background var(--duration-fast),
			transform var(--duration-fast);
	}

	.button:active {
		transform: scale(0.98);
	}

	.primary {
		background: var(--color-accent);
		color: var(--color-accent-contrast);
	}

	.primary:hover {
		background: var(--color-accent-strong);
	}

	.secondary {
		background: oklch(from var(--color-surface-raised) l c h / 0.7);
		color: var(--color-text);
		backdrop-filter: blur(8px);
	}

	.secondary:hover {
		background: var(--color-surface-hover);
	}
</style>
