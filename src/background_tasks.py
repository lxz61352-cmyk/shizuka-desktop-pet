"""Cancellable queue handoffs shared by background workers."""
import queue


def put_until_cancelled(target,item,cancelled):
    """A full consumer queue must not keep an obsolete producer blocked forever."""
    while not cancelled():
        try:
            target.put(item,timeout=.1)
            return True
        except queue.Full:
            continue
    return False
