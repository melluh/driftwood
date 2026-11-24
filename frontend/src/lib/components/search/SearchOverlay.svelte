<!--
	Full-screen search: a large, auto-focused input with instant suggestions.
	The highlighted result's backdrop fades in behind everything.
-->
<script lang="ts">
	import { goto } from '$app/navigation';
	import { MediaSearch, suggestionOptionId } from '#lib/search/media-search.svelte.ts';
	import { mediaHref } from '#lib/media/format.ts';
	import FadedBackdrop from '../media/FadedBackdrop.svelte';
	import IconButton from '../ui/IconButton.svelte';
	import SearchInput from './SearchInput.svelte';
	import SuggestionList from './SuggestionList.svelte';

	let { onclose }: { onclose: () => void } = $props();

	const search = new MediaSearch();
	const listId = 'search-suggestions';

	function openAsModal(dialog: HTMLDialogElement) {
		dialog.showModal();
		return () => dialog.close();
	}

	function selectHighlighted() {
		const item = search.highlighted;
		if (!item) return;
		onclose();
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

<dialog {@attach openAsModal} oncancel={handleCancel} aria-label="Search">
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
			<SuggestionList {search} id={listId} onselect={onclose} />
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
</style>
