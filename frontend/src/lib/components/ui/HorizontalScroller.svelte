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

	/**
	 * Share of an edge fade, measured from the outer edge, within which a card
	 * counts as faded out. Matches the mask's 30%-opacity stop.
	 */
	const FADED_SHARE = 0.78;

	function updateScrollState() {
		if (!list) return;
		canScrollBack = list.scrollLeft > 1;
		canScrollForward = list.scrollLeft + list.clientWidth < list.scrollWidth - 1;
		markFadedItems(list);
	}

	/** Cards that are (almost) entirely inside an edge fade can't be hovered or clicked. */
	function markFadedItems(node: HTMLUListElement) {
		const fadeWidth = parseFloat(getComputedStyle(node).getPropertyValue('--fade-width')) || 0;
		const backLimit = canScrollBack ? fadeWidth * FADED_SHARE : 0;
		const forwardLimit = canScrollForward ? fadeWidth * FADED_SHARE : 0;
		const bounds = node.getBoundingClientRect();
		for (const child of node.children) {
			const rect = child.getBoundingClientRect();
			const faded = rect.right - bounds.left < backLimit || bounds.right - rect.left < forwardLimit;
			child.toggleAttribute('data-faded', faded);
		}
	}

	// New or removed items change which cards sit in the fades
	$effect(() => {
		void items.length;
		updateScrollState();
	});

	/**
	 * Stretches or shrinks items slightly from `itemWidth` so a whole number
	 * of them (gaps included) exactly fills the content column, the list minus
	 * its gutters. Paging then moves whole cards and every stop looks the same.
	 */
	function fitItems(node: HTMLUListElement) {
		const style = getComputedStyle(node);
		const target = parseFloat(style.getPropertyValue('--item-width'));
		const gap = parseFloat(style.columnGap) || 0;
		const gutter = parseFloat(style.scrollPaddingLeft) || 0;
		const column = node.clientWidth - 2 * gutter;
		if (!(target > 0) || column <= 0) return;
		const count = Math.max(1, Math.round((column + gap) / (target + gap)));
		node.style.setProperty('--fitted-width', `${(column - (count - 1) * gap) / count}px`);
	}

	function trackScrollState(node: HTMLUListElement) {
		const observer = new ResizeObserver(() => {
			fitItems(node);
			updateScrollState();
		});
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

	/**
	 * Pages by whole cards within the content column (the list minus its
	 * gutters), so a card is never carried past the column into an edge fade.
	 * Forward: the first card not fully in the column moves to its start.
	 * Back: the card cut off at the start becomes the last one fully in view.
	 */
	function scrollByPage(direction: 1 | -1) {
		if (!list) return;
		const gutter = parseFloat(getComputedStyle(list).scrollPaddingLeft) || 0;
		const bounds = list.getBoundingClientRect();
		const columnStart = bounds.left + gutter;
		const columnEnd = bounds.right - gutter;
		const children = [...list.children];
		/** Scroll offset that puts `child` at the start of the column. */
		const startOffset = (child: Element) =>
			list!.scrollLeft + child.getBoundingClientRect().left - columnStart;

		let target: number | undefined;
		if (direction === 1) {
			const next = children.find((child) => child.getBoundingClientRect().right > columnEnd + 1);
			if (next) target = startOffset(next);
		} else {
			const cut = children.findLast(
				(child) => child.getBoundingClientRect().left < columnStart - 1
			);
			if (cut) {
				// Earliest card start that still keeps `cut` fully in the column
				const minStart =
					startOffset(cut) - (columnEnd - columnStart) + cut.getBoundingClientRect().width;
				const first = children.find((child) => startOffset(child) >= minStart - 1);
				target = first ? startOffset(first) : 0;
			}
		}
		// Fallback for cards wider than the column: plain paging
		if (target === undefined || Math.abs(target - list.scrollLeft) < 1) {
			target = list.scrollLeft + direction * (columnEnd - columnStart);
		}
		list.scrollTo({ left: target, behavior: 'smooth' });
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
				size="lg"
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
				size="lg"
				tabindex={-1}
				onclick={() => scrollByPage(1)}
			/>
		</div>
	{/if}
</div>

<style>
	/* Registered so script reads the target item width as resolved pixels */
	@property --item-width {
		syntax: '<length>';
		inherits: true;
		initial-value: 0px;
	}

	@property --fade-back {
		syntax: '<length>';
		inherits: true;
		initial-value: 0px;
	}

	/* Registered so the computed value is a resolved length script can read */
	@property --fade-width {
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
		/* Fitted to the column by fitItems(); the target width until then */
		grid-auto-columns: var(--fitted-width, var(--item-width));
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
		/* Each edge stays fully clear for its outer 60% (where the nav buttons
		   sit), then eases in towards the content column */
		mask-image: linear-gradient(
			to right,
			transparent calc(var(--fade-back) * 0.6),
			rgb(0 0 0 / 0.3) calc(var(--fade-back) * 0.78),
			rgb(0 0 0 / 0.7) calc(var(--fade-back) * 0.92),
			#000 var(--fade-back),
			#000 calc(100% - var(--fade-forward)),
			rgb(0 0 0 / 0.7) calc(100% - var(--fade-forward) * 0.92),
			rgb(0 0 0 / 0.3) calc(100% - var(--fade-forward) * 0.78),
			transparent calc(100% - var(--fade-forward) * 0.6)
		);
	}

	li {
		scroll-snap-align: start;
	}

	/* Set from script, so Svelte can't see it in the markup */
	li:global([data-faded]) {
		pointer-events: none;
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

	/* Centered in the edge fade's fully clear part, over no visible content
	   (1.5rem = half the button's width) */
	.back {
		left: max(var(--space-2), calc(var(--fade-width) / 2 - 1.5rem));
	}

	.forward {
		right: max(var(--space-2), calc(var(--fade-width) / 2 - 1.5rem));
	}

	.scroller:hover .nav {
		opacity: 1;
	}

	/* Solid, high-contrast buttons so they read over any card */
	.nav :global(.icon-button) {
		background: var(--color-surface-raised);
		border-color: var(--color-border);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
	}

	.nav :global(.icon-button:hover) {
		background: var(--color-surface-hover);
		border-color: var(--color-accent-soft);
		color: var(--color-accent-strong);
	}

	@media (hover: none) {
		.nav {
			display: none;
		}
	}
</style>
