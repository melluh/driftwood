<!--
	The top bar of every watch screen: finding a release, downloading, starting
	playback and the player itself. A back button on the left, then the title
	and episode. One component so moving between those screens never shifts
	the bar. Where it sits, and the scrim behind it, are up to the screen.
-->
<script lang="ts">
	import IconButton from '../ui/IconButton.svelte';

	let {
		title,
		detail,
		titleId,
		onclose
	}: {
		title: string;
		/** E.g. the episode being watched: `S01E01`. */
		detail?: string | null;
		/** DOM id for the title, for a dialog's aria-labelledby. */
		titleId?: string;
		onclose: () => void;
	} = $props();
</script>

<header class="watch-title-bar">
	<IconButton icon="arrow-left" label="Back (Esc)" size="lg" onclick={onclose} />
	<div class="title">
		<h2 id={titleId}>{title}</h2>
		{#if detail}<span>{detail}</span>{/if}
	</div>
</header>

<style>
	.watch-title-bar {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-4) var(--page-gutter) var(--space-12);
		color: #fff;
	}

	.title {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
		white-space: nowrap;
	}

	h2 {
		overflow: hidden;
		text-overflow: ellipsis;
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
	}

	span {
		flex-shrink: 0;
		color: oklch(100% 0 0 / 0.7);
	}

	/* Reads over any backdrop or video frame */
	.watch-title-bar :global(.icon-button) {
		flex-shrink: 0;
		border-color: oklch(100% 0 0 / 0.15);
		background: oklch(0% 0 0 / 0.35);
		color: #fff;
	}

	.watch-title-bar :global(.icon-button:hover) {
		background: oklch(0% 0 0 / 0.55);
		border-color: oklch(100% 0 0 / 0.3);
	}
</style>
