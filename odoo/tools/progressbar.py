# -*- coding: utf-8 -*-

import sys
import inspect
from progressbar import bar


def caller_name(skip=2):
    """Get a name of a caller in the format module.class.method

       `skip` specifies how many levels of stack to skip while getting caller
       name. skip=1 means "who calls me", skip=2 "who calls my caller" etc.

       An empty string is returned if skipped levels exceed stack height
    """
    stack = inspect.stack()
    start = 0 + skip
    if len(stack) < start + 1:
        return ''
    parentframe = stack[start][0]

    name = []
    module = inspect.getmodule(parentframe)
    if module:
        name.append(module.__name__)
    # detect classname
    if 'self' in parentframe.f_locals:
        name.append(parentframe.f_locals['self'].__class__.__name__)
    codename = parentframe.f_code.co_name
    if codename != '<module>':  # top level usually
        name.append(codename)  # function or a method

    ## Avoid circular refs and frame leaks
    #  https://docs.python.org/2.7/library/inspect.html#the-interpreter-stack
    del parentframe, stack

    return ".".join(name)


def progressbar(
    iterator,
    min_value=0,
    max_value=None,
    widgets=None,
    prefix=None,
    suffix=None,
    **kwargs
):
    if len(iterator) <= 1:
        for result in iterator:
            yield result
    else:
        if suffix is None:
            prefix = '{}: '.format(caller_name())
            # curframe = inspect.currentframe()
            # calframe = inspect.getouterframes(curframe, 2)
            # prefix = calframe[1][3]
        pb = bar.ProgressBar(
            min_value=min_value,
            max_value=max_value,
            widgets=widgets,
            prefix=prefix,
            suffix=suffix,
            **kwargs
        )
        for result in pb(iterator):
            yield result
