<!--
	What's on screen until the player has a first frame to show: the title's
	faded backdrop and the player's own title bar, so starting playback reads as
	one continuous screen rather than a loading page followed by a player.
	The loading indicator only fades in when starting takes a while, so a quick
	start never flashes it. Lifting it cross-fades to the player underneath.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import FadedBackdrop from '#lib/components/media/FadedBackdrop.svelte';
	import IconButton from '#lib/components/ui/IconButton.svelte';
	import Spinner from '#lib/components/ui/Spinner.svelte';

	let {
		title,
		detail,
		backdropPath,
		message = 'Starting playback',
		lifted = false,
		onclose
	}: {
		title: string;
		detail?: string | null;
		backdropPath: string | null | undefined;
		message?: string;
		/** The player is showing: fade out (and back in when it starts over). */
		lifted?: boolean;
		onclose: () => void;
	} = $props();

	/** Bumped each time the curtain comes back down, restarting the indicator's delay. */
	let shown = $state(0);
	let wasLifted = untrack(() => lifted);
	$effect(() => {
		if (wasLifted && !lifted) untrack(() => shown++);
		wasLifted = lifted;
	});
</script>

<div class="curtain" class:lifted aria-hidden={lifted}>
	<FadedBackdrop path={backdropPath} opacity={0.28} eager />
	<header>
		<IconButton icon="arrow-left" label="Back (Esc)" size="lg" onclick={onclose} />
		<div class="title">
			<h2>{title}</h2>
			{#if detail}<span>{detail}</span>{/if}
		</div>
	</header>
	{#key shown}
		<!-- Stays while the curtain fades, rather than popping off ahead of it. -->
		<div class="status" role={lifted ? undefined : 'status'} aria-live="polite">
			<Spinner size="2.5rem" label={message} />
			<p>{message}</p>
		</div>
	{/key}
</div>

<style>
	.curtain {
		position: fixed;
		inset: 0;
		/* Above the player (z-index 1), which loads underneath. */
		z-index: 2;
		isolation: isolate;
		display: grid;
		place-items: center;
		background: var(--color-bg);
		transition:
			opacity var(--duration-slow) var(--ease-out),
			visibility 0s;
	}

	.lifted {
		opacity: 0;
		visibility: hidden;
		pointer-events: none;
		/* Hidden only once faded out. */
		transition:
			opacity var(--duration-slow) var(--ease-out),
			visibility 0s linear var(--duration-slow);
	}

	.curtain :global(.backdrop) {
		z-index: -1;
	}

	/* Matches the player's top bar, which takes its place as the curtain lifts. */
	header {
		position: absolute;
		inset: 0 0 auto;
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-4) var(--page-gutter) var(--space-12);
	}

	.title {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
		min-width: 0;
		white-space: nowrap;
	}

	.title h2 {
		overflow: hidden;
		text-overflow: ellipsis;
		font-family: var(--font-display);
		font-size: var(--text-lg);
		font-weight: 600;
	}

	.title span {
		color: oklch(100% 0 0 / 0.7);
	}

	header :global(.icon-button) {
		flex-shrink: 0;
		border-color: oklch(100% 0 0 / 0.15);
		background: oklch(0% 0 0 / 0.35);
		color: #fff;
	}

	.status {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--text-sm);
		/* Only shown once starting takes long enough to notice. */
		animation: appear var(--duration-slow) var(--ease-out) 900ms both;
	}

	@keyframes appear {
		from {
			opacity: 0;
			transform: translateY(0.25rem);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.status {
			animation-name: appear-plain;
		}

		@keyframes appear-plain {
			from {
				opacity: 0;
			}
		}
	}
</style>
