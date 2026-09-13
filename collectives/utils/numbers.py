"""Module for formatting number and currencies"""

import math

import babel
import phonenumbers


def format_currency(amount):
    """
    Formats a decimal amount in euros following the french locale

    :param amount: The amount to be formatted
    :type amount: :py:class:`decimal.Decimal`
    :return: A string representing the amount in french locale, like "1,345.67 €"
    :rtype: string
    """
    return babel.numbers.format_currency(amount, "EUR", "#,##0.00 ¤", locale="fr_FR")


def format_bytes(size):
    """
    Formats a size in bytes to human-readable units

    :param size: The size in bytes
    :type size: int
    :return: A string representing the amount in human-readable form, e.g. ko, Go
    :rtype: string
    """
    if size == 0:
        return "0 B"
    names = ("B", "kB", "MB", "GB")
    index = math.floor(math.log2(size) / 10)
    unit = 1 << (10 * index)
    return f"{round(size / unit, 1)} {names[index]}"


def format_phones(phone_str: str) -> str:
    """:returns: a regurlarly formed phone number, with proper spacing.
    :param phone: A phone number
    """

    if not check_phone(phone_str):
        return str(phone_str)

    phone = phonenumbers.parse(phone_str, "FR")

    formats = phonenumbers.PhoneNumberFormat
    if phone.country_code != 33:
        return phonenumbers.format_number(phone, formats.INTERNATIONAL)

    return phonenumbers.format_number(phone, formats.NATIONAL)


def check_phone(number: str) -> bool:
    """:returns: True if the number if a real phone number"""
    try:
        number = phonenumbers.parse(number, "FR")
        if not phonenumbers.is_possible_number(number):
            return False

        return True

    except phonenumbers.NumberParseException:
        return False


def to_e164(phone_str: str) -> str | None:
    """Converts a phone number to its international E.164 representation.

    :param phone_str: A phone number, possibly in french national format
    :returns: The number as ``+33XXXXXXXXX``, or ``None`` if it cannot be parsed
    """

    if not phone_str:
        return None

    try:
        phone = phonenumbers.parse(phone_str, "FR")
    except phonenumbers.NumberParseException:
        return None

    if not phonenumbers.is_valid_number(phone):
        return None

    return phonenumbers.format_number(phone, phonenumbers.PhoneNumberFormat.E164)


def to_whatsapp_number(phone_str: str) -> str | None:
    """Converts a phone number to the format expected in ``wa.me`` links.

    WhatsApp click-to-chat links expect the international number without the
    leading ``+`` nor any separator.

    :param phone_str: A phone number, possibly in french national format
    :returns: The number as ``33XXXXXXXXX``, or ``None`` if it cannot be parsed
    """

    number = to_e164(phone_str)
    return None if number is None else number.lstrip("+")
