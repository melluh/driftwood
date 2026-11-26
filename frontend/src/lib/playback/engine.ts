import type { PlaybackSession } from '#lib/api/client.ts';

export type Engine = { destroy(): void };

export type AttachOptions = {
	video: HTMLVideoElement;
	url: string;
	mode: PlaybackSession['mode'];
	/** Seconds into the title to start at. */
	startAt: number;
	/** Playback broke beyond recovery. */
	onfatal: (message: string) => void;
};

function attachNative(video: HTMLVideoElement, url: string, startAt: number): Engine {
	if (startAt > 0) {
		video.addEventListener('loadedmetadata', () => (video.currentTime = startAt), { once: true });
	}
	video.src = url;
	return {
		destroy() {
			video.removeAttribute('src');
			video.load();
		}
	};
}

/**
 * Plays a session's URL in the video element: the file itself for direct
 * play, otherwise HLS through hls.js (native HLS only where there's no MSE).
 */
export async function attach({
	video,
	url,
	mode,
	startAt,
	onfatal
}: AttachOptions): Promise<Engine> {
	if (mode === 'direct') return attachNative(video, url, startAt);

	const { default: Hls } = await import('hls.js');
	if (!Hls.isSupported()) {
		if (video.canPlayType('application/vnd.apple.mpegurl')) {
			return attachNative(video, url, startAt);
		}
		throw new Error("This browser can't play HLS video.");
	}

	// The server cuts a segment after a seek on first request; that can take a
	// few seconds on a slow disk, so wait for it rather than retrying early.
	const segmentPolicy = {
		default: {
			maxTimeToFirstByteMs: 60_000,
			maxLoadTimeMs: 120_000,
			timeoutRetry: { maxNumRetry: 2, retryDelayMs: 0, maxRetryDelayMs: 0 },
			errorRetry: { maxNumRetry: 3, retryDelayMs: 1_000, maxRetryDelayMs: 8_000 }
		}
	};
	const hls = new Hls({
		startPosition: startAt,
		maxBufferLength: 45,
		maxMaxBufferLength: 120,
		backBufferLength: 30,
		fragLoadPolicy: segmentPolicy,
		// Embedded CEA-608 captions would appear as surprise native subtitles.
		enableCEA708Captions: false
	});
	let recoveredAt = 0;
	hls.on(Hls.Events.ERROR, (_event, data) => {
		if (!data.fatal) return;
		if (data.type === Hls.ErrorTypes.MEDIA_ERROR && performance.now() - recoveredAt > 10_000) {
			recoveredAt = performance.now();
			hls.recoverMediaError();
			return;
		}
		const status = data.response?.code;
		if (status === 404 || status === 410) {
			onfatal('The playback session ended. Start it again to keep watching.');
		} else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
			onfatal(`The browser couldn't decode this video (${data.details}).`);
		} else {
			onfatal(
				`Lost the connection to the server (${data.details}${status ? `, HTTP ${status}` : ''}).`
			);
		}
	});
	hls.loadSource(url);
	hls.attachMedia(video);
	return { destroy: () => hls.destroy() };
}
