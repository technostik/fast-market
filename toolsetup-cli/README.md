# toolsetup

Configure global settings and LLM providers for all fast-market CLI tools.

## Installation

```bash
pip install -e .
# or with all optional dependencies:
pip install -e .[all]
```

## Usage

### Interactive Setup Wizard

Run without arguments to launch the interactive configuration wizard:

```bash
toolsetup
```

This will guide you through:
- Adding/configuring LLM providers
- Setting a global default working directory

### Show Configuration

```bash
# Show all configuration
toolsetup --show

# Show config file paths
toolsetup --show-path
```

### LLM Provider Management

```bash
# List configured providers
toolsetup llm list

# Add a new provider
toolsetup llm add <provider>

# Remove a provider
toolsetup llm remove <provider>

# Set default provider
toolsetup llm set-default <provider>
```

Available providers: `anthropic`, `openai`, `openai-compatible`, `ollama`

### Working Directory

```bash
# Set global default working directory
toolsetup workdir /path/to/dir

# Show current working directory
toolsetup workdir

# Clean working directory (delete all files)
toolsetup clean-workdir

# Clean with confirmation skipped
toolsetup clean-workdir --force

# Clean including subdirectories and hidden files
toolsetup clean-workdir --all
```

## Shell Autocompletion

### Quick Setup

Generate and install shell completion for all fast-market CLI tools:

```bash
toolsetup autocomplete-configure
```

This will:
1. Generate completion scripts for: corpus, image, message, monitor, prompt, skill, task, tiktok, toolsetup, youtube
2. Save to `~/.config/fast-market/completions/fast-market.bash`
3. Print instructions to add to your shell config

### Shell Options

```bash
# For bash (default)
toolsetup autocomplete-configure --shell bash

# For zsh
toolsetup autocomplete-configure --shell zsh

# For fish
toolsetup autocomplete-configure --shell fish
```

### Enable Completions

After running `autocomplete-configure`, add this to your `~/.bashrc` (or `~/.zshrc` for zsh):

```bash
source ~/.config/fast-market/completions/fast-market.bash
```

Or for immediate effect in current shell:

```bash
source ~/.config/fast-market/completions/fast-market.bash
```

### Regenerate Completions

If you add new CLI tools or want to regenerate:

```bash
toolsetup autocomplete-configure --force
```

## Configuration Files

- Common config: `~/.config/fast-market/common/config.yaml`
- LLM config: `~/.config/fast-market/common/llm/config.yaml`
- Completions: `~/.config/fast-market/completions/`

## Available CLI Tools

After setup, you can use:
- `prompt` - Prompt management
- `task` - Task execution
- `skill` - Skill management
- `corpus` - Corpus indexing
- `youtube` - YouTube CLI
- `tiktok` - TikTok CLI
- `image` - Image generation
- `message` - Messaging (Telegram)
- `monitor` - Web monitoring
