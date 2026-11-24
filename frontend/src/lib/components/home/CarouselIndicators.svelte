<!--
	One bar per slide; the active bar fills up over the slide's duration
	(and holds while the carousel is paused).
-->
<script lang="ts">
	let {
		labels,
		index,
		durationMs,
		paused,
		onselect
	}: {
		/** Accessible name per slide. */
		labels: string[];
		index: number;
		durationMs: number;
		paused: boolean;
		onselect: (index: number) => void;
	} = $props();
</script>

<div class="indicators" role="group" aria-label="Choose featured title">
	{#each labels as label, i (i)}
		<button
			type="button"
			aria-label="Show {label}"
			aria-current={i === index ? 'true' : undefined}
			onclick={() => onselect(i)}
		>
			{#if i === index}
				{#key index}
					<span class="fill" class:paused style:animation-duration="{durationMs}ms"></span>
				{/key}
			{/if}
		</button>
	{/each}
</div>

<style>
	.indicators {
		display: flex;
		gap: var(--space-2);
	}

	button {
		position: relative;
		width: 2.25rem;
		height: 0.25rem;
		padding: 0;
		border: 0;
		border-radius: var(--radius-full);
		background: oklch(from var(--color-text) l c h / 0.25);
		overflow: hidden;
		cursor: pointer;
		transition: background var(--duration-fast);
	}

	/* Larger hit area than the visible bar */
	button::before {
		content: '';
		position: absolute;
		inset: -0.75rem -0.125rem;
	}

	button:hover {
		background: oklch(from var(--color-text) l c h / 0.45);
	}

	.fill {
		position: absolute;
		inset: 0;
		background: var(--color-accent);
		transform-origin: left;
		animation: fill linear forwards;
	}

	.fill.paused {
		animation-play-state: paused;
	}

	@keyframes fill {
		from {
			transform: scaleX(0);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.fill {
			animation: none;
		}
	}
</style>
