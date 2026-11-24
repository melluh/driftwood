import { prefersReducedMotion } from 'svelte/motion';

/**
 * Auto-advancing index for a carousel. Pauses while the user hovers or
 * focuses the carousel, and never auto-advances for reduced-motion users.
 * Must be constructed during component initialisation (it owns an effect).
 */
export class Rotation {
	index = $state(0);
	#hovered = $state(false);
	#focused = $state(false);
	#count: () => number;
	readonly intervalMs: number;

	constructor(count: () => number, { intervalMs = 8000 }: { intervalMs?: number } = {}) {
		this.#count = count;
		this.intervalMs = intervalMs;

		$effect(() => {
			if (this.paused || this.#count() < 2) return;
			void this.index; // restart the timer whenever the slide changes
			const timer = setTimeout(() => this.step(1), this.intervalMs);
			return () => clearTimeout(timer);
		});
	}

	get paused(): boolean {
		return this.#hovered || this.#focused || prefersReducedMotion.current;
	}

	goTo = (index: number): void => {
		const count = this.#count();
		if (count > 0) this.index = ((index % count) + count) % count;
	};

	step(delta: number): void {
		this.goTo(this.index + delta);
	}

	setHovered = (hovered: boolean): void => {
		this.#hovered = hovered;
	};

	setFocused = (focused: boolean): void => {
		this.#focused = focused;
	};
}
