from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    from commands.batch_transcript.register import register as _register

    return _register(plugin_manifests)
