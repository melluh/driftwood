<script lang="ts">
	import CastList from '#lib/components/media/CastList.svelte';
	import MediaFacts from '#lib/components/media/MediaFacts.svelte';
	import MediaHero from '#lib/components/media/MediaHero.svelte';
	import MyListButton from '#lib/components/media/MyListButton.svelte';
	import PageSection from '#lib/components/layout/PageSection.svelte';
	import ReleaseDebugPanel from '#lib/components/releases/ReleaseDebugPanel.svelte';
	import LinkButton from '#lib/components/ui/LinkButton.svelte';
	import type { MediaSummary } from '#lib/api/client.ts';
	import { watchHref } from '#lib/media/format.ts';
	import { isSameMedia } from '#lib/my-list/my-list.ts';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	const media = $derived(data.media);
	// Resets when navigating to another title; toggling overrides it.
	let inMyList = $derived(data.inMyList);

	function setInMyList(changed: MediaSummary, inList: boolean) {
		if (isSameMedia(changed, media)) inMyList = inList;
	}
</script>

<svelte:head>
	<title>{media.title}{media.year ? ` (${media.year})` : ''} · Driftwood</title>
</svelte:head>

<MediaHero {media}>
	{#if media.overview}
		<p class="overview">{media.overview}</p>
	{/if}
	<div class="actions">
		<LinkButton href={watchHref(media.media_type, media.id)} icon="play">Watch</LinkButton>
		{#if inMyList !== null}
			<MyListButton {media} inList={inMyList} onchange={setInMyList} />
		{/if}
	</div>
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
	.actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
		margin-top: var(--space-2);
	}

	.overview {
		max-width: 46rem;
		color: var(--color-text-muted);
		font-size: var(--text-md);
		line-height: 1.65;
	}
</style>
