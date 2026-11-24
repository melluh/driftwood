import { api, type MediaSummary, type SearchStatus } from '#lib/api/client.ts';

/** DOM id of a suggestion option, for the input's aria-activedescendant. */
export function suggestionOptionId(listId: string, index: number): string {
	return `${listId}-option-${index}`;
}

export type SearchPhase = 'idle' | 'loading' | 'ready' | 'error';

/**
 * Instant search state: debounced, cancellable queries against `/api/search`
 * plus keyboard highlight tracking. There is no "submit" - results follow the
 * query as it's typed. Previous results stay visible while the next query is
 * in flight, so the list doesn't flicker on every keystroke.
 */
export class MediaSearch {
	results: MediaSummary[] = $state([]);
	phase: SearchPhase = $state('idle');
	highlightedIndex = $state(0);
	/** Only fetched once a search comes back empty, to explain a still-building index. */
	indexStatus: SearchStatus | null = $state(null);

	#query = $state('');
	#debounceMs: number;
	#timer: ReturnType<typeof setTimeout> | undefined;
	#controller: AbortController | undefined;

	constructor({ debounceMs = 150 }: { debounceMs?: number } = {}) {
		this.#debounceMs = debounceMs;
	}

	get query(): string {
		return this.#query;
	}

	set query(value: string) {
		this.#query = value;
		this.#schedule();
	}

	get trimmedQuery(): string {
		return this.#query.trim();
	}

	get highlighted(): MediaSummary | undefined {
		return this.results[this.highlightedIndex];
	}

	moveHighlight(delta: number): void {
		const count = this.results.length;
		if (count === 0) return;
		this.highlightedIndex = (this.highlightedIndex + delta + count) % count;
	}

	reset(): void {
		this.#cancel();
		this.#query = '';
		this.results = [];
		this.phase = 'idle';
		this.highlightedIndex = 0;
	}

	#cancel(): void {
		clearTimeout(this.#timer);
		this.#controller?.abort();
	}

	#schedule(): void {
		this.#cancel();
		const query = this.trimmedQuery;
		if (!query) {
			this.results = [];
			this.phase = 'idle';
			return;
		}
		this.phase = 'loading';
		this.#timer = setTimeout(() => void this.#run(query), this.#debounceMs);
	}

	async #run(query: string): Promise<void> {
		const controller = new AbortController();
		this.#controller = controller;
		try {
			const { data, error } = await api.GET('/api/search', {
				params: { query: { q: query } },
				signal: controller.signal
			});
			if (controller.signal.aborted) return;
			if (error || !data) throw new Error('Search request failed');
			this.results = data;
			this.highlightedIndex = 0;
			this.phase = 'ready';
			if (data.length === 0) await this.#refreshIndexStatus();
		} catch {
			if (controller.signal.aborted) return;
			this.results = [];
			this.phase = 'error';
		}
	}

	async #refreshIndexStatus(): Promise<void> {
		const { data } = await api.GET('/api/search/status');
		this.indexStatus = data ?? null;
	}
}
