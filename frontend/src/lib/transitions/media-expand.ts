/*
 * "Expand into page": when a link to a media page is followed (a shelf card,
 * a search result), the details page is revealed by growing out of that
 * link's bounds to fill the viewport. Built on the View Transitions API;
 * browsers without it (or users preferring reduced motion) get a plain
 * navigation.
 *
 * Usage: call `setupMediaExpandTransition()` once from the root layout, and
 * `expandFrom(link)` just before (or as) the link is followed.
 */
import { onNavigate } from '$app/navigation';

export interface ExpandOptions {
	/**
	 * Runs when the destination page is about to replace the current one, after
	 * the old screen is captured — e.g. to close an overlay the link sits in, so
	 * it stays visible until the page grows over it.
	 */
	onleave?: () => void;
	/** Element whose bounds the page grows out of, when not the link itself. */
	bounds?: HTMLElement;
	/** Whether the starting shape has the card's rounded corners (default true). */
	rounded?: boolean;
}

interface Origin extends ExpandOptions {
	link: HTMLAnchorElement;
}

let pending: Origin | null = null;

/** Marks `link` as the origin of the transition into the page it points to. */
export function expandFrom(link: HTMLAnchorElement, options: ExpandOptions = {}): void {
	pending = { link, ...options };
}

/** A click the router will handle in place (not a new tab/window/download). */
export function isPlainClick(event: MouseEvent): boolean {
	const modified = event.ctrlKey || event.metaKey || event.shiftKey || event.altKey;
	return !event.defaultPrevented && !modified && event.button === 0;
}

export function setupMediaExpandTransition(): void {
	// Runs once the destination's data has loaded, right before the DOM swap
	onNavigate((navigation) => {
		const origin = pending;
		pending = null;
		if (!origin) return;
		const animate =
			navigation.to?.url.href === origin.link.href && origin.link.isConnected && canAnimate();
		if (!animate) {
			origin.onleave?.();
			return;
		}

		const root = document.documentElement;
		setExpandOrigin(root, (origin.bounds ?? origin.link).getBoundingClientRect());
		if (origin.rounded === false) root.style.setProperty('--expand-radius', '0px');
		root.dataset.transition = 'media-expand';

		return new Promise<void>((startNavigation) => {
			const transition = document.startViewTransition(async () => {
				// Old screen is captured: tear it down and let SvelteKit swap in the new page
				origin.onleave?.();
				startNavigation();
				await navigation.complete;
			});

			// A failed navigation aborts the transition; that's fine, just clean up
			transition.ready.catch(() => {});
			transition.finished
				.catch(() => {})
				.finally(() => {
					delete root.dataset.transition;
					for (const side of SIDES) root.style.removeProperty(`--expand-${side}`);
					root.style.removeProperty('--expand-radius');
				});
		});
	});
}

const SIDES = ['top', 'right', 'bottom', 'left'] as const;

/** Exposes the origin's viewport insets for the reveal's starting clip-path. */
function setExpandOrigin(root: HTMLElement, rect: DOMRect): void {
	const insets = {
		top: rect.top,
		right: root.clientWidth - rect.right,
		bottom: root.clientHeight - rect.bottom,
		left: rect.left
	};
	for (const side of SIDES) root.style.setProperty(`--expand-${side}`, `${insets[side]}px`);
}

function canAnimate(): boolean {
	return (
		typeof document.startViewTransition === 'function' &&
		!matchMedia('(prefers-reduced-motion: reduce)').matches
	);
}
