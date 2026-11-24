<script lang="ts">
	import type { CastMember } from '#lib/api/client.ts';
	import TmdbImage from './TmdbImage.svelte';

	let { member }: { member: CastMember } = $props();
</script>

<article class="cast-card">
	<TmdbImage path={member.profile_path} kind="profile" alt={member.name} sizes="8rem" radius="md" />
	<h3>{member.name}</h3>
	{#if member.character}
		<p>{member.character}</p>
	{/if}
</article>

<style>
	.cast-card {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	h3 {
		margin-top: var(--space-1);
	}

	h3 {
		font-size: var(--text-sm);
		font-weight: 600;
	}

	p {
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
</style>
