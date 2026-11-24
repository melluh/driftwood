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
		eager = false
	}: {
		path: string | null | undefined;
		opacity?: number;
		eager?: boolean;
	} = $props();
</script>

<div class="backdrop" style:--backdrop-opacity={opacity} aria-hidden="true">
	{#key path}
		{#if path}
			<div class="layer" transition:fade={{ duration: 400 }}>
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
		/* Fade out towards the bottom and both sides */
		mask-image:
			linear-gradient(to bottom, black 35%, transparent 100%),
			linear-gradient(to right, transparent 0%, black 22%, black 78%, transparent 100%);
		mask-composite: intersect;
	}

	.layer :global(.frame) {
		background: transparent;
	}
</style>
