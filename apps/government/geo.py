"""
Zambian province / district centroids (approximate, WGS-84) used to place
de-identified district aggregates on the national map. No boundary polygons are
shipped; each district is drawn as a proportional circle at its centroid.
An organisation whose district is not in this table is placed at its province
centroid and flagged ``approximate``.
"""

PROVINCE_CENTROIDS = {
    'Lusaka': (-15.40, 28.40), 'Copperbelt': (-13.00, 28.10), 'Central': (-14.40, 28.50),
    'Southern': (-16.70, 27.00), 'Eastern': (-13.70, 32.00), 'Northern': (-10.00, 31.00),
    'Muchinga': (-11.00, 32.00), 'Luapula': (-10.80, 29.00), 'North-Western': (-12.70, 25.00),
    'Western': (-15.60, 23.50),
}

# district -> (province, lat, lng)
DISTRICT_CENTROIDS = {
    # Lusaka
    'Lusaka': ('Lusaka', -15.42, 28.28), 'Chongwe': ('Lusaka', -15.33, 28.68), 'Kafue': ('Lusaka', -15.77, 28.18),
    'Chilanga': ('Lusaka', -15.55, 28.27), 'Luangwa': ('Lusaka', -15.62, 30.40), 'Rufunsa': ('Lusaka', -15.08, 29.65),
    'Chirundu': ('Lusaka', -16.03, 28.85),
    # Copperbelt
    'Ndola': ('Copperbelt', -12.97, 28.63), 'Kitwe': ('Copperbelt', -12.80, 28.21), 'Chingola': ('Copperbelt', -12.53, 27.85),
    'Mufulira': ('Copperbelt', -12.55, 28.24), 'Luanshya': ('Copperbelt', -13.14, 28.40), 'Kalulushi': ('Copperbelt', -12.84, 28.09),
    'Chililabombwe': ('Copperbelt', -12.36, 27.83), 'Masaiti': ('Copperbelt', -13.30, 28.60), 'Mpongwe': ('Copperbelt', -13.51, 28.15),
    'Lufwanyama': ('Copperbelt', -12.90, 27.60),
    # Central
    'Kabwe': ('Central', -14.44, 28.45), 'Kapiri Mposhi': ('Central', -13.97, 28.67), 'Mkushi': ('Central', -13.62, 29.39),
    'Serenje': ('Central', -13.23, 30.24), 'Mumbwa': ('Central', -14.98, 27.06), 'Chibombo': ('Central', -14.66, 28.07),
    'Chisamba': ('Central', -14.98, 28.38), 'Ngabwe': ('Central', -14.82, 27.67), 'Itezhi-Tezhi': ('Central', -15.75, 26.02),
    'Luano': ('Central', -14.42, 29.60), 'Shibuyunji': ('Central', -15.25, 27.78),
    # Southern
    'Livingstone': ('Southern', -17.85, 25.86), 'Choma': ('Southern', -16.81, 26.98), 'Mazabuka': ('Southern', -15.86, 27.75),
    'Monze': ('Southern', -16.28, 27.48), 'Kalomo': ('Southern', -17.03, 26.49), 'Namwala': ('Southern', -15.75, 26.44),
    'Siavonga': ('Southern', -16.54, 28.71), 'Gwembe': ('Southern', -16.50, 27.61), 'Sinazongwe': ('Southern', -17.26, 27.46),
    'Kazungula': ('Southern', -17.79, 25.27), 'Zimba': ('Southern', -17.32, 26.20), 'Pemba': ('Southern', -16.52, 27.36),
    'Chikankata': ('Southern', -15.95, 28.10),
    # Eastern
    'Chipata': ('Eastern', -13.64, 32.65), 'Petauke': ('Eastern', -14.24, 31.33), 'Katete': ('Eastern', -14.09, 32.06),
    'Lundazi': ('Eastern', -12.29, 33.18), 'Nyimba': ('Eastern', -14.55, 30.81), 'Mambwe': ('Eastern', -13.10, 31.93),
    'Chadiza': ('Eastern', -14.06, 32.44), 'Sinda': ('Eastern', -14.20, 31.78), 'Vubwi': ('Eastern', -14.10, 32.87),
    'Chasefu': ('Eastern', -11.60, 33.20), 'Lumezi': ('Eastern', -12.60, 32.80), 'Kasenengwa': ('Eastern', -13.50, 32.40),
    'Chipangali': ('Eastern', -13.30, 32.70),
    # Northern
    'Kasama': ('Northern', -10.21, 31.18), 'Mbala': ('Northern', -8.84, 31.37), 'Luwingu': ('Northern', -10.26, 29.93),
    'Mporokoso': ('Northern', -9.37, 30.12), 'Mungwi': ('Northern', -10.17, 31.37), 'Kaputa': ('Northern', -8.47, 29.66),
    'Chilubi': ('Northern', -11.10, 30.10), 'Nsama': ('Northern', -8.90, 29.95), 'Senga Hill': ('Northern', -9.35, 31.30),
    'Lupososhi': ('Northern', -10.50, 30.20), 'Lunte': ('Northern', -9.95, 30.90),
    # Muchinga
    'Chinsali': ('Muchinga', -10.55, 32.07), 'Nakonde': ('Muchinga', -9.34, 32.76), 'Isoka': ('Muchinga', -10.13, 32.63),
    'Mpika': ('Muchinga', -11.83, 31.45), 'Mafinga': ('Muchinga', -9.90, 33.10), "Shiwang'andu": ('Muchinga', -11.20, 31.75),
    'Chama': ('Muchinga', -11.21, 33.15), 'Kanchibiya': ('Muchinga', -11.60, 30.90), 'Lavushimanda': ('Muchinga', -12.30, 30.90),
    # Luapula
    'Mansa': ('Luapula', -11.20, 28.89), 'Samfya': ('Luapula', -11.36, 29.56), 'Kawambwa': ('Luapula', -9.79, 29.08),
    'Nchelenge': ('Luapula', -9.35, 28.73), 'Mwense': ('Luapula', -10.38, 28.70), 'Chiengi': ('Luapula', -8.65, 29.16),
    'Milenge': ('Luapula', -12.10, 29.30), 'Chembe': ('Luapula', -11.97, 28.75), 'Lunga': ('Luapula', -11.30, 30.00),
    'Mwansabombwe': ('Luapula', -9.82, 28.75), 'Chipili': ('Luapula', -10.72, 29.05), 'Chifunabuli': ('Luapula', -11.10, 29.70),
    # North-Western
    'Solwezi': ('North-Western', -12.17, 26.38), 'Kasempa': ('North-Western', -13.46, 25.83), 'Mwinilunga': ('North-Western', -11.73, 24.43),
    'Zambezi': ('North-Western', -13.54, 23.11), 'Kabompo': ('North-Western', -13.59, 24.20), 'Mufumbwe': ('North-Western', -13.68, 24.80),
    'Chavuma': ('North-Western', -13.08, 22.68), 'Ikelenge': ('North-Western', -11.23, 24.28), 'Manyinga': ('North-Western', -13.40, 24.30),
    'Kalumbila': ('North-Western', -12.25, 25.50), 'Mushindamo': ('North-Western', -12.10, 27.00),
    # Western
    'Mongu': ('Western', -15.25, 23.13), 'Senanga': ('Western', -16.12, 23.28), 'Kaoma': ('Western', -14.80, 24.80),
    'Sesheke': ('Western', -17.48, 24.30), 'Kalabo': ('Western', -14.99, 22.68), 'Lukulu': ('Western', -14.38, 23.24),
    'Shangombo': ('Western', -16.35, 22.10), 'Limulunga': ('Western', -15.10, 23.15), 'Luampa': ('Western', -15.05, 24.40),
    'Nkeyema': ('Western', -14.90, 25.10), 'Mulobezi': ('Western', -16.80, 25.20), 'Mwandi': ('Western', -17.50, 24.90),
    'Sikongo': ('Western', -14.90, 22.00), 'Nalolo': ('Western', -15.70, 23.20), 'Sioma': ('Western', -16.65, 23.60),
    'Mitete': ('Western', -14.60, 22.50),
}

_LOWER = {k.lower(): (k, *v) for k, v in DISTRICT_CENTROIDS.items()}
_PLOWER = {k.lower(): (k, *v) for k, v in PROVINCE_CENTROIDS.items()}

ZAMBIA_CENTER = (-13.45, 27.85)


def locate(province, district):
    """Return (canonical_province, canonical_district, lat, lng, approximate) or None if unplaceable."""
    d = (district or '').strip().lower()
    if d in _LOWER:
        name, prov, lat, lng = _LOWER[d]
        return prov, name, lat, lng, False
    p = (province or '').strip().lower()
    if p in _PLOWER:
        name, lat, lng = _PLOWER[p]
        return name, (district or '').strip() or None, lat, lng, True
    return None
