"""What the assistant is allowed to point people at: pages per account type and the built-in templates.

The frontend owns the real navigation; these lists must match the page ids used there. The assistant may only
suggest an id from the list for the asker's account type, and the server throws away anything else.
"""
import json
from functools import lru_cache

from django.conf import settings

FARM_PAGES = [
    ('dashboard', 'Dashboard'), ('production', 'Production'), ('processing', 'Processing'), ('inventory', 'Inventory'),
    ('sales', 'Sales'), ('trade-docs', 'Trade & Export'), ('finance', 'Finance'), ('credit', 'Credit Profile'),
    ('reports', 'Reports'), ('marketplace-food', 'AgriFood Market'), ('marketplace-supply', 'AgriSupply'),
    ('marketplace-services', 'AgriServices'), ('mkt-dealers', 'Agro Dealers'), ('mkt-hire', 'Equipment Hire'),
    ('mkt-vet', 'Vet Services'), ('ai-smart', 'Smart Engine'), ('ai-predictive', 'AI Insights'),
    ('ai-financial', 'Financial AI'), ('ai-vision', 'Smart Vision'), ('ai-weather', 'Weather'),
    ('ai-sustainability', 'Sustainability'), ('ai-devices', 'Smart Devices'), ('iot-water', 'Water Management'),
    ('iot-aquaculture', 'Aquaculture'), ('iot-poultry', 'Poultry Houses'), ('iot-energy', 'Energy'),
    ('iot-soil', 'Soil Depth'), ('iot-automation', 'Automation'), ('iot-gateway', 'Device Gateway'),
    ('iot-cold-chain', 'Cold Chain'), ('iot-farm-gateway', 'Farm Gateway'), ('notifications', 'Notifications'),
    ('animal-health', 'Animal Health'), ('staff-labour', 'Staff & Labour'), ('procurement', 'Procurement'),
    ('requisitions', 'Requisitions'), ('activity-log', 'Activity Log'), ('crop-rotation', 'Crop Rotation'),
    ('team', 'Team & Permissions'), ('config', 'Settings'), ('backup', 'Backup & Restore'),
]

_COMMON_VENDOR = [('clients', 'Clients'), ('invoices', 'Invoices'), ('revenue', 'Revenue'),
                  ('marketplace', 'Marketplace Listing'), ('team', 'Users & Permissions'), ('settings', 'Settings')]
_V = lambda *extra: [('overview', 'Overview')] + list(extra) + _COMMON_VENDOR  # noqa: E731

PAGES = {
    'farmer': FARM_PAGES,
    'cooperative': FARM_PAGES,
    'vet_provider': _V(('appointments', 'Appointments'), ('patients', 'Patient Records'), ('prescriptions', 'Prescriptions'), ('services', 'Services Catalog')),
    'equipment_hire': _V(('fleet', 'Fleet Management'), ('bookings', 'Bookings'), ('maintenance', 'Maintenance')),
    'transport': _V(('jobs', 'Transport Jobs'), ('fleet', 'Vehicles'), ('maintenance', 'Maintenance')),
    'agro_dealer': _V(('catalog', 'Product Catalog'), ('orders', 'Orders'), ('stock', 'Stock Management')),
    'agrisupply_provider': _V(('catalog', 'Supply Catalog'), ('orders', 'Purchase Orders'), ('stock', 'Stock Management'), ('deliveries', 'Deliveries')),
    'agrifood_seller': _V(('listings', 'Produce Listings'), ('orders', 'Buyer Orders'), ('pricing', 'Pricing & Stock')),
    'agriservices_provider': _V(('services', 'Services Catalog'), ('jobs', 'Job Schedule')),
    'processor': _V(('sourcing', 'Farm Sourcing'), ('processing', 'Processing Logs'), ('inventory', 'Inventory'), ('traceability', 'Traceability'), ('orders', 'Orders')),
    'government': [('overview', 'National Overview'), ('ecosystem', 'Ecosystem'), ('map', 'National Map'), ('production', 'Production'),
                   ('markets', 'Markets & Prices'), ('health', 'Disease & Alerts'), ('sustainability', 'Climate & Sustainability'),
                   ('registry', 'District Registry'), ('advisories', 'Advisories'), ('programmes', 'Programmes'), ('team', 'Team & Branches')],
    'extension': [('caseload', 'My Caseload'), ('visits', 'Visits & Follow-ups'), ('add', 'Add Farms'), ('programmes', 'Programmes'), ('team', 'Team & Branches')],
    'partner': [('programmes', 'Programmes'), ('gov:overview', 'National Overview'), ('gov:ecosystem', 'Ecosystem'), ('gov:map', 'National Map'),
                ('gov:production', 'Production'), ('gov:markets', 'Markets & Prices'), ('gov:health', 'Disease & Alerts'),
                ('gov:sustainability', 'Climate & Sustainability'), ('gov:registry', 'District Registry'), ('gov:advisories', 'Advisories'),
                ('team', 'Team & Branches')],
    'individual': [],
    'visitor': [],
}

ACCOUNT_LABEL = {
    'farmer': 'a farm', 'cooperative': 'a cooperative / farmer group', 'vet_provider': 'a veterinary business',
    'equipment_hire': 'an equipment hire business', 'transport': 'a transport and logistics business',
    'agro_dealer': 'an agro dealer / input shop', 'agrisupply_provider': 'an AgriSupply provider',
    'agrifood_seller': 'an AgriFood seller', 'agriservices_provider': 'an AgriServices provider',
    'processor': 'an agro processor', 'government': 'a government office', 'extension': 'an extension officer',
    'partner': 'an NGO / donor programme partner', 'individual': 'an individual buyer',
    'visitor': 'a visitor who has not registered yet',
}


def account_type(value):
    return value if value in ACCOUNT_LABEL else 'farmer'


def valid_pages(acct):
    return {p for p, _ in PAGES.get(acct, [])}


def page_label(acct, page):
    for p, label in PAGES.get(acct, []):
        if p == page:
            return label
    return page


@lru_cache(maxsize=1)
def templates():
    path = settings.BASE_DIR / 'apps' / 'assistant' / 'data' / 'templates.json'
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding='utf-8'))['templates']


def template_ids():
    return {t['id'] for t in templates()}


def template_line_list():
    """Compact one-line-per-template list for the model: id | name | category."""
    return '\n'.join(f"{t['id']} | {t['name']} | {t['category']}" for t in templates())
