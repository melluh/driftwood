<!--
	A centered, full-stop message in place of a page's content: an icon, a
	heading, what happened, and what to do next. For errors and empty results.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import Icon from './Icon.svelte';
	import type { IconName } from './icons.ts';

	let {
		icon,
		title,
		tone = 'neutral',
		role,
		children,
		actions
	}: {
		icon: IconName;
		title: string;
		/** `danger` colors the icon, for things that went wrong. */
		tone?: 'neutral' | 'danger';
		role?: 'alert' | 'status';
		/** What happened, as a paragraph's content. */
		children?: Snippet;
		actions?: Snippet;
	} = $props();
</script>

<div class="status-message {tone}" {role}>
	<Icon name={icon} size="2rem" />
	<h1>{title}</h1>
	{#if children}<p>{@render children()}</p>{/if}
	{#if actions}<div class="actions">{@render actions()}</div>{/if}
</div>

<style>
	.status-message {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		text-align: center;
		color: var(--color-text-muted);
	}

	.danger > :global(svg) {
		color: var(--color-danger);
	}

	h1 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
		color: var(--color-text);
	}

	p {
		max-width: 32rem;
		overflow-wrap: anywhere;
	}

	.actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-3);
		margin-top: var(--space-2);
	}
</style>
