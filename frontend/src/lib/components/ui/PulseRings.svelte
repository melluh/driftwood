<!--
	Two rings rippling out from the middle of the parent (which must be
	positioned), half a cycle apart: "something is in motion". With reduced
	motion they hold still at `restScale`, or stay hidden without one.
-->
<script lang="ts">
	let {
		from,
		to,
		peak,
		active = true,
		restScale = null
	}: {
		/** Scale (of the parent's size) each ring starts at, and grows to as it fades. */
		from: number;
		to: number;
		/** Opacity at the start of a ripple. */
		peak: number;
		active?: boolean;
		restScale?: number | null;
	} = $props();
</script>

{#each [0, 1] as ring (ring)}
	<span
		class="ring"
		class:active
		class:rest={restScale !== null}
		class:delayed={ring === 1}
		style:--from={from}
		style:--to={to}
		style:--peak={peak}
		style:--rest-scale={restScale}
		aria-hidden="true"
	></span>
{/each}

<style>
	.ring {
		position: absolute;
		inset: 0;
		border: 2px solid var(--color-accent);
		border-radius: var(--radius-full);
		opacity: 0;
		pointer-events: none;
	}

	.active {
		animation: ripple 2.4s var(--ease-out) infinite;
	}

	.delayed {
		animation-delay: 1.2s;
	}

	@keyframes ripple {
		from {
			transform: scale(var(--from));
			opacity: var(--peak);
		}
		to {
			transform: scale(var(--to));
			opacity: 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.active {
			animation: none;
		}

		.active.rest {
			opacity: 0.35;
			transform: scale(var(--rest-scale));
		}
	}
</style>
