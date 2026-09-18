# Global Cloud Key Control Design

Date: 2026-09-18

## Goal

Allow an administrator to set, replace, and one-click remove the shared RunningHub key from Admin without exposing it or editing server files.

## Storage and precedence

- Store the admin-managed global key encrypted in server-side runtime state, alongside a persisted enabled/disabled override.
- A configured admin-managed key takes precedence over the legacy `RUNNINGHUB_API_KEY` environment value.
- Removing the global key writes a disabled override, preventing an old environment value from becoming active again after restart.
- User-specific private keys continue to take precedence over the global key.

## Admin UI

- Add a Global Cloud key section above the Users list.
- Show only a masked status and effective concurrency; never return the raw key to the browser.
- Provide Set/Replace global key, configurable concurrency, and Remove global key actions.
- Remove requires an in-browser confirmation.

## Authorization and behavior

- Only admins may read global-key status or set/remove it.
- Removing the global key does not delete user private keys or alter Cloud workflow allowlists.
- Existing Cloud jobs keep their encrypted job key and can complete/cancel normally; subsequent jobs without a private key require a new global key.

## Validation

- Test global-key precedence, disabled override persistence behavior, admin authorization, encrypted storage, and removal behavior.
- Run focused Cloud tests, Python compilation, and JavaScript syntax checks.
