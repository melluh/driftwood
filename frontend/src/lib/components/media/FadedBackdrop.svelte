<!--
	A full-bleed backdrop that fades out into the page background (--fade-to),
	so it blends seamlessly with whatever sits on and around it. Changing
	`path` cross-fades to the new image.
-->
<script lang="ts">
	import { fade } from 'svelte/transition';
	import TmdbImage from './TmdbImage.svelte';

	let {
		path,
		opacity = 1,
		fadeMs = 400,
		eager = false
	}: {
		path: string | null | undefined;
		opacity?: number;
		/** Cross-fade duration when `path` changes. */
		fadeMs?: number;
		eager?: boolean;
	} = $props();
</script>

<div class="backdrop" style:--backdrop-opacity={opacity} aria-hidden="true">
	{#key path}
		{#if path}
			<div class="layer" transition:fade={{ duration: fadeMs }}>
				<TmdbImage
					{path}
					kind="backdrop"
					alt=""
					sizes="100vw"
					fill
					{eager}
					placeholderIcon={null}
				/>
			</div>
		{/if}
	{/key}
</div>

<style>
	.backdrop {
		position: absolute;
		inset: 0;
		overflow: hidden;
		pointer-events: none;
		background: var(--fade-to);
	}

	.layer {
		position: absolute;
		inset: 0;
		opacity: var(--backdrop-opacity);
		/*
		 * Fade out towards the bottom and both sides. The bottom fade follows a
		 * smoothstep curve (eased at both ends), so it melts into the page
		 * instead of ending in a visible edge like a linear ramp does.
		 */
		mask-image:
			linear-gradient(
				to bottom,
				black 25%,
				rgb(0 0 0 / 0.957) 34.4%,
				rgb(0 0 0 / 0.844) 43.75%,
				rgb(0 0 0 / 0.684) 53.1%,
				rgb(0 0 0 / 0.5) 62.5%,
				rgb(0 0 0 / 0.316) 71.9%,
				rgb(0 0 0 / 0.156) 81.25%,
				rgb(0 0 0 / 0.043) 90.6%,
				transparent 100%
			),
			linear-gradient(to right, transparent 0%, black 22%, black 78%, transparent 100%);
		mask-composite: intersect;
	}

	.layer :global(.frame) {
		background: transparent;
	}
</style>
