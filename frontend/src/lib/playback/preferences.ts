import type { PlaybackAudioTrack, PlaybackSubtitleTrack } from '#lib/api/client.ts';

/** Per-browser player settings, remembered between titles. */
export type PlayerPreferences = {
	volume: number;
	muted: boolean;
	/** Language of the audio picked last; null for the file's default. */
	audioLanguage: string | null;
	/** Language of the subtitles picked last; `off` once they were turned off. */
	subtitleLanguage: string | null;
};

const KEY = 'driftwood.player';
const DEFAULTS: PlayerPreferences = {
	volume: 1,
	muted: false,
	audioLanguage: null,
	subtitleLanguage: null
};

export function loadPreferences(): PlayerPreferences {
	try {
		const stored = JSON.parse(localStorage.getItem(KEY) ?? '{}') as Partial<PlayerPreferences>;
		return { ...DEFAULTS, ...stored };
	} catch {
		return { ...DEFAULTS };
	}
}

export function savePreferences(change: Partial<PlayerPreferences>): void {
	try {
		localStorage.setItem(KEY, JSON.stringify({ ...loadPreferences(), ...change }));
	} catch {
		// Storage can be unavailable (private windows); the defaults still work.
	}
}

export function pickAudio(
	tracks: PlaybackAudioTrack[],
	preferences: PlayerPreferences
): PlaybackAudioTrack | null {
	return (
		tracks.find(
			(track) => preferences.audioLanguage && track.language === preferences.audioLanguage
		) ??
		tracks.find((track) => track.default) ??
		tracks[0] ??
		null
	);
}

/**
 * The subtitles to start with: the language picked last time, or else forced
 * subtitles (signs, foreign dialogue) in the audio's language.
 */
export function pickSubtitles(
	tracks: PlaybackSubtitleTrack[],
	audio: PlaybackAudioTrack | null,
	preferences: PlayerPreferences
): PlaybackSubtitleTrack | null {
	const wanted = preferences.subtitleLanguage;
	if (wanted && wanted !== 'off') {
		const matching = tracks.filter((track) => track.language === wanted && !track.forced);
		const chosen = matching.find((track) => !track.hearing_impaired) ?? matching[0];
		if (chosen) return chosen;
	}
	return (
		tracks.find(
			(track) =>
				track.forced && (!track.language || !audio?.language || track.language === audio.language)
		) ?? null
	);
}
