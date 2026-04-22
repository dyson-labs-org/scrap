from sdr_devices import estimate_tx_power_str, format_power_dbm


def test_format_power_dbm_uses_expected_units():
    assert format_power_dbm(35) == "3.16 W (+35 dBm)"
    assert format_power_dbm(0) == "1 mW (+0 dBm)"
    assert format_power_dbm(-27) == "2 uW (-27 dBm)"
    assert format_power_dbm(-65) == "0.32 nW (-65 dBm)"


def test_format_power_dbm_optional_fields():
    got = format_power_dbm(-27, freq_mhz=915, approximate=True)
    assert got == "~2 uW (-27 dBm) at 915 MHz"


def test_estimate_tx_power_str_hides_gain_jargon():
    assert estimate_tx_power_str(3, False, 915) == "~2 uW (-27 dBm) at 915 MHz"
    assert estimate_tx_power_str(40, True, 2437) == "~251 mW (+24 dBm) at 2437 MHz"
