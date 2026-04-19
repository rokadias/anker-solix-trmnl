from dataclasses import asdict, dataclass
from typing import Optional
from google.cloud import datastore


@dataclass
class HomeEnergyDailyExport:
    energy_date: str
    grid_to_battery: float
    grid_to_home: float
    battery_to_home: float
    solar_production: float
    fixed_price_per_kwh: float
    value_of_energy_consumed: float
    super_off_peak_price_per_kwh: float
    cost_of_energy_consumed: float

    @classmethod
    def from_entity(cls, entity: datastore.Entity) -> "HomeEnergyDailyExport":
        """Converts a Datastore Entity back into our typed dataclass."""

        return cls(
            energy_date=entity.key.name,
            grid_to_battery=entity.grid_to_battery,
            grid_to_home=entity.grid_to_home,
            battery_to_home=entity.battery_to_home,
            solar_production=entity.solar_production,
            fixed_price_per_kwh=entity.fixed_price_per_kwh,
            value_of_energy_consumed=entity.value_of_energy_consumed,
            super_off_peak_price_per_kwh=entity.super_off_peak_price_per_kwh,
            cost_of_energy_consumed=entity.cost_of_energy_consumed,
        )


@dataclass
class HomeEnergyDailyAggregation:
    total_value_of_energy_consumed: float
    total_cost_of_energy_consumed: float
    total_saved: float


class HomeEnergyDailyExportRepo:
    KIND = "HomeEnergyDailyExport"

    def __init__(self, client: datastore.Client):
        self.client = client

    def upsert(self, export: HomeEnergyDailyExport) -> None:
        """
        Creates or updates a daily export.
        Uses energy_date as the unique key.
        """

        key = self.client.key(self.KIND, export.energy_date)
        entity = datastore.Entity(key=key)

        entity.update(asdict(export))

        self.client.put(entity)

    def get(self, energy_date: str) -> Optional[HomeEnergyDailyExport]:
        """Retrives the export data by energy date"""
        key = self.client.key(self.KIND, energy_date)
        entity = self.client.get(key)

        if not entity:
            return None

        return HomeEnergyDailyExport.from_entity(entity)

    def get_aggregation_stats(self) -> HomeEnergyDailyAggregation:
        all_exports_query = self.client.query(kind=self.KIND)
        aggregation_query = self.client.aggregation_query(all_exports_query)

        results = {
            "total_value_of_energy_consumed": 0.0,
            "total_cost_of_energy_consumed": 0.0,
            "total_saved": 0.0,
        }
        aggregation_query.add_aggregations(
            [
                datastore.aggregation.SumAggregation(
                    property_ref="value_of_energy_consumed",
                    alias="total_value_of_energy_consumed",
                ),
                datastore.aggregation.SumAggregation(
                    property_ref="cost_of_energy_consumed",
                    alias="total_cost_of_energy_consumed",
                ),
            ]
        )

        query_result = aggregation_query.fetch()
        for result_page in query_result:
            for result in result_page:
                results["total_value_of_energy_consumed"] += result.get(
                    "total_value_of_energy_consumed"
                )
                results["total_cost_of_energy_consumed"] += result.get(
                    "total_cost_of_energy_consumed"
                )

        aggregation = HomeEnergyDailyAggregation(**results)
        aggregation.total_saved = (
            aggregation.total_value_of_energy_consumed
            - aggregation.total_cost_of_energy_consumed
        )

        return aggregation
