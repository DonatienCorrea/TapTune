def create_app():
    from .web import create_app as factory

    return factory()


__all__ = ["create_app"]
