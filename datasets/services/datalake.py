"""
Read-only client for the EnergyGuard pilot data lake.

Every pilot partner owns a PostgreSQL database on the CARTIF data lake host,
holding a raw time-series table.

The dashboard does not serve data from here: the data management server exports
each partner nightly into MinIO, and preview/download read that object instead
(see pilot.py). What remains here is the client behind the `datalake_check`
management command, used to verify lake connectivity and to inspect the source
data — which is why it still mirrors `/export/{partner}/raw` exactly: the full
`public.f_tsdata` table, unfiltered and unlimited.
"""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


class DataLakeError(RuntimeError):
    """Any failure while talking to the data lake."""


class UnknownPartnerError(DataLakeError):
    """The requested pilot partner has no database registered."""


class PartnerDataUnavailableError(DataLakeError):
    """The partner database exists but holds no time-series tables yet."""


# Pilot partner -> database name on the data lake host.
PARTNER_DATABASES = {
    "RDN": "TEF1_RDN",
    "CEDER": "TEF2_CEDER",
    "BER": "TEF3_BER",
    "CEA": "TEF4_CEA",
    "CARTIF": "TEF5_CARTIF",
    "REA": "TEF6_REA",
    "ENGREEN": "TEF7_ENGREEN",
}

RAW_COLUMNS = ["ts_id", "calendar_id", "sensor_id", "f_value", "corrected"]

_RAW_SELECT = (
    "SELECT ts_id, calendar_id, sensor_id, f_value, corrected FROM public.f_tsdata"
)

PREVIEW_MAX_ROWS = 50


def resolve_partner(partner: str) -> str:
    """Normalise a partner name and return its data lake database name."""
    key = (partner or "").strip().upper()
    dbname = PARTNER_DATABASES.get(key)
    if dbname is None:
        raise UnknownPartnerError(
            f"Unknown pilot partner '{partner}'. "
            f"Valid options: {', '.join(PARTNER_DATABASES)}."
        )
    return dbname


def _connect(dbname: str):
    """Open a read-only connection to one partner database."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - psycopg is a hard dependency
        raise DataLakeError("psycopg is not installed.") from exc

    try:
        return psycopg.connect(
            host=settings.DATALAKE_HOST,
            port=settings.DATALAKE_PORT,
            user=settings.DATALAKE_USER,
            password=settings.DATALAKE_PASSWORD,
            dbname=dbname,
            connect_timeout=settings.DATALAKE_CONNECT_TIMEOUT,
        )
    except psycopg.OperationalError as exc:
        raise DataLakeError(f"Data lake connection failed: {exc}") from exc


def _assert_raw_table_exists(conn, partner: str) -> None:
    """
    Probe the raw table before streaming, so a missing table surfaces as a clean
    error instead of blowing up halfway through an already-started response.
    """
    import psycopg

    try:
        with conn.cursor() as cur:
            cur.execute(f"{_RAW_SELECT} LIMIT 0")
    except psycopg.errors.UndefinedTable as exc:
        raise PartnerDataUnavailableError(
            f"No data tables found for partner '{partner}'."
        ) from exc
    except psycopg.Error as exc:
        raise DataLakeError(f"Data lake query failed: {exc}") from exc


def _copy_blocks(conn, partner: str):
    """Yield the raw table as CSV bytes, streamed straight out of Postgres."""
    import psycopg

    try:
        with conn.cursor() as cur:
            copy_sql = f"COPY ({_RAW_SELECT}) TO STDOUT WITH (FORMAT CSV, HEADER)"
            with cur.copy(copy_sql) as copy:
                for block in copy:
                    yield bytes(block)
    except psycopg.Error as exc:
        logger.error("Data lake export failed for partner %s: %s", partner, exc)
        raise DataLakeError(f"Data lake export failed: {exc}") from exc
    finally:
        conn.close()


def stream_raw_csv(partner: str):
    """
    Return an iterator of CSV byte blocks for a partner's complete raw table.

    The whole table is exported — no LIMIT — using server-side COPY so nothing
    is buffered in the web process. Connection errors and missing tables are
    raised here, before the first byte is produced.
    """
    dbname = resolve_partner(partner)
    conn = _connect(dbname)
    try:
        _assert_raw_table_exists(conn, partner)
    except Exception:
        conn.close()
        raise
    return _copy_blocks(conn, partner)


def fetch_raw_preview(
    partner: str, limit: int = PREVIEW_MAX_ROWS
) -> tuple[list[str], list[list[str]]]:
    """Return (headers, rows) for the first `limit` rows of a partner's raw table."""
    import psycopg

    dbname = resolve_partner(partner)
    conn = _connect(dbname)
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(f"{_RAW_SELECT} LIMIT %s", (limit,))
            except psycopg.errors.UndefinedTable as exc:
                raise PartnerDataUnavailableError(
                    f"No data tables found for partner '{partner}'."
                ) from exc
            except psycopg.Error as exc:
                raise DataLakeError(f"Data lake query failed: {exc}") from exc

            rows = [
                ["" if value is None else str(value) for value in record]
                for record in cur.fetchall()
            ]
    finally:
        conn.close()

    return list(RAW_COLUMNS), rows
