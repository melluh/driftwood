import type { PlaybackSubtitleTrack } from '#lib/api/client.ts';
import pgsWorkerUrl from 'libpgs/dist/libpgs.worker.js?url';

type Jassub = { ready: Promise<void>; destroy(): void | Promise<void> };
type Pgs = { ready: Promise<void>; dispose(): void };

export type SubtitleResult = 'ass' | 'pgs' | 'text';

const absolute = (url: string) => new URL(url, location.href).href;

/**
 * Shows one subtitle track over a video. WebVTT cues are handed to `oncues`
 * to render (so they can move out of the way of the controls); ASS tracks are
 * drawn with their styling by JASSUB on a canvas over the video, falling back
 * to the plain-text rendition when that fails; PGS pictures (Blu-ray
 * subtitles) are drawn by libpgs on a canvas over the video.
 */
export class SubtitleRenderer {
	#video: HTMLVideoElement;
	#oncues: (cues: DocumentFragment[]) => void;
	#element: HTMLTrackElement | null = null;
	#jassub: Jassub | null = null;
	#pgs: Pgs | null = null;
	#generation = 0;

	constructor(video: HTMLVideoElement, oncues: (cues: DocumentFragment[]) => void) {
		this.#video = video;
		this.#oncues = oncues;
	}

	/** Resolves once the track shows; rejects when it can't be loaded. */
	async show(track: PlaybackSubtitleTrack | null, fonts: string[]): Promise<SubtitleResult | null> {
		const generation = ++this.#generation;
		this.#clear();
		if (!track) return null;
		if (track.format === 'pgs') {
			await this.#showPgs(track.url, generation);
			return 'pgs';
		}
		if (track.format === 'ass') {
			try {
				await this.#showAss(track.url, fonts, generation);
				return 'ass';
			} catch (error) {
				if (generation !== this.#generation) return null;
				console.warn('ASS subtitles failed; showing them as plain text', error);
				this.#clear();
			}
		}
		await this.#showText(track.text_url ?? track.url, track.language, generation);
		return 'text';
	}

	destroy() {
		this.#generation++;
		this.#clear();
	}

	async #showAss(url: string, fonts: string[], generation: number) {
		const { default: JASSUB } = await import('jassub');
		if (generation !== this.#generation) return;
		const renderer = new JASSUB({
			video: this.#video,
			subUrl: absolute(url),
			fonts: fonts.map(absolute)
		}) as unknown as Jassub;
		this.#jassub = renderer;
		await renderer.ready;
	}

	async #showPgs(url: string, generation: number) {
		const { PgsRenderer } = await import('libpgs');
		if (generation !== this.#generation) return;
		const renderer = new PgsRenderer({
			video: this.#video,
			subUrl: absolute(url),
			workerUrl: absolute(pgsWorkerUrl),
			// Matches the video's object-fit, so pictures land where the video is drawn.
			aspectRatio: 'contain'
		});
		this.#pgs = renderer;
		try {
			await renderer.ready;
		} catch (error) {
			if (generation === this.#generation) this.#clear();
			throw error;
		}
	}

	#showText(url: string, language: string | null, generation: number): Promise<void> {
		const element = document.createElement('track');
		element.kind = 'subtitles';
		element.src = url;
		if (language) element.srclang = language;
		this.#video.append(element);
		this.#element = element;
		// Hidden: cues still fire, but the browser doesn't draw them itself.
		element.track.mode = 'hidden';
		element.track.addEventListener('cuechange', () => {
			const active = Array.from(element.track.activeCues ?? []) as VTTCue[];
			this.#oncues(active.map((cue) => cue.getCueAsHTML()));
		});
		return new Promise((resolve, reject) => {
			element.addEventListener('load', () => resolve(), { once: true });
			element.addEventListener(
				'error',
				() => {
					if (generation === this.#generation) this.#clear();
					reject(new Error("The subtitles couldn't be loaded."));
				},
				{ once: true }
			);
		});
	}

	#clear() {
		this.#element?.remove();
		this.#element = null;
		void this.#jassub?.destroy();
		this.#jassub = null;
		this.#pgs?.dispose();
		this.#pgs = null;
		this.#oncues([]);
	}
}
