<!--
	A horizontally scrolling row of items with snap points and previous/next
	buttons (shown on hover for pointer devices); mice can also drag the row to
	scroll it. Items render via the `item`
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

	/** Pointer travel (px) before a press becomes a drag instead of a click. */
	const DRAG_THRESHOLD = 5;
	/** How far (ms) release velocity carries the row before it settles. */
	const MOMENTUM_MS = 150;

	let dragging = $state(false);

	/** Lets a mouse drag the row; touch and pen keep native scrolling. */
	function dragToScroll(node: HTMLUListElement) {
		let pointerId: number | null = null;
		let startX = 0;
		let startScroll = 0;
		let lastX = 0;
		let lastTime = 0;
		let velocity = 0; // px per ms, in scroll direction

		function onPointerDown(event: PointerEvent) {
			if (event.pointerType !== 'mouse' || event.button !== 0) return;
			pointerId = event.pointerId;
			startX = lastX = event.clientX;
			startScroll = node.scrollLeft;
			lastTime = event.timeStamp;
			velocity = 0;
		}

		function onPointerMove(event: PointerEvent) {
			if (event.pointerId !== pointerId) return;
			if (!dragging) {
				if (Math.abs(event.clientX - startX) < DRAG_THRESHOLD) return;
				dragging = true;
				node.setPointerCapture(event.pointerId);
			}
			const elapsed = event.timeStamp - lastTime;
			if (elapsed > 0) velocity = (lastX - event.clientX) / elapsed;
			lastX = event.clientX;
			lastTime = event.timeStamp;
			node.scrollLeft = startScroll - (event.clientX - startX);
		}

		function onPointerEnd(event: PointerEvent) {
			if (event.pointerId !== pointerId) return;
			pointerId = null;
			if (!dragging) return;
			// Swallow the click that follows the drag so links don't navigate
			node.addEventListener('click', suppressClick, { capture: true, once: true });
			setTimeout(() => node.removeEventListener('click', suppressClick, { capture: true }));
			settle(node.scrollLeft + velocity * MOMENTUM_MS);
		}

		/** Glides to the snap point nearest `target`, then restores snapping. */
		function settle(target: number) {
			const listLeft = node.getBoundingClientRect().left;
			const padding = parseFloat(getComputedStyle(node).scrollPaddingLeft) || 0;
			let best = target;
			let bestDistance = Infinity;
			for (const child of node.children) {
				const snap = node.scrollLeft + child.getBoundingClientRect().left - listLeft - padding;
				const distance = Math.abs(snap - target);
				if (distance < bestDistance) [best, bestDistance] = [snap, distance];
			}
			const done = () => (dragging = false);
			node.addEventListener('scrollend', done, { once: true });
			setTimeout(done, 600); // fallback where scrollend is unsupported
			node.scrollTo({ left: best, behavior: 'smooth' });
			// No scroll happens (and no scrollend fires) if we're already there
			if (Math.abs(best - node.scrollLeft) < 1) dragging = false;
		}

		function suppressClick(event: MouseEvent) {
			event.preventDefault();
			event.stopPropagation();
		}

		// Stop native link/image drag-and-drop from hijacking the gesture
		function onDragStart(event: DragEvent) {
			event.preventDefault();
		}

		node.addEventListener('pointerdown', onPointerDown);
		node.addEventListener('pointermove', onPointerMove);
		node.addEventListener('pointerup', onPointerEnd);
		node.addEventListener('pointercancel', onPointerEnd);
		node.addEventListener('dragstart', onDragStart);
		return () => {
			node.removeEventListener('pointerdown', onPointerDown);
			node.removeEventListener('pointermove', onPointerMove);
			node.removeEventListener('pointerup', onPointerEnd);
			node.removeEventListener('pointercancel', onPointerEnd);
			node.removeEventListener('dragstart', onDragStart);
		};
	}

	function scrollByPage(direction: 1 | -1) {
		list?.scrollBy({ left: direction * list.clientWidth * 0.85, behavior: 'smooth' });
	}
</script>

<div
	class="scroller"
	class:fade-back={canScrollBack}
	class:fade-forward={canScrollForward}
	style:--item-width={itemWidth}
	style:--gutter={gutter}
>
	<ul
		bind:this={list}
		class:dragging
		aria-label={label}
		onscroll={updateScrollState}
		{@attach trackScrollState}
		{@attach dragToScroll}
	>
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
	@property --fade-back {
		syntax: '<length>';
		inherits: true;
		initial-value: 0px;
	}

	@property --fade-forward {
		syntax: '<length>';
		inherits: true;
		initial-value: 0px;
	}

	.scroller {
		/* Width of the edge fade; reaches past the nav buttons */
		--fade-width: max(var(--gutter), 3rem);
		position: relative;
		transition:
			--fade-back var(--duration-fast),
			--fade-forward var(--duration-fast);
	}

	/* Fade out items scrolled past the gutter, behind the nav buttons */
	.fade-back {
		--fade-back: var(--fade-width);
	}

	.fade-forward {
		--fade-forward: var(--fade-width);
	}

	ul {
		display: grid;
		grid-auto-flow: column;
		grid-auto-columns: var(--item-width);
		gap: var(--space-4);
		/* Vertical padding leaves room for the card hover lift, which would
		   otherwise be clipped by the scroll container */
		margin: calc(-1 * var(--space-2)) 0 0;
		padding: var(--space-4) var(--gutter);
		list-style: none;
		overflow-x: auto;
		overscroll-behavior-x: contain;
		scroll-snap-type: x proximity;
		scroll-padding-inline: var(--gutter);
		scrollbar-width: none;
		mask-image: linear-gradient(
			to right,
			transparent,
			#000 var(--fade-back),
			#000 calc(100% - var(--fade-forward)),
			transparent
		);
	}

	li {
		scroll-snap-align: start;
	}

	/* Snapping would fight the pointer; settle() re-aligns on release */
	.dragging {
		scroll-snap-type: none;
		cursor: grabbing;
		user-select: none;
	}

	.dragging :global(*) {
		cursor: grabbing;
	}

	.nav {
		position: absolute;
		top: calc(-1 * var(--space-2));
		bottom: 0;
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
