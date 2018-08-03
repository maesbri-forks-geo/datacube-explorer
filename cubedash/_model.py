from __future__ import absolute_import

import flask
import structlog
from flask_caching import Cache
from pathlib import Path
from typing import Iterable, Tuple, Dict
from typing import Optional

from cubedash.summary import TimePeriodOverview, SummaryStore
from datacube.index import Index
from datacube.index import index_connect
from datacube.model import DatasetType
import dateutil.parser

NAME = 'cubedash'

app = flask.Flask(NAME)
cache = Cache(
    app=app,
    config={'CACHE_TYPE': 'simple'}
)

# Thread and multiprocess safe.
# As long as we don't run queries (ie. open db connections) before forking
# (hence validate=False).
index: Index = index_connect(application_name=NAME, validate_connection=False)

# Pre-computed summaries of products (to avoid doing them on page load).
SUMMARIES_DIR = Path(__file__).parent.parent / 'product-summaries'

# TODO: Proper configuration?
DEFAULT_STORE = SummaryStore.create(index)
# Which product to show by default when loading '/'. Picks the first available.
DEFAULT_START_PAGE_PRODUCTS = ('ls7_nbar_scene', 'ls5_nbar_scene')

_LOG = structlog.get_logger()


@cache.memoize(timeout=60)
def get_summary(
        product_name: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None) -> Optional[TimePeriodOverview]:

    # If it's a day, feel free to update/generate it, because it's quick.
    if day is not None:
        return DEFAULT_STORE.get_or_update(product_name, year, month, day)

    return DEFAULT_STORE.get(product_name, year, month, day)


@cache.memoize(timeout=60)
def get_datasets_geojson(
        product_name: str,
        year: Optional[int] = None,
        month: Optional[int] = None,
        day: Optional[int] = None) -> Dict:
    return DEFAULT_STORE.get_dataset_footprints(product_name, year, month, day)


@cache.memoize(timeout=120)
def get_last_updated():
    # Drop a text file in to override the "updated time": for example, when we know it's an old clone of our DB.
    path = SUMMARIES_DIR / 'generated.txt'
    if path.exists():
        date_text = path.read_text()
        try:
            return dateutil.parser.parse(date_text)
        except ValueError:
            _LOG.warn("invalid.summary.generated.txt", text=date_text, path=path)
    return DEFAULT_STORE.get_last_updated()


@cache.memoize(timeout=120)
def get_products_with_summaries() -> Iterable[Tuple[DatasetType, TimePeriodOverview]]:
    """
    The list of products that we have generated reports for.
    """
    index_products = {p.name: p for p in index.products.get_all()}
    products = [
        (index_products[product_name], get_summary(product_name))
        for product_name in DEFAULT_STORE.list_complete_products()
    ]
    if not products:
        raise RuntimeError(
            'No product reports. '
            'Run `python -m cubedash.generate --all` to generate some.'
        )

    return products
