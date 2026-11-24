import type { RankedRelease, SubtitleTrack } from '#lib/api/client.ts';
import { formatBytes } from '#lib/media/format.ts';

const SOURCES: Record<string, string> = {
	remux: 'Remux',
	'bluray-encode': 'Blu-ray',
	'web-dl': 'WEB-DL',
	webrip: 'WEBRip',
	hdtv: 'HDTV',
	dvd: 'DVD'
};

const CODECS: Record<string, string> = { h264: 'H.264', h265: 'HEVC', av1: 'AV1', xvid: 'XviD' };

const HDR: Record<string, string> = { dv: 'Dolby Vision', hdr10: 'HDR10', hdr10plus: 'HDR10+' };

/** Short quality tags for a release: `1080p`, `WEB-DL`, `HEVC`, `HDR10`. */
export function qualityTags(ranked: RankedRelease): string[] {
	const { resolution, source, codec, hdr_flags } = ranked.attributes;
	return [
		resolution,
		source ? (SOURCES[source] ?? source) : null,
		codec ? (CODECS[codec] ?? codec) : null,
		...hdr_flags.map((flag) => HDR[flag] ?? flag)
	].filter((tag): tag is string => !!tag);
}

/** `5.4 GB · 6.1 Mbps` */
export function sizeSummary(ranked: RankedRelease): string {
	const size = formatBytes(ranked.release.size) ?? 'Unknown size';
	return ranked.effective_mbps ? `${size} · ${ranked.effective_mbps.toFixed(1)} Mbps` : size;
}

/** `S01E01` */
export function episodeCode(season: number, episode: number): string {
	return `S${String(season).padStart(2, '0')}E${String(episode).padStart(2, '0')}`;
}

const SUBTITLE_FACTORS: Record<string, string> = {
	wanted: 'Has wanted subtitles',
	missing: 'No wanted subtitles',
	unknown: 'Subtitles unknown'
};

const LANGUAGE_NAMES = new Intl.DisplayNames(['en'], { type: 'language' });

/** `en` → `English`. */
export function languageName(code: string): string {
	if (code === 'und') return 'Untagged';
	try {
		return LANGUAGE_NAMES.of(code) ?? code;
	} catch {
		return code;
	}
}

function trackList(tracks: SubtitleTrack[]): string {
	return tracks
		.map((track) => `${languageName(track.language)}${track.forced ? ' (forced)' : ''}`)
		.join(', ');
}

export type SubtitleTone = 'good' | 'bad' | 'neutral';

/** What to say about a release's subtitles, given the wanted languages. */
export function subtitleSummary(
	ranked: RankedRelease,
	wanted: string[]
): { text: string; tone: SubtitleTone } | null {
	const listed = trackList(ranked.subtitles);
	switch (ranked.subtitle_status) {
		case 'wanted':
			return { text: listed, tone: 'good' };
		case 'missing': {
			const wantedNames = wanted.map(languageName).join(' or ');
			return { text: listed ? `No ${wantedNames} (only ${listed})` : 'None', tone: 'bad' };
		}
		case 'unknown':
			return { text: listed || "Unknown: no NFO, or it doesn't say", tone: 'neutral' };
		case 'not_checked':
			return { text: 'Not checked', tone: 'neutral' };
		default:
			return listed ? { text: listed, tone: 'neutral' } : null;
	}
}

/** `+25` / `−1000` */
export function formatPoints(points: number): string {
	return points < 0 ? `−${-points}` : `+${points}`;
}

/** Score factor names (`source:web-dl`) as readable labels. */
export function factorLabel(name: string): string {
	const [kind, value] = name.split(':', 2);
	switch (kind) {
		case 'source':
			return `Source: ${SOURCES[value] ?? value}`;
		case 'codec':
			return `Codec: ${CODECS[value] ?? value}`;
		case 'hdr':
			return `HDR: ${value === 'sdr' ? 'SDR' : value.replaceAll('_', ' + ').toUpperCase()}`;
		case 'subtitles':
			return SUBTITLE_FACTORS[value] ?? name;
		case 'freeleech':
			return 'Freeleech';
		case 'bitrate_fit':
			return 'Size close to target';
		case 'seeders':
			return 'Seeders';
		case 'audio':
			return 'Audio';
		case 'release_group_tier':
			return `Release group (tier ${value})`;
		default:
			return name;
	}
}
