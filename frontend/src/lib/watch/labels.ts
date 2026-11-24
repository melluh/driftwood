import type { RankedRelease } from '#lib/api/client.ts';
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
