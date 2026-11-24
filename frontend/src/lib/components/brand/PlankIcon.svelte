<!-- A weathered wooden plank: the Driftwood mark. Colors come from the wood tokens. -->
<script lang="ts">
	let { size = '2rem' }: { size?: string } = $props();
</script>

<svg viewBox="0 0 48 48" width={size} height={size} aria-hidden="true">
	<g transform="rotate(-24 24 24)">
		<!-- plank body with slightly irregular, worn ends -->
		<path
			class="body"
			d="M5 18.5c0-1.3 1-2.2 2.3-2.3L41 15.4c1.4 0 2.4 1 2.3 2.3l-.5 12.4c0 1.2-1 2.1-2.2 2.1L7.6 32.6C6.2 32.6 5 31.6 5 30.3Z"
		/>
		<!-- top-lit edge -->
		<path class="highlight" d="M7.4 17.4 40.8 16.6" />
		<!-- grain -->
		<path class="grain" d="M9 21.6c6-.9 10.4.6 15.6-.3 4.8-.8 9.6-.9 15.5-.1" />
		<path
			class="grain"
			d="M9.2 26.4c5.4-.6 8.3-1.9 13.4-1.3 3.6.4 5.5 2.4 9 2.2 3-.2 5-1.1 8-1.2"
		/>
		<path class="grain faint" d="M14 29.6c4.6-.2 9.6-.8 16.4-.3" />
		<!-- knot -->
		<ellipse class="knot" cx="31.5" cy="24.6" rx="2.4" ry="1.4" />
	</g>
</svg>

<style>
	svg {
		flex-shrink: 0;
	}

	.body {
		fill: var(--color-wood);
		stroke: var(--color-wood-dark);
		stroke-width: 1.2;
	}

	.highlight {
		stroke: var(--color-wood-light);
		stroke-width: 1.4;
		stroke-linecap: round;
		fill: none;
	}

	.grain {
		stroke: var(--color-wood-dark);
		stroke-width: 1;
		stroke-linecap: round;
		fill: none;
	}

	.faint {
		opacity: 0.6;
	}

	.knot {
		fill: none;
		stroke: var(--color-wood-dark);
		stroke-width: 1;
	}
</style>
