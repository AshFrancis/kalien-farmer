# Security

Kalien Farmer is a local tool designed to run on your own machine. It is not a networked service and has no authentication system. This document covers the security-relevant design decisions.

## Dashboard Network Binding

The dashboard HTTP server binds to `127.0.0.1` (localhost) by default. This means it is only accessible from the machine it runs on.

To expose the dashboard to other devices on your network (e.g., monitoring from your phone), use:

```bash
python3 kalien-farmer.py --host 0.0.0.0
```

**Only do this on trusted networks.** The dashboard has no authentication, no TLS, and no access controls. Anyone on the same network can:
- View all seed data and scores
- Start, stop, and pause the runner
- Add seeds to the queue
- Change settings (including the claimant address)

If you need remote access, use SSH port forwarding instead:

```bash
ssh -L 8420:localhost:8420 user@remote-machine
```

Then access `http://localhost:8420` on your local machine.

## No Authentication

The dashboard does not implement any form of authentication. All API endpoints are open. This is acceptable because:
- The dashboard is bound to localhost by default
- It is a single-user tool, not a multi-tenant service
- There are no destructive operations that cannot be reversed

## Claimant Address Handling

The Stellar claimant address is stored in plaintext in `tapes/settings.json`. This is a **public address** used for receiving rewards -- it is not a secret.

- No private keys or signing keys are ever handled by Kalien Farmer
- The claimant address is sent to the kalien.xyz API as a URL parameter during tape submission
- Changing the claimant address only affects future submissions

## No Secrets

Kalien Farmer does not handle, store, or transmit any secrets:
- No API keys
- No authentication tokens
- No private keys
- No passwords
- No cookies or sessions

## Tape Submission

Tape submission is a public API call to `https://kalien.xyz/api/proofs/jobs`. The call includes:
- The binary tape data (game inputs)
- The claimant address (public)
- The seed ID (public)

All communication with the kalien.xyz API uses HTTPS.

## Data on Disk

All data stored by Kalien Farmer is in the `tapes/` directory:
- Game tapes (binary files of game inputs)
- SQLite database (seed scores and status)
- JSON configuration files
- Text log files

None of this data is sensitive. The `tapes/` directory can be safely deleted, shared, or backed up without security concerns.

## Engine Binary

The engine (`engine/kalien`) is a compiled C++ binary that you build from source. It runs as a subprocess of the runner and:
- Reads a seed and parameters from command-line arguments
- Writes tape files and stdout output
- Has no network access
- Has no access to files outside its output directory
