<!--
	The full-screen "watch experience" shell: covers the app (header included)
	with a dimmed backdrop of the title under the shared watch title bar.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import FadedBackdrop from '../media/FadedBackdrop.svelte';
	import WatchTitleBar from './WatchTitleBar.svelte';

	let {
		title,
		detail,
		backdropPath,
		onclose,
		immersive = false,
		children
	}: {
		title: string;
		/** E.g. the episode being watched: `S01E01`. */
		detail?: string | null;
		backdropPath: string | null | undefined;
		onclose: () => void;
		/** The content (a player) fills the stage and brings its own title and close button. */
		immersive?: boolean;
		children: Snippet;
	} = $props();

	function onkeydown(event: KeyboardEvent) {
		if (event.key !== 'Escape' || event.defaultPrevented) return;
		// The search overlay, opened over the stage, closes on its own Esc.
		if (event.target instanceof Element && event.target.closest('dialog[open]')) return;
		onclose();
	}
</script>

<svelte:window {onkeydown} />

<div
	class="stage"
	role="dialog"
	aria-modal="true"
	aria-labelledby={immersive ? undefined : 'watch-title'}
	aria-label={immersive ? title : undefined}
>
	{#if immersive}
		{@render children()}
	{:else}
		<FadedBackdrop path={backdropPath} opacity={0.28} eager />
		<div class="bar">
			<WatchTitleBar {title} {detail} titleId="watch-title" {onclose} />
		</div>
		<div class="content">
			{@render children()}
		</div>
	{/if}
</div>

<style>
	.stage {
		position: fixed;
		inset: 0;
		z-index: 30;
		isolation: isolate;
		overflow-y: auto;
		background: var(--color-bg);
	}

	.stage :global(.backdrop) {
		position: fixed;
		z-index: -1;
	}

	.bar {
		position: fixed;
		inset: 0 0 auto;
		z-index: 1;
		/* Keeps the title legible when content scrolls underneath */
		background: linear-gradient(to bottom, oklch(from var(--color-bg) l c h / 0.85), transparent);
		/* Content scrolls under the bar's fade: only the button takes clicks */
		pointer-events: none;
	}

	.bar :global(.icon-button) {
		pointer-events: auto;
	}

	.content {
		width: min(100%, 52rem);
		min-height: 100%;
		margin: 0 auto;
		padding: calc(var(--header-height) + var(--space-8)) var(--page-gutter) var(--space-12);
		display: flex;
		flex-direction: column;
		justify-content: center;
		gap: var(--space-8);
	}
</style>
