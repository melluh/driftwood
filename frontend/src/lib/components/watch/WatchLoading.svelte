<script lang="ts">
	import Icon from '../ui/Icon.svelte';

	let { title, detail }: { title: string; detail?: string | null } = $props();
</script>

<div class="loading" role="status" aria-live="polite">
	<div class="pulse" aria-hidden="true">
		<span class="ring"></span>
		<span class="ring delayed"></span>
		<span class="core"><Icon name="search" size="1.75rem" /></span>
	</div>
	<div class="text">
		<h1>Checking for torrents</h1>
		<p>
			Looking for the best release of <strong>{title}</strong>{#if detail}&nbsp;{detail}{/if} to start
			watching right away.
		</p>
	</div>
</div>

<style>
	.loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-8);
		text-align: center;
	}

	.pulse {
		position: relative;
		display: grid;
		place-items: center;
		width: 8rem;
		height: 8rem;
	}

	.core {
		display: grid;
		place-items: center;
		width: 4.5rem;
		height: 4.5rem;
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		color: var(--color-accent-strong);
		box-shadow: 0 0 0 1px var(--color-accent-soft);
	}

	.ring {
		position: absolute;
		inset: 0;
		border: 2px solid var(--color-accent);
		border-radius: var(--radius-full);
		opacity: 0;
		animation: ripple 2.4s var(--ease-out) infinite;
	}

	.delayed {
		animation-delay: 1.2s;
	}

	@keyframes ripple {
		from {
			transform: scale(0.55);
			opacity: 0.7;
		}
		to {
			transform: scale(1.15);
			opacity: 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.ring {
			animation: none;
			opacity: 0.35;
			transform: scale(0.9);
		}
	}

	.text {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h1 {
		font-family: var(--font-display);
		font-size: var(--text-xl);
	}

	p {
		max-width: 30rem;
		color: var(--color-text-muted);
		text-wrap: balance;
	}

	strong {
		color: var(--color-text);
		font-weight: 600;
	}
</style>
