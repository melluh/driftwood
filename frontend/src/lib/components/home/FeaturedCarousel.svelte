<!--
	Large, auto-rotating highlights at the top of the home page. The backdrop
	cross-fades between slides, and the next slide's backdrop is preloaded.
-->
<script lang="ts">
	import { cubicOut } from 'svelte/easing';
	import { fade, fly } from 'svelte/transition';
	import type { MediaSummary } from '#lib/api/client.ts';
	import { Rotation } from '#lib/home/rotation.svelte.ts';
	import { isSameMedia } from '#lib/my-list/my-list.ts';
	import { tmdbSrcset } from '#lib/tmdb/images.ts';
	import { expandFrom } from '#lib/transitions/media-expand.ts';
	import HeroFrame from '../media/HeroFrame.svelte';
	import CarouselIndicators from './CarouselIndicators.svelte';
	import FeaturedInfo from './FeaturedInfo.svelte';

	let {
		items,
		myList,
		onmylistchange
	}: {
		items: MediaSummary[];
		/** The user's saved titles, to show whether each slide is on the list. */
		myList: MediaSummary[];
		onmylistchange: (media: MediaSummary, inList: boolean) => void;
	} = $props();

	const rotation = new Rotation(() => items.length);
	const current = $derived(items[rotation.index] ?? items[0]);
	const upcoming = $derived(items.length > 1 ? items[(rotation.index + 1) % items.length] : null);

	let container: HTMLElement | undefined = $state();

	/** The details page grows out of the whole hero, which shares its backdrop. */
	function expandFromHero(link: HTMLAnchorElement) {
		expandFrom(link, { bounds: container, rounded: false });
	}

	function handleFocusOut(event: FocusEvent) {
		const container = event.currentTarget as HTMLElement;
		if (!container.contains(event.relatedTarget as Node | null)) rotation.setFocused(false);
	}
</script>

<svelte:head>
	{#if upcoming?.backdrop_path}
		<link
			rel="preload"
			as="image"
			imagesrcset={tmdbSrcset(upcoming.backdrop_path, 'backdrop')}
			imagesizes="100vw"
		/>
	{/if}
</svelte:head>

{#if current}
	<div
		bind:this={container}
		class="featured"
		role="region"
		aria-roledescription="carousel"
		aria-label="Featured"
		onfocusin={() => rotation.setFocused(true)}
		onfocusout={handleFocusOut}
	>
		<HeroFrame
			backdropPath={current.backdrop_path}
			backdropOpacity={0.8}
			backdropFadeMs={900}
			tall
		>
			<div class="slide">
				{#key current}
					<!-- The outgoing slide fades out while the next drifts up into place -->
					<div
						class="info"
						in:fly={{ y: 16, duration: 700, delay: 200, easing: cubicOut }}
						out:fade={{ duration: 300 }}
					>
						<FeaturedInfo
							media={current}
							inMyList={myList.some((item) => isSameMedia(item, current))}
							{onmylistchange}
							onselect={expandFromHero}
						/>
					</div>
				{/key}
			</div>
			{#if items.length > 1}
				<CarouselIndicators
					labels={items.map((item) => item.title)}
					index={rotation.index}
					durationMs={rotation.intervalMs}
					paused={rotation.paused}
					onselect={rotation.goTo}
				/>
			{/if}
		</HeroFrame>
	</div>
{/if}

<style>
	.slide {
		display: grid;
		margin-bottom: var(--space-8);
	}

	/* Stack slides in one grid cell so the outgoing one never shifts layout */
	.info {
		grid-area: 1 / 1;
	}
</style>
