/**
 * A time-left estimate that only shows up once it can be trusted.
 *
 * qBittorrent's own ETA swings wildly in a torrent's first seconds (a burst from one peer, then
 * nothing). Instead, the speed is the average over a sliding window of progress readings, and
 * every reading turns it into a predicted *finish time*. Once those predictions have agreed
 * for a while (their spread is small next to the time left), the estimate is shown, as the
 * median of the recent predictions; after half a minute it's shown regardless. It stays up from
 * then on while data keeps flowing; a stall or pause starts over.
 */

type Sample = { at: number; bytes: number };
type Prediction = { at: number; finish: number };

export type EtaOptions = {
	/** Readings the speed is averaged over. */
	speedWindowMs: number;
	/** Shortest span of readings before a speed is trusted at all. */
	minSpeedSpanMs: number;
	/** How long predictions must agree before the estimate is shown. */
	stableWindowMs: number;
	/** Allowed spread of the predicted finish times, as a share of the time left... */
	tolerance: number;
	/** ...but never stricter than this. */
	minToleranceMs: number;
	/** Show the (smoothed) estimate after this long regardless: a lasting wobble still beats
	 * no estimate at all. */
	maxWaitMs: number;
};

const DEFAULTS: EtaOptions = {
	speedWindowMs: 15_000,
	minSpeedSpanMs: 5_000,
	stableWindowMs: 8_000,
	tolerance: 0.2,
	minToleranceMs: 20_000,
	maxWaitMs: 30_000
};

function median(values: number[]): number {
	const sorted = [...values].sort((a, b) => a - b);
	const middle = sorted.length >> 1;
	return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export class EtaEstimator {
	private samples: Sample[] = [];
	private predictions: Prediction[] = [];
	private stable = false;
	private since: number | null = null;
	private readonly options: EtaOptions;

	constructor(options: Partial<EtaOptions> = {}) {
		this.options = { ...DEFAULTS, ...options };
	}

	reset(): void {
		this.samples = [];
		this.predictions = [];
		this.stable = false;
		this.since = null;
	}

	/**
	 * Record a progress reading. Returns the seconds left to show, or null while there's no
	 * trustworthy estimate yet. `flowing` is false while stalled or paused.
	 */
	update(at: number, downloaded: number, size: number, flowing: boolean): number | null {
		if (!flowing || size <= 0) {
			this.reset();
			return null;
		}
		const { options } = this;
		const last = this.samples.at(-1);
		if (last && downloaded < last.bytes) {
			// A real drop means the data was rechecked: start over. A dip is just noise.
			if (last.bytes - downloaded > size * 0.01) this.reset();
			else downloaded = last.bytes;
		}
		const samples = this.samples; // after any reset, which replaces the array
		samples.push({ at, bytes: downloaded });
		// Keep one reading at or before the window's start as the baseline.
		while (samples.length > 2 && samples[1].at <= at - options.speedWindowMs) samples.shift();

		const first = samples[0];
		const span = at - first.at;
		if (span < options.minSpeedSpanMs) return null;
		const bytesPerMs = (downloaded - first.bytes) / span;
		if (bytesPerMs <= 0) return null;

		this.since ??= at;
		const remaining = Math.max(0, size - downloaded);
		this.predictions.push({ at, finish: at + remaining / bytesPerMs });
		this.predictions = this.predictions.filter((p) => p.at > at - options.stableWindowMs);
		const finishes = this.predictions.map((p) => p.finish);
		const estimate = median(finishes) - at;

		if (!this.stable) {
			const covered = at - this.predictions[0].at >= options.stableWindowMs * 0.75;
			const spread = Math.max(...finishes) - Math.min(...finishes);
			const allowed = Math.max(options.minToleranceMs, options.tolerance * estimate);
			const waitedOut = at - this.since >= options.maxWaitMs;
			if (!waitedOut && (!covered || spread > allowed)) return null;
			this.stable = true;
		}
		return Math.max(0, Math.round(estimate / 1000));
	}
}
