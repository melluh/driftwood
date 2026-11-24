<script lang="ts">
	import CastList from '#lib/components/media/CastList.svelte';
	import MediaFacts from '#lib/components/media/MediaFacts.svelte';
	import MediaHero from '#lib/components/media/MediaHero.svelte';
	import PageSection from '#lib/components/layout/PageSection.svelte';
	import ReleaseDebugPanel from '#lib/components/releases/ReleaseDebugPanel.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const media = $derived(data.media);
</script>

<svelte:head>
	<title>{media.title}{media.year ? ` (${media.year})` : ''} · Driftwood</title>
</svelte:head>

<MediaHero {media}>
	{#if media.overview}
		<p class="overview">{media.overview}</p>
	{/if}
</MediaHero>

<PageSection>
	<MediaFacts {media} />
</PageSection>

{#if media.cast.length}
	<PageSection title="Cast">
		<CastList cast={media.cast} />
	</PageSection>
{/if}

<PageSection title="Releases (debug)">
	{#key `${media.media_type}/${media.id}`}
		<ReleaseDebugPanel mediaType={media.media_type} mediaId={media.id} />
	{/key}
</PageSection>

<style>
	.overview {
		max-width: 46rem;
		color: var(--color-text-muted);
		font-size: var(--text-md);
		line-height: 1.65;
	}
</style>
