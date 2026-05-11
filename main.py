#!/usr/bin/env python
"""Example exec module to test the Anker API for various methods or direct endpoint requests with various parameters related to solarbank devices."""

import importlib

import asyncio
import copy
from datetime import datetime
from google.cloud import datastore
from enum import Enum
import json
import math
import os
import re
import statistics
import logging
from pathlib import Path

from aiohttp import ClientSession
import aiohttp.web
from anker_solix_api import common
from anker_solix_api.api.api import AnkerSolixApi

from repos import HomeEnergyDailyExport, HomeEnergyDailyExportRepo

_LOGGER: logging.Logger = logging.getLogger(__name__)
_LOGGER.addHandler(logging.StreamHandler())
# _LOGGER.setLevel(logging.DEBUG)    # enable for detailed API output
CONSOLE: logging.Logger = common.CONSOLE

datastore_client = datastore.Client()
export_repo = HomeEnergyDailyExportRepo(datastore_client)


def _out(jsondata):
    CONSOLE.info(json.dumps(jsondata, default=str, indent=2))


class TouRate(Enum):
    SUPER_OFF_PEAK = "super_off_peak"
    MID_OFF_PEAK = "mid_off_peak"
    PEAK = "peak"


FLAT_PRICE_PER_KWH = 0.1338

RATE_COST_PER_KWH_LOOKUP = {
    TouRate.SUPER_OFF_PEAK: 0.0805,
    TouRate.MID_OFF_PEAK: 0.1409,
    TouRate.PEAK: 0.1610,
}


SUPER_OFF_PEAK_HOURS = [[0, 5]]
MID_OFF_PEAK_HOURS = [[6, 16], [21, 23]]
PEAK_HOURS = [[17, 20]]


RATE_BY_HOUR_LOOKUP = (
    {
        i: TouRate.SUPER_OFF_PEAK
        for rate_arr in SUPER_OFF_PEAK_HOURS
        for i in range(rate_arr[0], rate_arr[1] + 1)
    }
    | {
        i: TouRate.MID_OFF_PEAK
        for rate_arr in MID_OFF_PEAK_HOURS
        for i in range(rate_arr[0], rate_arr[1] + 1)
    }
    | {
        i: TouRate.PEAK
        for rate_arr in PEAK_HOURS
        for i in range(rate_arr[0], rate_arr[1] + 1)
    }
)

TIMING_PATTERN = re.compile(r"(?P<hour>\d{2}):(?P<minute>\d{2})")


async def get_cost(myapi, anker_data) -> float:
    cost_date = datetime.strptime(anker_data["date"], "%Y-%m-%d")

    stats = await myapi.powerpanelApi.energy_statistics(
        siteId=list(myapi.sites.keys())[0],
        rangeType="day",
        startDay=cost_date,
        endDay=cost_date,
        sourceType="grid",
    )
    _out(stats)

    results = {}
    for pwr in stats["power"]:
        match_time = TIMING_PATTERN.search(pwr["time"])
        hour = int(match_time.group("hour"))
        minute = int(match_time.group("minute"))
        hour = hour if minute > 0 else (hour + 23) % 24

        results.setdefault(hour, [])
        results[hour] += [
            float(info["value"]) for info in pwr["powerInfos"] if info["type"] == "grid"
        ]
    for [h, powers] in results.items():
        results[h] = round(statistics.fmean(powers), 2)

    total_cost = round(
        math.fsum(
            RATE_COST_PER_KWH_LOOKUP[RATE_BY_HOUR_LOOKUP[h]] * energy_delivered
            for [h, energy_delivered] in results.items()
        ),
        2,
    )

    return total_cost


async def update_repo(myapi, anker_data) -> HomeEnergyDailyExport:
    grid_to_battery = float(anker_data["grid_to_battery"])
    grid_to_home = float(anker_data["grid_to_home"])
    battery_to_home = float(anker_data["battery_to_home"])

    value_of_energy_consumed = (grid_to_home + battery_to_home) * FLAT_PRICE_PER_KWH
    cost_of_energy_consumed = await get_cost(myapi, anker_data)

    entity = HomeEnergyDailyExport(
        energy_date=anker_data["date"],
        grid_to_battery=grid_to_battery,
        grid_to_home=grid_to_home,
        battery_to_home=battery_to_home,
        solar_production=float(anker_data["solar_production"]),
        fixed_price_per_kwh=FLAT_PRICE_PER_KWH,
        value_of_energy_consumed=value_of_energy_consumed,
        super_off_peak_price_per_kwh=RATE_COST_PER_KWH_LOOKUP[TouRate.SUPER_OFF_PEAK],
        cost_of_energy_consumed=cost_of_energy_consumed,
    )

    export_repo.upsert(entity)

    return entity


async def update_trmnl(myapi) -> None:
    _system = list(myapi.sites.values())[0]

    if "energy_details" in _system and "last_period" in _system["energy_details"]:
        _out(_system["energy_details"]["last_period"])
        export = await update_repo(myapi, _system["energy_details"]["last_period"])
        trmnl_payload = copy.deepcopy(_system["energy_details"]["last_period"])
        trmnl_payload["total_saved"] = (
            export.value_of_energy_consumed - export.cost_of_energy_consumed
        )
        aggregation = export_repo.get_aggregation_stats()
        trmnl_payload["lifetime_total_saved"] = aggregation.total_saved
        trmnl_payload["solar_data"] = [
            [trmnl_payload["date"], trmnl_payload["solar_production"]]
        ]
        trmnl_payload["grid_data"] = [
            [trmnl_payload["date"], trmnl_payload["grid_import"]]
        ]
        payload = {
            "merge_variables": trmnl_payload,
            "merge_strategy": "stream",
            "stream_limit": 7,
        }
        headers = {"Content-Type": "application/json"}

        plugin_uuid = os.environ.get("TRML_PLUGIN_UUID")
        assert plugin_uuid is not None

        async with ClientSession() as session:
            async with session.post(
                f"https://usetrmnl.com/api/custom_plugins/{plugin_uuid}",
                headers=headers,
                json=payload,
            ) as response:
                print("Status:", response.status)
                data = await response.json()
                print("Response JSON:", data)


async def solix_sync(request):
    CONSOLE.info("Retrieving from Solix API:")
    async with ClientSession() as websession:

        myapi = AnkerSolixApi(
            common.user(),
            common.password(),
            common.country(),
            websession,
            _LOGGER,
        )

        await myapi.update_sites()
        await myapi.update_site_details()
        await myapi.update_device_energy()
        await update_trmnl(myapi)

    return aiohttp.web.Response(text="OK")


async def create_app() -> None:
    """Create the aiohttp session and run the example."""
    app = aiohttp.web.Application()
    app.router.add_get("/task/solix-sync", solix_sync)
    return app


# run async main
if __name__ == "__main__":
    try:
        aiohttp.web.run_app(create_app(), port=os.environ.get("PORT", 8080))
    except Exception as err:  # pylint: disable=broad-exception-caught  # noqa: BLE001
        CONSOLE.exception("%s: %s", type(err), err)
