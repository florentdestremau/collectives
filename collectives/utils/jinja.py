"""Helpers functions that are make available to Jinja.

This module should not contains other functions than :py:func:`helpers_processors`
"""
import inspect
import html

from . import time as custom_time
from . import numbers
from .misc import isMobileUser
from .. import models
from ..routes.auth import get_bad_phone_message
from .render_markdown import markdown_to_html


def helpers_processor():
    """Function used by Jinja to access utils fonctions.

    :return: Dictionnary of :py:mod:`collectives.utils.time` functions.
    :rtype: dict(Function)
    """
    helper_functions = dict(inspect.getmembers(custom_time, inspect.isfunction))
    helper_functions.update(dict(inspect.getmembers(numbers, inspect.isfunction)))
    helper_functions["isMobileUser"] = isMobileUser
    helper_functions["version_link"] = version_link
    helper_functions["models"] = models
    helper_functions["get_bad_phone_message"] = get_bad_phone_message
    helper_functions["Configuration"] = models.Configuration
    helper_functions["markdown_to_html"] = markdown_to_html

    return helper_functions


def version_link(version):
    """Convert a git version to an http link.

    Meanwhile, it also sanitize the version since it will be included as html in the
    page.

    :param string version: The version as a ``git describe`` format.
    :return: HTML string a the version wih its links.
    :rtype: string
    """
    parts = html.escape(version, quote=True).split("-")

    if len(parts) >= 3:
        parts[
            2
        ] = f'<a href="https://github.com/Club-Alpin-Annecy/collectives/commit/{parts[2][1:]}">{parts[2]}</a>'
    parts[
        0
    ] = f'<a href="https://github.com/Club-Alpin-Annecy/collectives/releases/tag/{parts[0]}">{parts[0]}</a>'

    return "-".join(parts)
