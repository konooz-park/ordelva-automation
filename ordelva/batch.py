"""Legacy entry point kept for Windows Task Scheduler: runs the same daily pipeline as the cloud."""


def run():
    from .pipeline import daily
    daily()
