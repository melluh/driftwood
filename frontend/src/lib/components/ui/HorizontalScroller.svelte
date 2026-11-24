<!--
	A horizontally scrolling row of items with snap points and previous/next
	buttons (shown on hover for pointer devices). Items render via the `item`
	snippet; `gutter` insets the first and last item from the viewport edge.
-->
<script lang="ts" generics="T">
	import type { Snippet } from 'svelte';
	import IconButton from './IconButton.svelte';

	let {
		items,
		key,
		item,
		label,
		itemWidth,
		gutter = '0px'
	}: {
		items: T[];
		key: (item: T) => string | number;
		item: Snippet<[T]>;
		/** Accessible name for the list. */
		label: string;
		itemWidth: string;
		gutter?: string;
	} = $props();

	let list: HTMLUListElement | undefined = $state();
	let canScrollBack = $state(false);
	let canScrollForward = $state(false);

	function updateScrollState() {
		if (!list) return;
		canScrollBack = list.scrollLeft > 1;
		canScrollForward = list.scrollLeft + list.clientWidth < list.scrollWidth - 1;
	}

	function trackScrollState(node: HTMLUListElement) {
		const observer = new ResizeObserver(updateScrollState);
		observer.observe(node);
		return () => observer.disconnect();
	}

	function scrollByPage(direction: 1 | -1) {
		list?.scrollBy({ left: direction * list.clientWidth * 0.85, behavior: 'smooth' });
	}
</script>

<div class="scroller" style:--item-width={itemWidth} style:--gutter={gutter}>
	<ul bind:this={list} aria-label={label} onscroll={updateScrollState} {@attach trackScrollState}>
		{#each items as entry (key(entry))}
			<li>{@render item(entry)}</li>
		{/each}
	</ul>

	{#if canScrollBack}
		<div class="nav back">
			<IconButton
				icon="chevron-left"
				label="Scroll back"
				tabindex={-1}
				onclick={() => scrollByPage(-1)}
			/>
		</div>
	{/if}
	{#if canScrollForward}
		<div class="nav forward">
			<IconButton
				icon="chevron-right"
				label="Scroll forward"
				tabindex={-1}
				onclick={() => scrollByPage(1)}
			/>
		</div>
	{/if}
</div>

<style>
	.scroller {
		position: relative;
	}

	ul {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: var(--item-width);
		gap: var(--space-4);
		margin: 0;
		padding: var(--space-2) var(--gutter) var(--space-4);
		list-style: none;
		overflow-x: auto;
		overscroll-behavior-x: contain;
		scroll-snap-type: x proximity;
		scroll-padding-inline: var(--gutter);
		scrollbar-width: none;
	}

	li {
		scroll-snap-align: start;
	}

	.nav {
		position: absolute;
		top: 0;
		bottom: var(--space-4);
		display: flex;
		align-items: center;
		opacity: 0;
		transition: opacity var(--duration-fast);
	}

	.back {
		left: max(var(--space-2), calc(var(--gutter) - 1.25rem));
	}

	.forward {
		right: max(var(--space-2), calc(var(--gutter) - 1.25rem));
	}

	.scroller:hover .nav {
		opacity: 1;
	}

	@media (hover: none) {
		.nav {
			display: none;
		}
	}
</style>
