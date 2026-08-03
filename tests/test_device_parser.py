"""Tests for the device status parser (operation mode selects).

parse_device_status extracts the controller operation modes (the i_x16 device
blocks with their i_x7 selects). These tests cover a valid single-controller
page and, importantly, the real-world failure mode where the Bayrol portal
returns HTML without any i_x16 blocks: parsing must degrade to an empty result
and log a warning, never raise.
"""
import logging

from custom_components.bayrol_cloud.client.device_parser import parse_device_status

# Minimal single-controller device page: one i_x16 device block followed by its
# i_item sibling containing the operation-mode select (i_x7).
SINGLE_DEVICE_HTML = """
<div>
  <div class="i_item item1_100"><div class="i_x16">Filter Pump</div></div>
  <div class="i_item item3_153">
    <select class="i_x7">
      <option value="0" selected>Off</option>
      <option value="1">Auto</option>
      <option value="2">On</option>
    </select>
  </div>
</div>
"""

# HTML shaped like the measurement overview (tab_box), which has no i_x16 blocks.
# This mirrors what the portal returned when device-status parsing broke.
NO_I_X16_HTML = (
    '<div><div class="tab_box stat_ok"><span>pH&nbsp;[pH]</span><h1>7.20</h1></div>'
    '<div class="tab_box stat_ok"><span>mV&nbsp;[mV]</span><h1>796</h1></div>'
    '<div class="tab_box stat_ok"><span>T1&nbsp;[°C]</span><h1>30.6</h1></div></div>'
)


def test_parse_device_status_single_controller():
    """A valid device block yields the operation mode with its selected value."""
    data = parse_device_status(SINGLE_DEVICE_HTML)

    assert "filter_pump" in data
    entry = data["filter_pump"]
    assert entry["name"] == "Filter Pump"
    assert entry["item_number"] == "item3_153"
    assert entry["current_value"] == 0
    assert entry["current_text"] == "Off"
    assert [opt["text"] for opt in entry["options"]] == ["Off", "Auto", "On"]


def test_parse_device_status_no_i_x16_returns_empty(caplog):
    """No i_x16 blocks -> empty dict plus a warning, never an exception."""
    caplog.set_level(logging.WARNING)

    data = parse_device_status(NO_I_X16_HTML)

    assert data == {}
    assert any(
        "No device divs" in record.message for record in caplog.records
    ), "expected a warning about missing device divs"


def test_parse_device_status_empty_html():
    """Empty input is handled gracefully."""
    assert parse_device_status("") == {}
