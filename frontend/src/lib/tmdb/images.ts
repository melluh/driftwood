/**
 * TMDB image URLs. Images are served straight from TMDB's CDN; components
 * pass a `sizes` hint and get a `srcset` over TMDB's fixed widths, so the
 * browser downloads the smallest image that is sharp at the rendered size.
 */

const TMDB_IMAGE_BASE = 'https://image.tmdb.org/t/p';

/** `still`: an episode's frame grab. */
export type ImageKind = 'poster' | 'backdrop' | 'profile' | 'still';

/** TMDB's available widths per image kind (excluding `original`). */
const WIDTHS: Record<ImageKind, readonly number[]> = {
	poster: [92, 154, 185, 342, 500, 780],
	backdrop: [300, 780, 1280],
	profile: [45, 185],
	still: [92, 185, 300]
};

/** Intrinsic aspect ratio (width / height) per kind, for layout reservation. */
export const ASPECT_RATIO: Record<ImageKind, number> = {
	poster: 2 / 3,
	backdrop: 16 / 9,
	profile: 2 / 3,
	still: 16 / 9
};

export function tmdbImageUrl(path: string, width: number): string {
	return `${TMDB_IMAGE_BASE}/w${width}${path}`;
}

export function tmdbSrcset(path: string, kind: ImageKind): string {
	return WIDTHS[kind].map((width) => `${tmdbImageUrl(path, width)} ${width}w`).join(', ');
}

/** A sensible single-URL fallback (`src`) for browsers that ignore srcset. */
export function tmdbFallbackUrl(path: string, kind: ImageKind): string {
	const widths = WIDTHS[kind];
	return tmdbImageUrl(path, widths[Math.min(1, widths.length - 1)]);
}
