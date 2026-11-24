<script lang="ts">
	import type { CurrentUser } from '#lib/api/client.ts';

	let { user, size = '2.5rem' }: { user: CurrentUser; size?: string } = $props();

	let failedUrl = $state<string | null>(null);
	const showImage = $derived(!!user.avatar_url && failedUrl !== user.avatar_url);

	const initials = $derived(
		user.name
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((word) => word[0]?.toUpperCase())
			.join('') || '?'
	);
</script>

<span class="avatar" style:--size={size} aria-hidden="true">
	{#if showImage}
		<!-- no-referrer: some providers (e.g. Google) refuse hotlinked avatars otherwise -->
		<img
			src={user.avatar_url}
			alt=""
			referrerpolicy="no-referrer"
			onerror={() => (failedUrl = user.avatar_url)}
		/>
	{:else}
		{initials}
	{/if}
</span>

<style>
	.avatar {
		display: inline-grid;
		place-items: center;
		width: var(--size);
		height: var(--size);
		flex-shrink: 0;
		overflow: hidden;
		border-radius: var(--radius-full);
		background: var(--color-accent-soft);
		color: var(--color-accent-strong);
		font-size: calc(var(--size) * 0.38);
		font-weight: 600;
		letter-spacing: 0.02em;
		user-select: none;
	}

	img {
		width: 100%;
		height: 100%;
		object-fit: cover;
	}
</style>
