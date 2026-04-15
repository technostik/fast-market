from commands.base import CommandManifest


def register(plugin_manifests: dict) -> CommandManifest:
    from commands.batch_video_reply.register import register as _register

    return _register(plugin_manifests)
