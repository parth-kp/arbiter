__version__ = "0.1.0"


def evaluate(*args, **kwargs):
    from arbiter.api import evaluate as _evaluate

    return _evaluate(*args, **kwargs)
