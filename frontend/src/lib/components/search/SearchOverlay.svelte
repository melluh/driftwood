<!--
	Full-screen search: a large, auto-focused input with instant suggestions.
	The highlighted result's backdrop fades in behind everything.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { cubicOut } from 'svelte/easing';
	import { prefersReducedMotion } from 'svelte/motion';
	import type { TransitionConfig } from 'svelte/transition';
	import { MediaSearch, suggestionOptionId } from '#lib/search/media-search.svelte.ts';
	import { mediaHref } from '#lib/media/format.ts';
	import { expandFrom } from '#lib/transitions/media-expand.ts';
	import FadedBackdrop from '../media/FadedBackdrop.svelte';
	import IconButton from '../ui/IconButton.svelte';
	import SearchInput from './SearchInput.svelte';
	import SuggestionList from './SuggestionList.svelte';

	let { onclose }: { onclose: () => void } = $props();

	const search = new MediaSearch();
	const listId = 'search-suggestions';

	/** Closing because a result is being followed, not dismissed. */
	let leaving = false;

	/**
	 * Dismissing fades search out. Following a result closes it at once: the
	 * page is about to grow over it, and a half-faded overlay would be captured
	 * in that transition's new screen.
	 */
	const dismiss: (node: Element) => TransitionConfig = () => {
		if (leaving) return { duration: 0 };
		return {
			duration: 200,
			easing: cubicOut,
			css: (t) =>
				prefersReducedMotion.current
					? `opacity: ${t}`
					: `opacity: ${t}; transform: scale(${1 + (1 - t) * 0.01})`
		};
	};

	function leave() {
		leaving = true;
		onclose();
	}

	function openAsModal(dialog: HTMLDialogElement) {
		dialog.showModal();
		return () => dialog.close();
	}

	/**
	 * Following a result keeps search open until the destination page is ready,
	 * then grows that page out of the result while search closes.
	 */
	function leaveFrom(link: HTMLAnchorElement) {
		expandFrom(link, { onleave: leave });
	}

	function selectHighlighted() {
		const item = search.highlighted;
		if (!item) return;
		const option = document.getElementById(suggestionOptionId(listId, search.highlightedIndex));
		const link = option?.querySelector('a');
		if (link) leaveFrom(link);
		else leave();
		// eslint-disable-next-line svelte/no-navigation-without-resolve -- mediaHref() resolves the route
		void goto(mediaHref(item.media_type, item.id));
	}

	function handleKeydown(event: KeyboardEvent) {
		const actions: Record<string, () => void> = {
			ArrowDown: () => search.moveHighlight(1),
			ArrowUp: () => search.moveHighlight(-1),
			Enter: selectHighlighted,
			// Handled here too: a search input swallows the first Esc to clear itself
			Escape: onclose
		};
		const action = actions[event.key];
		if (action) {
			event.preventDefault();
			action();
		}
	}

	function handleCancel(event: Event) {
		// Esc: let Svelte unmount the dialog instead of the browser closing it.
		event.preventDefault();
		onclose();
	}
</script>

<dialog {@attach openAsModal} out:dismiss oncancel={handleCancel} aria-label="Search">
	<FadedBackdrop path={search.highlighted?.backdrop_path} opacity={0.35} />

	<div class="layout">
		<div class="top">
			<SearchInput
				bind:value={search.query}
				loading={search.phase === 'loading'}
				onkeydown={handleKeydown}
				role="combobox"
				aria-expanded={search.results.length > 0}
				aria-controls={listId}
				aria-activedescendant={search.highlighted
					? suggestionOptionId(listId, search.highlightedIndex)
					: undefined}
			/>
			<IconButton icon="close" label="Close search" size="lg" onclick={onclose} />
		</div>

		<div class="results">
			<SuggestionList {search} id={listId} onselect={leaveFrom} />
		</div>
	</div>
</dialog>

<style>
	dialog {
		position: fixed;
		inset: 0;
		width: 100%;
		max-width: none;
		height: 100%;
		max-height: none;
		margin: 0;
		padding: 0;
		border: 0;
		background: var(--color-bg);
		color: var(--color-text);
		overflow: hidden;
		animation: appear var(--duration-slow) var(--ease-out);
	}

	dialog::backdrop {
		background: transparent;
	}

	.layout {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		width: 100%;
		max-width: 52rem;
		height: 100%;
		margin: 0 auto;
		padding: var(--space-12) var(--page-gutter) 0;
	}

	.top {
		display: flex;
		align-items: center;
		gap: var(--space-4);
	}

	.results {
		flex: 1;
		overflow-y: auto;
		padding-bottom: var(--space-12);
		mask-image: linear-gradient(
			to bottom,
			transparent 0,
			black var(--space-4),
			black 85%,
			transparent
		);
		padding-top: var(--space-4);
		scrollbar-width: none;
	}

	@keyframes appear {
		from {
			opacity: 0;
			transform: scale(1.01);
		}
	}

	@keyframes appear-plain {
		from {
			opacity: 0;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		dialog {
			animation-name: appear-plain;
		}
	}
</style>
