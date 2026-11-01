"""The "Mirror Try-On" menu item in base.html.

Builds a stand-in Flask app (like the other route tests) so importing the real
app.py — which opens the live databases — is never needed.
"""
import os

import pytest
from flask import Flask, render_template_string

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRYON = "https://shubham-nx-tryon.vercel.app"
PAGE = '{% extends "base.html" %}{% block content %}hi{% endblock %}'


def render(tryon_url, role):
    app = Flask(
        __name__,
        template_folder=os.path.join(ROOT, "templates"),
        static_folder=os.path.join(ROOT, "static"),
    )

    @app.context_processor
    def inject():
        return {
            "share_base_url": "",
            "tryon_url": tryon_url,
            "server_today": "2026-01-01",
            "sv": "1",
            "current_user": {
                "id": 1, "username": "u", "role": role,
                "is_admin": role == "admin",
                "is_staff": role == "staff",
                "is_tailor": role == "tailor",
            },
        }

    with app.test_request_context("/"):
        return render_template_string(PAGE)


@pytest.mark.parametrize("role", ["admin", "staff"])
def test_link_shown_and_opens_in_new_tab(role):
    html = render(TRYON, role)
    assert f'href="{TRYON}" target="_blank" rel="noopener"' in html
    assert "Mirror Try-On" in html      # sidebar
    assert "<span>Try-On</span>" in html  # mobile bottom nav


def test_link_hidden_from_tailor():
    assert TRYON not in render(TRYON, "tailor")


def test_link_hidden_when_url_blank():
    html = render("", "admin")
    assert "Mirror Try-On" not in html
    assert "<span>Try-On</span>" not in html
