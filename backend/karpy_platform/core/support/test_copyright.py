from datetime import datetime, timezone

from karpy_platform.core.support.copyright import with_current_year

NOW = datetime(2027, 1, 1, tzinfo=timezone.utc)


def test_saved_year_follows_the_calendar():
    assert with_current_year("Copyright 2026 Acme. All rights reserved.", NOW) == "Copyright 2027 Acme. All rights reserved."
    assert with_current_year("2026 Acme Payments", NOW) == "2027 Acme Payments"


def test_range_keeps_its_start_and_token_is_filled():
    assert with_current_year("© 2024–2026 Acme", NOW) == "© 2024–2027 Acme"
    assert with_current_year("Copyright {year} Acme", NOW) == "Copyright 2027 Acme"
    assert with_current_year("Acme", NOW) == "Acme"
