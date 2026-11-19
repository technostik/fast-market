# message-agent

Alert and interact with users via messaging platforms (e.g., Telegram).

## Installation

```bash
cd message-agent
pip install -e .
```

## Configuration

The first time you run `message-agent`, you'll need to configure your Telegram bot:

```bash
message setup --plugin telegram
```

Or manually create `~/.local/share/fast-market/config/message-agent.yaml`:

```yaml
telegram:
  bot_token: "123456789:ABCdefGHIjklMNOpqrsTUVwxyz"
  allowed_chat_id: null        # null = accept from any chat
  default_timeout: 300         # seconds (0 = no timeout)
  default_wait_for_ack: false  # wait for ack by default on alerts
```

### Getting a Telegram Bot Token

1. Open Telegram and search for @BotFather
2. Send `/newbot` command
3. Follow the prompts to name your bot
4. Copy the bot token (starts with `123456789:ABCdef...`)

## Usage

### Ask a Question

Send a message and wait for the user's reply:

```bash
message ask "Do you want to continue?"
message ask "What is your name?" --timeout 60
message ask "Select an option" --format json
```

### Send an Alert

Fire-and-forget notification:

```bash
message alert "Build complete!"
message alert "Deploy finished" --format json
```

Alert with acknowledgment wait:

```bash
message alert "Deployment started" --wait
message alert "Please confirm" --wait --timeout 120
```

## Commands

### ask

Send a message and wait for a reply.

```
Arguments:
  MESSAGE    Message to send to user

Options:
  --source [telegram]  Messaging platform to use
  --format [json|text] Output format
  --target TEXT        Named target id or raw chat id (default: telegram.default_target)
  --timeout INTEGER    Timeout in seconds (0 = no timeout, default from config)
```

### alert

Send a notification message.

```
Arguments:
  MESSAGE    Message to send to user

Options:
  --source [telegram]   Messaging platform to use
  --format [json|text]  Output format
  --target TEXT         Named target id or raw chat id (default: telegram.default_target)
  --wait                Wait for acknowledgment instead of fire-and-forget
  --timeout INTEGER     Timeout in seconds for --wait (0 = no timeout, default from config)
```

### targets

Manage the named Telegram targets stored in this profile's config.

```bash
message targets list
# The id is resolved from a public @username or t.me link:
message targets add technostik --username @technostik
message targets add technostik --username https://t.me/technostik
# Write to another profile without switching the active one:
message targets add technostik --username @technostik --profile technostik_tv
# Or add a known numeric id directly:
message targets add joriel --chat-id 255925597 --label "Johann" --type private
message targets default technostik      # used when --target is omitted
message targets discover                # one-shot scan of pending updates
message targets discover --chat @technostik   # resolve public channels/links
message targets discover --wait 120     # listen for a fresh post (private channels)
message targets discover --dry-run      # preview without writing
message targets remove technostik
```

Discovery walks around a Bot API limitation: there is no "list my chats" call.
Three paths exist:

1. **Public channel or group by username/link** — `discover --chat @name` (or a
   `t.me` link) calls `getChat` and stores the numeric id. No prior post needed.
2. **New post in a channel** — the bot only receives channel posts when it is an
   **administrator**. Add it as admin, post once, then run
   `discover --wait 120`; the command listens for the new update while it runs.
   `discover` never confirms the update offset, so it does not consume updates.
3. **Known numeric id** — add it with `--chat-id`. To find it, forward a channel
   post to `@RawDataBot` (or `@userinfobot`), or open the channel on
   `web.telegram.org`: the id (`-100…`) is in the URL.

Telegram keeps pending updates for about 24 hours and deletes them once an
offset is confirmed (for example by a previous `message ask`). A private channel
with no pending update cannot be enumerated by the Bot API; posting again and
using `--wait` is the reliable path.

### setup

Interactive wizard for plugin configuration.

```
Options:
  --plugin [telegram]  Plugin to configure
```

## Architecture

```
message-agent/
├── message_entry/       # CLI entry point
├── cli/                 # Click main group
├── core/                # Config and models
├── plugins/             # Platform integrations
│   └── telegram/        # Telegram bot plugin
├── commands/            # CLI commands
│   ├── ask/
│   ├── alert/
│   ├── targets/         # Named target management + discovery
│   └── setup/
└── common -> ../common  # Shared utilities symlink
```

## Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bot_token` | string | required | Telegram bot token from @BotFather |
| `allowed_chat_id` | int/null | null | Legacy single-chat fallback (null = any) |
| `default_target` | string | null | Target id used when `--target` is omitted |
| `targets` | map | {} | Named targets: `id: {chat_id, label?, type?}` |
| `default_timeout` | int | 300 | Default timeout in seconds (0 = no timeout) |
| `default_wait_for_ack` | bool | false | Wait for ack on alerts by default |

Resolution order for `--target`: explicit named id (or raw numeric chat id),
then `default_target`, then a target matching the legacy `allowed_chat_id`, then
the only configured target, then `allowed_chat_id` alone. Several targets with
no default is an error, so a typo can never broadcast to the wrong channel.

## Use Cases

### CI/CD Pipeline

```bash
# Wait for deployment approval
response=$(message ask "Deploy to production?" --timeout 600)
if [ "$response" = "yes" ]; then
  deploy_to_production
fi
```

### Long-running Task Notification

```bash
# Start backup
message alert "Backup started"

# ... run backup ...

# Notify completion
message alert "Backup complete!" --wait
```

### Interactive CLI

```bash
# Ask for confirmation
message ask "Delete all data?" --timeout 60
```
