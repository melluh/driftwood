import { createContext } from 'svelte';

/** Open/closed state of the full-screen search overlay, shared via context. */
export class SearchOverlayState {
	isOpen = $state(false);

	open = (): void => {
		this.isOpen = true;
	};

	close = (): void => {
		this.isOpen = false;
	};
}

export const [getSearchOverlay, setSearchOverlay] = createContext<SearchOverlayState>();
