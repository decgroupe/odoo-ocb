# -*- coding: utf-8 -*-

import sys
import traceback
import threading


def print_stacktrace(logger):
    frames = sys._current_frames()
    thread_ident = threading.current_thread().ident
    if thread_ident in frames:
        callstack = traceback.format_stack(
            frames[thread_ident]
        )
        logger.error('\n' + ''.join(callstack[:-2]))
