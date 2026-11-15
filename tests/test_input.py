import pytest
from osmnx._errors import InsufficientResponseError
from requests.exceptions import Timeout

from app.gis.input import DownloadError, OSMProvider


def test_empty_is_success(monkeypatch):
    def empty(*args, **kwargs):
        raise InsufficientResponseError(
            "No matching features. Check query location, tags, and log."
        )

    monkeypatch.setattr("app.gis.input.ox.features_from_bbox", empty)
    assert OSMProvider().fetch((33, 44, 33.01, 44.01)).empty


@pytest.mark.parametrize(
    "error", [Timeout("offline"), InsufficientResponseError("Invalid response")]
)
def test_network_error_is_not_empty(monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr("app.gis.input.ox.features_from_bbox", fail)
    with pytest.raises(DownloadError):
        OSMProvider().fetch((33, 44, 33.01, 44.01))
