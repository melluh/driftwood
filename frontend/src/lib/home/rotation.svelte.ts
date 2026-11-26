import { prefersReducedMotion } from 'svelte/motion';

/**
 * Auto-advancing index for a carousel. Pauses while keyboard focus or the
 * mouse is inside the carousel and while the tab is hidden, and never
 * auto-advances for reduced-motion users. A pause holds the time left on the
 * slide, so it resumes where it stopped (in step with its progress bar).
 * Must be constructed during component initialisation (it owns effects).
 */
export class Rotation {
	index = $state(0);
	#focused = $state(false);
	#hovered = $state(false);
	#hidden = $state(document.visibilityState === 'hidden');
	#count: () => number;
	readonly intervalMs: number;

	/** Time left on the slide at `#remainingIndex`, as of the last pause. */
	#remaining: number;
	#remainingIndex = 0;

	constructor(count: () => number, { intervalMs = 8000 }: { intervalMs?: number } = {}) {
		this.#count = count;
		this.intervalMs = intervalMs;
		this.#remaining = intervalMs;

		$effect(() => {
			const index = this.index;
			// A new slide gets its full time
			if (index !== this.#remainingIndex) {
				this.#remainingIndex = index;
				this.#remaining = this.intervalMs;
			}
			if (this.paused || this.#count() < 2) return;
			const started = performance.now();
			const timer = setTimeout(() => this.step(1), this.#remaining);
			return () => {
				clearTimeout(timer);
				this.#remaining = Math.max(0, this.#remaining - (performance.now() - started));
			};
		});

		$effect(() => {
			const update = () => (this.#hidden = document.visibilityState === 'hidden');
			document.addEventListener('visibilitychange', update);
			return () => document.removeEventListener('visibilitychange', update);
		});
	}

	get paused(): boolean {
		return this.#focused || this.#hovered || this.#hidden || prefersReducedMotion.current;
	}

	goTo = (index: number): void => {
		const count = this.#count();
		if (count > 0) this.index = ((index % count) + count) % count;
	};

	step(delta: number): void {
		this.goTo(this.index + delta);
	}

	setFocused = (focused: boolean): void => {
		this.#focused = focused;
	};

	setHovered = (hovered: boolean): void => {
		this.#hovered = hovered;
	};
}
