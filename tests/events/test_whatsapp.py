"""Tests for the WhatsApp group blocks of the event page."""

from collectives.models import Event, db
from tests import utils

# pylint: disable=unused-import
from tests.mock.config import configuration_override

GROUP_LINK = "https://chat.whatsapp.com/AbCdEfGh123456"


def test_group_link_hidden_when_disabled(
    user1_client, event1_with_reg: Event, configuration_override
):
    """Test that nothing is shown when the feature is turned off for the instance"""

    configuration_override("WHATSAPP_ENABLED", False)
    event1_with_reg.whatsapp_link = GROUP_LINK
    db.session.commit()

    response = user1_client.get(
        f"/collectives/{event1_with_reg.id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert GROUP_LINK not in response.text


def test_group_link_shown_to_registered_user(
    user1_client, event1_with_reg: Event, configuration_override
):
    """Test that a registered user is offered to join the group"""

    configuration_override("WHATSAPP_ENABLED", True)
    event1_with_reg.whatsapp_link = GROUP_LINK
    db.session.commit()

    response = user1_client.get(
        f"/collectives/{event1_with_reg.id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert GROUP_LINK in response.text


def test_group_link_hidden_from_other_users(
    user3_client, event1: Event, configuration_override
):
    """Test that a user who is not registered does not get the invitation link"""

    configuration_override("WHATSAPP_ENABLED", True)
    event1.whatsapp_link = GROUP_LINK
    db.session.commit()

    response = user3_client.get(f"/collectives/{event1.id}", follow_redirects=True)
    assert response.status_code == 200
    assert GROUP_LINK not in response.text


def test_group_link_hidden_from_waiting_list(
    user3_client, event1_with_reg_waiting_list: Event, configuration_override
):
    """Test that a user on the waiting list is not invited to the group yet"""

    configuration_override("WHATSAPP_ENABLED", True)
    event1_with_reg_waiting_list.whatsapp_link = GROUP_LINK
    db.session.commit()

    response = user3_client.get(
        f"/collectives/{event1_with_reg_waiting_list.id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert "liste d'attente" in response.text.lower()
    assert GROUP_LINK not in response.text


def test_leader_whatsapp_block(
    leader_client, event1_with_reg: Event, user1, configuration_override
):
    """Test the leader block: invitation link, contact list and per-participant links"""

    configuration_override("WHATSAPP_ENABLED", True)
    event1_with_reg.whatsapp_link = GROUP_LINK
    db.session.commit()

    response = leader_client.get(
        f"/collectives/{event1_with_reg.id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert GROUP_LINK in response.text
    # Contact list, in international format
    assert "+33601020001" in response.text
    # Per-participant click-to-chat link
    assert "https://wa.me/33601020001?text=" in response.text
    assert user1.full_name() in response.text


def test_leader_whatsapp_block_without_group(
    leader_client, event1_with_reg: Event, configuration_override
):
    """Test that the leader is told how to create the group when none is set"""

    configuration_override("WHATSAPP_ENABLED", True)

    response = leader_client.get(
        f"/collectives/{event1_with_reg.id}", follow_redirects=True
    )
    assert response.status_code == 200
    assert "Aucun groupe associé à cette collective" in response.text
    # The contact list is still offered, it is what the group is built from
    assert "+33601020001" in response.text


def test_whatsapp_link_edition(leader_client, event: Event, configuration_override):
    """Test that a leader can set the group link, and that bogus links are refused"""

    configuration_override("WHATSAPP_ENABLED", True)

    response = leader_client.get(f"/collectives/{event.id}/edit")
    assert response.status_code == 200
    assert "whatsapp_link" in response.text

    data = utils.load_data_from_form(response.text, "form_edit_event")
    data["whatsapp_link"] = f"  {GROUP_LINK}  "
    response = leader_client.post(
        f"/collectives/{event.id}/edit", data=data, follow_redirects=True
    )
    assert response.status_code == 200
    # Surrounding whitespace is stripped before storing
    assert db.session.get(Event, event.id).whatsapp_link == GROUP_LINK

    # A wa.me link would leak the leader own phone number, it must be refused
    data["whatsapp_link"] = "https://wa.me/33601020001"
    response = leader_client.post(f"/collectives/{event.id}/edit", data=data)
    assert response.status_code == 200
    assert len(utils.get_form_errors(response.text)) == 1
    assert db.session.get(Event, event.id).whatsapp_link == GROUP_LINK
