"""Unit tests for the WhatsApp group features"""

import pytest
from wtforms.validators import ValidationError

from collectives.forms.validators import WhatsAppLinkValidator
from collectives.models import Event, db
from collectives.utils.numbers import to_e164, to_whatsapp_number


@pytest.mark.parametrize(
    "phone,expected",
    [
        ("06 12 34 56 78", "+33612345678"),
        ("0612345678", "+33612345678"),
        ("+33612345678", "+33612345678"),
        ("0033612345678", "+33612345678"),
        ("+41 22 767 41 11", "+41227674111"),
        ("", None),
        (None, None),
        ("123", None),
        ("pas un numéro", None),
    ],
)
def test_to_e164(phone, expected):
    """Test conversion of phone numbers to the international format"""
    assert to_e164(phone) == expected


def test_to_whatsapp_number():
    """Test that wa.me numbers carry no '+' nor separator"""
    assert to_whatsapp_number("06 12 34 56 78") == "33612345678"
    assert to_whatsapp_number("+41 22 767 41 11") == "41227674111"
    assert to_whatsapp_number("123") is None


class FakeField:
    """Minimal stand-in for a WTForms field, holding only its data"""

    def __init__(self, data):
        self.data = data


@pytest.mark.parametrize(
    "link",
    [
        "https://chat.whatsapp.com/AbCdEfGh123456",
        "https://chat.whatsapp.com/AbCdEfGh123456?mode=ac_t",
        "  https://chat.whatsapp.com/AbCdEfGh123456  ",
        "",
        None,
    ],
)
def test_whatsapp_link_validator_accepts(link):
    """Test that group invitation links, and empty values, are accepted"""
    WhatsAppLinkValidator()(None, FakeField(link))


@pytest.mark.parametrize(
    "link",
    [
        "https://wa.me/33612345678",
        "http://chat.whatsapp.com/AbCdEfGh123456",
        "https://chat.whatsapp.com/short",
        "https://chat.whatsapp.example.com/AbCdEfGh123456",
        "javascript:alert(1)",
    ],
)
def test_whatsapp_link_validator_rejects(link):
    """Test that anything but a group invitation link is rejected.

    A ``wa.me`` link would expose the leader own phone number to every participant.
    """
    with pytest.raises(ValidationError):
        WhatsAppLinkValidator()(None, FakeField(link))


def test_international_phone_numbers(event1_with_reg: Event, user1, user5):
    """Test the contact list used to create the event WhatsApp group"""

    numbers = event1_with_reg.international_phone_numbers()
    assert len(numbers) == 4
    assert all(number.startswith("+33") for number in numbers)
    assert to_e164(user1.phone) in numbers

    # A user without a usable phone number is skipped rather than breaking the list
    user1.phone = "n/a"
    db.session.commit()
    assert to_e164(user1.phone) is None
    assert len(event1_with_reg.international_phone_numbers()) == 3

    # Users without an active registration are not part of the group
    assert to_e164(user5.phone) not in event1_with_reg.international_phone_numbers()
