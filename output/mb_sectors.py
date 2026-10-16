"""
Plan 0026 stage 4b — sector and sub-sector of every researched multibagger name, from what the research agent
established the company actually does (verdict.json business.what_it_does, read against its filings).

Why not stocks.sector / stocks.industry: the vendor tags were wrong for about 1 in 6 researched names (a denim mill
tagged "Paper", silver electrical contacts tagged "Retail", a sugar holdco tagged "Chemicals"), which also made the
peer tables meaningless. Sectors are a short fixed list; the sub-sector says what the company makes or sells.
Classified by hand 2026-10-16 from the 105 research reports; a newly researched sid needs a line here
(output.mb_research.set_sectors reports any that are missing).
"""

SECTORS = {
    # Chemicals
    "ARRO": ("Chemicals", "Anti-counterfeit security threads and water-soluble films"),
    "BHAE": ("Chemicals", "Dye intermediates (H-acid, vinyl sulphone)"),
    "BODA": ("Chemicals", "Dyes, dye intermediates and chlor-alkali"),
    "CHEMC": ("Chemicals", "Pharma intermediates and oilfield bromides"),
    "DHARA": ("Chemicals", "Sulphuric acid, oleum and boron chemicals"),
    "IGPT": ("Chemicals", "Phthalic and maleic anhydride"),
    "INDOM": ("Chemicals", "Fatty amines and specialty chemicals"),
    "KRON": ("Chemicals", "High-purity fine chemicals (pharma excipients, reagents)"),
    "MNLI": ("Chemicals", "Propylene glycol and polyols"),
    "OCC": ("Chemicals", "Insoluble sulphur (tyre vulcanising agent)"),
    "SRHL": ("Chemicals", "Calcium hypochlorite and bleaching chemicals"),
    "TPL": ("Chemicals", "Linear alkyl benzene (detergent feedstock) and caustic soda"),
    "VALI": ("Chemicals", "Benzene-derivative and chlorophenol intermediates"),
    # Agrochemicals and fertilisers
    "ADVAN": ("Agrochemicals & Fertilisers", "Agrochemical formulations (insecticides, herbicides)"),
    "ARAI": ("Agrochemicals & Fertilisers", "Micronutrients and specialty fertilisers"),
    # Pharmaceuticals
    "AHC": ("Pharmaceuticals", "APIs and pharma intermediates"),
    "KIDI": ("Pharmaceuticals", "Generic formulations for export (incl. Ethiopia plant)"),
    "KPRN": ("Pharmaceuticals", "Generic formulations and APIs (export)"),
    "LINP": ("Pharmaceuticals", "Branded generics for export"),
    "MED": ("Pharmaceuticals", "Generic formulations for export tenders"),
    "MEDI": ("Pharmaceuticals", "Formulations for export (incl. oncology)"),
    "THEM": ("Pharmaceuticals", "Branded formulations and APIs"),
    "VENR": ("Pharmaceuticals", "Sterile injectables (critical care, antibiotics)"),
    "ZIM": ("Pharmaceuticals", "Oral solid-dosage intermediates and formulations"),
    # Textiles and apparel
    "AMBK": ("Textiles & Apparel", "Fine-count cotton yarn (spinning)"),
    "CNTE": ("Textiles & Apparel", "Nylon filament yarn and tyre cord fabric"),
    "GHC": ("Textiles & Apparel", "Cotton and blended yarn (spinning)"),
    "IRIC": ("Textiles & Apparel", "Kidswear brand (DOREME)"),
    "KSRM": ("Textiles & Apparel", "Viscose filament yarn and cellophane film (holding company)"),
    "MAN": ("Textiles & Apparel", "Denim fabric and cotton yarn"),
    "PASUP": ("Textiles & Apparel", "Acrylic staple fibre (plus grain ethanol)"),
    "PURPL": ("Textiles & Apparel", "Kids' apparel and footwear brand"),
    "RSWM": ("Textiles & Apparel", "Yarn, denim and knitted fabric"),
    "SARL": ("Textiles & Apparel", "Polyester and nylon yarn processing"),
    "SPO": ("Textiles & Apparel", "Cotton and synthetic yarn (spinning)"),
    "SWARA": ("Textiles & Apparel", "Denim and cotton fabric"),
    # Autos and auto components
    "ALIO": ("Auto & Auto Components", "Aluminium alloy castings"),
    "ATUL": ("Auto & Auto Components", "Three-wheeler maker"),
    "AUIN": ("Auto & Auto Components", "Sheet-metal stampings and assemblies"),
    "GNAA": ("Auto & Auto Components", "Axle shafts and forgings (trucks, tractors)"),
    "KROS": ("Auto & Auto Components", "Trailer axles and truck drivetrain parts"),
    "MUAU": ("Auto & Auto Components", "Two-wheeler exhausts and stampings (plus wind blades)"),
    "OMXA": ("Auto & Auto Components", "Truck chassis frames"),
    "REIN": ("Auto & Auto Components", "Control cables and gear shifters"),
    # Metals
    "BAH": ("Metals", "Aluminium scrap recycling (deoxidants, alloy ingots)"),
    "GYSC": ("Metals", "Stainless and mild steel long products"),
    "KAMI": ("Metals", "TMT steel bar brand (franchise royalty)"),
    "MMPI": ("Metals", "Aluminium powder, foil and conductors"),
    "MUKA": ("Metals", "Alloy and stainless steel long products"),
    "NRL": ("Metals", "Non-ferrous scrap recycling (zinc, aluminium)"),
    "SUNLI": ("Metals", "Copper scrap recycling (wire rods)"),
    # Plastics and packaging
    "CSFL": ("Plastics & Packaging", "BOPP and BOPET packaging films"),
    "ESTR": ("Plastics & Packaging", "Polyester (BOPET) films and specialty polymers"),
    "GSM": ("Plastics & Packaging", "Pharma blister and strip aluminium foil"),
    "PLST": ("Plastics & Packaging", "Masterbatches and plastic compounds"),
    "PRPF": ("Plastics & Packaging", "PVC flooring, sheeting and leather cloth"),
    "PYR": ("Plastics & Packaging", "Industrial drums and bulk containers"),
    "TPLP": ("Plastics & Packaging", "Industrial drums and bulk containers (merging into parent)"),
    "UFLX": ("Plastics & Packaging", "Flexible packaging and packaging films"),
    # Paper
    "KAUN": ("Paper", "Writing and printing paper (agro and wood pulp)"),
    "SSHA": ("Paper", "Writing and printing paper"),
    "TNNP": ("Paper", "Paper and packaging board (Tamil Nadu govt)"),
    # Sugar
    "DBO": ("Sugar & Ethanol", "Integrated sugar, ethanol and liquor"),
    "MAWS": ("Sugar & Ethanol", "Integrated sugar, power and ethanol"),
    "PONS": ("Sugar & Ethanol", "Sugar mill with co-generation power"),
    "UGSW": ("Sugar & Ethanol", "Integrated sugar, alcohol and power"),
    # Food
    "GOKU": ("Food Products", "Edible and castor oil, agri trading"),
    "HMA": ("Food Products", "Frozen buffalo meat exports"),
    "MUKK": ("Food Products", "Fishmeal and fish oil (feed ingredients)"),
    # Oil and gas
    "ABSM": ("Oil & Gas", "Offshore support vessels for ONGC"),
    "ASIAO": ("Oil & Gas", "Oilfield services (plus oil and gas blocks after merger)"),
    "DOLP": ("Oil & Gas", "Offshore accommodation barge charter"),
    "GAND": ("Oil & Gas", "Specialty oils (white oils, lubricants)"),
    "KOTY": ("Oil & Gas", "Biodiesel"),
    "PAPT": ("Oil & Gas", "Specialty oils (white oils, petroleum jelly)"),
    # Financials
    "AFI": ("Financial Services", "NBFC: vehicle and small-business loans"),
    "DNBK": ("Financial Services", "Private bank (Kerala, gold loans)"),
    "IIAB": ("Financial Services", "Holding company: real estate and lending"),
    "MANBA": ("Financial Services", "NBFC: two-wheeler and used-vehicle loans"),
    # Jewellery
    "MVG": ("Jewellery", "Gold jewellery retail (Andhra Pradesh)"),
    "RAD": ("Jewellery", "Jewellery retail (Rajkot)"),
    "RBZ": ("Jewellery", "Gold jewellery maker and retailer (Ahmedabad)"),
    "RENA": ("Jewellery", "Diamond jewellery exports to the US (plus D2C brands)"),
    "SHANG": ("Jewellery", "B2B gold jewellery manufacturing"),
    # Electrical equipment and electronics
    "BRLE": ("Electrical Equipment", "Telecom and LAN cables (merging into parent)"),
    "KATL": ("Electrical Equipment", "RF antennas and components (defence, telecom)"),
    "MAXVO": ("Electrical Equipment", "Lithium-ion battery packs"),
    "MODIS": ("Electrical Equipment", "Silver electrical contacts for switchgear"),
    "SUPRM": ("Electrical Equipment", "Power and distribution transformers"),
    # Capital goods and engineering
    "FELX": ("Capital Goods & Engineering", "Water treatment and zero-discharge EPC"),
    "MOLD": ("Capital Goods & Engineering", "Structural engineering services for US clients"),
    "PATIL": ("Capital Goods & Engineering", "Welding and assembly automation lines"),
    "SAFEE": ("Capital Goods & Engineering", "Retail shop fixtures"),
    "TEMB": ("Capital Goods & Engineering", "Pipe supports, fasteners and piping EPC"),
    # Building materials
    "ORBL": ("Building Materials", "Ceramic and vitrified tiles"),
    "PRAS": ("Building Materials", "PVC pipes (plus flexible packaging)"),
    "VSKI": ("Building Materials", "Fibre-cement roofing and boards"),
    # Services
    "FLY": ("Services", "Private-jet charter"),
    "KRYS": ("Services", "Facility management and staffing"),
    "UIVA": ("Services", "Construction EPC (public buildings, metro systems)"),
    "VERAN": ("Services", "Test-prep coaching and schools"),
    # Retail
    "PATER": ("Retail", "Value supermarkets (plus agri trading)"),
    # Holding companies
    "BHIL": ("Holding Companies", "Land and wind power left after the copper demerger"),
    "SATI": ("Holding Companies", "Stakes in Aeroflex Industries (hoses) and Aeroflex Neu"),
    "ZURI": ("Holding Companies", "Sugar, real estate and engineering (Adventz group)"),
}
