#!/usr/bin/env python
"""Example exec module to test the Anker API for various methods or direct endpoint requests with various parameters related to solarbank devices."""

import importlib

import asyncio
import copy
from datetime import datetime
import json
import os
import logging
from pathlib import Path

from aiohttp import ClientSession
import aiohttp.web
from anker_solix_api import common
from anker_solix_api.api.api import AnkerSolixApi

_LOGGER: logging.Logger = logging.getLogger(__name__)
_LOGGER.addHandler(logging.StreamHandler())
# _LOGGER.setLevel(logging.DEBUG)    # enable for detailed API output
CONSOLE: logging.Logger = common.CONSOLE


def _out(jsondata):
    CONSOLE.info(json.dumps(jsondata, indent=2))


FLAT_PRICE_PER_KWH = 0.1375


async def update_trmnl(myapi) -> None:
    _system = list(myapi.sites.values())[0]

    if "energy_details" in _system and "last_period" in _system["energy_details"]:
        _out(_system["energy_details"]["last_period"])
        trmnl_payload = copy.deepcopy(_system["energy_details"]["last_period"])
        costs = (
            float(trmnl_payload["grid_to_battery"])
            + float(trmnl_payload["grid_to_home"])
        ) * FLAT_PRICE_PER_KWH
        usage = (
            float(trmnl_payload["grid_to_home"])
            + float(trmnl_payload["battery_to_home"])
        ) * FLAT_PRICE_PER_KWH
        trmnl_payload["total_saved"] = usage - costs
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
