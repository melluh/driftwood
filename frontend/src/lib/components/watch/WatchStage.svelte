<!--
	The full-screen "watch experience" shell: covers the app (header included)
	with a dimmed backdrop of the title, the title in the top-left corner and a
	close button back to its page in the top-right.
-->
<script lang="ts">
	import type { Snippet } from 'svelte';
	import FadedBackdrop from '../media/FadedBackdrop.svelte';
	import IconButton from '../ui/IconButton.svelte';

	let {
		title,
		year,
		detail,
		backdropPath,
		onclose,
		immersive = false,
		children
	}: {
		title: string;
		year?: number | null;
		/** E.g. the episode being watched: `S01E01`. */
		detail?: string | null;
		backdropPath: string | null | undefined;
		onclose: () => void;
		/** The content (a player) fills the stage and brings its own title and close button. */
		immersive?: boolean;
		children: Snippet;
	} = $props();

	function onkeydown(event: KeyboardEvent) {
		if (event.key === 'Escape') onclose();
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
		<header>
			<h2 id="watch-title">
				<span class="name">{title}</span>
				{#if year}<span class="muted">({year})</span>{/if}
				{#if detail}<span class="muted">· {detail}</span>{/if}
			</h2>
			<IconButton icon="close" label="Close (Esc)" size="lg" onclick={onclose} />
		</header>
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

	header {
		position: fixed;
		inset: 0 0 auto;
		z-index: 1;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-4) var(--page-gutter);
		/* Keeps the title legible when content scrolls underneath */
		background: linear-gradient(to bottom, oklch(from var(--color-bg) l c h / 0.85), transparent);
	}

	h2 {
		display: flex;
		align-items: baseline;
		gap: 0.4em;
		min-width: 0;
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
		white-space: nowrap;
	}

	.name {
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.muted {
		flex-shrink: 0;
		color: var(--color-text-muted);
		font-weight: 400;
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
