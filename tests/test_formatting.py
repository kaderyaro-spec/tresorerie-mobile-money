"""Filtres d'affichage et statut d'abonnement (fonctions pures)."""
import datetime

from conftest import appmod


def test_fmt_thousands():
    assert appmod.fmt(5000) == "5 000"
    assert appmod.fmt(1500000) == "1 500 000"
    assert appmod.fmt(0) == "0"


def test_fmt_phone():
    assert appmod.fmt_phone("0710101010") == "07 10 10 10 10"
    assert appmod.fmt_phone("2250710101010") == "07 10 10 10 10"   # indicatif retiré
    assert appmod.fmt_phone("") == ""


def test_subscription_states():
    fut = (datetime.date.today() + datetime.timedelta(days=10)).strftime("%Y-%m-%d")
    past = (datetime.date.today() - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    assert appmod.subscription_info({"subscription_until": None})["state"] == "trial"
    assert appmod.subscription_info({"subscription_until": fut})["state"] == "active"
    assert appmod.subscription_info({"subscription_until": past})["state"] == "expired"
