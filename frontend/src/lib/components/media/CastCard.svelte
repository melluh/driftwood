<script lang="ts">
	import type { CastMember } from '#lib/api/client.ts';
	import TmdbImage from './TmdbImage.svelte';

	let { member }: { member: CastMember } = $props();
</script>

<a
	class="cast-card"
	href="https://www.themoviedb.org/person/{member.id}"
	target="_blank"
	rel="noopener noreferrer"
	title="{member.name} on TMDB"
>
	<div class="photo">
		<TmdbImage
			path={member.profile_path}
			kind="profile"
			alt={member.name}
			sizes="8rem"
			radius="md"
		/>
	</div>
	<h3>{member.name}</h3>
	{#if member.character}
		<p>{member.character}</p>
	{/if}
</a>

<style>
	.cast-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.cast-card:focus-visible {
		outline: none;
	}

	/* Same hover as the media cards: the photo lifts and gets an accent ring */
	.photo {
		border-radius: var(--radius-md);
		transition:
			transform var(--duration-slow) var(--ease-out),
			box-shadow var(--duration-fast);
	}

	.cast-card:hover .photo,
	.cast-card:focus-visible .photo {
		transform: translateY(-0.25rem) scale(1.03);
		box-shadow: 0 0 0 2px var(--color-accent);
	}

	h3 {
		margin-top: var(--space-1);
		font-size: var(--text-sm);
		font-weight: 600;
	}

	p {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
</style>
