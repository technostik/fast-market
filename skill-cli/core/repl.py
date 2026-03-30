from __future__ import annotations

from typing import Callable

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.styles import Style


REPL_STYLE = Style.from_dict(
    {
        "prompt": "ansicyan bold",
        "option": "ansigreen",
        "default": "ansiyellow",
    }
)


def prompt_with_options(
    prompt_text: str,
    options: list[str],
    default: str | None = None,
) -> str:
    """Prompt user with a list of valid options.

    Args:
        prompt_text: The prompt text to display
        options: List of valid option letters (e.g., ["r", "a", "q"])
        default: Default option if user just presses Enter

    Returns:
        The selected option
    """
    completer = WordCompleter(options, ignore_case=True)

    while True:
        try:
            answer = (
                prompt(
                    prompt_text,
                    completer=completer,
                    style=REPL_STYLE,
                    default=default or "",
                )
                .strip()
                .lower()
            )

            if not answer and default:
                return default

            if answer in [opt.lower() for opt in options]:
                return answer

            print(f"Valid options: {', '.join(options)}")
        except KeyboardInterrupt:
            print()
            return "q"
        except EOFError:
            return "q"


def prompt_free_text(prompt_text: str) -> str:
    """Prompt user for free-form text input.

    Args:
        prompt_text: The prompt text to display

    Returns:
        The user's input
    """
    while True:
        try:
            answer = prompt(prompt_text, style=REPL_STYLE).strip()
            return answer
        except KeyboardInterrupt:
            print()
            return ""
        except EOFError:
            return ""


def prompt_confirm(prompt_text: str, default: bool = False) -> bool:
    """Prompt user for yes/no confirmation.

    Args:
        prompt_text: The prompt text to display
        default: Default value if user just presses Enter

    Returns:
        True if user confirmed, False otherwise
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    default_str = "y" if default else "n"

    while True:
        try:
            answer = prompt(prompt_text + suffix, style=REPL_STYLE).strip().lower()

            if not answer:
                return default

            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False

            print("Please answer y or n")
        except KeyboardInterrupt:
            print()
            return False
        except EOFError:
            return False
