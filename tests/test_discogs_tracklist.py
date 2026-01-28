from __future__ import annotations

from services.discogs_service import format_tracklist


def test_discogs_tracklist_formatting():
    tracklist = [
        {"position": "A1", "title": "Intro", "duration": "1:00"},
        {"position": "A2", "title": "Song", "duration": "3:30"},
        {"position": "B1", "title": "Outro", "duration": "2:00"},
    ]
    html = format_tracklist(tracklist)
    assert "<h3>Tracklist</h3>" in html
    assert "<ol>" in html
    assert "<li>A1 Intro (1:00)</li>" in html
    assert "<li>A2 Song (3:30)</li>" in html
    assert "<li>B1 Outro (2:00)</li>" in html
