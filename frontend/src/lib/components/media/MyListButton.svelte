<!--
	Adds a title to, or removes it from, "My list". The parent owns `inList`:
	`onchange` fires right away (optimistic) and again with the old value if
	the server rejects the change.

	Icon-only and square, the same height as the text buttons next to it; a
	tooltip spells out the state on hover and keyboard focus.
-->
<script lang="ts">
	import type { MediaSummary } from '#lib/api/client.ts';
	import { setInMyList } from '#lib/my-list/my-list.ts';
	import Icon from '../ui/Icon.svelte';

	let {
		media,
		inList,
		onchange,
		size = 'md'
	}: {
		media: MediaSummary;
		inList: boolean;
		/** Gets the title the click was for, which may no longer be `media` on a revert. */
		onchange: (media: MediaSummary, inList: boolean) => void;
		/** `md` lines up with text buttons; `sm` sits in a poster corner. */
		size?: 'md' | 'sm';
	} = $props();

	let saving = $state(false);

	async function toggle() {
		if (saving) return;
		const target = media;
		const next = !inList;
		saving = true;
		onchange(target, next);
		try {
			if (!(await setInMyList(target, next))) onchange(target, !next);
		} catch {
			onchange(target, !next);
		} finally {
			saving = false;
		}
	}
</script>

<!-- The label stays fixed and aria-pressed carries the state, per the toggle-button pattern. -->
<button
	type="button"
	class="my-list {size}"
	aria-label="My list"
	aria-pressed={inList}
	onclick={toggle}
>
	<Icon name={inList ? 'check' : 'plus'} />
	<span class="tooltip" aria-hidden="true">{inList ? 'Added to my list' : 'Add to my list'}</span>
</button>

<style>
	.my-list {
		/* Matches Button/LinkButton: one line of text plus their vertical padding. */
		--size: calc(1lh + 2 * var(--space-3));

		position: relative;
		display: inline-grid;
		place-items: center;
		width: var(--size);
		height: var(--size);
		padding: 0;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
		transition:
			background var(--duration-fast),
			transform var(--duration-fast);
	}

	.my-list:hover {
		background: var(--color-surface-hover);
	}

	.my-list:active {
		transform: scale(0.98);
	}

	.tooltip {
		position: absolute;
		bottom: calc(100% + var(--space-2));
		left: 50%;
		z-index: 1;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font-size: var(--text-sm);
		font-weight: 500;
		white-space: nowrap;
		pointer-events: none;
		opacity: 0;
		translate: -50% var(--space-1);
		transition:
			opacity var(--duration-fast),
			translate var(--duration-fast);
	}

	/* Over a poster: smaller, translucent, and the tooltip drops below so the
	   scroller's overflow doesn't clip it. */
	.sm {
		--size: 1.75rem;
		border-radius: var(--radius-sm);
		background: oklch(from var(--color-surface-raised) l c h / 0.7);
		backdrop-filter: blur(8px);
		font-size: var(--text-sm);
	}

	.sm .tooltip {
		top: calc(100% + var(--space-1));
		right: 0;
		bottom: auto;
		left: auto;
		font-size: var(--text-xs);
		translate: 0 calc(-1 * var(--space-1));
	}

	.my-list:focus-visible .tooltip {
		opacity: 1;
		translate: -50% 0;
	}

	/* Hover only where it exists, so a tap on touch screens doesn't leave it stuck open. */
	@media (hover: hover) {
		.my-list:hover .tooltip {
			opacity: 1;
			translate: -50% 0;
		}
	}

	.sm:focus-visible .tooltip {
		translate: 0 0;
	}

	@media (hover: hover) {
		.sm:hover .tooltip {
			translate: 0 0;
		}
	}
</style>
