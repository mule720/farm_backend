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
from apps.market.provider_schema import ProviderQuery, ProviderMutation
from apps.market.vendor_schema import VendorQuery, VendorMutation
from apps.weather.schema import WeatherQuery, WeatherMutation
from apps.sustainability.schema import SustainabilityQuery, SustainabilityMutation
from apps.financials.schema import FinancialsQuery, FinancialsMutation
from apps.greenhouse.schema import GreenhouseQuery, GreenhouseMutation
from apps.labor.schema import LaborQuery, LaborMutation
from apps.notifications.schema import NotificationQuery, NotificationMutation
from apps.video_calls.schema import VideoCallQuery, VideoCallMutation
from apps.integration_settings.schema import IntegrationSettingsQuery, IntegrationSettingsMutation
from apps.government.schema import GovernmentQuery, GovernmentMutation
from apps.extension.schema import ExtensionQuery, ExtensionMutation
from apps.partners.schema import PartnerQuery, PartnerMutation
from apps.market.export_schema import ExportQuery, ExportMutation
from apps.financials.credit_schema import CreditQuery, CreditMutation
from apps.accounts.team_schema import TeamQuery, TeamMutation
from apps.accounts.workspace_schema import WorkspaceQuery, WorkspaceMutation
from apps.financials.ledger_schema import LedgerQuery, LedgerMutation
from apps.sales.schema import SalesQuery, SalesMutation
from apps.inventory.stock_schema import StockQuery, StockMutation
from apps.government.ecosystem import EcosystemQuery, EcosystemMapQuery
from apps.partners.map_schema import ProgrammeMapQuery
from apps.partners.logframe import LogframeQuery, LogframeMutation


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
    ProviderQuery,
    VendorQuery,
    WeatherQuery,
    SustainabilityQuery,
    FinancialsQuery,
    GreenhouseQuery,
    LaborQuery,
    NotificationQuery,
    VideoCallQuery,
    IntegrationSettingsQuery,
    GovernmentQuery,
    ExtensionQuery,
    PartnerQuery,
    ExportQuery,
    CreditQuery,
    TeamQuery,
    WorkspaceQuery,
    LedgerQuery,
    SalesQuery,
    StockQuery,
    EcosystemQuery,
    EcosystemMapQuery,
    ProgrammeMapQuery,
    LogframeQuery,
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
    ProviderMutation,
    VendorMutation,
    WeatherMutation,
    SustainabilityMutation,
    FinancialsMutation,
    GreenhouseMutation,
    LaborMutation,
    NotificationMutation,
    VideoCallMutation,
    IntegrationSettingsMutation,
    GovernmentMutation,
    ExtensionMutation,
    PartnerMutation,
    LogframeMutation,
    ExportMutation,
    CreditMutation,
    TeamMutation,
    WorkspaceMutation,
    LedgerMutation,
    SalesMutation,
    StockMutation,
    graphene.ObjectType,
):
    pass


schema = graphene.Schema(query=Query, mutation=Mutation)
