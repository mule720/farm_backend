import graphene

from apps.accounts.schema import AccountQuery, AccountMutation
from apps.enterprises.schema import EnterpriseQuery, EnterpriseMutation
from apps.forms_engine.schema import FormsQuery, FormsMutation
from apps.kpis.schema import KPIQuery, KPIMutation
from apps.automation.schema import AutomationQuery, AutomationMutation
from apps.inventory.schema import InventoryQuery, InventoryMutation
from apps.production.schema import ProductionQuery, ProductionMutation
from apps.intelligence.schema import IntelligenceQuery, IntelligenceMutation
from apps.dashboard.schema import DashboardQuery, DashboardMutation
from apps.devices.schema import DevicesQuery, DevicesMutation
from apps.plans.schema import PlansQuery, PlansMutation
from apps.vision.schema import VisionQuery, VisionMutation
from apps.irrigation.schema import IrrigationQuery, IrrigationMutation
from apps.equipment.schema import EquipmentQuery, EquipmentMutation
from apps.tracking.schema import TrackingQuery, TrackingMutation
from apps.market.schema import MarketQuery, MarketMutation
from apps.weather.schema import WeatherQuery, WeatherMutation
from apps.sustainability.schema import SustainabilityQuery, SustainabilityMutation
from apps.financials.schema import FinancialsQuery, FinancialsMutation
from apps.greenhouse.schema import GreenhouseQuery, GreenhouseMutation
from apps.labor.schema import LaborQuery, LaborMutation
from apps.notifications.schema import NotificationQuery, NotificationMutation


class Query(
    AccountQuery,
    EnterpriseQuery,
    FormsQuery,
    KPIQuery,
    AutomationQuery,
    InventoryQuery,
    ProductionQuery,
    IntelligenceQuery,
    DashboardQuery,
    DevicesQuery,
    PlansQuery,
    VisionQuery,
    IrrigationQuery,
    EquipmentQuery,
    TrackingQuery,
    MarketQuery,
    WeatherQuery,
    SustainabilityQuery,
    FinancialsQuery,
    GreenhouseQuery,
    LaborQuery,
    NotificationQuery,
    graphene.ObjectType,
):
    pass


class Mutation(
    AccountMutation,
    EnterpriseMutation,
    FormsMutation,
    KPIMutation,
    AutomationMutation,
    InventoryMutation,
    ProductionMutation,
    IntelligenceMutation,
    DashboardMutation,
    DevicesMutation,
    PlansMutation,
    VisionMutation,
    IrrigationMutation,
    EquipmentMutation,
    TrackingMutation,
    MarketMutation,
    WeatherMutation,
    SustainabilityMutation,
    FinancialsMutation,
    GreenhouseMutation,
    LaborMutation,
    NotificationMutation,
    graphene.ObjectType,
):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)
