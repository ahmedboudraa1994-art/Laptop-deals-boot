# NOTE:
# This is the reviewed version based on the code you shared.
# Apply the two recommended tuning changes:
MAX_PRICE_WORKERS = 4
MAX_CANDIDATES_PER_SEARCH = 6

# Then keep the remainder of the code exactly as in the version you provided.
#
# Replace:
# MAX_PRICE_WORKERS = 10
#
# with:
# MAX_PRICE_WORKERS = 4
# MAX_CANDIDATES_PER_SEARCH = 6
#
# And in scrape_search(), before creating the ThreadPoolExecutor,
# deduplicate candidates and keep only the first
# MAX_CANDIDATES_PER_SEARCH candidates.
#
# I couldn't faithfully reconstruct the remaining 500+ lines without
# risking changing your working code, so use the code you already have
# and apply only these reviewed modifications.
