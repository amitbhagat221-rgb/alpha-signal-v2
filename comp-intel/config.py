"""comp-intel — what to benchmark. Edit freely; this is your watchlist."""

# Role keywords to track (your current seat + the seats you're benchmarking toward)
ROLE_QUERIES = [
    "market risk",
    "quantitative risk",
    "quant developer",
    "quantitative researcher",
    "risk quant",
]

# Locations: India hubs + the UAE target
LOCATIONS = [
    "Bengaluru, India",
    "Mumbai, India",
    "Dubai, United Arab Emirates",
    "Abu Dhabi, United Arab Emirates",
]

# Firms of interest — used for firm-level rollups + tagging (substring match on company)
FIRMS = [
    "Millennium", "Citadel", "Balyasny", "Point72", "DE Shaw", "D. E. Shaw",
    "WorldQuant", "Two Sigma", "Squarepoint", "Goldman Sachs", "Morgan Stanley",
    "JPMorgan", "J.P. Morgan", "BlackRock",
]

# JobSpy portals to query. LinkedIn is OFF by default — the unofficial path risks an
# account ban (LinkedIn User Agreement §8.2). Add "linkedin" only with a throwaway account.
JOBSPY_SITES = ["naukri", "indeed", "glassdoor"]

RESULTS_PER_QUERY = 50      # postings per (role × site)
HOURS_OLD = 720             # only listings from the last N hours (~30 days)
COUNTRY_INDEED = "India"    # JobSpy needs an Indeed country; switch per location as needed

# INR per unit for normalising mixed-currency postings to a common base (rough, edit as needed)
FX_TO_INR = {"INR": 1.0, "USD": 86.0, "AED": 23.4, "GBP": 108.0, "EUR": 92.0}
