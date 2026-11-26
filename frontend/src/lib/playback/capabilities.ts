import type { PlaybackCapabilities } from '#lib/api/client.ts';

type MediaSourceLike = { isTypeSupported(type: string): boolean };

function mediaSource(): MediaSourceLike | null {
	const scope = globalThis as unknown as {
		ManagedMediaSource?: MediaSourceLike;
		MediaSource?: MediaSourceLike;
	};
	// iPhone Safari only has ManagedMediaSource, which hls.js also uses.
	return scope.ManagedMediaSource ?? scope.MediaSource ?? null;
}

/**
 * What the browser can decode through Media Source Extensions, which is how
 * hls.js plays the library's HLS streams. Browsers without MSE fall back to
 * native HLS, which doesn't take HEVC in MPEG-TS, so they report no HEVC.
 */
export function detectCapabilities(): PlaybackCapabilities {
	const source = mediaSource();
	const supports = (codecs: string) => {
		try {
			return source?.isTypeSupported(`video/mp4; codecs="${codecs}"`) ?? false;
		} catch {
			return false;
		}
	};
	return {
		hevc: supports('hvc1.1.6.L120.90'),
		hevc_main10: supports('hvc1.2.4.L150.90')
	};
}
