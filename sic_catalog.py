"""SIC industry catalog: 10 divisions → 83 subindustries.

Each division maps to a set of subindustries (SIC major groups). Each subindustry
defines a small relational schema (tables + columns), domain-specific value vocab
(for the offline mock generator), and a one-line blurb (to guide the LLM). Consumed
by demo_app's catalog-driven generator, which normalizes table names and labels.
"""

SIC_CATALOG = {
"agriculture_forestry_fishing": {
    "label": "Agriculture, Forestry & Fishing",
    "subs": {
        "crop_production": {
            "label": "Crop Production",
            "blurb": "A row-crop and specialty farming operation managing fields, planting and harvest cycles, and crop sales; tables track farms, the fields and crops grown on them, and harvest yields sold to buyers.",
            "tables": [
                ("farm", ["farm_id", "farm_name", "owner_name", "total_acreage", "region", "irrigation_type", "established_date"]),
                ("field", ["field_id", "farm_id", "field_name", "acreage", "soil_type", "crop_type", "planting_date"]),
                ("harvest", ["harvest_id", "field_id", "crop_type", "yield_quantity", "harvest_date", "quality_grade", "revenue"]),
            ],
            "vocab": {
                "crop_type": ["Corn", "Soybeans", "Winter Wheat", "Cotton", "Alfalfa", "Rice", "Sorghum", "Sugar Beets", "Canola", "Barley", "Sunflower", "Peanuts"],
                "soil_type": ["Loam", "Sandy Loam", "Clay", "Silty Clay", "Silt Loam", "Sandy", "Peat", "Chalk", "Clay Loam"],
                "irrigation_type": ["Center Pivot", "Drip", "Furrow", "Flood", "Sprinkler", "Subsurface Drip", "Rain-fed", "Micro-sprinkler"],
                "quality_grade": ["U.S. No. 1", "U.S. No. 2", "U.S. No. 3", "Sample Grade", "Premium", "Feed Grade", "Milling Grade"],
            },
        },
        "livestock_production": {
            "label": "Livestock & Animal Specialties",
            "blurb": "A livestock ranch raising animals for meat, dairy, and breeding; tables track herds, individual animals, their health and feeding records, and sales of livestock and animal products.",
            "tables": [
                ("ranch", ["ranch_id", "ranch_name", "operator_name", "pasture_acreage", "region", "livestock_type", "registered_date"]),
                ("animal", ["animal_id", "ranch_id", "tag_number", "breed", "livestock_type", "birth_date", "weight", "health_status"]),
                ("feed_log", ["feed_log_id", "animal_id", "feed_type", "quantity", "cost", "feeding_date"]),
                ("livestock_sale", ["livestock_sale_id", "animal_id", "buyer_name", "sale_weight", "price", "sale_date", "sale_type"]),
            ],
            "vocab": {
                "livestock_type": ["Beef Cattle", "Dairy Cattle", "Swine", "Sheep", "Goats", "Broiler Chickens", "Laying Hens", "Turkeys", "Horses", "Bison"],
                "breed": ["Angus", "Hereford", "Holstein", "Jersey", "Yorkshire", "Duroc", "Suffolk", "Boer", "Rhode Island Red", "Charolais", "Brahman", "Simmental"],
                "feed_type": ["Hay", "Silage", "Corn Grain", "Soybean Meal", "Alfalfa Pellets", "Mineral Supplement", "Pasture Grass", "Distillers Grain", "Molasses Mix"],
                "health_status": ["Healthy", "Under Treatment", "Vaccinated", "Quarantined", "Pregnant", "Lactating", "Weaned", "Deceased"],
                "sale_type": ["Auction", "Direct to Packer", "Private Treaty", "Breeding Stock", "Feeder Sale", "Cull Sale"],
            },
        },
        "agricultural_services": {
            "label": "Agricultural Services",
            "blurb": "A contract agricultural services company providing crop spraying, soil testing, and equipment operation to client farms; tables track client farms, service contracts, and the work orders completed by field crews.",
            "tables": [
                ("client_farm", ["client_farm_id", "farm_name", "contact_name", "acreage", "region", "primary_crop", "onboarded_date"]),
                ("service_contract", ["service_contract_id", "client_farm_id", "service_type", "contract_amount", "start_date", "billing_cycle", "status"]),
                ("work_order", ["work_order_id", "service_contract_id", "service_type", "scheduled_date", "area_covered", "cost", "completion_status"]),
            ],
            "vocab": {
                "service_type": ["Aerial Spraying", "Soil Testing", "Custom Harvesting", "Crop Dusting", "Fertilizer Application", "Tillage", "Irrigation Maintenance", "Pest Scouting", "Seeding", "Lime Spreading"],
                "billing_cycle": ["Per Acre", "Per Job", "Monthly", "Seasonal", "Annual", "Per Hour"],
                "completion_status": ["Scheduled", "In Progress", "Completed", "Weather Delayed", "Cancelled", "Rescheduled", "Partially Complete"],
                "primary_crop": ["Corn", "Soybeans", "Wheat", "Cotton", "Vegetables", "Orchard Fruit", "Vineyard", "Hay", "Rice"],
            },
        },
        "forestry": {
            "label": "Forestry",
            "blurb": "A timber and forest management operation overseeing forested tracts, timber stands, and logging harvests; tables track managed tracts, the stands and species within them, and the harvest sales of logs to mills.",
            "tables": [
                ("tract", ["tract_id", "tract_name", "owner_name", "acreage", "region", "forest_type", "acquired_date"]),
                ("timber_stand", ["timber_stand_id", "tract_id", "species", "stand_age", "stocking_density", "stand_status", "surveyed_date"]),
                ("timber_harvest", ["timber_harvest_id", "timber_stand_id", "harvest_method", "volume_board_feet", "log_grade", "harvest_date", "revenue"]),
            ],
            "vocab": {
                "forest_type": ["Southern Pine", "Douglas Fir", "Northern Hardwood", "Mixed Conifer", "Oak-Hickory", "Spruce-Fir", "Bottomland Hardwood", "Ponderosa Pine", "Aspen-Birch"],
                "species": ["Loblolly Pine", "Douglas Fir", "Red Oak", "Sugar Maple", "Western Hemlock", "Ponderosa Pine", "White Spruce", "Yellow Poplar", "Black Walnut", "Eastern White Pine", "Cherry", "Ash"],
                "harvest_method": ["Clearcut", "Selective Cut", "Shelterwood", "Seed Tree", "Thinning", "Group Selection", "Salvage Cut"],
                "log_grade": ["Veneer", "Sawlog Grade 1", "Sawlog Grade 2", "Sawlog Grade 3", "Pulpwood", "Pole", "Chip-n-Saw", "Cull"],
                "stand_status": ["Pre-commercial", "Merchantable", "Mature", "Recently Harvested", "Regenerating", "Reserved", "Diseased"],
            },
        },
        "fishing_hunting_trapping": {
            "label": "Fishing, Hunting & Trapping",
            "blurb": "A commercial fishing and trapping enterprise operating vessels and harvesting wild species for sale; tables track vessels, fishing trips and their catches by species, and the dockside sales to processors.",
            "tables": [
                ("vessel", ["vessel_id", "vessel_name", "captain_name", "home_port", "gear_type", "vessel_length", "registered_date"]),
                ("fishing_trip", ["fishing_trip_id", "vessel_id", "departure_date", "return_date", "fishing_ground", "trip_status", "total_catch_weight"]),
                ("catch_record", ["catch_record_id", "fishing_trip_id", "species", "weight", "grade", "catch_date", "disposition"]),
                ("dockside_sale", ["dockside_sale_id", "catch_record_id", "buyer_name", "species", "quantity", "price", "sale_date"]),
            ],
            "vocab": {
                "gear_type": ["Longline", "Gillnet", "Purse Seine", "Trawl", "Trap/Pot", "Trolling", "Dredge", "Handline", "Beam Trawl", "Seine Net"],
                "species": ["Atlantic Cod", "Alaska Pollock", "Pacific Halibut", "Snow Crab", "American Lobster", "Yellowfin Tuna", "Sockeye Salmon", "Bay Scallop", "Gulf Shrimp", "Blue Crab", "Atlantic Mackerel", "Haddock"],
                "fishing_ground": ["Georges Bank", "Gulf of Maine", "Bering Sea", "Gulf of Alaska", "Grand Banks", "Gulf of Mexico", "Chesapeake Bay", "Bristol Bay", "Pacific Northwest Coast"],
                "grade": ["Sashimi Grade", "Grade A", "Grade B", "Market Grade", "Cull", "Jumbo", "Select", "Standard"],
                "disposition": ["Sold Fresh", "Frozen at Sea", "Iced", "Live Holding", "Bait", "Discarded", "Processed Onboard"],
            },
        },
    },
},
"mining": {
    "label": "Mining",
    "subs": {
        "metal_mining": {
            "label": "Metal Mining",
            "blurb": "Extraction of metallic ores from open-pit and underground mines, tracking deposits, ore shipments to mills, and recovered metal assays.",
            "tables": [
                ("deposit", ["deposit_id", "deposit_name", "ore_type", "extraction_method", "discovery_date", "estimated_reserves_tons", "status"]),
                ("ore_shipment", ["shipment_id", "deposit_id", "ore_grade", "shipment_date", "tonnage", "destination_mill", "freight_cost"]),
                ("assay_result", ["assay_id", "shipment_id", "metal_recovered", "recovery_percent", "assay_date", "market_value", "lab_technician"]),
            ],
            "vocab": {
                "ore_type": ["Copper Porphyry", "Iron Magnetite", "Gold Quartz Vein", "Bauxite", "Lead-Zinc Sulfide", "Nickel Laterite", "Silver Argentite", "Molybdenite", "Hematite", "Chalcopyrite", "Cassiterite", "Uranite"],
                "extraction_method": ["Open-Pit", "Underground Shaft", "Block Caving", "Heap Leaching", "Room and Pillar", "Cut and Fill", "Sublevel Stoping", "In-Situ Leaching"],
                "ore_grade": ["High Grade", "Medium Grade", "Low Grade", "Marginal", "Sub-Economic"],
                "metal_recovered": ["Copper", "Gold", "Silver", "Iron", "Nickel", "Lead", "Zinc", "Molybdenum", "Tin", "Aluminum", "Uranium", "Cobalt"],
            },
        },
        "coal_mining": {
            "label": "Coal Mining",
            "blurb": "Mining of bituminous, anthracite, and lignite coal seams, tracking mine sites, production runs by seam, and coal sales contracts to power and industrial buyers.",
            "tables": [
                ("mine_site", ["mine_id", "mine_name", "mine_type", "seam_name", "opening_date", "permitted_acreage", "status"]),
                ("production_run", ["run_id", "mine_id", "coal_grade", "run_date", "tons_extracted", "btu_per_pound", "sulfur_content_percent"]),
                ("sales_contract", ["contract_id", "run_id", "buyer_segment", "contract_date", "tons_sold", "price_per_ton", "delivery_status"]),
            ],
            "vocab": {
                "mine_type": ["Surface Strip", "Underground Longwall", "Underground Room and Pillar", "Mountaintop Removal", "Contour Mining", "Auger Mining", "Highwall Mining", "Drift Mine"],
                "coal_grade": ["Anthracite", "Bituminous", "Sub-Bituminous", "Lignite", "Metallurgical Coking", "Steam Coal", "Semi-Anthracite", "Cannel Coal"],
                "buyer_segment": ["Electric Utility", "Steel Mill", "Cement Plant", "Industrial Boiler", "Coal Export Terminal", "Residential Heating", "Coke Producer", "Paper Mill"],
            },
        },
        "oil_gas_extraction": {
            "label": "Oil & Gas Extraction",
            "blurb": "Exploration and production of crude oil and natural gas from wells, tracking leases, well production volumes, and royalty payments to mineral rights owners.",
            "tables": [
                ("lease", ["lease_id", "lease_name", "basin", "lease_type", "acquisition_date", "net_acres", "status"]),
                ("well", ["well_id", "lease_id", "well_type", "drive_mechanism", "spud_date", "total_depth_feet", "production_status"]),
                ("production_volume", ["volume_id", "well_id", "product_type", "production_date", "barrels_oil_equivalent", "wellhead_price", "operating_cost"]),
                ("royalty_payment", ["payment_id", "volume_id", "owner_name", "payment_date", "royalty_rate_percent", "gross_amount", "payment_status"]),
            ],
            "vocab": {
                "basin": ["Permian", "Bakken", "Marcellus", "Eagle Ford", "Anadarko", "Appalachian", "Gulf of Mexico", "Haynesville", "Niobrara", "Williston", "Powder River", "Utica"],
                "lease_type": ["Fee Simple", "State Lease", "Federal Onshore", "Federal Offshore", "Tribal", "Private Mineral", "Farmout", "Unitized"],
                "well_type": ["Horizontal", "Vertical", "Directional", "Multilateral", "Exploratory Wildcat", "Development", "Injection", "Disposal"],
                "drive_mechanism": ["Solution Gas Drive", "Water Drive", "Gas Cap Drive", "Gravity Drainage", "Combination Drive", "Artificial Lift", "Rod Pump", "Electric Submersible Pump"],
                "product_type": ["Crude Oil", "Natural Gas", "Condensate", "Natural Gas Liquids", "Casinghead Gas", "Sour Gas", "Sweet Crude", "Heavy Crude"],
            },
        },
        "nonmetallic_minerals_mining": {
            "label": "Nonmetallic Minerals Mining (except fuels)",
            "blurb": "Quarrying and mining of industrial and construction minerals such as sand, gravel, stone, and clay, tracking quarries, extraction batches, and bulk material sales.",
            "tables": [
                ("quarry", ["quarry_id", "quarry_name", "mineral", "quarry_method", "opening_date", "reserve_volume_cubic_yards", "status"]),
                ("extraction_batch", ["batch_id", "quarry_id", "product_grade", "extraction_date", "tons_quarried", "moisture_content_percent", "processing_cost"]),
                ("material_sale", ["sale_id", "batch_id", "end_use", "sale_date", "tons_sold", "price_per_ton", "delivery_status"]),
            ],
            "vocab": {
                "mineral": ["Limestone", "Sand and Gravel", "Crushed Granite", "Gypsum", "Kaolin Clay", "Silica Sand", "Dolomite", "Bentonite", "Phosphate Rock", "Potash", "Feldspar", "Marble"],
                "quarry_method": ["Open-Pit Quarrying", "Dredging", "Bench Blasting", "Hydraulic Mining", "Dry Pit Excavation", "Wet Pit Dredging", "Terrace Mining", "Strip Quarrying"],
                "product_grade": ["Construction Grade", "Industrial Grade", "Glass Grade", "Foundry Grade", "Agricultural Grade", "Filler Grade", "Ceramic Grade", "Aggregate Base"],
                "end_use": ["Ready-Mix Concrete", "Asphalt Paving", "Road Base", "Glass Manufacturing", "Cement Production", "Drywall Manufacturing", "Ceramics", "Soil Amendment", "Filtration Media", "Foundry Casting"],
            },
        },
    },
},
"construction": {
    "label": "Construction",
    "subs": {
        "building_construction": {
            "label": "Building Construction (General Contractors)",
            "blurb": "General contractors that build and renovate residential and commercial structures; tables track building projects, the subcontractor work packages on each, and progress-billing invoices.",
            "tables": [
                ("project", ["project_id", "project_name", "building_type", "delivery_method", "contract_value", "start_date", "completion_status", "site_address"]),
                ("work_package", ["work_package_id", "project_id", "trade_division", "scope_description", "subcontractor_name", "package_amount", "package_status"]),
                ("progress_billing", ["progress_billing_id", "project_id", "billing_date", "percent_complete", "amount_billed", "retainage_amount", "payment_status"]),
            ],
            "vocab": {
                "building_type": ["Single-Family Home", "Multifamily Apartment", "Office Building", "Retail Center", "Warehouse", "Medical Clinic", "School", "Hotel", "Mixed-Use", "Restaurant", "Industrial Plant", "Parking Structure"],
                "delivery_method": ["Design-Bid-Build", "Design-Build", "Construction Manager at Risk", "CM Agency", "Integrated Project Delivery", "Job Order Contracting", "Negotiated GMP", "Turnkey"],
                "trade_division": ["Sitework", "Concrete", "Masonry", "Structural Steel", "Carpentry", "Roofing", "Drywall", "Electrical", "Plumbing", "HVAC", "Finishes", "Fire Protection"],
            },
        },
        "heavy_construction": {
            "label": "Heavy Construction (non-building)",
            "blurb": "Heavy and civil engineering firms that build infrastructure such as roads, bridges, and utilities; tables track infrastructure projects, the heavy equipment assigned to them, and bulk material deliveries.",
            "tables": [
                ("infra_project", ["infra_project_id", "project_name", "project_type", "funding_source", "contract_amount", "award_date", "project_status", "location_county"]),
                ("equipment_assignment", ["equipment_assignment_id", "infra_project_id", "equipment_type", "operator_name", "assigned_date", "daily_rate", "assignment_status"]),
                ("material_delivery", ["material_delivery_id", "infra_project_id", "material_type", "delivery_date", "quantity_tons", "unit_cost", "delivery_status"]),
            ],
            "vocab": {
                "project_type": ["Highway Construction", "Bridge Construction", "Water Treatment Plant", "Sewer Main", "Dam Construction", "Airport Runway", "Railroad Grading", "Pipeline", "Land Reclamation", "Tunnel Boring", "Flood Control Channel", "Power Transmission Line"],
                "funding_source": ["Federal Highway Grant", "State DOT Bond", "Municipal Bond", "Public-Private Partnership", "Federal Infrastructure Grant", "County Sales Tax", "Utility Ratepayer Fund", "EPA Revolving Fund"],
                "equipment_type": ["Excavator", "Bulldozer", "Motor Grader", "Wheel Loader", "Backhoe", "Dump Truck", "Crawler Crane", "Asphalt Paver", "Compactor Roller", "Scraper", "Trencher", "Concrete Pump"],
                "material_type": ["Crushed Aggregate", "Ready-Mix Concrete", "Hot-Mix Asphalt", "Structural Steel", "Rebar", "Riprap", "Fill Dirt", "Gravel Base", "Sand", "Precast Beams", "Pipe Sections", "Geotextile Fabric"],
            },
        },
        "special_trade_contractors": {
            "label": "Special Trade Contractors",
            "blurb": "Specialty subcontractors performing a single trade such as electrical, plumbing, or HVAC; tables track service jobs, the licensed crews dispatched, and the permits pulled for each job.",
            "tables": [
                ("trade_job", ["trade_job_id", "customer_name", "trade_type", "job_date", "service_address", "labor_amount", "job_status", "warranty_type"]),
                ("crew_assignment", ["crew_assignment_id", "trade_job_id", "lead_technician", "license_class", "scheduled_date", "hours_worked", "assignment_status"]),
                ("permit", ["permit_id", "trade_job_id", "permit_type", "issuing_authority", "issue_date", "permit_fee", "inspection_status"]),
            ],
            "vocab": {
                "trade_type": ["Electrical", "Plumbing", "HVAC", "Roofing", "Masonry", "Painting", "Drywall", "Flooring", "Glazing", "Insulation", "Fire Sprinkler", "Concrete Finishing"],
                "license_class": ["Master Electrician", "Journeyman Electrician", "Master Plumber", "Journeyman Plumber", "HVAC Universal", "EPA 608 Type II", "Apprentice", "Certified Welder", "General Trade License"],
                "permit_type": ["Electrical Permit", "Plumbing Permit", "Mechanical Permit", "Building Permit", "Demolition Permit", "Gas Line Permit", "Fire Sprinkler Permit", "Reroof Permit", "Sign Permit", "Right-of-Way Permit"],
                "warranty_type": ["1-Year Workmanship", "5-Year Limited", "10-Year Limited", "Lifetime Workmanship", "Manufacturer Parts Only", "Labor Only", "Extended Service Plan", "No Warranty"],
                "inspection_status": ["Scheduled", "Passed", "Failed", "Partial Pass", "Reinspection Required", "Waived", "Pending Correction", "Final Approved"],
            },
        },
    },
},
"manufacturing": {
    "label": "Manufacturing",
    "subs": {
        "food_manufacturing": {
            "label": "Food & Kindred Products",
            "blurb": "A food processing company that produces packaged consumables; tables track production batches, recipe formulations, and shipments to distributors.",
            "tables": [
                ("batch", ["batch_id", "product_category", "production_date", "quantity_produced", "shelf_life_days", "batch_status"]),
                ("recipe", ["recipe_id", "batch_id", "ingredient_type", "allergen_class", "unit_cost", "yield_percent"]),
                ("shipment", ["shipment_id", "batch_id", "distributor_name", "ship_date", "case_count", "shipment_status"]),
            ],
            "vocab": {
                "product_category": ["Dairy", "Baked Goods", "Frozen Entrees", "Canned Vegetables", "Snack Foods", "Beverages", "Confectionery", "Sauces & Condiments", "Breakfast Cereal", "Meat Products"],
                "ingredient_type": ["Flour", "Sugar", "Vegetable Oil", "Salt", "Yeast", "Whey Protein", "Citric Acid", "Natural Flavor", "Soy Lecithin", "Corn Syrup"],
                "allergen_class": ["Milk", "Eggs", "Wheat/Gluten", "Soy", "Tree Nuts", "Peanuts", "Fish", "Shellfish", "Sesame", "None"],
            },
        },
        "tobacco_products": {
            "label": "Tobacco Products",
            "blurb": "A tobacco manufacturer producing cigarettes and related goods; tables track product lots, leaf curing inventory, and excise tax filings.",
            "tables": [
                ("product_lot", ["product_lot_id", "product_type", "manufacture_date", "units_produced", "nicotine_mg", "lot_status"]),
                ("leaf_inventory", ["leaf_inventory_id", "product_lot_id", "leaf_grade", "curing_method", "weight_kg", "moisture_percent"]),
                ("excise_filing", ["excise_filing_id", "product_lot_id", "filing_date", "tax_amount", "carton_count", "filing_status"]),
            ],
            "vocab": {
                "product_type": ["Filtered Cigarettes", "Cigars", "Cigarillos", "Pipe Tobacco", "Roll-Your-Own", "Chewing Tobacco", "Snuff", "Snus", "Nicotine Pouches", "Hookah Tobacco"],
                "leaf_grade": ["Bright Virginia", "Burley", "Oriental", "Maryland", "Dark Fired", "Dark Air-Cured", "Cigar Filler", "Cigar Wrapper", "Cigar Binder", "Reconstituted"],
                "curing_method": ["Flue-Cured", "Air-Cured", "Fire-Cured", "Sun-Cured"],
            },
        },
        "textile_mills": {
            "label": "Textile Mill Products",
            "blurb": "A textile mill spinning yarn and weaving fabric; tables track fabric production runs, fiber inputs, and dyeing operations.",
            "tables": [
                ("fabric_run", ["fabric_run_id", "fabric_type", "weave_pattern", "production_date", "yards_produced", "run_status"]),
                ("fiber_input", ["fiber_input_id", "fabric_run_id", "fiber_type", "yarn_count", "weight_lbs", "unit_cost"]),
                ("dye_lot", ["dye_lot_id", "fabric_run_id", "dye_class", "color_name", "dye_date", "batch_quantity"]),
            ],
            "vocab": {
                "fabric_type": ["Denim", "Twill", "Poplin", "Jersey Knit", "Fleece", "Canvas", "Satin", "Corduroy", "Flannel", "Terry Cloth", "Chambray", "Oxford Cloth"],
                "weave_pattern": ["Plain Weave", "Twill Weave", "Satin Weave", "Basket Weave", "Jacquard", "Dobby", "Herringbone", "Pile Weave"],
                "fiber_type": ["Cotton", "Polyester", "Wool", "Nylon", "Rayon", "Linen", "Acrylic", "Spandex", "Silk", "Hemp"],
                "dye_class": ["Reactive", "Disperse", "Vat", "Direct", "Acid", "Sulfur", "Pigment", "Azoic"],
            },
        },
        "apparel_manufacturing": {
            "label": "Apparel & Finished Fabric Products",
            "blurb": "An apparel manufacturer cutting and sewing finished garments; tables track style orders, material consumption, and sewing line output.",
            "tables": [
                ("style_order", ["style_order_id", "garment_category", "size_range", "order_date", "unit_quantity", "order_status"]),
                ("material_usage", ["material_usage_id", "style_order_id", "fabric_type", "trim_type", "yardage_used", "material_cost"]),
                ("sewing_run", ["sewing_run_id", "style_order_id", "line_number", "run_date", "pieces_completed", "defect_count"]),
            ],
            "vocab": {
                "garment_category": ["T-Shirts", "Dress Shirts", "Jeans", "Trousers", "Jackets", "Dresses", "Skirts", "Activewear", "Outerwear", "Underwear", "Sleepwear", "Suits"],
                "fabric_type": ["Cotton Knit", "Denim", "Polyester Blend", "Wool Suiting", "Fleece", "Chiffon", "Linen", "Spandex Blend", "Twill", "Satin"],
                "trim_type": ["Zippers", "Buttons", "Elastic", "Snaps", "Drawcords", "Hook & Loop", "Rivets", "Labels", "Interfacing", "Bias Tape"],
            },
        },
        "lumber_wood_products": {
            "label": "Lumber & Wood Products (except furniture)",
            "blurb": "A sawmill and wood products operation processing logs into lumber; tables track milling runs, log inputs, and graded lumber inventory.",
            "tables": [
                ("mill_run", ["mill_run_id", "product_type", "wood_species", "run_date", "board_feet", "run_status"]),
                ("log_input", ["log_input_id", "mill_run_id", "log_grade", "diameter_inches", "volume_cubic_feet", "unit_cost"]),
                ("lumber_inventory", ["lumber_inventory_id", "mill_run_id", "lumber_grade", "moisture_content", "piece_count", "stock_status"]),
            ],
            "vocab": {
                "product_type": ["Dimensional Lumber", "Plywood", "Oriented Strand Board", "Particleboard", "Wood Veneer", "Hardwood Flooring", "Wood Shingles", "Laminated Beams", "Wood Pallets", "Treated Posts"],
                "wood_species": ["Douglas Fir", "Southern Pine", "Red Oak", "Maple", "Walnut", "Cherry", "Spruce", "Hemlock", "Cedar", "Poplar", "Birch", "Ash"],
                "lumber_grade": ["Select Structural", "No. 1 Common", "No. 2 Common", "Construction", "Standard", "Utility", "Clear", "FAS", "Select", "No. 1 Shop"],
            },
        },
        "furniture_fixtures": {
            "label": "Furniture & Fixtures",
            "blurb": "A furniture manufacturer building wood and upholstered pieces; tables track product builds, component parts, and finishing operations.",
            "tables": [
                ("furniture_build", ["furniture_build_id", "furniture_category", "frame_material", "build_date", "units_built", "build_status"]),
                ("component_part", ["component_part_id", "furniture_build_id", "part_type", "material_type", "quantity_used", "unit_cost"]),
                ("finishing_job", ["finishing_job_id", "furniture_build_id", "finish_type", "upholstery_fabric", "finish_date", "labor_hours"]),
            ],
            "vocab": {
                "furniture_category": ["Sofas", "Dining Tables", "Chairs", "Bedroom Sets", "Bookcases", "Desks", "Cabinets", "Recliners", "Dressers", "Office Seating", "Coffee Tables", "Nightstands"],
                "frame_material": ["Solid Hardwood", "Plywood", "Engineered Wood", "Steel", "Aluminum", "Particleboard", "Bamboo", "Rattan"],
                "part_type": ["Legs", "Drawer Slides", "Hinges", "Casters", "Seat Cushions", "Armrests", "Shelves", "Backrest", "Springs", "Knobs"],
                "finish_type": ["Lacquer", "Stain", "Varnish", "Paint", "Oil Finish", "Wax", "Powder Coat", "Veneer Laminate"],
                "upholstery_fabric": ["Leather", "Microfiber", "Linen", "Velvet", "Polyester Blend", "Faux Leather", "Chenille", "Cotton Canvas", "Tweed", "Suede"],
            },
        },
        "paper_products": {
            "label": "Paper & Allied Products",
            "blurb": "A paper mill converting pulp into paper and packaging; tables track production reels, pulp furnish inputs, and converted product orders.",
            "tables": [
                ("paper_reel", ["paper_reel_id", "paper_grade", "basis_weight", "production_date", "tonnage", "reel_status"]),
                ("pulp_furnish", ["pulp_furnish_id", "paper_reel_id", "pulp_type", "brightness_percent", "weight_tons", "unit_cost"]),
                ("converted_order", ["converted_order_id", "paper_reel_id", "product_form", "order_date", "unit_quantity", "order_status"]),
            ],
            "vocab": {
                "paper_grade": ["Newsprint", "Bond", "Kraft Liner", "Coated Freesheet", "Tissue", "Corrugated Medium", "Bleached Board", "Cardstock", "Cover Stock", "Glassine", "Label Paper", "Bag Paper"],
                "pulp_type": ["Bleached Kraft", "Unbleached Kraft", "Mechanical", "Recycled Fiber", "Thermomechanical", "Sulfite", "Deinked", "Chemical Hardwood", "Chemical Softwood", "Cotton Linter"],
                "product_form": ["Cut Sheets", "Roll Stock", "Corrugated Boxes", "Paper Bags", "Envelopes", "Folding Cartons", "Tissue Rolls", "Paper Towels", "Labels", "Cardboard Tubes"],
            },
        },
        "printing_publishing": {
            "label": "Printing, Publishing & Allied Industries",
            "blurb": "A commercial printer and publisher producing print materials; tables track print jobs, plate prepress setups, and binding finishing tasks.",
            "tables": [
                ("print_job", ["print_job_id", "print_method", "publication_type", "job_date", "impression_count", "job_status"]),
                ("prepress_setup", ["prepress_setup_id", "print_job_id", "plate_type", "color_mode", "page_count", "setup_cost"]),
                ("bindery_task", ["bindery_task_id", "print_job_id", "binding_type", "finish_date", "finished_quantity", "labor_hours"]),
            ],
            "vocab": {
                "print_method": ["Offset Lithography", "Digital", "Flexography", "Gravure", "Letterpress", "Screen Printing", "Inkjet Web", "Thermography"],
                "publication_type": ["Books", "Magazines", "Newspapers", "Catalogs", "Brochures", "Business Forms", "Packaging", "Direct Mail", "Posters", "Greeting Cards", "Labels", "Calendars"],
                "plate_type": ["Aluminum Offset", "Photopolymer", "Thermal CTP", "Gravure Cylinder", "Flexo Sleeve", "Screen Mesh", "Waterless Plate", "Digital None"],
                "color_mode": ["CMYK Process", "Spot Pantone", "Black & White", "Two-Color", "Hexachrome", "Grayscale"],
                "binding_type": ["Perfect Bound", "Saddle Stitch", "Spiral", "Wire-O", "Case Bound", "Comb Bound", "Tape Bound", "Loose-Leaf"],
            },
        },
        "chemicals_manufacturing": {
            "label": "Chemicals & Allied Products",
            "blurb": "A chemical manufacturer producing industrial and specialty chemicals; tables track reaction batches, raw material feedstocks, and quality assay results.",
            "tables": [
                ("reaction_batch", ["reaction_batch_id", "chemical_class", "process_type", "batch_date", "yield_kg", "batch_status"]),
                ("feedstock", ["feedstock_id", "reaction_batch_id", "raw_material", "hazard_class", "quantity_kg", "unit_cost"]),
                ("quality_assay", ["quality_assay_id", "reaction_batch_id", "assay_type", "purity_percent", "test_date", "result_status"]),
            ],
            "vocab": {
                "chemical_class": ["Petrochemicals", "Industrial Gases", "Polymers & Resins", "Pesticides", "Fertilizers", "Pharmaceuticals", "Adhesives", "Coatings & Paints", "Surfactants", "Solvents", "Pigments & Dyes", "Specialty Additives"],
                "process_type": ["Polymerization", "Distillation", "Esterification", "Hydrogenation", "Oxidation", "Neutralization", "Crystallization", "Fermentation"],
                "raw_material": ["Ethylene", "Benzene", "Ammonia", "Chlorine", "Sulfuric Acid", "Sodium Hydroxide", "Methanol", "Propylene", "Phosphoric Acid", "Titanium Dioxide"],
                "hazard_class": ["Flammable", "Corrosive", "Toxic", "Oxidizer", "Reactive", "Compressed Gas", "Environmental Hazard", "Non-Hazardous"],
                "assay_type": ["Gas Chromatography", "Titration", "HPLC", "Mass Spectrometry", "Spectrophotometry", "Karl Fischer", "Viscosity", "pH Analysis"],
            },
        },
        "petroleum_refining": {
            "label": "Petroleum Refining & Related Industries",
            "blurb": "A petroleum refinery converting crude oil into refined products; tables track refining runs, crude feedstock receipts, and product blends.",
            "tables": [
                ("refining_run", ["refining_run_id", "process_unit", "crude_type", "run_date", "barrels_processed", "run_status"]),
                ("crude_receipt", ["crude_receipt_id", "refining_run_id", "crude_grade", "api_gravity", "volume_barrels", "unit_cost"]),
                ("product_blend", ["product_blend_id", "refining_run_id", "refined_product", "octane_rating", "blend_date", "blend_volume"]),
            ],
            "vocab": {
                "process_unit": ["Atmospheric Distillation", "Vacuum Distillation", "Catalytic Cracking", "Hydrocracking", "Catalytic Reforming", "Alkylation", "Coking", "Hydrotreating", "Isomerization", "Desulfurization"],
                "crude_type": ["Light Sweet", "Heavy Sour", "Medium Sour", "Light Sour", "Extra Heavy", "Condensate", "Synthetic", "Bitumen"],
                "crude_grade": ["West Texas Intermediate", "Brent Blend", "Dubai Crude", "Maya", "Bonny Light", "Urals", "Western Canadian Select", "Arab Light"],
                "refined_product": ["Regular Gasoline", "Premium Gasoline", "Diesel Fuel", "Jet Fuel", "Heating Oil", "Liquefied Petroleum Gas", "Asphalt", "Lubricating Oil", "Naphtha", "Petroleum Coke"],
            },
        },
        "rubber_plastics": {
            "label": "Rubber & Miscellaneous Plastics Products",
            "blurb": "A rubber and plastics products manufacturer using molding and extrusion; tables track molding runs, resin material inputs, and tooling assets.",
            "tables": [
                ("molding_run", ["molding_run_id", "product_category", "process_method", "run_date", "parts_produced", "run_status"]),
                ("resin_input", ["resin_input_id", "molding_run_id", "polymer_type", "additive_type", "weight_lbs", "unit_cost"]),
                ("tooling_asset", ["tooling_asset_id", "molding_run_id", "mold_type", "cavity_count", "acquisition_date", "maintenance_status"]),
            ],
            "vocab": {
                "product_category": ["Injection Molded Parts", "Plastic Packaging", "Rubber Hoses", "Tires", "Gaskets & Seals", "Plastic Film", "Rubber Belts", "Plastic Bottles", "Foam Products", "Vinyl Sheeting", "O-Rings", "Plastic Pipe"],
                "process_method": ["Injection Molding", "Blow Molding", "Extrusion", "Compression Molding", "Thermoforming", "Rotational Molding", "Calendering", "Vulcanization"],
                "polymer_type": ["Polyethylene", "Polypropylene", "PVC", "Polystyrene", "ABS", "Nylon", "Natural Rubber", "SBR", "Nitrile Rubber", "Polycarbonate", "PET", "EPDM"],
                "additive_type": ["Plasticizer", "Colorant", "UV Stabilizer", "Flame Retardant", "Filler", "Antioxidant", "Blowing Agent", "Lubricant"],
                "mold_type": ["Single Cavity", "Multi-Cavity", "Family Mold", "Hot Runner", "Cold Runner", "Insert Mold", "Two-Shot Mold", "Stack Mold"],
            },
        },
        "leather_products": {
            "label": "Leather & Leather Products",
            "blurb": "A leather goods manufacturer tanning hides and producing finished products; tables track tanning batches, hide inputs, and finished goods orders.",
            "tables": [
                ("tanning_batch", ["tanning_batch_id", "leather_type", "tanning_method", "batch_date", "hide_count", "batch_status"]),
                ("hide_input", ["hide_input_id", "tanning_batch_id", "hide_source", "hide_grade", "area_sqft", "unit_cost"]),
                ("finished_goods_order", ["finished_goods_order_id", "tanning_batch_id", "product_category", "order_date", "unit_quantity", "order_status"]),
            ],
            "vocab": {
                "leather_type": ["Full-Grain", "Top-Grain", "Suede", "Nubuck", "Patent Leather", "Split Leather", "Bonded Leather", "Aniline", "Semi-Aniline", "Nappa"],
                "tanning_method": ["Chrome Tanning", "Vegetable Tanning", "Aldehyde Tanning", "Brain Tanning", "Synthetic Tanning", "Combination Tanning", "Oil Tanning", "Alum Tawing"],
                "hide_source": ["Cowhide", "Calfskin", "Goatskin", "Sheepskin", "Pigskin", "Deerskin", "Buffalo", "Lambskin", "Horsehide", "Exotic"],
                "product_category": ["Footwear", "Handbags", "Belts", "Wallets", "Jackets", "Gloves", "Luggage", "Watch Straps", "Furniture Upholstery", "Saddlery"],
            },
        },
        "stone_clay_glass": {
            "label": "Stone, Clay, Glass & Concrete Products",
            "blurb": "A manufacturer of stone, clay, glass, and concrete building products; tables track production batches, mineral material inputs, and kiln or curing operations.",
            "tables": [
                ("production_batch", ["production_batch_id", "product_category", "forming_method", "production_date", "units_produced", "batch_status"]),
                ("mineral_input", ["mineral_input_id", "production_batch_id", "material_type", "particle_grade", "weight_tons", "unit_cost"]),
                ("kiln_operation", ["kiln_operation_id", "production_batch_id", "process_type", "peak_temp_c", "operation_date", "duration_hours"]),
            ],
            "vocab": {
                "product_category": ["Flat Glass", "Container Glass", "Brick", "Ceramic Tile", "Ready-Mix Concrete", "Concrete Block", "Cement", "Pottery", "Gypsum Board", "Cut Stone", "Refractory Brick", "Fiberglass"],
                "forming_method": ["Float Process", "Pressing", "Extrusion", "Casting", "Slip Casting", "Dry Pressing", "Blowing", "Molding"],
                "material_type": ["Silica Sand", "Limestone", "Clay", "Feldspar", "Portland Cement", "Gravel Aggregate", "Soda Ash", "Kaolin", "Gypsum", "Dolomite"],
                "particle_grade": ["Coarse", "Medium", "Fine", "Ultra-Fine", "Granular", "Powder", "Pelletized", "Lump"],
                "process_type": ["Firing", "Sintering", "Annealing", "Curing", "Calcining", "Vitrification", "Tempering", "Drying"],
            },
        },
        "primary_metals": {
            "label": "Primary Metal Industries",
            "blurb": "A primary metals producer smelting and casting metal; tables track heat melt runs, ore and scrap charges, and cast product output.",
            "tables": [
                ("heat_run", ["heat_run_id", "metal_type", "furnace_type", "melt_date", "tonnage", "heat_status"]),
                ("charge_material", ["charge_material_id", "heat_run_id", "input_material", "alloy_grade", "weight_tons", "unit_cost"]),
                ("cast_product", ["cast_product_id", "heat_run_id", "product_form", "cast_date", "piece_count", "quality_status"]),
            ],
            "vocab": {
                "metal_type": ["Carbon Steel", "Stainless Steel", "Aluminum", "Copper", "Cast Iron", "Zinc", "Lead", "Nickel Alloy", "Titanium", "Brass", "Bronze", "Magnesium"],
                "furnace_type": ["Electric Arc", "Basic Oxygen", "Blast Furnace", "Induction", "Cupola", "Reverberatory", "Crucible", "Vacuum Arc"],
                "input_material": ["Iron Ore", "Steel Scrap", "Bauxite", "Coke", "Limestone Flux", "Ferroalloys", "Pig Iron", "Copper Concentrate", "Aluminum Scrap", "Direct Reduced Iron"],
                "alloy_grade": ["A36 Structural", "304 Stainless", "316 Stainless", "6061 Aluminum", "1018 Mild Steel", "4140 Alloy", "C11000 Copper", "A356 Aluminum", "Ductile Iron", "Gray Iron"],
                "product_form": ["Billets", "Slabs", "Blooms", "Ingots", "Sheet", "Plate", "Bar", "Wire Rod", "Castings", "Pipe & Tube"],
            },
        },
        "fabricated_metals": {
            "label": "Fabricated Metal Products",
            "blurb": "A metal fabrication shop cutting, forming, and welding metal products; tables track fabrication work orders, metal stock inputs, and finishing or coating jobs.",
            "tables": [
                ("work_order", ["work_order_id", "product_category", "fabrication_process", "order_date", "units_produced", "order_status"]),
                ("metal_stock", ["metal_stock_id", "work_order_id", "metal_grade", "stock_form", "weight_lbs", "unit_cost"]),
                ("coating_job", ["coating_job_id", "work_order_id", "coating_type", "finish_date", "surface_area_sqft", "labor_hours"]),
            ],
            "vocab": {
                "product_category": ["Structural Steel", "Sheet Metal Parts", "Hand Tools", "Fasteners", "Wire Products", "Metal Stampings", "Pressure Vessels", "Metal Cans", "Springs", "Valves & Fittings", "Hardware", "Cutlery"],
                "fabrication_process": ["Laser Cutting", "CNC Machining", "Stamping", "Welding", "Bending", "Punching", "Forging", "Roll Forming", "Shearing", "Plasma Cutting"],
                "metal_grade": ["A36 Carbon Steel", "304 Stainless", "316 Stainless", "6061 Aluminum", "5052 Aluminum", "Galvanized Steel", "1008 Cold Rolled", "Hot Rolled Steel", "Brass", "Copper"],
                "stock_form": ["Sheet", "Plate", "Bar Stock", "Tube", "Angle", "Channel", "Coil", "Rod", "Pipe", "Wire"],
                "coating_type": ["Powder Coat", "Galvanizing", "Anodizing", "Electroplating", "Wet Paint", "Passivation", "Black Oxide", "Chrome Plating"],
            },
        },
        "machinery_computer_equipment": {
            "label": "Industrial & Commercial Machinery & Computer Equipment",
            "blurb": "A manufacturer of industrial machinery and computer equipment; tables track assembly orders, sourced components, and quality test results.",
            "tables": [
                ("assembly_order", ["assembly_order_id", "machine_category", "assembly_line", "order_date", "units_assembled", "order_status"]),
                ("component_part", ["component_part_id", "assembly_order_id", "component_type", "supplier_name", "quantity_used", "unit_cost"]),
                ("quality_test", ["quality_test_id", "assembly_order_id", "test_type", "test_date", "pass_count", "test_status"]),
            ],
            "vocab": {
                "machine_category": ["Machine Tools", "Pumps & Compressors", "Construction Equipment", "Agricultural Machinery", "HVAC Equipment", "Servers & Computers", "Printing Presses", "Packaging Machinery", "Material Handling", "Turbines", "Bearings", "Industrial Robots"],
                "component_type": ["Electric Motors", "Bearings", "Gears", "Hydraulic Cylinders", "Circuit Boards", "Sensors", "Pumps", "Valves", "Shafts", "Couplings", "Power Supplies", "Control Panels"],
                "test_type": ["Functional Test", "Load Test", "Vibration Test", "Pressure Test", "Burn-In Test", "Calibration", "Leak Test", "Performance Benchmark"],
            },
        },
        "electronic_equipment": {
            "label": "Electronic & Other Electrical Equipment",
            "blurb": "A manufacturer of electronic and electrical equipment; tables track production lots, electronic components, and circuit board assembly runs.",
            "tables": [
                ("production_lot", ["production_lot_id", "product_category", "production_date", "units_produced", "unit_cost", "lot_status"]),
                ("component_inventory", ["component_inventory_id", "production_lot_id", "component_type", "package_type", "quantity_used", "supplier_name"]),
                ("assembly_run", ["assembly_run_id", "production_lot_id", "assembly_method", "board_type", "run_date", "defect_count"]),
            ],
            "vocab": {
                "product_category": ["Semiconductors", "Household Appliances", "Lighting Fixtures", "Batteries", "Electric Motors", "Transformers", "Consumer Electronics", "Switchgear", "Wiring Devices", "Power Tools", "Audio Equipment", "Capacitors"],
                "component_type": ["Resistors", "Capacitors", "Integrated Circuits", "Diodes", "Transistors", "Inductors", "Connectors", "Microcontrollers", "LEDs", "Relays", "Crystals", "Transformers"],
                "package_type": ["Surface Mount", "Through-Hole", "BGA", "QFP", "SOIC", "DIP", "Chip Scale", "Axial Lead"],
                "assembly_method": ["SMT Pick-and-Place", "Wave Soldering", "Reflow Soldering", "Hand Soldering", "Conformal Coating", "Press Fit", "Wire Bonding"],
                "board_type": ["Single-Sided PCB", "Double-Sided PCB", "Multilayer PCB", "Flex PCB", "Rigid-Flex", "Aluminum Backed", "HDI Board"],
            },
        },
        "transportation_equipment": {
            "label": "Transportation Equipment",
            "blurb": "A manufacturer of vehicles and transportation equipment; tables track vehicle build orders, sourced parts, and final inspection records.",
            "tables": [
                ("build_order", ["build_order_id", "vehicle_type", "assembly_plant", "build_date", "units_built", "order_status"]),
                ("vehicle_part", ["vehicle_part_id", "build_order_id", "part_category", "supplier_name", "quantity_used", "unit_cost"]),
                ("inspection_record", ["inspection_record_id", "build_order_id", "inspection_type", "inspection_date", "defect_count", "inspection_status"]),
            ],
            "vocab": {
                "vehicle_type": ["Passenger Cars", "Light Trucks", "Heavy Trucks", "Motorcycles", "Aircraft", "Ships & Boats", "Railroad Cars", "Buses", "Trailers", "Recreational Vehicles", "Spacecraft", "Military Vehicles"],
                "part_category": ["Engines", "Transmissions", "Body Panels", "Suspension", "Brakes", "Electrical Systems", "Tires & Wheels", "Interior Trim", "Fuel Systems", "Exhaust Systems", "Steering", "Chassis"],
                "inspection_type": ["Road Test", "Paint Inspection", "Weld Inspection", "Electrical Check", "Emissions Test", "Safety Compliance", "Fit & Finish", "Leak Test"],
            },
        },
        "instruments": {
            "label": "Measuring, Analyzing & Controlling Instruments",
            "blurb": "A manufacturer of precision measuring and analytical instruments; tables track instrument builds, precision components, and calibration certifications.",
            "tables": [
                ("instrument_build", ["instrument_build_id", "instrument_category", "build_date", "units_built", "unit_cost", "build_status"]),
                ("precision_component", ["precision_component_id", "instrument_build_id", "component_type", "tolerance_class", "quantity_used", "supplier_name"]),
                ("calibration_cert", ["calibration_cert_id", "instrument_build_id", "calibration_standard", "calibration_date", "accuracy_rating", "cert_status"]),
            ],
            "vocab": {
                "instrument_category": ["Pressure Gauges", "Thermometers", "Multimeters", "Oscilloscopes", "Flow Meters", "Spectrometers", "Microscopes", "Surgical Instruments", "Navigation Systems", "Scales & Balances", "Gas Analyzers", "Calipers"],
                "component_type": ["Sensors", "Transducers", "Optical Lenses", "Precision Gears", "Display Modules", "Probes", "Amplifier Circuits", "Quartz Crystals", "Strain Gauges", "Thermocouples"],
                "tolerance_class": ["Class 0", "Class 1", "Class 2", "Class 3", "Precision Grade", "Laboratory Grade", "Industrial Grade", "Reference Grade"],
                "calibration_standard": ["NIST Traceable", "ISO 17025", "ASTM", "DIN", "JIS", "MIL-STD", "Manufacturer Standard", "Factory Reference"],
            },
        },
        "misc_manufacturing": {
            "label": "Miscellaneous Manufacturing",
            "blurb": "A diversified manufacturer of miscellaneous finished goods; tables track production orders, material inputs, and packaging or shipping records.",
            "tables": [
                ("production_order", ["production_order_id", "product_category", "production_date", "units_produced", "unit_cost", "order_status"]),
                ("material_input", ["material_input_id", "production_order_id", "material_type", "quantity_used", "unit_cost", "supplier_name"]),
                ("packaging_record", ["packaging_record_id", "production_order_id", "package_type", "pack_date", "carton_count", "shipment_status"]),
            ],
            "vocab": {
                "product_category": ["Jewelry", "Toys & Games", "Sporting Goods", "Musical Instruments", "Pens & Pencils", "Brooms & Brushes", "Signs & Displays", "Costume Jewelry", "Buttons & Notions", "Caskets", "Dolls", "Umbrellas"],
                "material_type": ["Plastic Resin", "Sheet Metal", "Wood", "Glass Beads", "Precious Metal", "Synthetic Fiber", "Rubber", "Paperboard", "Foam", "Ceramic", "Wire", "Felt"],
                "package_type": ["Blister Pack", "Clamshell", "Boxed", "Shrink Wrap", "Bagged", "Bulk Carton", "Display Box", "Gift Box"],
            },
        },
    },
},
"transportation_communications_utilities": {
    "label": "Transportation, Communications & Utilities",
    "subs": {
        "railroad_transportation": {
            "label": "Railroad Transportation",
            "blurb": "Freight and passenger rail carriers operating locomotives over track networks; tables track rail cars, scheduled trains, and the shipments hauled along each route.",
            "tables": [
                ("rail_car", ["rail_car_id", "car_type", "reporting_mark", "capacity_tons", "build_date", "ownership_type", "status"]),
                ("train_run", ["train_run_id", "rail_car_id", "departure_date", "origin_yard", "destination_yard", "track_class", "distance_miles", "status"]),
                ("rail_shipment", ["rail_shipment_id", "train_run_id", "commodity_class", "weight_tons", "freight_charge", "ship_date", "hazmat_flag"]),
            ],
            "vocab": {
                "car_type": ["Boxcar", "Hopper", "Gondola", "Tank Car", "Flatcar", "Refrigerated Car", "Auto Rack", "Centerbeam", "Well Car", "Covered Hopper", "Stock Car", "Caboose"],
                "track_class": ["Class 1", "Class 2", "Class 3", "Class 4", "Class 5", "Excepted", "Yard Limit", "Mainline", "Branch Line", "Siding"],
                "commodity_class": ["Coal", "Grain", "Intermodal", "Chemicals", "Automotive", "Lumber", "Crushed Stone", "Petroleum", "Metals", "Paper", "Food Products", "Containers"],
            },
        },
        "transit_passenger_transport": {
            "label": "Local & Suburban Transit",
            "blurb": "Urban and suburban passenger transit operators running buses, light rail, and commuter services along fixed routes; tables track vehicles, routes, and fare-paying trips.",
            "tables": [
                ("transit_vehicle", ["transit_vehicle_id", "vehicle_mode", "fleet_number", "seat_capacity", "in_service_date", "fuel_type", "status"]),
                ("transit_route", ["transit_route_id", "transit_vehicle_id", "route_type", "service_zone", "headway_minutes", "route_length_miles", "status"]),
                ("transit_trip", ["transit_trip_id", "transit_route_id", "trip_date", "boardings_count", "fare_class", "fare_amount", "on_time_flag"]),
            ],
            "vocab": {
                "vehicle_mode": ["Diesel Bus", "Electric Bus", "Trolleybus", "Light Rail", "Streetcar", "Commuter Rail", "Subway", "Cable Car", "Ferry Shuttle", "Paratransit Van", "Articulated Bus", "Monorail"],
                "route_type": ["Local", "Express", "Limited Stop", "Circulator", "Feeder", "Crosstown", "Rapid", "Night Owl", "Shuttle", "Commuter"],
                "fuel_type": ["Diesel", "Compressed Natural Gas", "Battery Electric", "Hybrid Diesel-Electric", "Hydrogen Fuel Cell", "Biodiesel", "Overhead Electric", "Liquefied Natural Gas"],
                "fare_class": ["Adult", "Senior", "Student", "Child", "Disabled", "Day Pass", "Monthly Pass", "Reduced Fare", "Free Transfer", "Express Surcharge"],
            },
        },
        "motor_freight_warehousing": {
            "label": "Motor Freight Transportation & Warehousing",
            "blurb": "Trucking carriers and warehouse operators moving and storing goods by road; tables track trucks, freight shipments, and warehouse storage of inventory.",
            "tables": [
                ("freight_truck", ["freight_truck_id", "truck_class", "vin", "max_payload_lbs", "purchase_date", "trailer_type", "status"]),
                ("freight_shipment", ["freight_shipment_id", "freight_truck_id", "service_level", "weight_lbs", "freight_rate", "pickup_date", "delivery_status"]),
                ("warehouse_storage", ["warehouse_storage_id", "freight_shipment_id", "storage_type", "pallet_count", "storage_fee", "intake_date", "zone_code"]),
            ],
            "vocab": {
                "truck_class": ["Class 3 Light Duty", "Class 5 Medium Duty", "Class 6 Medium Duty", "Class 7 Heavy Duty", "Class 8 Tractor", "Box Truck", "Cargo Van", "Day Cab", "Sleeper Cab", "Straight Truck"],
                "trailer_type": ["Dry Van", "Reefer", "Flatbed", "Step Deck", "Tanker", "Lowboy", "Conestoga", "Curtain Side", "Intermodal Container", "Double Drop"],
                "service_level": ["Standard LTL", "Truckload", "Expedited", "Same Day", "Next Day", "Economy", "White Glove", "Hot Shot", "Dedicated", "Drayage"],
                "storage_type": ["Ambient", "Refrigerated", "Frozen", "Bonded", "Hazmat", "Bulk", "Rack Storage", "Floor Stacked", "Climate Controlled", "Cross Dock"],
            },
        },
        "postal_service": {
            "label": "United States Postal Service",
            "blurb": "National postal operator processing and delivering mail and parcels through facilities and carrier routes; tables track mail pieces, delivery routes, and processing facilities.",
            "tables": [
                ("mail_piece", ["mail_piece_id", "mail_class", "weight_oz", "postage_amount", "induction_date", "tracking_status", "destination_zip"]),
                ("delivery_route", ["delivery_route_id", "mail_piece_id", "route_type", "carrier_mode", "stop_count", "route_miles", "service_date"]),
                ("processing_facility", ["processing_facility_id", "delivery_route_id", "facility_type", "throughput_volume", "operating_cost", "report_date", "region_code"]),
            ],
            "vocab": {
                "mail_class": ["First-Class Mail", "Priority Mail", "Priority Mail Express", "USPS Ground Advantage", "Media Mail", "Marketing Mail", "Periodicals", "Bound Printed Matter", "Library Mail", "Certified Mail", "Registered Mail"],
                "route_type": ["City Delivery", "Rural Route", "Highway Contract", "Post Office Box", "Business District", "Collection Route", "Parcel Post", "Express Route", "Combined Route", "Auxiliary Route"],
                "carrier_mode": ["Walking", "Curbline", "Mounted", "Park and Loop", "Central Delivery", "Cluster Box", "Vehicle Delivery", "Foot Carry", "Dismount"],
                "facility_type": ["Processing & Distribution Center", "Network Distribution Center", "Sectional Center Facility", "Bulk Mail Center", "Post Office", "Annex", "Air Mail Facility", "International Service Center", "Sorting Hub", "Carrier Annex"],
            },
        },
        "water_transportation": {
            "label": "Water Transportation",
            "blurb": "Maritime carriers operating vessels to move cargo and passengers over oceans and inland waterways; tables track vessels, voyages, and the cargo manifested on each voyage.",
            "tables": [
                ("vessel", ["vessel_id", "vessel_type", "imo_number", "gross_tonnage", "flag_state", "build_date", "status"]),
                ("voyage", ["voyage_id", "vessel_id", "route_type", "origin_port", "destination_port", "departure_date", "distance_nm", "status"]),
                ("cargo_manifest", ["cargo_manifest_id", "voyage_id", "cargo_type", "weight_tons", "freight_revenue", "load_date", "container_count"]),
            ],
            "vocab": {
                "vessel_type": ["Container Ship", "Bulk Carrier", "Oil Tanker", "Chemical Tanker", "LNG Carrier", "Roll-on/Roll-off", "Car Carrier", "Tugboat", "Barge", "Cruise Ship", "Ferry", "General Cargo"],
                "route_type": ["Transpacific", "Transatlantic", "Coastal", "Inland Waterway", "Intracoastal", "Great Lakes", "Short Sea", "Round-the-World", "Feeder Service", "River Barge"],
                "cargo_type": ["Containerized", "Dry Bulk", "Liquid Bulk", "Breakbulk", "Project Cargo", "Refrigerated", "Crude Oil", "Grain", "Coal", "Iron Ore", "Vehicles", "Chemicals"],
                "flag_state": ["Panama", "Liberia", "Marshall Islands", "Singapore", "Malta", "Bahamas", "Hong Kong", "Greece", "Cyprus", "United States", "Norway", "Japan"],
            },
        },
        "air_transportation": {
            "label": "Air Transportation",
            "blurb": "Airlines and air cargo carriers operating aircraft on scheduled flights; tables track aircraft, flights, and passenger or cargo bookings on each flight.",
            "tables": [
                ("aircraft", ["aircraft_id", "aircraft_type", "tail_number", "seat_capacity", "delivery_date", "service_category", "status"]),
                ("flight", ["flight_id", "aircraft_id", "flight_type", "origin_airport", "destination_airport", "departure_date", "block_hours", "status"]),
                ("flight_booking", ["flight_booking_id", "flight_id", "fare_class", "passenger_count", "ticket_revenue", "booking_date", "payment_status"]),
            ],
            "vocab": {
                "aircraft_type": ["Boeing 737", "Boeing 777", "Boeing 787", "Airbus A320", "Airbus A321neo", "Airbus A350", "Embraer E175", "Bombardier CRJ900", "Boeing 767 Freighter", "ATR 72", "Cessna Caravan", "Airbus A380"],
                "flight_type": ["Domestic Scheduled", "International Scheduled", "Regional", "Long Haul", "Short Haul", "Charter", "Cargo", "Codeshare", "Red Eye", "Repositioning"],
                "service_category": ["Mainline", "Regional", "Wide-Body", "Narrow-Body", "Freighter", "Turboprop", "Business Jet", "Low-Cost", "Ultra Long Range"],
                "fare_class": ["First", "Business", "Premium Economy", "Economy", "Basic Economy", "Award", "Group", "Refundable", "Promotional", "Standby"],
            },
        },
        "pipelines": {
            "label": "Pipelines (except natural gas)",
            "blurb": "Operators transporting crude oil, refined products, and other liquids through long-distance pipeline networks; tables track pipeline segments, throughput batches, and pump stations.",
            "tables": [
                ("pipeline_segment", ["pipeline_segment_id", "commodity_carried", "diameter_inches", "length_miles", "max_pressure_psi", "commission_date", "status"]),
                ("throughput_batch", ["throughput_batch_id", "pipeline_segment_id", "product_grade", "volume_barrels", "tariff_charge", "inject_date", "delivery_status"]),
                ("pump_station", ["pump_station_id", "pipeline_segment_id", "station_type", "horsepower", "operating_cost", "inspection_date", "region_code"]),
            ],
            "vocab": {
                "commodity_carried": ["Crude Oil", "Refined Gasoline", "Diesel Fuel", "Jet Fuel", "Liquefied Petroleum Gas", "Ethanol", "Natural Gas Liquids", "Heating Oil", "Naphtha", "Bitumen Blend", "Anhydrous Ammonia", "Carbon Dioxide"],
                "product_grade": ["West Texas Intermediate", "Brent Blend", "Light Sweet", "Heavy Sour", "Conventional Gasoline", "Premium Gasoline", "Ultra Low Sulfur Diesel", "Jet A", "Propane", "Butane"],
                "station_type": ["Mainline Pump", "Booster Station", "Origin Station", "Delivery Station", "Injection Station", "Metering Station", "Heater Station", "Relief Station", "Breakout Tank Farm"],
            },
        },
        "transportation_services": {
            "label": "Transportation Services",
            "blurb": "Freight forwarders, brokers, and travel arrangement firms coordinating shipments and bookings across carriers; tables track client bookings, carrier assignments, and billing invoices.",
            "tables": [
                ("freight_booking", ["freight_booking_id", "service_type", "mode_of_transport", "origin_location", "destination_location", "booking_date", "declared_value", "status"]),
                ("carrier_assignment", ["carrier_assignment_id", "freight_booking_id", "carrier_name", "equipment_type", "assigned_rate", "assign_date", "transit_status"]),
                ("billing_invoice", ["billing_invoice_id", "carrier_assignment_id", "invoice_type", "billed_amount", "issue_date", "payment_terms", "payment_status"]),
            ],
            "vocab": {
                "service_type": ["Freight Forwarding", "Customs Brokerage", "Freight Brokerage", "Third-Party Logistics", "Travel Arrangement", "Cargo Inspection", "Packing & Crating", "Vehicle Transport", "Courier Coordination", "Cargo Insurance"],
                "mode_of_transport": ["Ocean Freight", "Air Freight", "Truckload", "Less Than Truckload", "Rail Intermodal", "Multimodal", "Courier", "Drayage", "Barge", "Express Parcel"],
                "equipment_type": ["40ft Container", "20ft Container", "Reefer Container", "Dry Van", "Flatbed", "Air ULD", "Tanker", "Step Deck", "Bulk Trailer", "Open Top Container"],
                "invoice_type": ["Freight Charges", "Accessorial", "Customs Duty", "Fuel Surcharge", "Demurrage", "Detention", "Storage", "Brokerage Fee", "Insurance Premium", "Documentation Fee"],
            },
        },
        "communications": {
            "label": "Communications",
            "blurb": "Telephone, broadcast, and broadband providers delivering voice, data, and media services to subscribers; tables track service plans, customer subscriptions, and usage records.",
            "tables": [
                ("service_plan", ["service_plan_id", "service_category", "plan_name", "monthly_price", "data_allowance_gb", "launch_date", "status"]),
                ("subscription", ["subscription_id", "service_plan_id", "connection_type", "activation_date", "contract_term_months", "monthly_charge", "account_status"]),
                ("usage_record", ["usage_record_id", "subscription_id", "usage_type", "usage_quantity", "billed_amount", "usage_date", "overage_flag"]),
            ],
            "vocab": {
                "service_category": ["Mobile Wireless", "Broadband Internet", "Fixed-Line Telephone", "Cable Television", "Satellite TV", "Voice over IP", "Fiber Internet", "Streaming Media", "Radio Broadcast", "Business Data Lines", "Paging Service"],
                "connection_type": ["Fiber to the Home", "Coaxial Cable", "DSL", "5G Wireless", "4G LTE", "Satellite", "Fixed Wireless", "Dial-Up", "Ethernet", "Hybrid Fiber-Coax"],
                "usage_type": ["Voice Minutes", "Text Messages", "Mobile Data", "Broadband Data", "International Roaming", "Premium Channels", "Video on Demand", "Long Distance", "Conference Call", "Cloud Storage"],
            },
        },
        "utilities_sanitary": {
            "label": "Electric, Gas & Sanitary Services",
            "blurb": "Regulated utilities generating and distributing electricity, gas, and water and providing sanitary services; tables track utility accounts, metered consumption, and customer billing.",
            "tables": [
                ("utility_account", ["utility_account_id", "utility_type", "service_class", "meter_number", "connection_date", "rate_schedule", "account_status"]),
                ("meter_reading", ["meter_reading_id", "utility_account_id", "reading_type", "consumption_amount", "unit_of_measure", "reading_date", "estimated_flag"]),
                ("utility_bill", ["utility_bill_id", "meter_reading_id", "billing_period", "amount_due", "issue_date", "payment_status", "late_fee"]),
            ],
            "vocab": {
                "utility_type": ["Electric", "Natural Gas", "Water", "Wastewater", "Steam", "Sewage Treatment", "Refuse Collection", "Recycling", "Stormwater", "District Heating", "District Cooling"],
                "service_class": ["Residential", "Commercial", "Industrial", "Agricultural", "Municipal", "Street Lighting", "Large Power", "Small General Service", "Irrigation", "Public Authority"],
                "reading_type": ["Actual", "Estimated", "Smart Meter", "Manual Read", "Remote Read", "Customer Read", "Final Read", "Check Read", "Demand Read", "Interval Read"],
                "rate_schedule": ["Flat Rate", "Tiered Block", "Time-of-Use", "Demand Charge", "Seasonal Rate", "Net Metering", "Lifeline Rate", "Interruptible", "Real-Time Pricing", "Fixed Monthly"],
            },
        },
    },
},
"wholesale_trade": {
    "label": "Wholesale Trade",
    "subs": {
        "wholesale_durable": {
            "label": "Wholesale Trade - Durable Goods",
            "blurb": "A wholesale distributor of durable goods such as machinery, vehicles, electronics, and construction materials, where tables track product inventory, customer orders, and shipments to retailers and businesses.",
            "tables": [
                ("product", ["product_id", "product_name", "product_category", "unit_price", "units_in_stock", "warehouse_location", "reorder_level", "status"]),
                ("customer_order", ["order_id", "product_id", "customer_name", "order_date", "quantity", "order_total", "sales_channel", "order_status"]),
                ("shipment", ["shipment_id", "order_id", "ship_date", "carrier", "freight_cost", "shipment_status", "tracking_number"]),
                ("supplier", ["supplier_id", "product_id", "supplier_name", "lead_time_days", "purchase_cost", "country_of_origin"]),
            ],
            "vocab": {
                "product_category": ["Industrial Machinery", "Motor Vehicles & Parts", "Electronic Components", "Construction Materials", "Furniture & Fixtures", "Household Appliances", "Computer Hardware", "Sporting Goods", "Metals & Minerals", "Farm Equipment", "HVAC Equipment", "Lumber & Plywood"],
                "sales_channel": ["Direct Sales", "Distributor Network", "Online B2B Portal", "Field Sales Rep", "Catalog Order", "Trade Show", "Drop Ship", "Wholesale Club"],
                "carrier": ["FedEx Freight", "UPS Ground", "XPO Logistics", "Old Dominion", "Estes Express", "J.B. Hunt", "Schneider National", "YRC Freight"],
            },
        },
        "wholesale_nondurable": {
            "label": "Wholesale Trade - Nondurable Goods",
            "blurb": "A wholesale distributor of nondurable goods such as food, beverages, apparel, paper, and chemicals, where tables track perishable inventory lots, distribution orders, and deliveries to retail and foodservice clients.",
            "tables": [
                ("goods_item", ["item_id", "item_name", "goods_type", "unit_price", "quantity_on_hand", "storage_condition", "expiration_date", "status"]),
                ("distribution_order", ["order_id", "item_id", "client_name", "order_date", "case_quantity", "order_amount", "client_segment", "order_status"]),
                ("delivery", ["delivery_id", "order_id", "delivery_date", "route_name", "delivery_fee", "temperature_control", "delivery_status"]),
                ("inventory_lot", ["lot_id", "item_id", "received_date", "lot_quantity", "batch_number", "supplier_name"]),
            ],
            "vocab": {
                "goods_type": ["Packaged Foods", "Fresh Produce", "Dairy Products", "Frozen Foods", "Beverages", "Apparel & Textiles", "Paper Products", "Pharmaceuticals", "Tobacco Products", "Industrial Chemicals", "Cleaning Supplies", "Health & Beauty Aids"],
                "storage_condition": ["Ambient Dry", "Refrigerated", "Frozen", "Climate Controlled", "Hazardous Storage", "Cool & Dark", "Humidity Controlled", "Bonded Warehouse"],
                "client_segment": ["Grocery Retail", "Foodservice", "Convenience Store", "Restaurant Chain", "Hospitality", "Institutional", "Pharmacy", "Discount Retail"],
                "temperature_control": ["Dry Van", "Refrigerated Reefer", "Frozen Reefer", "Insulated", "Multi-Temp", "Ambient"],
            },
        },
    },
},
"retail_trade": {
    "label": "Retail Trade",
    "subs": {
        "building_materials_retail": {
            "label": "Building Materials, Hardware & Garden",
            "blurb": "A home improvement and hardware retailer selling lumber, tools, and garden supplies, tracking store inventory, customer sales orders, and contractor pro accounts.",
            "tables": [
                ("product", ["product_id", "sku", "product_name", "product_category", "unit_price", "stock_quantity", "brand", "unit_of_measure"]),
                ("sales_order", ["order_id", "product_id", "order_date", "quantity", "total_amount", "fulfillment_method", "status"]),
                ("contractor_account", ["account_id", "order_id", "trade_specialty", "credit_limit", "discount_tier", "opened_date"]),
            ],
            "vocab": {
                "product_category": ["Lumber & Composites", "Power Tools", "Hand Tools", "Plumbing", "Electrical", "Paint & Sundries", "Garden & Nursery", "Fasteners & Hardware", "Flooring & Tile", "Building Materials", "Lighting & Fans", "Outdoor Power Equipment"],
                "unit_of_measure": ["Each", "Linear Foot", "Board Foot", "Square Foot", "Bag", "Box", "Gallon", "Pound", "Bundle", "Sheet"],
                "fulfillment_method": ["In-Store Pickup", "Curbside Pickup", "Home Delivery", "Job Site Delivery", "Ship to Store", "Truck Rental Haul"],
                "trade_specialty": ["General Contractor", "Plumber", "Electrician", "Landscaper", "Roofer", "Carpenter", "HVAC Technician", "Painter", "Mason", "Flooring Installer"],
                "discount_tier": ["Standard", "Bronze Pro", "Silver Pro", "Gold Pro", "Platinum Pro", "Volume Bid"],
            },
        },
        "general_merchandise": {
            "label": "General Merchandise Stores",
            "blurb": "A department and discount store chain selling a broad mix of goods, tracking departmental product lines, point-of-sale transactions, and loyalty program members.",
            "tables": [
                ("merchandise_item", ["item_id", "sku", "item_name", "department", "retail_price", "on_hand_quantity", "supplier_name"]),
                ("pos_transaction", ["transaction_id", "item_id", "transaction_date", "quantity_sold", "line_total", "payment_method", "register_number"]),
                ("loyalty_member", ["member_id", "transaction_id", "membership_tier", "points_earned", "enrollment_date", "status"]),
            ],
            "vocab": {
                "department": ["Apparel", "Electronics", "Home & Kitchen", "Toys & Games", "Health & Beauty", "Grocery", "Sporting Goods", "Automotive", "Garden & Patio", "Pet Supplies", "Office & School", "Seasonal"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "Store Gift Card", "Mobile Wallet", "Store Credit Card", "EBT/SNAP", "Buy Now Pay Later"],
                "membership_tier": ["Basic", "Plus", "Premium", "VIP", "Employee", "Senior"],
            },
        },
        "food_stores": {
            "label": "Food Stores",
            "blurb": "A grocery supermarket selling fresh and packaged foods, tracking product inventory by aisle, checkout sales lines, and weekly promotional pricing events.",
            "tables": [
                ("grocery_product", ["grocery_product_id", "upc_code", "product_name", "food_category", "shelf_price", "stock_quantity", "storage_type", "supplier_name"]),
                ("checkout_line", ["checkout_line_id", "grocery_product_id", "sale_date", "quantity", "extended_price", "payment_method", "lane_number"]),
                ("promotion", ["promotion_id", "grocery_product_id", "promo_type", "discount_amount", "start_date", "end_date", "status"]),
            ],
            "vocab": {
                "food_category": ["Produce", "Dairy & Eggs", "Meat & Seafood", "Bakery", "Frozen Foods", "Pantry & Dry Goods", "Beverages", "Snacks & Candy", "Deli & Prepared", "Health Foods", "Baby & Pet", "Household & Cleaning"],
                "storage_type": ["Ambient", "Refrigerated", "Frozen", "Fresh Produce", "Deli Case", "Bulk Bin"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "EBT/SNAP", "WIC Voucher", "Mobile Wallet", "Store Gift Card", "Check"],
                "promo_type": ["BOGO", "Percent Off", "Dollar Off", "Loyalty Price", "Manager's Special", "Weekly Circular", "Bulk Discount", "Clearance"],
            },
        },
        "automotive_dealers": {
            "label": "Automotive Dealers & Gas Stations",
            "blurb": "A vehicle dealership with an attached service center and fuel station, tracking vehicle inventory, customer sales deals, and service repair orders.",
            "tables": [
                ("vehicle", ["vehicle_id", "vin", "make_model", "body_style", "model_year", "listing_price", "mileage", "fuel_type"]),
                ("sales_deal", ["deal_id", "vehicle_id", "sale_date", "sale_price", "financing_type", "trade_in_value", "status"]),
                ("service_order", ["service_order_id", "vehicle_id", "service_date", "service_type", "labor_hours", "total_charge", "status"]),
            ],
            "vocab": {
                "body_style": ["Sedan", "SUV", "Pickup Truck", "Coupe", "Hatchback", "Minivan", "Convertible", "Crossover", "Wagon", "Cargo Van"],
                "fuel_type": ["Gasoline", "Diesel", "Hybrid", "Plug-in Hybrid", "Electric", "Flex Fuel", "Compressed Natural Gas"],
                "financing_type": ["Cash", "Bank Loan", "Dealer Financing", "Lease", "Manufacturer 0% APR", "Credit Union Loan", "Buy Here Pay Here"],
                "service_type": ["Oil Change", "Tire Rotation", "Brake Service", "Engine Diagnostic", "Transmission Repair", "Battery Replacement", "Recall Repair", "State Inspection", "AC Service", "Scheduled Maintenance"],
            },
        },
        "apparel_stores": {
            "label": "Apparel & Accessory Stores",
            "blurb": "A clothing and accessories retailer selling seasonal fashion lines, tracking SKU-level garment inventory, customer purchases, and product return records.",
            "tables": [
                ("garment", ["garment_id", "sku", "garment_name", "apparel_category", "size", "color", "retail_price", "inventory_count"]),
                ("purchase", ["purchase_id", "garment_id", "purchase_date", "quantity", "total_amount", "sales_channel", "payment_method"]),
                ("return_record", ["return_id", "purchase_id", "return_date", "return_reason", "refund_amount", "status"]),
            ],
            "vocab": {
                "apparel_category": ["Women's Tops", "Women's Dresses", "Men's Shirts", "Men's Pants", "Denim", "Outerwear", "Activewear", "Footwear", "Handbags & Accessories", "Children's Wear", "Intimates", "Swimwear"],
                "size": ["XS", "S", "M", "L", "XL", "XXL", "0", "2", "4", "6", "8", "10"],
                "color": ["Black", "White", "Navy", "Gray", "Beige", "Red", "Blue", "Green", "Burgundy", "Olive", "Pink", "Charcoal"],
                "sales_channel": ["In-Store", "Online", "Mobile App", "Phone Order", "Curbside Pickup", "Marketplace"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "Store Card", "Mobile Wallet", "Gift Card", "Buy Now Pay Later"],
                "return_reason": ["Wrong Size", "Did Not Fit", "Defective", "Not As Described", "Changed Mind", "Wrong Item Shipped", "Damaged in Transit", "Better Price Elsewhere"],
            },
        },
        "furniture_stores": {
            "label": "Home Furniture & Furnishings Stores",
            "blurb": "A home furniture and furnishings retailer selling living room, bedroom, and decor goods, tracking catalog inventory, customer orders, and home delivery scheduling.",
            "tables": [
                ("furniture_item", ["furniture_item_id", "sku", "item_name", "furniture_category", "material", "retail_price", "stock_quantity", "collection_name"]),
                ("furniture_order", ["furniture_order_id", "furniture_item_id", "order_date", "quantity", "total_amount", "payment_method", "status"]),
                ("delivery", ["delivery_id", "furniture_order_id", "scheduled_date", "delivery_type", "delivery_fee", "delivery_window", "status"]),
            ],
            "vocab": {
                "furniture_category": ["Sofas & Sectionals", "Beds & Mattresses", "Dining Sets", "Coffee & End Tables", "Dressers & Chests", "Office Furniture", "Outdoor Furniture", "Rugs & Lighting", "Bookcases & Storage", "Recliners & Accent Chairs", "Kids' Furniture", "Home Decor"],
                "material": ["Solid Wood", "Engineered Wood", "Genuine Leather", "Faux Leather", "Linen Fabric", "Velvet", "Metal", "Glass", "Rattan", "Upholstered"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "Store Financing", "Layaway", "Lease to Own", "Gift Card"],
                "delivery_type": ["White Glove", "Threshold Delivery", "Curbside Drop-off", "In-Home Setup", "Customer Pickup", "Standard Freight"],
                "delivery_window": ["Morning 8-12", "Afternoon 12-4", "Evening 4-8", "All Day", "Weekend Only", "Next Available"],
            },
        },
        "eating_drinking_places": {
            "label": "Eating & Drinking Places",
            "blurb": "A full-service restaurant and bar serving food and beverages, tracking menu items, customer orders by table, and reservation bookings.",
            "tables": [
                ("menu_item", ["menu_item_id", "item_name", "menu_category", "menu_price", "prep_time_minutes", "is_available", "dietary_tag"]),
                ("food_order", ["food_order_id", "menu_item_id", "order_date", "quantity", "line_total", "order_type", "payment_method"]),
                ("reservation", ["reservation_id", "food_order_id", "reservation_date", "party_size", "table_section", "status"]),
            ],
            "vocab": {
                "menu_category": ["Appetizers", "Soups & Salads", "Entrees", "Burgers & Sandwiches", "Pasta", "Seafood", "Steaks & Grill", "Desserts", "Sides", "Kids' Menu", "Cocktails", "Wine & Beer"],
                "dietary_tag": ["Vegetarian", "Vegan", "Gluten-Free", "Dairy-Free", "Nut-Free", "Spicy", "Keto-Friendly", "Contains Shellfish", "Halal", "Low-Calorie"],
                "order_type": ["Dine-In", "Takeout", "Delivery", "Curbside", "Bar Seating", "Online Order", "Catering"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "Mobile Wallet", "Gift Card", "Split Check", "Comp"],
                "table_section": ["Main Dining", "Patio", "Bar Area", "Private Room", "Booth", "Window", "Counter", "Lounge"],
            },
        },
        "misc_retail": {
            "label": "Miscellaneous Retail",
            "blurb": "A specialty retail store carrying assorted niche goods such as books, sporting equipment, and gifts, tracking product inventory, sales transactions, and supplier purchase orders.",
            "tables": [
                ("retail_product", ["retail_product_id", "sku", "product_name", "store_category", "unit_price", "quantity_on_hand", "supplier_name"]),
                ("sale", ["sale_id", "retail_product_id", "sale_date", "quantity", "total_amount", "payment_method", "sales_channel"]),
                ("purchase_order", ["purchase_order_id", "retail_product_id", "order_date", "order_quantity", "order_cost", "expected_delivery_date", "status"]),
            ],
            "vocab": {
                "store_category": ["Books & Stationery", "Sporting Goods", "Toys & Hobbies", "Gifts & Novelties", "Jewelry & Watches", "Florist", "Pet Supplies", "Musical Instruments", "Art & Craft Supplies", "Tobacco & Vape", "Optical Goods", "Used Merchandise"],
                "payment_method": ["Cash", "Credit Card", "Debit Card", "Mobile Wallet", "Gift Card", "Store Credit", "Layaway", "Check"],
                "sales_channel": ["In-Store", "Online", "Mobile App", "Marketplace", "Phone Order", "Consignment", "Pop-up Booth"],
            },
        },
    },
},
"finance_insurance_real_estate": {
    "label": "Finance, Insurance & Real Estate",
    "subs": {
        "depository_institutions": {
            "label": "Depository Institutions",
            "blurb": "Commercial banks, savings institutions, and credit unions that accept customer deposits and originate loans; tables track customers, their deposit accounts, and the transactions posted against those accounts.",
            "tables": [
                ("customer", ["customer_id", "full_name", "email", "phone", "branch_name", "customer_segment", "onboarding_date"]),
                ("deposit_account", ["account_id", "customer_id", "account_type", "current_balance", "interest_rate", "opened_date", "status"]),
                ("account_transaction", ["transaction_id", "account_id", "transaction_type", "amount", "transaction_date", "channel", "running_balance"]),
            ],
            "vocab": {
                "account_type": ["Checking", "Savings", "Money Market", "Certificate of Deposit", "Individual Retirement Account", "Health Savings Account", "Trust Account", "Joint Checking", "Business Checking", "Negotiable Order of Withdrawal"],
                "customer_segment": ["Retail", "Mass Market", "Affluent", "Private Banking", "Small Business", "Commercial", "Student", "Senior"],
                "transaction_type": ["Deposit", "Withdrawal", "ACH Credit", "ACH Debit", "Wire Transfer", "Check Payment", "Card Purchase", "ATM Withdrawal", "Interest Credit", "Service Fee"],
                "channel": ["Branch", "ATM", "Online Banking", "Mobile App", "Phone Banking", "ACH Network", "Wire", "Point of Sale"],
            },
        },
        "nondepository_credit": {
            "label": "Non-depository Credit Institutions",
            "blurb": "Lenders such as finance companies, mortgage bankers, and credit card issuers that extend credit without taking deposits; tables track borrowers, the loans issued to them, and the repayment schedule.",
            "tables": [
                ("borrower", ["borrower_id", "full_name", "email", "phone", "credit_score", "annual_income", "employment_status", "registration_date"]),
                ("loan", ["loan_id", "borrower_id", "loan_type", "principal_amount", "interest_rate", "term_months", "origination_date", "status"]),
                ("repayment", ["repayment_id", "loan_id", "due_date", "scheduled_amount", "paid_amount", "payment_status", "principal_portion", "interest_portion"]),
            ],
            "vocab": {
                "loan_type": ["Mortgage", "Auto Loan", "Personal Loan", "Credit Card", "Home Equity Line", "Student Loan", "Payday Loan", "Business Loan", "Debt Consolidation", "Buy Now Pay Later", "Installment Loan"],
                "employment_status": ["Full-Time", "Part-Time", "Self-Employed", "Contractor", "Unemployed", "Retired", "Student", "Gig Worker"],
                "payment_status": ["Scheduled", "Paid On Time", "Paid Late", "Partial", "Missed", "In Grace Period", "Defaulted", "Deferred"],
            },
        },
        "security_commodity_brokers": {
            "label": "Security & Commodity Brokers",
            "blurb": "Broker-dealers and commodity firms that execute trades and manage client portfolios; tables track brokerage accounts, the securities held, and the buy/sell orders placed.",
            "tables": [
                ("brokerage_account", ["account_id", "account_holder_name", "account_type", "cash_balance", "opened_date", "risk_profile", "status"]),
                ("holding", ["holding_id", "account_id", "ticker_symbol", "asset_class", "quantity", "average_cost", "market_value", "acquired_date"]),
                ("trade_order", ["order_id", "account_id", "ticker_symbol", "order_type", "side", "quantity", "executed_price", "order_date"]),
            ],
            "vocab": {
                "account_type": ["Individual Brokerage", "Joint Brokerage", "Margin Account", "Cash Account", "Traditional IRA", "Roth IRA", "Custodial Account", "Trust Account", "Corporate Account", "Options Account"],
                "risk_profile": ["Conservative", "Moderately Conservative", "Moderate", "Moderately Aggressive", "Aggressive", "Speculative", "Income-Focused", "Growth-Focused"],
                "asset_class": ["Common Stock", "Preferred Stock", "Corporate Bond", "Municipal Bond", "Treasury Bond", "Exchange-Traded Fund", "Mutual Fund", "Option", "Commodity Future", "Real Estate Investment Trust"],
                "order_type": ["Market", "Limit", "Stop", "Stop-Limit", "Trailing Stop", "Fill or Kill", "Good Til Canceled", "Day Order"],
                "side": ["Buy", "Sell", "Buy to Open", "Sell to Close", "Short Sell", "Buy to Cover"],
            },
        },
        "insurance_carriers": {
            "label": "Insurance Carriers",
            "blurb": "Companies that underwrite and bear insurance risk across life, health, and property lines; tables track issued policies, the policyholders, and the claims filed against policies.",
            "tables": [
                ("policy", ["policy_id", "policyholder_name", "policy_type", "coverage_amount", "annual_premium", "effective_date", "expiration_date", "status"]),
                ("policyholder", ["policyholder_id", "full_name", "email", "phone", "date_of_birth", "address", "enrollment_date"]),
                ("claim", ["claim_id", "policy_id", "claim_type", "claim_amount", "paid_amount", "filed_date", "claim_status", "adjuster_name"]),
            ],
            "vocab": {
                "policy_type": ["Term Life", "Whole Life", "Auto", "Homeowners", "Renters", "Health", "Disability", "Umbrella", "Commercial Property", "Workers Compensation", "Travel", "Pet"],
                "claim_type": ["Collision", "Property Damage", "Bodily Injury", "Theft", "Fire", "Water Damage", "Medical Expense", "Death Benefit", "Liability", "Natural Disaster", "Vandalism"],
                "claim_status": ["Filed", "Under Review", "Investigating", "Approved", "Partially Approved", "Denied", "Paid", "Closed", "Appealed", "Pending Documentation"],
            },
        },
        "insurance_agents": {
            "label": "Insurance Agents & Brokers",
            "blurb": "Independent agencies and brokers that sell insurance policies on behalf of carriers and earn commissions; tables track agents, the quotes they generate for prospects, and the commissions earned on bound policies.",
            "tables": [
                ("agent", ["agent_id", "full_name", "email", "phone", "license_type", "agency_name", "hire_date", "status"]),
                ("quote", ["quote_id", "agent_id", "prospect_name", "line_of_business", "quoted_premium", "coverage_amount", "quote_date", "quote_status"]),
                ("commission", ["commission_id", "quote_id", "agent_id", "commission_rate", "commission_amount", "payout_date", "payment_status"]),
            ],
            "vocab": {
                "license_type": ["Property & Casualty", "Life & Health", "Personal Lines", "Surplus Lines", "Title Insurance", "Variable Products", "Adjuster", "Limited Lines"],
                "line_of_business": ["Auto", "Homeowners", "Life", "Health", "Commercial General Liability", "Workers Compensation", "Professional Liability", "Marine", "Crop", "Annuity"],
                "quote_status": ["Draft", "Presented", "Negotiating", "Bound", "Issued", "Declined", "Expired", "Lost to Competitor"],
            },
        },
        "real_estate": {
            "label": "Real Estate",
            "blurb": "Brokerages and property managers that list, lease, and sell residential and commercial property; tables track property listings, the agents handling them, and the lease or sale transactions closed.",
            "tables": [
                ("property", ["property_id", "address", "property_type", "listing_price", "square_footage", "bedrooms", "listing_date", "listing_status"]),
                ("agent", ["agent_id", "full_name", "email", "phone", "brokerage_name", "license_number", "hire_date"]),
                ("transaction", ["transaction_id", "property_id", "agent_id", "transaction_type", "sale_price", "commission_amount", "closing_date", "deal_status"]),
            ],
            "vocab": {
                "property_type": ["Single-Family Home", "Condominium", "Townhouse", "Multi-Family", "Apartment Building", "Office Space", "Retail Storefront", "Industrial Warehouse", "Vacant Land", "Mixed-Use", "Mobile Home", "Commercial Lot"],
                "listing_status": ["Active", "Pending", "Under Contract", "Sold", "Withdrawn", "Expired", "Contingent", "Coming Soon", "Off Market"],
                "transaction_type": ["Sale", "Purchase", "Residential Lease", "Commercial Lease", "Sublease", "Lease Renewal", "Land Sale", "Auction Sale"],
                "deal_status": ["Offer Made", "Under Negotiation", "In Escrow", "Inspection Period", "Financing Pending", "Closed", "Fell Through", "Cancelled"],
            },
        },
        "investment_offices": {
            "label": "Holding & Other Investment Offices",
            "blurb": "Holding companies, mutual funds, REITs, and asset managers that pool capital and manage investment funds; tables track managed funds, investor positions in those funds, and capital distributions paid out.",
            "tables": [
                ("fund", ["fund_id", "fund_name", "fund_type", "total_assets_under_management", "expense_ratio", "inception_date", "investment_strategy", "status"]),
                ("investor_position", ["position_id", "fund_id", "investor_name", "units_held", "invested_amount", "current_value", "investment_date"]),
                ("distribution", ["distribution_id", "fund_id", "distribution_type", "amount_per_unit", "total_amount", "record_date", "payment_date"]),
            ],
            "vocab": {
                "fund_type": ["Mutual Fund", "Hedge Fund", "Private Equity Fund", "Venture Capital Fund", "Real Estate Investment Trust", "Exchange-Traded Fund", "Money Market Fund", "Index Fund", "Closed-End Fund", "Fund of Funds", "Pension Fund"],
                "investment_strategy": ["Growth", "Value", "Income", "Balanced", "Index Tracking", "Long/Short Equity", "Market Neutral", "Distressed Assets", "Emerging Markets", "Sector-Focused", "Global Macro"],
                "distribution_type": ["Ordinary Dividend", "Qualified Dividend", "Capital Gains", "Return of Capital", "Interest Income", "Special Distribution", "Stock Dividend", "Liquidating Distribution"],
            },
        },
    },
},
"services": {
    "label": "Services",
    "subs": {
        "hotels_lodging": {
            "label": "Hotels & Lodging",
            "blurb": "Hotels and lodging establishments managing guest reservations, room inventory, and folio charges across stays.",
            "tables": [
                ("reservation", ["reservation_id", "guest_name", "room_type", "rate_plan", "check_in_date", "nights_count", "total_amount", "status"]),
                ("room", ["room_id", "reservation_id", "room_number", "room_type", "floor", "occupancy_status"]),
                ("folio_charge", ["folio_charge_id", "reservation_id", "charge_type", "posted_date", "amount", "department"]),
            ],
            "vocab": {
                "room_type": ["Standard King", "Standard Double", "Deluxe King", "Junior Suite", "Executive Suite", "Presidential Suite", "Accessible Queen", "Family Room", "Studio", "Penthouse"],
                "rate_plan": ["Best Available Rate", "Advance Purchase", "Corporate Negotiated", "Government Per Diem", "AAA Member", "Package Bed & Breakfast", "Group Block", "Loyalty Redemption", "Weekend Getaway", "Extended Stay"],
                "charge_type": ["Room Charge", "Room Tax", "Resort Fee", "Restaurant", "Room Service", "Minibar", "Parking", "Spa", "Laundry", "Telephone", "Wi-Fi", "Incidentals"],
                "department": ["Front Desk", "Food & Beverage", "Housekeeping", "Spa & Wellness", "Parking & Valet", "Business Center", "Concierge", "Banquets"],
            },
        },
        "personal_services": {
            "label": "Personal Services",
            "blurb": "Personal service providers such as salons, dry cleaners, and laundries booking client appointments and tracking service tickets.",
            "tables": [
                ("client", ["client_id", "full_name", "phone", "email", "join_date", "loyalty_tier", "status"]),
                ("appointment", ["appointment_id", "client_id", "service_type", "appointment_date", "duration_minutes", "staff_name", "price", "status"]),
                ("service_ticket", ["service_ticket_id", "appointment_id", "ticket_type", "ready_date", "item_count", "total_amount"]),
            ],
            "vocab": {
                "service_type": ["Haircut", "Hair Coloring", "Blow Dry", "Manicure", "Pedicure", "Facial", "Massage", "Waxing", "Dry Cleaning", "Wash & Fold", "Alterations", "Shoe Repair"],
                "loyalty_tier": ["None", "Bronze", "Silver", "Gold", "Platinum", "VIP"],
                "ticket_type": ["Standard Cleaning", "Express Cleaning", "Wash & Fold", "Pressing Only", "Alteration", "Leather Care", "Wedding Gown", "Household Linens"],
            },
        },
        "business_services": {
            "label": "Business Services",
            "blurb": "Business service firms (advertising, staffing, computer services) managing client engagements and project deliverables.",
            "tables": [
                ("client_account", ["client_account_id", "company_name", "industry", "account_manager", "onboard_date", "contract_value", "status"]),
                ("engagement", ["engagement_id", "client_account_id", "service_type", "start_date", "end_date", "billing_rate", "status"]),
                ("deliverable", ["deliverable_id", "engagement_id", "deliverable_type", "due_date", "hours_logged", "status"]),
            ],
            "vocab": {
                "service_type": ["Advertising Campaign", "Public Relations", "Temp Staffing", "Direct Mail", "Credit Reporting", "Data Processing", "IT Consulting", "Equipment Rental", "Security Guard", "Janitorial", "Photocopying", "Mailing & Fulfillment"],
                "deliverable_type": ["Creative Brief", "Media Plan", "Press Release", "Candidate Shortlist", "Software Build", "Data Report", "Audit Findings", "Marketing Collateral", "Service Report", "Invoice Package"],
            },
        },
        "automotive_repair": {
            "label": "Automotive Repair & Parking",
            "blurb": "Automotive repair shops and parking operators tracking vehicle repair orders, labor, and parts.",
            "tables": [
                ("repair_order", ["repair_order_id", "customer_name", "vehicle_make", "vehicle_year", "service_type", "drop_off_date", "total_amount", "status"]),
                ("labor_line", ["labor_line_id", "repair_order_id", "labor_type", "technician_name", "hours_billed", "labor_rate"]),
                ("part_used", ["part_used_id", "repair_order_id", "part_name", "part_category", "quantity", "unit_price"]),
            ],
            "vocab": {
                "service_type": ["Oil Change", "Brake Service", "Tire Rotation", "Wheel Alignment", "Engine Diagnostic", "Transmission Repair", "Battery Replacement", "AC Service", "Body Work", "State Inspection", "Detailing", "Towing"],
                "labor_type": ["Diagnostic", "Engine Repair", "Brake Repair", "Suspension", "Electrical", "Bodywork", "Painting", "Tire Service", "Routine Maintenance", "AC & Heating"],
                "part_category": ["Filters", "Brakes", "Tires", "Belts & Hoses", "Battery & Electrical", "Engine", "Suspension", "Fluids", "Body Panels", "Exhaust"],
            },
        },
        "misc_repair": {
            "label": "Miscellaneous Repair Services",
            "blurb": "Repair shops servicing electronics, appliances, and equipment, logging repair jobs and replacement parts.",
            "tables": [
                ("repair_job", ["repair_job_id", "customer_name", "item_category", "problem_description", "received_date", "estimate_amount", "warranty_type", "status"]),
                ("technician_assignment", ["technician_assignment_id", "repair_job_id", "technician_name", "assigned_date", "hours_worked", "labor_charge"]),
                ("replacement_part", ["replacement_part_id", "repair_job_id", "part_name", "part_category", "quantity", "unit_cost"]),
            ],
            "vocab": {
                "item_category": ["Smartphone", "Laptop", "Desktop PC", "Television", "Refrigerator", "Washing Machine", "Power Tool", "Watch", "Camera", "Audio Equipment", "Lawn Mower", "Bicycle"],
                "warranty_type": ["In Warranty", "Out of Warranty", "Extended Warranty", "Manufacturer Recall", "Service Contract", "No Warranty"],
                "part_category": ["Display", "Battery", "Circuit Board", "Motor", "Compressor", "Power Supply", "Cable & Connector", "Housing", "Sensor", "Gasket & Seal"],
            },
        },
        "motion_pictures": {
            "label": "Motion Pictures",
            "blurb": "Film production and distribution companies managing titles, production phases, and theatrical/licensing revenue.",
            "tables": [
                ("title", ["title_id", "title_name", "genre", "production_status", "release_date", "budget_amount", "rating", "status"]),
                ("production_phase", ["production_phase_id", "title_id", "phase_type", "start_date", "end_date", "phase_cost", "status"]),
                ("distribution_deal", ["distribution_deal_id", "title_id", "distribution_channel", "territory", "deal_date", "license_fee"]),
            ],
            "vocab": {
                "genre": ["Action", "Comedy", "Drama", "Horror", "Documentary", "Animation", "Science Fiction", "Romance", "Thriller", "Family", "Musical", "Western"],
                "production_status": ["Development", "Pre-Production", "Principal Photography", "Post-Production", "Completed", "Released", "Shelved"],
                "rating": ["G", "PG", "PG-13", "R", "NC-17", "Not Rated"],
                "phase_type": ["Development", "Pre-Production", "Principal Photography", "Reshoots", "Editing", "Visual Effects", "Sound Mixing", "Color Grading", "Marketing", "Distribution"],
                "distribution_channel": ["Theatrical", "Streaming", "Pay-TV", "Broadcast TV", "Home Video", "Airline & Hospitality", "Educational", "Video on Demand"],
            },
        },
        "amusement_recreation": {
            "label": "Amusement & Recreation Services",
            "blurb": "Amusement parks, gyms, and recreation venues selling admissions and memberships and scheduling activities.",
            "tables": [
                ("member", ["member_id", "full_name", "membership_type", "join_date", "monthly_fee", "renewal_date", "status"]),
                ("admission", ["admission_id", "member_id", "ticket_type", "visit_date", "party_size", "amount_paid"]),
                ("activity_booking", ["activity_booking_id", "member_id", "activity_type", "booking_date", "duration_minutes", "instructor_name", "fee"]),
            ],
            "vocab": {
                "membership_type": ["Day Pass", "Monthly", "Annual", "Family Plan", "Student", "Senior", "Corporate", "Premium All-Access", "Off-Peak", "Founding Member"],
                "ticket_type": ["General Admission", "Child", "Senior", "Group", "Season Pass", "VIP Fast-Track", "Twilight", "Spectator", "Combo"],
                "activity_type": ["Yoga Class", "Spin Class", "Personal Training", "Swimming Lesson", "Rock Climbing", "Tennis Court", "Golf Round", "Bowling Lane", "Go-Kart Session", "Mini Golf", "Boat Rental", "Group Fitness"],
            },
        },
        "health_services": {
            "label": "Health Services",
            "blurb": "Healthcare providers and clinics scheduling patient visits, recording diagnoses, and billing for services.",
            "tables": [
                ("patient", ["patient_id", "full_name", "date_of_birth", "insurance_type", "registration_date", "primary_provider", "status"]),
                ("visit", ["visit_id", "patient_id", "visit_type", "visit_date", "specialty", "provider_name", "charge_amount", "status"]),
                ("diagnosis", ["diagnosis_id", "visit_id", "diagnosis_code", "diagnosis_description", "severity", "recorded_date"]),
                ("billing_claim", ["billing_claim_id", "visit_id", "payer_type", "submitted_date", "claim_amount", "status"]),
            ],
            "vocab": {
                "visit_type": ["New Patient", "Follow-Up", "Annual Physical", "Urgent Care", "Telehealth", "Procedure", "Lab Work", "Immunization", "Consultation", "Emergency"],
                "specialty": ["Family Medicine", "Internal Medicine", "Pediatrics", "Cardiology", "Dermatology", "Orthopedics", "Obstetrics & Gynecology", "Psychiatry", "Radiology", "Oncology", "Neurology", "Ophthalmology"],
                "insurance_type": ["Private PPO", "Private HMO", "Medicare", "Medicaid", "Self-Pay", "Workers Compensation", "Tricare", "Veterans Affairs"],
                "payer_type": ["Commercial Insurance", "Medicare", "Medicaid", "Self-Pay", "Workers Compensation", "Auto Insurance", "Government Program"],
                "severity": ["Mild", "Moderate", "Severe", "Critical", "Chronic", "Resolved"],
            },
        },
        "legal_services": {
            "label": "Legal Services",
            "blurb": "Law firms managing client matters, attorney time entries, and billing across practice areas.",
            "tables": [
                ("matter", ["matter_id", "client_name", "practice_area", "case_type", "open_date", "responsible_attorney", "billing_arrangement", "status"]),
                ("time_entry", ["time_entry_id", "matter_id", "attorney_name", "task_type", "entry_date", "hours_billed", "billing_rate"]),
                ("invoice", ["invoice_id", "matter_id", "issue_date", "billed_amount", "amount_paid", "status"]),
            ],
            "vocab": {
                "practice_area": ["Litigation", "Corporate", "Real Estate", "Family Law", "Criminal Defense", "Estate Planning", "Intellectual Property", "Employment", "Bankruptcy", "Immigration", "Tax", "Personal Injury"],
                "case_type": ["Contract Dispute", "Divorce", "Will & Trust", "Patent Filing", "Merger & Acquisition", "Property Closing", "DUI Defense", "Wrongful Termination", "Chapter 7 Filing", "Visa Petition", "Tort Claim"],
                "billing_arrangement": ["Hourly", "Flat Fee", "Contingency", "Retainer", "Capped Fee", "Pro Bono"],
                "task_type": ["Legal Research", "Drafting", "Court Appearance", "Client Meeting", "Deposition", "Document Review", "Negotiation", "Filing", "Phone Conference", "Travel"],
            },
        },
        "educational_services": {
            "label": "Educational Services",
            "blurb": "Schools and training providers enrolling students in courses and tracking attendance and tuition.",
            "tables": [
                ("student", ["student_id", "full_name", "enrollment_date", "program_type", "grade_level", "tuition_balance", "status"]),
                ("course_enrollment", ["course_enrollment_id", "student_id", "course_name", "subject_area", "term", "credit_hours", "tuition_amount", "status"]),
                ("attendance_record", ["attendance_record_id", "course_enrollment_id", "session_date", "attendance_status", "minutes_present"]),
                ("grade", ["grade_id", "course_enrollment_id", "assessment_type", "recorded_date", "score", "letter_grade"]),
            ],
            "vocab": {
                "program_type": ["K-12", "Undergraduate", "Graduate", "Vocational", "Continuing Education", "Test Prep", "ESL", "Certificate", "Online Degree", "Early Childhood"],
                "subject_area": ["Mathematics", "Science", "English", "History", "Computer Science", "Business", "Art", "Music", "Physical Education", "Foreign Language", "Engineering", "Health Sciences"],
                "attendance_status": ["Present", "Absent", "Tardy", "Excused", "Remote", "Withdrawn"],
                "assessment_type": ["Quiz", "Midterm Exam", "Final Exam", "Homework", "Project", "Lab Report", "Participation", "Presentation", "Essay"],
                "grade_level": ["Elementary", "Middle School", "High School", "Freshman", "Sophomore", "Junior", "Senior", "Postgraduate", "Adult Learner"],
            },
        },
        "social_services": {
            "label": "Social Services",
            "blurb": "Social service agencies enrolling clients in programs and tracking case management and benefit disbursements.",
            "tables": [
                ("client_case", ["client_case_id", "client_name", "program_type", "intake_date", "case_worker", "household_size", "status"]),
                ("service_episode", ["service_episode_id", "client_case_id", "service_type", "service_date", "duration_minutes", "provider_name", "status"]),
                ("benefit_disbursement", ["benefit_disbursement_id", "client_case_id", "benefit_type", "disbursement_date", "amount", "status"]),
            ],
            "vocab": {
                "program_type": ["Child Welfare", "Elderly Care", "Job Training", "Housing Assistance", "Food Assistance", "Substance Abuse", "Mental Health", "Disability Support", "Refugee Resettlement", "Youth Services", "Family Counseling", "Veteran Services"],
                "service_type": ["Case Assessment", "Counseling Session", "Home Visit", "Crisis Intervention", "Skills Workshop", "Referral", "Transportation", "Childcare", "Meal Delivery", "Legal Aid"],
                "benefit_type": ["Cash Assistance", "Food Stamps", "Housing Voucher", "Childcare Subsidy", "Utility Assistance", "Medical Coverage", "Transportation Allowance", "Emergency Grant"],
            },
        },
        "museums_galleries": {
            "label": "Museums, Galleries & Gardens",
            "blurb": "Museums, galleries, and botanical gardens cataloging collection items, mounting exhibitions, and selling visitor admissions.",
            "tables": [
                ("collection_item", ["collection_item_id", "item_title", "item_category", "acquisition_date", "creator_name", "appraised_value", "status"]),
                ("exhibition", ["exhibition_id", "exhibition_name", "exhibition_type", "start_date", "end_date", "budget_amount", "status"]),
                ("exhibit_placement", ["exhibit_placement_id", "exhibition_id", "collection_item_id", "gallery_location", "display_order"]),
                ("visitor_admission", ["visitor_admission_id", "exhibition_id", "ticket_type", "visit_date", "party_size", "amount_paid"]),
            ],
            "vocab": {
                "item_category": ["Painting", "Sculpture", "Photograph", "Manuscript", "Textile", "Ceramic", "Decorative Art", "Natural Specimen", "Fossil", "Artifact", "Living Plant", "Mixed Media"],
                "exhibition_type": ["Permanent Collection", "Temporary Exhibition", "Traveling Exhibition", "Special Event", "Retrospective", "Group Show", "Seasonal Display", "Interactive Installation"],
                "ticket_type": ["General Admission", "Member", "Student", "Senior", "Child", "Group Tour", "Special Exhibition", "Free Day", "Guided Tour"],
                "gallery_location": ["East Wing", "West Wing", "Main Hall", "Upper Gallery", "Sculpture Garden", "Atrium", "Mezzanine", "Conservatory", "Special Exhibits Hall"],
            },
        },
        "membership_organizations": {
            "label": "Membership Organizations",
            "blurb": "Membership organizations such as associations and unions managing members, dues, and events.",
            "tables": [
                ("member", ["member_id", "full_name", "membership_type", "join_date", "renewal_date", "annual_dues", "status"]),
                ("dues_payment", ["dues_payment_id", "member_id", "payment_date", "amount", "payment_method", "status"]),
                ("event_registration", ["event_registration_id", "member_id", "event_type", "event_date", "registration_fee", "status"]),
            ],
            "vocab": {
                "membership_type": ["Individual", "Family", "Student", "Senior", "Corporate", "Lifetime", "Honorary", "Associate", "Professional", "Patron"],
                "event_type": ["Annual Conference", "Networking Mixer", "Workshop", "Webinar", "Fundraiser", "Awards Banquet", "Town Hall", "Training Seminar", "Community Service", "Chapter Meeting"],
                "payment_method": ["Credit Card", "Check", "Bank Transfer", "Cash", "Payroll Deduction", "Online Portal", "Automatic Renewal"],
            },
        },
        "professional_services": {
            "label": "Engineering, Accounting, Research & Management",
            "blurb": "Professional firms in engineering, accounting, research, and management consulting delivering client projects and tracking billable work.",
            "tables": [
                ("project", ["project_id", "client_name", "discipline", "engagement_type", "start_date", "contract_value", "project_manager", "status"]),
                ("consultant_assignment", ["consultant_assignment_id", "project_id", "consultant_name", "role", "assigned_date", "billing_rate", "hours_allocated"]),
                ("project_milestone", ["project_milestone_id", "project_id", "milestone_name", "due_date", "billing_amount", "status"]),
            ],
            "vocab": {
                "discipline": ["Civil Engineering", "Mechanical Engineering", "Electrical Engineering", "Structural Engineering", "Accounting & Audit", "Tax Advisory", "Management Consulting", "Market Research", "Environmental", "Surveying", "Architecture", "IT Strategy"],
                "engagement_type": ["Feasibility Study", "Design Build", "Financial Audit", "Tax Preparation", "Strategy Consulting", "Process Improvement", "Market Analysis", "Due Diligence", "Compliance Review", "Research Study"],
                "role": ["Principal", "Project Manager", "Senior Consultant", "Consultant", "Analyst", "Subject Matter Expert", "Quality Reviewer", "Associate"],
            },
        },
        "private_households": {
            "label": "Private Households",
            "blurb": "Private households employing domestic staff and tracking employee assignments, payroll, and household expenses.",
            "tables": [
                ("household_employee", ["household_employee_id", "full_name", "position_type", "hire_date", "hourly_wage", "employment_status", "status"]),
                ("work_shift", ["work_shift_id", "household_employee_id", "shift_date", "duties_performed", "hours_worked", "shift_pay"]),
                ("household_expense", ["household_expense_id", "household_employee_id", "expense_category", "expense_date", "amount", "payment_method"]),
            ],
            "vocab": {
                "position_type": ["Housekeeper", "Nanny", "Gardener", "Cook", "Personal Chef", "Butler", "Driver", "Caregiver", "Estate Manager", "Au Pair", "Maintenance Worker", "Personal Assistant"],
                "duties_performed": ["Cleaning", "Childcare", "Cooking", "Laundry", "Grocery Shopping", "Gardening", "Driving", "Elder Care", "Pet Care", "Home Maintenance", "Errands", "Organizing"],
                "expense_category": ["Wages", "Household Supplies", "Groceries", "Maintenance", "Utilities", "Insurance", "Payroll Tax", "Bonus", "Reimbursement"],
                "payment_method": ["Direct Deposit", "Check", "Cash", "Payroll Service", "Bank Transfer"],
            },
        },
        "misc_services": {
            "label": "Miscellaneous Services",
            "blurb": "Miscellaneous service businesses fulfilling varied customer service requests and tracking work orders and charges.",
            "tables": [
                ("service_request", ["service_request_id", "customer_name", "service_category", "request_date", "priority_level", "quoted_amount", "status"]),
                ("work_order", ["work_order_id", "service_request_id", "assigned_staff", "scheduled_date", "hours_estimated", "labor_charge", "status"]),
                ("service_charge", ["service_charge_id", "work_order_id", "charge_type", "charge_date", "amount", "billing_status"]),
            ],
            "vocab": {
                "service_category": ["Photography", "Event Planning", "Pet Grooming", "Interior Design", "Tailoring", "Tax Preparation", "Translation", "Locksmith", "Courier", "Catering", "Cleaning", "Consulting"],
                "priority_level": ["Low", "Standard", "High", "Urgent", "Emergency"],
                "charge_type": ["Labor", "Materials", "Travel", "Rush Fee", "Consultation", "Equipment Rental", "Disposal", "Service Fee"],
                "billing_status": ["Unbilled", "Invoiced", "Paid", "Overdue", "Disputed", "Written Off"],
            },
        },
    },
},
"public_administration": {
    "label": "Public Administration",
    "subs": {
        "government_administration": {
            "label": "Executive, Legislative & General Government",
            "blurb": "General government offices that adopt legislation, issue executive orders, and manage public operations; tables track governing bodies, the ordinances they enact, and budget appropriations.",
            "tables": [
                ("agency", ["agency_id", "agency_name", "branch_type", "jurisdiction_level", "established_date", "annual_budget", "headcount", "status"]),
                ("ordinance", ["ordinance_id", "agency_id", "title", "ordinance_type", "introduced_date", "effective_date", "vote_outcome", "status"]),
                ("appropriation", ["appropriation_id", "agency_id", "fiscal_year", "fund_category", "appropriated_amount", "spent_amount", "approval_date"]),
            ],
            "vocab": {
                "branch_type": ["Executive", "Legislative", "Judicial", "Mayor's Office", "City Council", "County Board", "Administrative Services", "Office of the Governor", "Clerk's Office", "City Manager"],
                "jurisdiction_level": ["Federal", "State", "County", "Municipal", "Township", "Special District", "Regional", "Tribal"],
                "ordinance_type": ["Zoning", "Budget Appropriation", "Public Health", "Tax Levy", "Land Use", "Procurement", "Ethics", "Charter Amendment", "Resolution", "Emergency Order"],
                "vote_outcome": ["Passed Unanimous", "Passed Majority", "Failed", "Tabled", "Vetoed", "Override Sustained", "Withdrawn", "Pending"],
                "fund_category": ["General Fund", "Capital Improvement", "Debt Service", "Enterprise Fund", "Special Revenue", "Grant Fund", "Internal Service", "Pension Trust"],
            },
        },
        "justice_public_safety": {
            "label": "Justice, Public Order & Safety",
            "blurb": "Courts, law enforcement, and corrections agencies that handle criminal and civil matters; tables track legal cases, the agencies involved, and detention or incident records.",
            "tables": [
                ("case_file", ["case_file_id", "case_number", "case_type", "filing_date", "court_level", "disposition", "bail_amount", "status"]),
                ("agency", ["agency_id", "case_file_id", "agency_name", "agency_type", "officer_count", "jurisdiction", "established_date"]),
                ("incident", ["incident_id", "case_file_id", "incident_type", "occurred_date", "location", "severity_level", "response_minutes", "status"]),
                ("detention", ["detention_id", "case_file_id", "facility_name", "intake_date", "release_date", "custody_type", "daily_cost"]),
            ],
            "vocab": {
                "case_type": ["Felony", "Misdemeanor", "Civil Tort", "Family", "Traffic", "Juvenile", "Small Claims", "Appeal", "Probate", "Bankruptcy"],
                "court_level": ["Municipal", "District", "Superior", "Appellate", "Supreme", "Federal District", "Magistrate", "Family Court"],
                "disposition": ["Convicted", "Acquitted", "Dismissed", "Plea Bargain", "Settled", "Pending Trial", "Mistrial", "Diverted", "Probation", "Continued"],
                "agency_type": ["Police Department", "Sheriff's Office", "State Patrol", "District Attorney", "Public Defender", "Corrections", "Probation Office", "Marshal Service", "Fire Marshal", "Forensics Lab"],
                "incident_type": ["Burglary", "Assault", "Traffic Collision", "Domestic Disturbance", "Theft", "Vandalism", "Drug Offense", "Fraud", "Disorderly Conduct", "Trespassing"],
                "severity_level": ["Critical", "High", "Moderate", "Low", "Minor"],
                "custody_type": ["Pretrial Detention", "Sentenced", "Holding", "Work Release", "House Arrest", "Transfer Hold", "Immigration Hold", "Juvenile Detention"],
            },
        },
        "public_finance": {
            "label": "Public Finance, Taxation & Monetary Policy",
            "blurb": "Treasury, tax, and revenue offices that collect public funds and issue debt; tables track tax accounts, levied assessments, and government bond issuances.",
            "tables": [
                ("tax_account", ["tax_account_id", "taxpayer_name", "account_type", "parcel_number", "registered_date", "assessed_value", "balance_due", "status"]),
                ("assessment", ["assessment_id", "tax_account_id", "tax_type", "levy_date", "due_date", "assessed_amount", "paid_amount", "status"]),
                ("bond_issue", ["bond_issue_id", "tax_account_id", "series_name", "bond_type", "issue_date", "maturity_date", "principal_amount", "coupon_rate"]),
                ("collection_action", ["collection_action_id", "assessment_id", "action_type", "initiated_date", "recovered_amount", "status"]),
            ],
            "vocab": {
                "account_type": ["Individual", "Corporate", "Real Property", "Personal Property", "Sales Tax Vendor", "Excise", "Estate", "Nonprofit Exempt"],
                "tax_type": ["Property Tax", "Income Tax", "Sales Tax", "Use Tax", "Excise Tax", "Estate Tax", "Payroll Tax", "Franchise Tax", "Capital Gains", "Special Assessment"],
                "bond_type": ["General Obligation", "Revenue Bond", "Municipal Note", "Tax Anticipation Note", "Refunding Bond", "Industrial Development", "Build America Bond", "Green Bond"],
                "action_type": ["Lien Filed", "Wage Garnishment", "Property Seizure", "Payment Plan", "Penalty Assessed", "Tax Sale", "Levy Release", "Bankruptcy Stay", "Write-Off", "Refund Issued"],
            },
        },
        "human_resource_programs": {
            "label": "Administration of Human Resource Programs",
            "blurb": "Agencies administering social, health, education, and welfare programs; tables track public assistance programs, enrolled beneficiaries, and disbursed benefit payments.",
            "tables": [
                ("program", ["program_id", "program_name", "program_type", "administering_agency", "launch_date", "annual_budget", "enrollment_cap", "status"]),
                ("beneficiary", ["beneficiary_id", "program_id", "household_size", "enrollment_date", "eligibility_category", "monthly_income", "status"]),
                ("benefit_payment", ["benefit_payment_id", "beneficiary_id", "payment_date", "benefit_type", "payment_amount", "payment_method", "status"]),
            ],
            "vocab": {
                "program_type": ["Medicaid", "SNAP Food Assistance", "TANF Cash Aid", "Unemployment Insurance", "Housing Voucher", "Childcare Subsidy", "WIC Nutrition", "Veterans Benefits", "Disability Support", "Workforce Training"],
                "eligibility_category": ["Low Income", "Disabled", "Elderly", "Single Parent", "Unemployed", "Veteran", "Pregnant", "Refugee", "Foster Youth", "Homeless"],
                "benefit_type": ["Cash Transfer", "Food Voucher", "Medical Coverage", "Housing Subsidy", "Childcare Credit", "Utility Assistance", "Job Stipend", "Transportation Voucher"],
                "payment_method": ["EBT Card", "Direct Deposit", "Paper Check", "Prepaid Card", "Voucher", "In-Kind Service"],
            },
        },
        "environmental_housing_programs": {
            "label": "Administration of Environmental Quality & Housing",
            "blurb": "Agencies regulating environmental quality and managing public housing; tables track regulated facilities, environmental permits, and housing project units along with inspections.",
            "tables": [
                ("facility", ["facility_id", "facility_name", "facility_type", "region", "registered_date", "compliance_status", "annual_emissions", "status"]),
                ("permit", ["permit_id", "facility_id", "permit_type", "issue_date", "expiration_date", "permitted_limit", "fee_amount", "status"]),
                ("housing_project", ["housing_project_id", "facility_id", "project_name", "unit_count", "funding_source", "completion_date", "total_budget", "occupancy_rate"]),
                ("inspection", ["inspection_id", "permit_id", "inspection_date", "inspection_type", "violation_count", "penalty_amount", "result"]),
            ],
            "vocab": {
                "facility_type": ["Wastewater Plant", "Landfill", "Power Plant", "Manufacturing Site", "Public Housing Complex", "Recycling Center", "Hazardous Waste Site", "Water Treatment", "Air Monitoring Station", "Brownfield Site"],
                "permit_type": ["Air Quality", "Water Discharge", "Solid Waste", "Hazardous Materials", "Wetlands", "Stormwater", "Construction", "Demolition", "Underground Storage", "Emissions Trading"],
                "funding_source": ["HUD Section 8", "Low Income Housing Tax Credit", "Community Development Block Grant", "State Housing Fund", "Public Bond", "Federal HOME Grant", "Local Trust Fund", "HUD Capital Fund"],
                "inspection_type": ["Routine Compliance", "Complaint Response", "Pre-Permit", "Emissions Audit", "Habitability", "Hazardous Spill", "Annual Recertification", "Follow-Up"],
                "result": ["Pass", "Pass with Conditions", "Minor Violations", "Major Violations", "Failed", "Pending Review", "Closed Compliant", "Enforcement Referred"],
            },
        },
        "economic_programs": {
            "label": "Administration of Economic Programs",
            "blurb": "Agencies regulating commerce, transportation, labor, and industry; tables track regulated entities, the licenses they hold, and economic development grants awarded.",
            "tables": [
                ("regulated_entity", ["regulated_entity_id", "entity_name", "sector", "registration_date", "employee_count", "annual_revenue", "compliance_rating", "status"]),
                ("license", ["license_id", "regulated_entity_id", "license_type", "issue_date", "expiration_date", "renewal_fee", "status"]),
                ("development_grant", ["development_grant_id", "regulated_entity_id", "grant_program", "award_date", "grant_amount", "jobs_created", "status"]),
                ("compliance_filing", ["compliance_filing_id", "regulated_entity_id", "filing_type", "submitted_date", "reporting_period", "penalty_amount", "status"]),
            ],
            "vocab": {
                "sector": ["Transportation", "Telecommunications", "Energy Utilities", "Banking", "Agriculture", "Manufacturing", "Mining", "Insurance", "Construction", "Hospitality"],
                "license_type": ["Business Operating", "Commercial Transport", "Broadcast", "Utility Franchise", "Liquor", "Contractor", "Import-Export", "Securities Dealer", "Mining Permit", "Food Service"],
                "grant_program": ["Small Business Loan", "Enterprise Zone Credit", "Export Assistance", "Workforce Development", "Innovation Grant", "Rural Development", "Tourism Promotion", "Minority Business", "Infrastructure Match", "Industry Modernization"],
                "filing_type": ["Annual Report", "Tariff Filing", "Safety Disclosure", "Financial Statement", "Rate Adjustment", "Merger Notice", "Labor Compliance", "Environmental Impact"],
            },
        },
        "national_security": {
            "label": "National Security & International Affairs",
            "blurb": "Defense, foreign affairs, and international relations agencies; tables track operational missions, deployed personnel and units, and foreign aid or diplomatic programs.",
            "tables": [
                ("mission", ["mission_id", "mission_name", "mission_type", "command_branch", "start_date", "operational_budget", "personnel_count", "status"]),
                ("deployment", ["deployment_id", "mission_id", "unit_name", "deployment_date", "return_date", "region", "personnel_assigned", "status"]),
                ("aid_program", ["aid_program_id", "mission_id", "recipient_country", "program_type", "authorized_date", "aid_amount", "disbursed_amount", "status"]),
            ],
            "vocab": {
                "mission_type": ["Combat Operation", "Peacekeeping", "Humanitarian Relief", "Intelligence", "Border Security", "Counterterrorism", "Training Mission", "Disaster Response", "Maritime Patrol", "Cyber Defense"],
                "command_branch": ["Army", "Navy", "Air Force", "Marines", "Coast Guard", "Space Force", "Joint Command", "National Guard", "Special Operations", "Defense Intelligence"],
                "region": ["North America", "Europe", "Middle East", "East Asia", "Africa", "South America", "Central Asia", "Pacific", "Caribbean", "Arctic"],
                "program_type": ["Development Aid", "Military Assistance", "Disaster Relief", "Health Initiative", "Food Security", "Democracy Support", "Refugee Aid", "Trade Capacity", "Counter-Narcotics", "Education Grant"],
            },
        },
        "nonclassifiable": {
            "label": "Nonclassifiable Establishments",
            "blurb": "Small establishments that do not fit a standard classification; tables track companies, their contacts, and financial transactions.",
            "tables": [
                ("company", ["company_id", "company_name", "industry_type", "founded_date", "employee_count", "annual_revenue", "status"]),
                ("contact", ["contact_id", "company_id", "full_name", "role", "email", "phone", "added_date"]),
                ("transaction", ["transaction_id", "company_id", "transaction_date", "transaction_type", "amount", "payment_method", "status"]),
            ],
            "vocab": {
                "industry_type": ["General Services", "Miscellaneous Retail", "Consulting", "Holding Company", "Independent Contractor", "Trade Association", "Research Group", "Nonprofit", "Startup Venture", "Family Business"],
                "transaction_type": ["Sale", "Purchase", "Refund", "Service Fee", "Subscription", "Reimbursement", "Deposit", "Withdrawal", "Adjustment", "Transfer"],
                "payment_method": ["Credit Card", "Bank Transfer", "Cash", "Check", "Wire Transfer", "Digital Wallet", "ACH", "Money Order"],
            },
        },
    },
},
}
