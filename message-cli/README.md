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
  --wait                Wait for acknowledgment instead of fire-and-forget
  --timeout INTEGER     Timeout in seconds for --wait (0 = no timeout, default from config)
```

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
│   └── setup/
└── common -> ../common  # Shared utilities symlink
```

## Configuration Reference

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `bot_token` | string | required | Telegram bot token from @BotFather |
| `allowed_chat_id` | int/null | null | Restrict to specific chat ID (null = any) |
| `default_timeout` | int | 300 | Default timeout in seconds (0 = no timeout) |
| `default_wait_for_ack` | bool | false | Wait for ack on alerts by default |

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
