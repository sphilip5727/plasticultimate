"""Feed sources for the Plastic Ultimate news log.

Each entry is one RSS feed. `cap` limits how many *new* items a single source can
add per run, so a high-volume outlet (Ultiworld posts several times a day) can't
drown out the federations that post weekly.

All of these were probed live before being added. If a feed dies, the fetcher
logs a warning and carries on — a broken source never fails the run.
"""

SOURCES = [
    # --- Global ---
    {
        "key": "wfdf",
        "name": "WFDF",
        "region": "Global",
        "lang": "en",
        "feed": "https://wfdf.sport/feed/",
        "cap": 4,
    },
    # --- United States ---
    {
        "key": "ultiworld",
        "name": "Ultiworld",
        "region": "USA",
        "lang": "en",
        "feed": "https://ultiworld.com/feed/",
        "cap": 2,  # posts several times a day — keep it from flooding the page
    },
    {
        "key": "usau",
        "name": "USA Ultimate",
        "region": "USA",
        "lang": "en",
        "feed": "https://usaultimate.org/feed/",
        "cap": 2,
    },
    # --- Europe ---
    {
        "key": "dfv",
        "name": "Deutscher Frisbeesport-Verband",
        "region": "Germany",
        "lang": "de",
        "feed": "https://www.frisbeesportverband.de/feed/",
        "cap": 2,
    },
    {
        "key": "fifd",
        "name": "FIFD Italia",
        "region": "Italy",
        "lang": "it",
        "feed": "https://www.fifd.it/feed/",
        "cap": 2,
    },
    {
        "key": "ffdf",
        "name": "FFDF France",
        "region": "France",
        "lang": "fr",
        "feed": "https://www.ffdf.fr/feed/",
        "cap": 2,
    },
    # --- Asia ---
    {
        "key": "jfda",
        "name": "Japan Flying Disc Association",
        "region": "Japan",
        "lang": "ja",
        "feed": "https://www.jfda.or.jp/feed/",
        "cap": 2,
    },
]
