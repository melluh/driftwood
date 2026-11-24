<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { alternateTitle, mediaHref } from '#lib/media/format.ts';
	import MediaMeta from '../media/MediaMeta.svelte';
	import TmdbImage from '../media/TmdbImage.svelte';

	let {
		item,
		id,
		highlighted = false,
		onselect,
		onhover
	}: {
		item: MediaSummary;
		/** DOM id, for the input's aria-activedescendant. */
		id: string;
		highlighted?: boolean;
		onselect?: () => void;
		onhover?: () => void;
	} = $props();

	const originalTitle = $derived(alternateTitle(item));

	/** Plain clicks navigate here and close search; modified clicks (new tab etc.) don't. */
	function handleClick(event: MouseEvent) {
		const modified = event.ctrlKey || event.metaKey || event.shiftKey || event.altKey;
		if (!modified && event.button === 0) onselect?.();
	}

	function scrollIntoViewWhenHighlighted(node: HTMLElement) {
		if (highlighted) node.scrollIntoView({ block: 'nearest' });
	}
</script>

<li role="option" aria-selected={highlighted} {id}>
	<!-- eslint-disable svelte/no-navigation-without-resolve -- mediaHref() resolves the route -->
	<a
		href={mediaHref(item.media_type, item.id)}
		class:highlighted
		tabindex="-1"
		onclick={handleClick}
		onmousemove={onhover}
		{@attach scrollIntoViewWhenHighlighted}
	>
		<!-- eslint-enable svelte/no-navigation-without-resolve -->
		<div class="thumb">
			<TmdbImage path={item.poster_path} kind="poster" alt="" sizes="3.5rem" radius="sm" />
		</div>
		<div class="text">
			<span class="title truncate">{item.title}</span>
			{#if originalTitle}
				<span class="original truncate">{originalTitle}</span>
			{/if}
			<span class="meta">
				<MediaMeta media={item} />
			</span>
		</div>
	</a>
</li>

<style>
	a {
		display: flex;
		align-items: center;
		gap: var(--space-4);
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-md);
		transition: background var(--duration-fast);
	}

	a.highlighted {
		background: oklch(from var(--color-surface-hover) l c h / 0.85);
	}

	.thumb {
		width: 3.5rem;
		flex-shrink: 0;
	}

	.text {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.title {
		font-size: var(--text-lg);
		font-weight: 600;
	}

	.original {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	.meta {
		font-size: var(--text-sm);
	}
</style>
