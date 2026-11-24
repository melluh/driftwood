<!--
	Every TMDB image in the app goes through this component: it requests a
	right-sized image via srcset/sizes, fades it in once loaded, and shows a
	themed placeholder when there's no image (or it fails to load).
	Fills its container's width; height follows the image kind's aspect ratio
	unless `fill` is set, in which case it fills the container's height too.
-->
<script lang="ts">
	import Icon from '../ui/Icon.svelte';
	import type { IconName } from '../ui/icons.ts';
	import { ASPECT_RATIO, tmdbFallbackUrl, tmdbSrcset, type ImageKind } from '#lib/tmdb/images.ts';

	const PLACEHOLDER_ICONS: Record<ImageKind, IconName> = {
		poster: 'film',
		backdrop: 'film',
		profile: 'person'
	};

	let {
		path,
		kind,
		alt,
		sizes,
		fill = false,
		eager = false,
		placeholderIcon = PLACEHOLDER_ICONS[kind],
		radius = 'none'
	}: {
		path: string | null | undefined;
		kind: ImageKind;
		alt: string;
		/** The `sizes` attribute: the image's rendered width, e.g. "3rem" or "(min-width: 60rem) 20rem, 40vw". */
		sizes: string;
		fill?: boolean;
		/** Load immediately (above-the-fold images) instead of lazily. */
		eager?: boolean;
		placeholderIcon?: IconName | null;
		radius?: 'none' | 'sm' | 'md';
	} = $props();

	let loaded = $state(false);
	let failed = $state(false);

	// A new path is a new image: reset the load state.
	$effect.pre(() => {
		void path;
		loaded = false;
		failed = false;
	});

	const showImage = $derived(!!path && !failed);
</script>

<div class="frame radius-{radius}" class:fill style:--ratio={ASPECT_RATIO[kind]}>
	{#if showImage && path}
		<img
			src={tmdbFallbackUrl(path, kind)}
			srcset={tmdbSrcset(path, kind)}
			{sizes}
			{alt}
			loading={eager ? 'eager' : 'lazy'}
			decoding="async"
			class:loaded
			onload={() => (loaded = true)}
			onerror={() => (failed = true)}
		/>
	{/if}
	{#if !showImage && placeholderIcon}
		<div class="placeholder" role="img" aria-label={alt}>
			<Icon name={placeholderIcon} size="40%" />
		</div>
	{/if}
</div>

<style>
	.frame {
		position: relative;
		width: 100%;
		aspect-ratio: var(--ratio);
		overflow: hidden;
		background: var(--color-surface-raised);
	}

	.radius-sm {
		border-radius: var(--radius-sm);
	}

	.radius-md {
		border-radius: var(--radius-md);
	}

	.fill {
		height: 100%;
		aspect-ratio: auto;
	}

	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
		opacity: 0;
		transition: opacity var(--duration-slow) var(--ease-out);
	}

	img.loaded {
		opacity: 1;
	}

	.placeholder {
		position: absolute;
		inset: 0;
		display: grid;
		place-items: center;
		color: var(--color-text-faint);
		container-type: size;
	}

	.placeholder :global(svg) {
		max-width: 3rem;
		max-height: 3rem;
	}
</style>
