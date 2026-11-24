<script lang="ts">
	import { resolve } from '$app/paths';
	import PlankIcon from './PlankIcon.svelte';

	let {
		size = 'md',
		href = resolve('/')
	}: {
		size?: 'md' | 'lg';
		/** Where the logo links to; pass `null` for a non-link logo. */
		href?: string | null;
	} = $props();
</script>

<svelte:element this={href ? 'a' : 'span'} {href} class="logo {size}" aria-label="Driftwood">
	<PlankIcon size="1.6em" />
	<span class="wordmark">Driftwood</span>
</svelte:element>

<style>
	.logo {
		display: inline-flex;
		align-items: center;
		gap: 0.4em;
		color: var(--color-text);
	}

	.md {
		font-size: var(--text-lg);
	}

	.lg {
		font-size: var(--text-2xl);
	}

	.wordmark {
		font-family: var(--font-display);
		font-weight: 600;
		letter-spacing: 0.01em;
	}
</style>
