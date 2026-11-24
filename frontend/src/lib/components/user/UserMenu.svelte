<script lang="ts">
	import type { CurrentUser } from '#lib/api/client.ts';
	import { logout } from '#lib/auth/session.ts';
	import Icon from '../ui/Icon.svelte';
	import UserAvatar from './UserAvatar.svelte';

	let { user }: { user: CurrentUser } = $props();

	const menuId = $props.id();
	let open = $state(false);
	let loggingOut = $state(false);

	async function handleLogout() {
		loggingOut = true;
		await logout();
	}
</script>

<!-- A native popover: light dismiss, Escape and focus return come for free. -->
<button
	type="button"
	class="trigger"
	popovertarget={menuId}
	aria-expanded={open}
	aria-label="Account: {user.name}"
	title={user.name}
>
	<UserAvatar {user} />
</button>

<div
	id={menuId}
	class="menu"
	popover="auto"
	ontoggle={(event) => (open = event.newState === 'open')}
>
	<div class="profile">
		<UserAvatar {user} size="2.75rem" />
		<div class="identity">
			<p class="name truncate">{user.name}</p>
			{#if user.email}<p class="email truncate">{user.email}</p>{/if}
		</div>
	</div>

	<ul role="list">
		<li>
			<button type="button" class="item" disabled title="Coming soon">
				<Icon name="settings" />
				<span>User settings</span>
				<span class="soon">Soon</span>
			</button>
		</li>
		<li>
			<button type="button" class="item" onclick={handleLogout} disabled={loggingOut}>
				<Icon name="log-out" />
				<span>{loggingOut ? 'Logging out…' : 'Log out'}</span>
			</button>
		</li>
	</ul>
</div>

<style>
	.trigger {
		display: inline-grid;
		place-items: center;
		padding: 0;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-full);
		background: var(--color-surface);
		cursor: pointer;
		transition:
			border-color var(--duration-fast),
			box-shadow var(--duration-fast);
	}

	.trigger:hover,
	.trigger[aria-expanded='true'] {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 3px var(--color-accent-soft);
	}

	/* Popovers live in the top layer; pin it under the header's right edge. */
	.menu {
		position: fixed;
		inset: auto;
		top: calc(var(--header-height) - var(--space-1));
		right: var(--content-inset);
		width: min(18rem, calc(100vw - 2 * var(--page-gutter)));
		margin: 0;
		padding: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface-raised);
		color: var(--color-text);
		box-shadow: var(--shadow-lg);
		transform-origin: top right;
		opacity: 0;
		transform: translateY(-0.25rem) scale(0.97);
		transition:
			opacity var(--duration-fast) var(--ease-out),
			transform var(--duration-fast) var(--ease-out),
			overlay var(--duration-fast) allow-discrete,
			display var(--duration-fast) allow-discrete;
	}

	.menu:popover-open {
		opacity: 1;
		transform: none;
	}

	@starting-style {
		.menu:popover-open {
			opacity: 0;
			transform: translateY(-0.25rem) scale(0.97);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.menu {
			transition: none;
		}
	}

	.profile {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-2) var(--space-3);
		margin-bottom: var(--space-1);
		border-bottom: 1px solid var(--color-border);
	}

	.identity {
		min-width: 0;
	}

	.name {
		font-weight: 600;
	}

	.email {
		font-size: var(--text-sm);
		color: var(--color-text-muted);
	}

	ul {
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		padding: var(--space-2) var(--space-3);
		border: none;
		border-radius: var(--radius-md);
		background: none;
		text-align: left;
		cursor: pointer;
		transition: background var(--duration-fast);
	}

	.item:hover:not(:disabled),
	.item:focus-visible {
		background: var(--color-surface-hover);
	}

	.item:disabled {
		cursor: default;
		color: var(--color-text-faint);
	}

	.soon {
		margin-left: auto;
		padding: 0 var(--space-2);
		border-radius: var(--radius-full);
		background: var(--color-surface-hover);
		font-size: var(--text-xs);
		color: var(--color-text-muted);
	}
</style>
